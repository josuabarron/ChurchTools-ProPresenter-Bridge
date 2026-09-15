import Foundation
import Network

final class LiveAgendaRedirectServer: @unchecked Sendable {
    private let listener: NWListener
    private let handler: (LiveAgendaRoute) async -> LiveAgendaServerResponse
    private let queue = DispatchQueue(label: "io.github.churchtools-bridge.live-agenda-redirect")

    init(port: Int, handler: @escaping (LiveAgendaRoute) async -> LiveAgendaServerResponse) throws {
        guard let endpointPort = NWEndpoint.Port(rawValue: UInt16(port)) else {
            throw RedirectServerError.invalidPort(port)
        }
        let parameters = NWParameters.tcp
        parameters.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: endpointPort)
        self.listener = try NWListener(using: parameters)
        self.handler = handler
    }

    func start() async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            let startState = ListenerStartState(continuation: continuation)

            listener.stateUpdateHandler = { state in
                switch state {
                case .ready:
                    startState.resume(.success(()))
                case .failed(let error):
                    startState.resume(.failure(RedirectServerError.listenerFailed(error.localizedDescription)))
                case .cancelled:
                    startState.resume(.failure(RedirectServerError.listenerCancelled))
                default:
                    break
                }
            }
            listener.newConnectionHandler = { [weak self] connection in
                self?.handle(connection)
            }
            listener.start(queue: queue)
        }
    }

    func stop() {
        listener.cancel()
    }

    private func handle(_ connection: NWConnection) {
        connection.start(queue: queue)
        connection.receive(minimumIncompleteLength: 1, maximumLength: 8_192) { [weak self] data, _, _, _ in
            guard let self else { return }
            // Zugriffsschutz: das ist Netzwerkisolation (127.0.0.1), aber keine
            // Zugriffskontrolle. Ohne diese Prüfungen könnte eine fremde Seite
            // per DNS-Rebinding die Ansichten lesen.
            if let grund = Self.abgelehnt(data) {
                let response = LiveAgendaServerResponse.forbidden(grund).httpResponse
                connection.send(content: Data(response.utf8), completion: .contentProcessed { _ in
                    connection.cancel()
                })
                return
            }
            let route = Self.route(from: data)
            Task {
                let response = await self.handler(route)
                connection.send(content: Data(response.httpResponse.utf8), completion: .contentProcessed { _ in
                    connection.cancel()
                })
            }
        }
    }

    /// Prüft Host, Origin und Sec-Fetch-Site. Gibt den Grund zurück, wenn die
    /// Anfrage abgelehnt wird.
    private static func abgelehnt(_ data: Data?) -> String? {
        guard let data, let request = String(data: data, encoding: .utf8) else { return nil }
        let header = request.split(separator: "\r\n").dropFirst()

        func wert(_ name: String) -> String? {
            for zeile in header {
                guard let doppel = zeile.firstIndex(of: ":") else { continue }
                let feld = zeile[zeile.startIndex..<doppel].trimmingCharacters(in: .whitespaces)
                guard feld.caseInsensitiveCompare(name) == .orderedSame else { continue }
                return String(zeile[zeile.index(after: doppel)...]).trimmingCharacters(in: .whitespaces)
            }
            return nil
        }

        func istLoopback(_ kopf: String) -> Bool {
            // Port und etwaige Zugangsdaten abschneiden.
            var name = kopf.split(separator: "@").last.map(String.init) ?? kopf
            if let punkt = name.lastIndex(of: ":"), name[name.index(after: punkt)...].allSatisfy(\.isNumber) {
                name = String(name[name.startIndex..<punkt])
            }
            name = name.trimmingCharacters(in: CharacterSet(charactersIn: "[]")).lowercased()
            return name == "127.0.0.1" || name == "localhost" || name == "::1"
        }

        if let host = wert("Host"), !host.isEmpty, !istLoopback(host) {
            return "unbekannter Host"
        }
        if let origin = wert("Origin"), !origin.isEmpty {
            if origin == "null" { return "fremde Herkunft" }
            guard let host = URL(string: origin)?.host, istLoopback(host) else {
                return "fremde Herkunft"
            }
        }
        if let fetchSite = wert("Sec-Fetch-Site"), !fetchSite.isEmpty {
            let eigene = ["none", "same-origin", "same-site"]
            if !eigene.contains(fetchSite.lowercased()) { return "seitenübergreifende Anfrage" }
        }
        return nil
    }

    private static func route(from data: Data?) -> LiveAgendaRoute {
        guard
            let data,
            let request = String(data: data, encoding: .utf8),
            let firstLine = request.split(separator: "\r\n").first
        else { return .live }

        let parts = firstLine.split(separator: " ")
        guard parts.count >= 2 else { return .live }
        let target = String(parts[1])
        let path = target.split(separator: "?").first.map(String.init) ?? "/live"

        switch path {
        case "/help", "/live/help": return .help
        case "/live/settings.json": return .settingsData
        case "/live/strip.json": return .stripData
        case "/live/notes.json": return .notesData
        case "/live/strip": return .strip
        case "/live/notes": return .notes
        default: return .live
        }
    }
}

