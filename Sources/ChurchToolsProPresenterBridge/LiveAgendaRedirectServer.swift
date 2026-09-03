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
            let route = Self.route(from: data)
            Task {
                let response = await self.handler(route)
                switch response {
                case .eventStream(let makeEvent):
                    self.sendEventStream(connection, makeEvent: makeEvent)
                default:
                    connection.send(content: Data(response.httpResponse.utf8), completion: .contentProcessed { _ in
                        connection.cancel()
                    })
                }
            }
        }
    }

    private func sendEventStream(_ connection: NWConnection, makeEvent: @escaping () async -> String) {
        let headers = """
        HTTP/1.1 200 OK\r
        Content-Type: text/event-stream; charset=utf-8\r
        Cache-Control: no-store\r
        Connection: keep-alive\r
        X-Accel-Buffering: no\r
        \r
        """
        connection.send(content: Data(headers.utf8), completion: .contentProcessed { [weak self] error in
            guard error == nil else {
                connection.cancel()
                return
            }
            self?.sendNextEvent(connection, makeEvent: makeEvent)
        })
    }

    private func sendNextEvent(_ connection: NWConnection, makeEvent: @escaping () async -> String) {
        Task {
            let payload = await makeEvent()
            let event = "data: \(payload)\n\n"
            connection.send(content: Data(event.utf8), completion: .contentProcessed { [weak self] error in
                guard error == nil else {
                    connection.cancel()
                    return
                }
                Task {
                    try? await Task.sleep(nanoseconds: 750_000_000)
                    self?.sendNextEvent(connection, makeEvent: makeEvent)
                }
            })
        }
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
        case "/live/strip.events": return .stripEvents
        case "/live/notes.events": return .notesEvents
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
    case strip
    case notes
    case stripData
    case notesData
    case stripEvents
    case notesEvents
}

enum LiveAgendaServerResponse {
    case redirect(URL)
    case html(String)
    case json(String)
    case eventStream(() async -> String)
    case unavailable(String)

    var httpResponse: String {
        switch self {
        case .redirect(let url):
            return "HTTP/1.1 302 Found\r\nLocation: \(url.absoluteString)\r\nCache-Control: no-store\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        case .html(let body):
            return "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nCache-Control: no-store\r\nContent-Length: \(body.utf8.count)\r\nConnection: close\r\n\r\n\(body)"
        case .json(let body):
            return "HTTP/1.1 200 OK\r\nContent-Type: application/json; charset=utf-8\r\nCache-Control: no-store\r\nContent-Length: \(body.utf8.count)\r\nConnection: close\r\n\r\n\(body)"
        case .eventStream:
            return ""
        case .unavailable(let body):
            return "HTTP/1.1 503 Service Unavailable\r\nContent-Type: text/plain; charset=utf-8\r\nCache-Control: no-store\r\nContent-Length: \(body.utf8.count)\r\nConnection: close\r\n\r\n\(body)"
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
