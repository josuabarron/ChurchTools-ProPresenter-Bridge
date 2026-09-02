import Foundation
import Network

final class LiveAgendaRedirectServer {
    private let listener: NWListener
    private let destinationURL: () -> URL?
    private let queue = DispatchQueue(label: "io.github.churchtools-bridge.live-agenda-redirect")

    init(port: Int, destinationURL: @escaping () -> URL?) throws {
        guard let endpointPort = NWEndpoint.Port(rawValue: UInt16(port)) else {
            throw RedirectServerError.invalidPort(port)
        }
        let parameters = NWParameters.tcp
        parameters.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: endpointPort)
        self.listener = try NWListener(using: parameters)
        self.destinationURL = destinationURL
    }

    func start() {
        listener.newConnectionHandler = { [weak self] connection in
            self?.handle(connection)
        }
        listener.start(queue: queue)
    }

    func stop() {
        listener.cancel()
    }

    private func handle(_ connection: NWConnection) {
        connection.start(queue: queue)
        connection.receive(minimumIncompleteLength: 1, maximumLength: 8_192) { [weak self] _, _, _, _ in
            guard let self else { return }
            let response: String
            if let destinationURL = self.destinationURL() {
                response = "HTTP/1.1 302 Found\r\nLocation: \(destinationURL.absoluteString)\r\nCache-Control: no-store\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            } else {
                let body = "No matching ChurchTools event is selected."
                response = "HTTP/1.1 503 Service Unavailable\r\nContent-Type: text/plain; charset=utf-8\r\nCache-Control: no-store\r\nContent-Length: \(body.utf8.count)\r\nConnection: close\r\n\r\n\(body)"
            }
            connection.send(content: Data(response.utf8), completion: .contentProcessed { _ in
                connection.cancel()
            })
        }
    }
}

enum RedirectServerError: LocalizedError {
    case invalidPort(Int)

    var errorDescription: String? {
        switch self {
        case .invalidPort(let port): return "Ungültiger Redirect-Port: \(port)"
        }
    }
}
