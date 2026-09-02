import Foundation

final class ChurchToolsClient {
    private let baseURL: URL
    private let token: String
    private let csrfToken: String?
    private var sessionCSRFToken: String?
    private let browserTabID = UUID().uuidString
    private let decoder: JSONDecoder

    init(baseURL: URL, token: String, csrfToken: String? = nil) {
        self.baseURL = baseURL
        self.token = token
        self.csrfToken = csrfToken
        self.decoder = JSONDecoder()
        self.decoder.dateDecodingStrategy = .custom { decoder in
            try Self.decodeDate(from: decoder)
        }
    }

    func checkConnection() async throws {
        let _: ChurchToolsWhoAmIResponse = try await get(
            "/whoami",
            queryItems: [],
            responseType: ChurchToolsWhoAmIResponse.self
        )
    }

    func selectEvent(searchDays: Int, nameContains: String?, requireLockedAgenda: Bool) async throws -> ChurchToolsEvent? {
        let calendar = Calendar(identifier: .gregorian)
        let now = Date()
        let from = Self.dateFormatter.string(from: now)
        let to = Self.dateFormatter.string(from: calendar.date(byAdding: .day, value: searchDays, to: now) ?? now)
        let events: [ChurchToolsEvent] = try await get(
            "/events",
            queryItems: [
                URLQueryItem(name: "from", value: from),
                URLQueryItem(name: "to", value: to),
                URLQueryItem(name: "direction", value: "forward"),
                URLQueryItem(name: "limit", value: "25"),
                URLQueryItem(name: "canceled", value: "false")
            ],
            responseType: ChurchToolsListResponse<ChurchToolsEvent>.self
        ).data

        let filtered = events
            .filter { !$0.isCanceled }
            .filter { event in
                guard let nameContains, !nameContains.isEmpty else { return true }
                return event.name.localizedCaseInsensitiveContains(nameContains)
            }
            .sorted { ($0.startDate ?? .distantFuture) < ($1.startDate ?? .distantFuture) }

        for event in filtered {
            guard requireLockedAgenda else { return event }
            if try await loadAgenda(eventId: event.id).isLocked { return event }
        }
        return nil
    }

    func triggerLiveAgenda(_ kind: AgendaCommand.Kind, eventId: Int) async throws {
        guard kind != .reloadEvent else { return }
        let agenda = try await loadAgenda(eventId: eventId)
        let position = try await loadLivePosition(eventId: eventId, agendaId: agenda.id)
        let items = agenda.items.filter { $0.type != "header" }
        let newPosition: Int

        switch kind {
        case .next:
            newPosition = Self.nextPosition(after: position.position, items: items)
        case .previous:
            newPosition = max(0, position.position - 1)
        case .goToPosition, .reloadEvent:
            return
        }

        guard newPosition != position.position else { return }
        try await saveLivePosition(eventId: eventId, position: newPosition)
    }

    func setLiveAgendaPosition(eventId: Int, position: Int) async throws {
        let agenda = try await loadAgenda(eventId: eventId)
        let itemCount = agenda.items.filter { $0.type != "header" }.count
        guard (0...(itemCount + 1)).contains(position) else {
            throw BridgeError.invalidAgendaPosition(position, maximum: itemCount + 1)
        }
        try await saveLivePosition(eventId: eventId, position: position)
    }

    static func nextPosition(after currentPosition: Int, items: [ChurchToolsAgendaItem]) -> Int {
        // Position 0 is "not started"; the position after the final item is "end".
        let endPosition = items.count + 1
        var candidate = min(currentPosition + 1, endPosition)
        while candidate <= items.count {
            let item = items[candidate - 1]
            if item.duration != 0 || item.song == nil { break }
            candidate += 1
        }
        return min(candidate, endPosition)
    }

    private func loadAgenda(eventId: Int) async throws -> ChurchToolsAgenda {
        let response: ChurchToolsAgendaResponse = try await get(
            "/events/\(eventId)/agenda",
            queryItems: [],
            responseType: ChurchToolsAgendaResponse.self
        )
        return response.data
    }

    private func loadLivePosition(eventId: Int, agendaId: Int) async throws -> ChurchToolsLivePosition {
        let response: ChurchToolsLegacyResponse<ChurchToolsLivePosition> = try await legacyRequest([
            "func": "loadAgendaLivePosition",
            "event_id": String(eventId),
            "agenda_id": String(agendaId)
        ])
        return response.data ?? ChurchToolsLivePosition(position: 0)
    }

    private func saveLivePosition(eventId: Int, position: Int) async throws {
        let _: ChurchToolsLegacyResponse<EmptyLegacyData> = try await legacyRequest([
            "func": "saveAgendaLivePosition",
            "event_id": String(eventId),
            "pos_id": String(position),
            "addseconds": "0"
        ])
    }