private final class ListenerStartState: @unchecked Sendable {
    private let lock = NSLock()
    private var didResume = false
    private let continuation: CheckedContinuation<Void, Error>

    init(continuation: CheckedContinuation<Void, Error>) {
        self.continuation = continuation
    }

    func resume(_ result: Result<Void, Error>) {
        lock.lock()
        defer { lock.unlock() }
        guard !didResume else { return }
        didResume = true
        switch result {
        case .success: continuation.resume()
        case .failure(let error): continuation.resume(throwing: error)
        }
    }
}

enum LiveAgendaRoute {
    case live
    case help
    case strip
    case notes
    case settingsData
    case stripData
    case notesData
}

enum LiveAgendaServerResponse {
    case redirect(URL)
    case html(String)
    case json(String)
    case unavailable(String)
    case forbidden(String)

    /// Gemeinsame Sicherheitsköpfe. Gleicher Stand wie unter Windows
    /// (windows/server.py): keine fremde Einbettung, keine Referrer-Abgabe,
    /// kein MIME-Raten.
    private static let sicherheitsKöpfe = [
        "Cache-Control: no-store",
        "Referrer-Policy: no-referrer",
        "X-Content-Type-Options: nosniff",
        "X-Frame-Options: DENY",
    ].joined(separator: "\r\n")

    private static func antwort(_ status: String, inhalt: String, body: String) -> String {
        "\(status)\r\n\(inhalt)\r\n\(sicherheitsKöpfe)\r\nContent-Length: \(body.utf8.count)\r\nConnection: close\r\n\r\n\(body)"
    }

    var httpResponse: String {
        switch self {
        case .redirect(let url):
            return "HTTP/1.1 302 Found\r\nLocation: \(url.absoluteString)\r\n\(Self.sicherheitsköpfe)\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        case .html(let body):
            return Self.antwort("HTTP/1.1 200 OK", inhalt: "Content-Type: text/html; charset=utf-8", body: body)
        case .json(let body):
            return Self.antwort("HTTP/1.1 200 OK", inhalt: "Content-Type: application/json; charset=utf-8", body: body)
        case .unavailable(let body):
            return Self.antwort("HTTP/1.1 503 Service Unavailable", inhalt: "Content-Type: text/plain; charset=utf-8", body: body)
        case .forbidden(let grund):
            return Self.antwort("HTTP/1.1 403 Forbidden", inhalt: "Content-Type: text/plain; charset=utf-8", body: "Zugriff abgelehnt: \(grund)")
        }
    }
}

enum RedirectServerError: LocalizedError {
    case invalidPort(Int)
    case listenerFailed(String)
    case listenerCancelled

    var errorDescription: String? {
        switch self {
        case .invalidPort(let port): return "Ungültiger Redirect-Port: \(port)"
        case .listenerFailed(let message): return "Localhost-Server konnte nicht starten: \(message)"
        case .listenerCancelled: return "Localhost-Server wurde beim Start gestoppt."
        }
    }
}
