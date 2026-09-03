import Foundation

final class Bridge {
    private let config: BridgeConfig
    private let churchTools: ChurchToolsClient
    private var selectedEvent: ChurchToolsEvent?
    private var lastCommandAt: [UUID: Date] = [:]
    private var redirectServer: LiveAgendaRedirectServer?
    private let onStatus: (BridgeRuntimeStatus) -> Void

    init(config: BridgeConfig, onStatus: @escaping (BridgeRuntimeStatus) -> Void = { _ in }) {
        self.config = config
        self.onStatus = onStatus
        churchTools = ChurchToolsClient(
            baseURL: config.churchToolsBaseURL,
            token: config.churchToolsToken,
            csrfToken: config.churchToolsCSRFToken
        )
    }

    func run() async throws {
        let redirectServer = try LiveAgendaRedirectServer(port: config.redirectPort) { [weak self] route in
            await self?.handleLiveAgendaRoute(route) ?? .unavailable("No matching ChurchTools event is selected.")
        }
        try await redirectServer.start()
        self.redirectServer = redirectServer
        onStatus(.redirectListening(port: config.redirectPort))

        do {
            try await churchTools.checkConnection()
            onStatus(.churchToolsConnected)
            let events = try await churchTools.candidateEvents(
                searchDays: config.eventSearchDays,
                nameContains: config.eventNameContains,
                requireLockedAgenda: config.requireLockedAgenda
            )
            selectedEvent = events.first(where: { $0.id == config.preferredEventID }) ?? events.first
            onStatus(.eventOptions(
                events.map { EventOption(id: $0.id, name: $0.name, startDate: $0.startDate) },
                selectedID: selectedEvent?.id
            ))
        } catch {
            onStatus(.churchToolsFailed(error.localizedDescription))
            selectedEvent = nil
        }

        if let selectedEvent {
            onStatus(.eventSelected(id: selectedEvent.id, name: selectedEvent.name))
        } else {
            onStatus(.noEvent)
        }

        let listener = try MIDIListener()
        onStatus(.midiListening(notes: config.sends.map(\.midiNote)))

        for try await message in listener.messages() {
            try Task.checkCancellation()
            onStatus(.midiMessageReceived(note: message.note, channel: message.channel))
            guard let send = config.sends.first(where: { $0.midiNote == message.note }) else { continue }
            await handle(send)
        }
    }

    private func handle(_ send: SendActionSetting) async {
        guard shouldAccept(send.id), let selectedEvent else { return }
        do {
            try await churchTools.execute(send.resolvedTarget, eventId: selectedEvent.id)
            onStatus(.commandSucceeded(send.target))
        } catch {
            onStatus(.commandFailed(error.localizedDescription))
        }
    }

    private func shouldAccept(_ id: UUID) -> Bool {
        let now = Date()
        defer { lastCommandAt[id] = now }
        guard let last = lastCommandAt[id] else { return true }
        return now.timeIntervalSince(last) >= Double(config.debounceMilliseconds) / 1000
    }

    private func handleLiveAgendaRoute(_ route: LiveAgendaRoute) async -> LiveAgendaServerResponse {
        switch route {
        case .live:
            guard let url = liveAgendaURL() else {
                return .unavailable("No matching ChurchTools event is selected.")
            }
            return .redirect(url)
        case .strip:
            return await renderLiveStrip()
        case .notes:
            return await renderLiveNotes()
        case .stripData:
            return await liveStripData()
        case .notesData:
            return await liveNotesData()
        }
    }

    private func liveAgendaURL() -> URL? {
        guard let selectedEvent else { return nil }
        let rootURL = config.churchToolsBaseURL.lastPathComponent == "api"
            ? config.churchToolsBaseURL.deletingLastPathComponent()
            : config.churchToolsBaseURL
        var components = URLComponents(url: rootURL, resolvingAgainstBaseURL: false)
        components?.queryItems = [
            URLQueryItem(name: "q", value: "churchservice/liveview"),
            URLQueryItem(name: "event_id", value: String(selectedEvent.id))
        ]
        if let token = config.liveAgendaLoginToken, !token.isEmpty {
            components?.queryItems?.append(URLQueryItem(name: "login_token", value: token))
        }
        if let userID = config.liveAgendaUserID {
            components?.queryItems?.append(URLQueryItem(name: "user_id", value: String(userID)))
        }
        components?.fragment = "LiveView"
        return components?.url
    }