    private func get<T: Decodable>(_ path: String, queryItems: [URLQueryItem], responseType: T.Type) async throws -> T {
        var components = URLComponents(url: makeURL(path: path), resolvingAgainstBaseURL: false)
        components?.queryItems = queryItems.isEmpty ? nil : queryItems
        guard let url = components?.url else { throw BridgeError.invalidURL(path) }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        authorize(&request)
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)
        return try decoder.decode(T.self, from: data)
    }

    private func legacyRequest<T: Decodable>(_ parameters: [String: String]) async throws -> T {
        let csrfToken = try await resolveCSRFToken()
        let rootURL = baseURL.lastPathComponent == "api" ? baseURL.deletingLastPathComponent() : baseURL
        guard var components = URLComponents(url: rootURL.appendingPathComponent("index.php"), resolvingAgainstBaseURL: false) else {
            throw BridgeError.invalidURL("churchservice/ajax")
        }
        components.queryItems = [URLQueryItem(name: "q", value: "churchservice/ajax")]
        guard let url = components.url else { throw BridgeError.invalidURL("churchservice/ajax") }

        var form = parameters
        form["browsertabId"] = browserTabID
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = Self.formEncoded(form)
        request.setValue("application/x-www-form-urlencoded; charset=UTF-8", forHTTPHeaderField: "Content-Type")
        request.setValue(csrfToken, forHTTPHeaderField: "CSRF-Token")
        authorize(&request)

        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)
        let result = try decoder.decode(T.self, from: data)
        if let legacy = result as? any ChurchToolsLegacyStatus, legacy.status != "success" {
            throw BridgeError.legacy(legacy.message ?? "Unknown ChurchTools error")
        }
        return result
    }

    private func resolveCSRFToken() async throws -> String {
        if let csrfToken, !csrfToken.isEmpty { return csrfToken }
        if let sessionCSRFToken { return sessionCSRFToken }
        let response: ChurchToolsCSRFResponse = try await get(
            "/csrftoken",
            queryItems: [],
            responseType: ChurchToolsCSRFResponse.self
        )
        sessionCSRFToken = response.data
        return response.data
    }

    private func authorize(_ request: inout URLRequest) {
        request.setValue("Login \(token)", forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 10
    }

    private func validate(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else { return }
        guard (200..<300).contains(http.statusCode) else {
            throw BridgeError.http(http.statusCode, String(data: data, encoding: .utf8) ?? "")
        }
    }

    private static func formEncoded(_ values: [String: String]) -> Data? {
        var components = URLComponents()
        components.queryItems = values.sorted { $0.key < $1.key }.map(URLQueryItem.init)
        return components.percentEncodedQuery?.data(using: .utf8)
    }

    private static let dateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()

    private static let dateTimeFormatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    private static let dateTimeFormatterWithoutFractions: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    private static func decodeDate(from decoder: Decoder) throws -> Date {
        let container = try decoder.singleValueContainer()
        let value = try container.decode(String.self)
        if let date = dateTimeFormatter.date(from: value) { return date }
        if let date = dateTimeFormatterWithoutFractions.date(from: value) { return date }
        if let date = dateFormatter.date(from: value) { return date }
        throw DecodingError.dataCorruptedError(in: container, debugDescription: "Unsupported date format: \(value)")
    }

    private func makeURL(path: String) -> URL {
        let relativePath = path.hasPrefix("/") ? String(path.dropFirst()) : path
        return baseURL.appendingPathComponent(relativePath)
    }
}

struct ChurchToolsListResponse<T: Decodable>: Decodable { var data: [T] }
struct ChurchToolsWhoAmIResponse: Decodable { var data: ChurchToolsWhoAmIData }
struct ChurchToolsWhoAmIData: Decodable {}
struct ChurchToolsCSRFResponse: Decodable { var data: String }
struct ChurchToolsAgendaResponse: Decodable { var data: ChurchToolsAgenda }
struct ChurchToolsAgenda: Decodable {
    var id: Int
    var isLocked: Bool
    var items: [ChurchToolsAgendaItem]
}
struct ChurchToolsAgendaItem: Decodable {
    var type: String
    var duration: Int
    var song: ChurchToolsAgendaSong?
}
struct ChurchToolsAgendaSong: Decodable {}
struct ChurchToolsEvent: Decodable {
    var id: Int
    var name: String
    var startDate: Date?
    var endDate: Date?
    var isCanceled: Bool
}

private protocol ChurchToolsLegacyStatus {
    var status: String { get }
    var message: String? { get }
}
private struct ChurchToolsLegacyResponse<T: Decodable>: Decodable, ChurchToolsLegacyStatus {
    var status: String
    var data: T?
    var message: String?
}
private struct ChurchToolsLivePosition: Decodable {
    var position: Int

    enum CodingKeys: String, CodingKey { case position = "pos_id" }

    init(position: Int) {
        self.position = position
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        guard container.contains(.position), !(try container.decodeNil(forKey: .position)) else {
            position = 0
            return
        }
        if let value = try? container.decode(Int.self, forKey: .position) {
            position = value
        } else {
            let value = try container.decode(String.self, forKey: .position)
            guard let parsed = Int(value) else {
                throw DecodingError.dataCorruptedError(
                    forKey: .position,
                    in: container,
                    debugDescription: "Invalid live agenda position: \(value)"
                )
            }
            position = parsed
        }
    }
}
private struct EmptyLegacyData: Decodable {
    init(from decoder: Decoder) throws {}
}

enum BridgeError: LocalizedError {
    case invalidURL(String)
    case http(Int, String)
    case legacy(String)
    case noMatchingEvent
    case invalidAgendaPosition(Int, maximum: Int)

    var errorDescription: String? {
        switch self {
        case .invalidURL(let value): return "Invalid URL: \(value)"
        case .http(let status, let body): return "ChurchTools HTTP \(status): \(body)"
        case .legacy(let message): return "ChurchTools Live Agenda: \(message)"
        case .noMatchingEvent: return "Kein passendes ChurchTools-Event mit Agenda gefunden."
        case .invalidAgendaPosition(let position, let maximum):
            return "Agenda-Position \(position) ist ungültig. Erlaubt sind 0 bis \(maximum)."
        }
    }
}
