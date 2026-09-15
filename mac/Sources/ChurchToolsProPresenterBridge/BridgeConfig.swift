import Foundation

struct SendActionSetting: Codable, Identifiable, Equatable {
    var id: UUID
    var target: String
    var midiNote: Int

    init(id: UUID = UUID(), target: String, midiNote: Int) {
        self.id = id
        self.target = target
        self.midiNote = midiNote
    }

    var resolvedTarget: SendTarget {
        let value = target.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalized = value.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current)
        switch normalized {
        case "zuruck", "previous", "back": return .previous
        case "vor", "weiter", "next", "forward": return .next
        default:
            if let position = Int(value) { return .position(position) }
            return .title(value)
        }
    }
}

enum SendTarget: Equatable {
    case previous
    case next
    case position(Int)
    case title(String)
}

struct BridgeConfig {
    var sends: [SendActionSetting]
    var preferredEventID: Int?
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
}

struct EventOption: Identifiable, Equatable {
    let id: Int
    let name: String
    let startDate: Date?

    var displayName: String {
        guard let startDate else { return name }
        return "\(Self.timeFormatter.string(from: startDate)) · \(name)"
    }

    private static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "de_DE")
        formatter.dateFormat = "HH:mm"
        return formatter
    }()
}

struct AgendaCommand {
    enum Kind: String { case next, previous }
    var kind: Kind
}