    private func renderLiveStrip() async -> LiveAgendaServerResponse {
        guard let selectedEvent else {
            return .unavailable("No matching ChurchTools event is selected.")
        }
        do {
            let snapshot = try await churchTools.loadLiveSnapshot(eventId: selectedEvent.id)
            return .html(Self.stripHTML(for: snapshot, event: selectedEvent))
        } catch {
            return .unavailable(error.localizedDescription)
        }
    }

    private func renderLiveNotes() async -> LiveAgendaServerResponse {
        guard let selectedEvent else {
            return .unavailable("No matching ChurchTools event is selected.")
        }
        do {
            let snapshot = try await churchTools.loadLiveSnapshot(eventId: selectedEvent.id)
            return .html(Self.notesHTML(for: snapshot, event: selectedEvent))
        } catch {
            return .unavailable(error.localizedDescription)
        }
    }

    private func liveStripData() async -> LiveAgendaServerResponse {
        guard let selectedEvent else {
            return .json(Self.errorJSON("No matching ChurchTools event is selected."))
        }
        do {
            let snapshot = try await churchTools.loadLiveSnapshot(eventId: selectedEvent.id)
            return .json(Self.stripJSON(for: snapshot, event: selectedEvent))
        } catch {
            return .json(Self.errorJSON(error.localizedDescription))
        }
    }

    private func liveNotesData() async -> LiveAgendaServerResponse {
        guard let selectedEvent else {
            return .json(Self.errorJSON("No matching ChurchTools event is selected."))
        }
        do {
            let snapshot = try await churchTools.loadLiveSnapshot(eventId: selectedEvent.id)
            return .json(Self.notesJSON(for: snapshot, event: selectedEvent))
        } catch {
            return .json(Self.errorJSON(error.localizedDescription))
        }
    }

    private static func stripHTML(for snapshot: ChurchToolsLiveSnapshot, event: ChurchToolsEvent) -> String {
        let current = snapshot.current?.displayTitle.nonEmpty ?? "Noch nicht gestartet"
        let next = snapshot.next?.displayTitle.nonEmpty ?? ""
        return """
        <!doctype html>
        <html lang="de">
        <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Live Agenda Strip</title>
        <style>
        :root { color-scheme: dark; font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif; }
        * { box-sizing: border-box; }
        body { margin: 0; min-height: 100vh; background: #050607; color: white; overflow: hidden; }
        .strip { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr); gap: min(4vw, 36px); align-items: center; min-height: 100vh; padding: min(4vw, 28px); }
        .block { min-width: 0; display: grid; gap: min(.9vw, 8px); }
        .label { color: #7f858c; font-weight: 650; letter-spacing: 0; text-transform: uppercase; font-size: clamp(10px, 1.55vw, 20px); line-height: 1; }
        .item { min-width: 0; white-space: nowrap; overflow: hidden; font-weight: 950; line-height: .92; }
        .current { color: #ffffff; }
        .next { color: #d9dcdf; }
        </style>
        </head>
        <body>
        <main class="strip" aria-label="\(event.name.htmlEscaped)">
        <section class="block"><div class="label">Jetzt</div><div id="current" class="item current">\(current.htmlEscaped)</div></section>
        <section class="block"><div class="label">Dann</div><div id="next" class="item next">\(next.htmlEscaped)</div></section>
        </main>
        <script>
        const fields = ["current", "next"].map(id => document.getElementById(id));
        const setText = (id, value) => { const el = document.getElementById(id); if (el.textContent !== value) el.textContent = value; };
        const fit = el => {
          let low = 14, high = Math.max(22, Math.min(window.innerHeight * 0.86, window.innerWidth * 0.25));
          el.style.fontSize = high + "px";
          for (let i = 0; i < 10; i++) {
            const mid = (low + high) / 2;
            el.style.fontSize = mid + "px";
            if (el.scrollWidth <= el.clientWidth && el.scrollHeight <= el.clientHeight) low = mid; else high = mid;
          }
          el.style.fontSize = Math.floor(low) + "px";
        };
        const fitAll = () => fields.forEach(fit);
        const refresh = async () => {
          try {
            const response = await fetch("/live/strip.json", { cache: "no-store" });
            const data = await response.json();
            setText("current", data.current || "Noch nicht gestartet");
            setText("next", data.next || "");
            fitAll();
          } catch (_) {}
        };
        window.addEventListener("resize", fitAll);
        fitAll();
        setInterval(refresh, 750);
        </script>
        </body>
        </html>
        """
    }

