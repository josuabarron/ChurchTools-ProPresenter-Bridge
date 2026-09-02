import Foundation

struct BridgeConfig: Decodable {
    var midiPreviousNote: Int
    var midiNextNote: Int
    var midiGoToNote: Int
    var goToPosition: Int
    var redirectPort: Int
    var churchToolsBaseURL: URL
    var churchToolsToken: String
    var liveAgendaLoginToken: String?
    var liveAgendaUserID: Int?
    var churchToolsCSRFToken: String?
    var eventSearchDays: Int
    var eventNameContains: String?
    var requireLockedAgenda: Bool
    var debounceMilliseconds: Int

    static func load() throws -> BridgeConfig {
        let path = ProcessInfo.processInfo.environment["BRIDGE_CONFIG"] ?? "bridge-config.json"
        let url = URL(fileURLWithPath: path)
        let data = try Data(contentsOf: url)
        var config = try JSONDecoder().decode(BridgeConfig.self, from: data)

        if let token = ProcessInfo.processInfo.environment["CHURCHTOOLS_LOGIN_TOKEN"], !token.isEmpty {
            config.churchToolsToken = token
        }
        if let token = ProcessInfo.processInfo.environment["CHURCHTOOLS_CSRF_TOKEN"], !token.isEmpty {
            config.churchToolsCSRFToken = token
        }

        return config
    }
}

struct AgendaCommand: Decodable {
    enum Kind: String, Decodable {
        case next
        case previous
        case goToPosition
        case reloadEvent
    }

    var kind: Kind

    init(kind: Kind) {
        self.kind = kind
    }
}
