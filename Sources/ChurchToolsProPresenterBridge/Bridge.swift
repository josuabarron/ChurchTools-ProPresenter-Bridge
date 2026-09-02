import Foundation

final class Bridge {
    private let config: BridgeConfig
    private let churchTools: ChurchToolsClient
    private var selectedEvent: ChurchToolsEvent?
    private var lastCommandAt: [AgendaCommand.Kind: Date] = [:]
    private var redirectServer: LiveAgendaRedirectServer?
    private let onStatus: (BridgeRuntimeStatus) -> Void

    init(config: BridgeConfig, onStatus: @escaping (BridgeRuntimeStatus) -> Void = { _ in }) {
        self.config = config
        self.onStatus = onStatus
        self.churchTools = ChurchToolsClient(
            baseURL: config.churchToolsBaseURL,
            token: config.churchToolsToken,
            csrfToken: config.churchToolsCSRFToken
        )
    }

    func run() async throws {
        do {
            try await churchTools.checkConnection()
            onStatus(.churchToolsConnected)
            selectedEvent = try await churchTools.selectEvent(
                searchDays: config.eventSearchDays,
                nameContains: config.eventNameContains,
                requireLockedAgenda: config.requireLockedAgenda
            )
        } catch {
            onStatus(.churchToolsFailed(error.localizedDescription))
            selectedEvent = nil
        }

        if let selectedEvent {
            print("Selected ChurchTools event #\(selectedEvent.id): \(selectedEvent.name)")
            onStatus(.eventSelected(selectedEvent.name))
        } else {
            print("No matching ChurchTools event found yet. /churchtools/reload-event can retry.")
            onStatus(.noEvent)
        }

        let redirectServer = try LiveAgendaRedirectServer(port: config.redirectPort) { [weak self] in
            self?.liveAgendaURL()
        }
        redirectServer.start()
        self.redirectServer = redirectServer
        onStatus(.redirectListening(port: config.redirectPort))

        let listener = try MIDIListener()
        print("Listening for MIDI notes \(config.midiPreviousNote), \(config.midiNextNote), and \(config.midiGoToNote)")
        onStatus(.midiListening(
            previousNote: config.midiPreviousNote,
            nextNote: config.midiNextNote,
            goToNote: config.midiGoToNote
        ))

        for try await message in listener.messages() {
            try Task.checkCancellation()
            onStatus(.midiMessageReceived(note: message.note, channel: message.channel))
            let command: AgendaCommand
            if message.note == config.midiNextNote {
                command = AgendaCommand(kind: .next)
            } else if message.note == config.midiPreviousNote {
                command = AgendaCommand(kind: .previous)
            } else if message.note == config.midiGoToNote {
                command = AgendaCommand(kind: .goToPosition)
            } else {
                print("Ignored MIDI note \(message.note) on channel \(message.channel)")
                continue
            }

            await handle(command: command, sourceAddress: "MIDI note \(message.note)")
        }
    }

    private func handle(command: AgendaCommand, sourceAddress: String) async {
        guard shouldAccept(command.kind) else {
            print("Debounced \(sourceAddress)")
            return
        }

        do {
            switch command.kind {
            case .reloadEvent:
                selectedEvent = try await churchTools.selectEvent(
                    searchDays: config.eventSearchDays,
                    nameContains: config.eventNameContains,
                    requireLockedAgenda: config.requireLockedAgenda
                )
                print("Reloaded event: \(selectedEvent.map { "#\($0.id) \($0.name)" } ?? "none")")

            case .next, .previous:
                guard let selectedEvent else {
                    print("No selected event; ignoring \(sourceAddress)")
                    return
                }
                try await churchTools.triggerLiveAgenda(command.kind, eventId: selectedEvent.id)
                print("Sent \(command.kind.rawValue) for event #\(selectedEvent.id)")
                onStatus(.commandSucceeded(command.kind.rawValue))
            case .goToPosition:
                guard let selectedEvent else {
                    print("No selected event; ignoring \(sourceAddress)")
                    return
                }
                try await churchTools.setLiveAgendaPosition(
                    eventId: selectedEvent.id,
                    position: config.goToPosition
                )
                onStatus(.commandSucceeded("position \(config.goToPosition)"))
            }
        } catch {
            print("Command \(sourceAddress) failed: \(error.localizedDescription)")
            onStatus(.commandFailed(error.localizedDescription))
        }
    }

    private func shouldAccept(_ kind: AgendaCommand.Kind) -> Bool {
        let now = Date()
        defer { lastCommandAt[kind] = now }

        guard let last = lastCommandAt[kind] else { return true }
        let minimumInterval = Double(config.debounceMilliseconds) / 1000.0
        return now.timeIntervalSince(last) >= minimumInterval
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
        if let loginToken = config.liveAgendaLoginToken, !loginToken.isEmpty {
            components?.queryItems?.append(URLQueryItem(name: "login_token", value: loginToken))
        }
        if let userID = config.liveAgendaUserID {
            components?.queryItems?.append(URLQueryItem(name: "user_id", value: String(userID)))
        }
        components?.fragment = "LiveView"
        return components?.url
    }
}

enum BridgeRuntimeStatus {
    case churchToolsConnected
    case churchToolsFailed(String)
    case midiListening(previousNote: Int, nextNote: Int, goToNote: Int)
    case midiMessageReceived(note: Int, channel: Int)
    case eventSelected(String)
    case noEvent
    case commandSucceeded(String)
    case commandFailed(String)
    case redirectListening(port: Int)
}