    private static func notesHTML(for snapshot: ChurchToolsLiveSnapshot, event: ChurchToolsEvent) -> String {
        let notes = snapshot.current?.displayNotes.nonEmpty ?? ""
        let body = notes.isEmpty ? "Keine Notizen" : notes
        return """
        <!doctype html>
        <html lang="de">
        <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Live Agenda Notes</title>
        <style>
        :root { color-scheme: dark; font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif; }
        * { box-sizing: border-box; }
        body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 5vw; background: #050607; color: #ffffff; overflow: hidden; }
        .notes { width: 100%; max-height: 100%; white-space: pre-wrap; overflow-wrap: anywhere; font-weight: 750; line-height: 1.12; text-align: center; }
        .empty { color: #8f969e; }
        </style>
        </head>
        <body aria-label="\(event.name.htmlEscaped)">
        <main id="notes" class="notes \(notes.isEmpty ? "empty" : "")">\(body.htmlEscaped)</main>
        <script>
        const notes = document.getElementById("notes");
        const fit = () => {
          let low = 12, high = Math.max(24, Math.min(window.innerHeight * 0.5, window.innerWidth * 0.16));
          notes.style.fontSize = high + "px";
          for (let i = 0; i < 11; i++) {
            const mid = (low + high) / 2;
            notes.style.fontSize = mid + "px";
            if (notes.scrollWidth <= notes.clientWidth && notes.scrollHeight <= notes.clientHeight) low = mid; else high = mid;
          }
          notes.style.fontSize = Math.floor(low) + "px";
        };
        const refresh = async () => {
          try {
            const response = await fetch("/live/notes.json", { cache: "no-store" });
            const data = await response.json();
            const text = data.notes || "Keine Notizen";
            if (notes.textContent !== text) notes.textContent = text;
            notes.classList.toggle("empty", !data.notes);
            fit();
          } catch (_) {}
        };
        window.addEventListener("resize", fit);
        fit();
        setInterval(refresh, 750);
        </script>
        </body>
        </html>
        """
    }

    private static func stripJSON(for snapshot: ChurchToolsLiveSnapshot, event: ChurchToolsEvent) -> String {
        let current = snapshot.current?.displayTitle.nonEmpty ?? "Noch nicht gestartet"
        let next = snapshot.next?.displayTitle.nonEmpty ?? ""
        return """
        {"event":"\(event.name.jsonEscaped)","position":\(snapshot.position),"current":"\(current.jsonEscaped)","next":"\(next.jsonEscaped)"}
        """
    }

    private static func notesJSON(for snapshot: ChurchToolsLiveSnapshot, event: ChurchToolsEvent) -> String {
        let notes = snapshot.current?.displayNotes.nonEmpty ?? ""
        return """
        {"event":"\(event.name.jsonEscaped)","position":\(snapshot.position),"notes":"\(notes.jsonEscaped)"}
        """
    }

    private static func errorJSON(_ message: String) -> String {
        """
        {"error":"\(message.jsonEscaped)"}
        """
    }

}

private extension String {
    var nonEmpty: String? {
        let trimmed = trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    var htmlEscaped: String {
        replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
            .replacingOccurrences(of: "\"", with: "&quot;")
            .replacingOccurrences(of: "'", with: "&#39;")
    }

    var jsonEscaped: String {
        var result = ""
        for scalar in unicodeScalars {
            switch scalar.value {
            case 0x5C: result += "\\\\"
            case 0x22: result += "\\\""
            case 0x0A: result += "\\n"
            case 0x0D: result += "\\r"
            case 0x09: result += "\\t"
            default:
                if scalar.value < 0x20 {
                    result += String(format: "\\u%04X", scalar.value)
                } else {
                    result.unicodeScalars.append(scalar)
                }
            }
        }
        return result
    }
}

enum BridgeRuntimeStatus {
    case churchToolsConnected
    case churchToolsFailed(String)
    case midiListening(notes: [Int])
    case midiMessageReceived(note: Int, channel: Int)
    case eventOptions([EventOption], selectedID: Int?)
    case eventSelected(id: Int, name: String)
    case noEvent
    case commandSucceeded(String)
    case commandFailed(String)
    case redirectListening(port: Int)
}
