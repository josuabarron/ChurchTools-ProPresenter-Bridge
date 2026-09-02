import Foundation
import ServiceManagement

@MainActor
final class AppSettings: ObservableObject {
    @Published var baseURL: String
    @Published var eventNameContains: String
    @Published var midiPreviousNote: Int
    @Published var midiNextNote: Int
    @Published var midiGoToNote: Int
    @Published var goToPosition: Int
    @Published var redirectPort: Int
    @Published var liveAgendaUserID: Int
    @Published var requireLockedAgenda: Bool
    @Published var launchAtLogin: Bool

    private let defaults = UserDefaults.standard
    private let keychain = KeychainStore(service: "io.github.ChurchToolsProPresenterBridge")
    private var cachedToken: String?

    init() {
        baseURL = defaults.string(forKey: "churchToolsBaseURL") ?? ""
        eventNameContains = defaults.string(forKey: "eventNameContains") ?? ""
        midiPreviousNote = defaults.object(forKey: "midiPreviousNote") as? Int ?? 60
        midiNextNote = defaults.object(forKey: "midiNextNote") as? Int ?? 61
        midiGoToNote = defaults.object(forKey: "midiGoToNote") as? Int ?? 62
        goToPosition = defaults.object(forKey: "goToPosition") as? Int ?? 3
        redirectPort = defaults.object(forKey: "redirectPort") as? Int ?? 8765
        liveAgendaUserID = defaults.object(forKey: "liveAgendaUserID") as? Int ?? 0
        requireLockedAgenda = defaults.object(forKey: "requireLockedAgenda") as? Bool ?? true
        launchAtLogin = SMAppService.mainApp.status == .enabled
    }

    func loadToken() -> String {
        if let cachedToken { return cachedToken }
        let token = (try? keychain.read(account: "login-token")) ?? ""
        cachedToken = token
        return token
    }

    func save(token: String) throws {
        guard URL(string: baseURL) != nil else { throw SettingsError.invalidURL }
        guard (0...127).contains(midiPreviousNote),
              (0...127).contains(midiNextNote),
              (0...127).contains(midiGoToNote) else {
            throw SettingsError.invalidMIDINote
        }
        guard Set([midiPreviousNote, midiNextNote, midiGoToNote]).count == 3 else {
            throw SettingsError.duplicateMIDINote
        }
        guard goToPosition >= 0 else { throw SettingsError.invalidPosition }
        guard (1024...65535).contains(redirectPort) else { throw SettingsError.invalidRedirectPort }
        guard liveAgendaUserID >= 0 else { throw SettingsError.invalidLiveAgendaUserID }
        guard !token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw SettingsError.missingToken
        }

        defaults.set(baseURL, forKey: "churchToolsBaseURL")
        defaults.set(eventNameContains, forKey: "eventNameContains")
        defaults.set(midiPreviousNote, forKey: "midiPreviousNote")
        defaults.set(midiNextNote, forKey: "midiNextNote")
        defaults.set(midiGoToNote, forKey: "midiGoToNote")
        defaults.set(goToPosition, forKey: "goToPosition")
        defaults.set(redirectPort, forKey: "redirectPort")
        defaults.set(liveAgendaUserID, forKey: "liveAgendaUserID")
        defaults.set(requireLockedAgenda, forKey: "requireLockedAgenda")
        if cachedToken != token {
            try keychain.write(token, account: "login-token")
            cachedToken = token
        }
    }

    func setLaunchAtLogin(_ enabled: Bool) throws {
        if enabled {
            try SMAppService.mainApp.register()
        } else {
            try SMAppService.mainApp.unregister()
        }
        launchAtLogin = SMAppService.mainApp.status == .enabled
    }

    func makeConfig(token: String) -> BridgeConfig {
        BridgeConfig(
            midiPreviousNote: midiPreviousNote,
            midiNextNote: midiNextNote,
            midiGoToNote: midiGoToNote,
            goToPosition: goToPosition,
            redirectPort: redirectPort,
            churchToolsBaseURL: URL(string: baseURL)!,
            churchToolsToken: token,
            liveAgendaLoginToken: token,
            liveAgendaUserID: liveAgendaUserID > 0 ? liveAgendaUserID : nil,
            churchToolsCSRFToken: nil,
            eventSearchDays: 30,
            eventNameContains: eventNameContains.isEmpty ? nil : eventNameContains,
            requireLockedAgenda: requireLockedAgenda,
            debounceMilliseconds: 800
        )
    }
}

enum SettingsError: LocalizedError {
    case invalidURL
    case invalidMIDINote
    case duplicateMIDINote
    case invalidPosition
    case invalidRedirectPort
    case missingToken
    case invalidLiveAgendaUserID

    var errorDescription: String? {
        switch self {
        case .invalidURL: return "Die ChurchTools-URL ist ungültig."
        case .invalidMIDINote: return "MIDI-Noten müssen zwischen 0 und 127 liegen."
        case .duplicateMIDINote: return "Alle drei MIDI-Kommandos benötigen unterschiedliche Noten."
        case .invalidPosition: return "Die Zielposition darf nicht negativ sein."
        case .invalidRedirectPort: return "Der lokale Port muss zwischen 1024 und 65535 liegen."
        case .missingToken: return "Bitte einen ChurchTools Login-Token eintragen."
        case .invalidLiveAgendaUserID: return "Die Live-Agenda User-ID darf nicht negativ sein."
        }
    }
}
