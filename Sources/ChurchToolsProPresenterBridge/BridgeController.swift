import SwiftUI

@MainActor
final class BridgeController: ObservableObject {
    @Published private(set) var isRunning = false
    @Published private(set) var hasCheckedConnection = false
    @Published private(set) var churchToolsStatus = "Nicht geprüft"
    @Published private(set) var midiStatus = "Gestoppt"
    @Published private(set) var redirectStatus = "Gestoppt"
    @Published private(set) var isChurchToolsConnected = false
    @Published private(set) var isProPresenterConnected = false
    @Published private(set) var isSendingCommand = false
    @Published private(set) var commandStatus: String?
    @Published private(set) var logEntries: [String] = []
    @Published private(set) var availableEvents: [EventOption] = []
    @Published private(set) var selectedEventID: Int?

    private var bridgeTask: Task<Void, Never>?
    private var restartGeneration = 0
    private var connectionTask: Task<Void, Never>?
    private var commandTask: Task<Void, Never>?

    var summary: String {
        switch (isChurchToolsConnected, isProPresenterConnected) {
        case (true, true): return "ChurchTools und ProPresenter verbunden"
        case (true, false): return "Nur ChurchTools verbunden"
        case (false, true): return "Nur ProPresenter verbunden"
        case (false, false): return "Keine Verbindung"
        }
    }

    var logText: String { logEntries.joined(separator: "\n") }

    func testConnection(config: BridgeConfig) {
        connectionTask?.cancel()
        churchToolsStatus = "Prüfe..."
        isChurchToolsConnected = false
        addLog("ChurchTools-Verbindung wird geprüft")
        hasCheckedConnection = true
        connectionTask = Task {
            do {
                let client = makeClient(config)
                try await client.checkConnection()
                guard !Task.isCancelled else { return }
                churchToolsStatus = "Verbunden"
                isChurchToolsConnected = true
                addLog("ChurchTools verbunden")
            } catch {
                guard !Task.isCancelled else { return }
                churchToolsStatus = "Fehler: \(error.localizedDescription)"
                isChurchToolsConnected = false
                addLog("ChurchTools-Verbindung fehlgeschlagen: \(error.localizedDescription)")
            }
        }
    }

    func start(config: BridgeConfig) {
        restartGeneration += 1
        let generation = restartGeneration
        bridgeTask?.cancel()
        bridgeTask = nil
        commandTask?.cancel()
        commandTask = nil
        isRunning = true
        addLog("Bridge wird gestartet")
        churchToolsStatus = "Prüfe..."
        midiStatus = "Starte..."
        redirectStatus = "Starte..."
        isProPresenterConnected = false
        bridgeTask = Task {
            try? await Task.sleep(nanoseconds: 350_000_000)
            guard !Task.isCancelled else { return }
            let isCurrentGeneration = await MainActor.run { generation == restartGeneration }
            guard isCurrentGeneration else { return }
            let bridge = Bridge(config: config) { [weak self] status in
                Task { @MainActor in self?.apply(status) }
            }
            do {
                try await bridge.run()
            } catch is CancellationError {
            } catch {
                guard !Task.isCancelled else { return }
                isRunning = false
                midiStatus = "Fehler: \(error.localizedDescription)"
                redirectStatus = "Fehler"
                addLog("Bridge gestoppt: \(error.localizedDescription)")
            }
        }
    }

    func sendTest(_ send: SendActionSetting, config: BridgeConfig) {
        commandTask?.cancel()
        isSendingCommand = true
        commandStatus = "Sende \(send.target)..."
        commandTask = Task {
            defer { isSendingCommand = false }
            do {
                let client = makeClient(config)
                let events = try await client.candidateEvents(
                    searchDays: config.eventSearchDays,
                    nameContains: config.eventNameContains,
                    requireLockedAgenda: config.requireLockedAgenda
                )
                guard let event = events.first(where: { $0.id == config.preferredEventID }) ?? events.first else {
                    throw BridgeError.noMatchingEvent
                }
                try await client.execute(send.resolvedTarget, eventId: event.id)
                commandStatus = "\(send.target) gesendet"
                addLog("Test-Send \(send.target) für Event #\(event.id) gesendet")
            } catch {
                let detail = Self.errorDetail(error)
                commandStatus = "Fehler: \(detail)"
                addLog("Test-Send fehlgeschlagen: \(detail)")
            }
        }
    }

    func stop() {
        restartGeneration += 1
        bridgeTask?.cancel()
        bridgeTask = nil
        commandTask?.cancel()
        commandTask = nil
        isRunning = false
        midiStatus = "Gestoppt"
        redirectStatus = "Gestoppt"
        isProPresenterConnected = false
        addLog("Bridge gestoppt")
    }

    private func makeClient(_ config: BridgeConfig) -> ChurchToolsClient {
        ChurchToolsClient(baseURL: config.churchToolsBaseURL, token: config.churchToolsToken, csrfToken: config.churchToolsCSRFToken)
    }

    private func apply(_ status: BridgeRuntimeStatus) {
        switch status {
        case .churchToolsConnected:
            hasCheckedConnection = true; churchToolsStatus = "Verbunden"; isChurchToolsConnected = true
            addLog("ChurchTools verbunden")
        case .churchToolsFailed(let message):
            hasCheckedConnection = true; churchToolsStatus = "Fehler: \(message)"; isChurchToolsConnected = false
            addLog("ChurchTools-Fehler: \(message)")
        case .midiListening(let notes):
            midiStatus = "Bereit · \(notes.map(String.init).joined(separator: "/"))"
            addLog("MIDI bereit: Noten \(notes.map(String.init).joined(separator: ", "))")
        case .midiMessageReceived(let note, let channel):
            isProPresenterConnected = true; midiStatus = "Note \(note) · Kanal \(channel)"
            addLog("MIDI Note On empfangen: Note \(note), Kanal \(channel)")
        case .eventOptions(let events, let selectedID):
            availableEvents = events; selectedEventID = selectedID
            addLog("\(events.count) Agenda(s) für den ausgewählten Tag geladen")
        case .eventSelected(let id, let name):
            selectedEventID = id; isChurchToolsConnected = true; churchToolsStatus = "Verbunden · \(name)"
            addLog("Agenda-Cache für Event #\(id) bereit")
        case .noEvent:
            availableEvents = []; selectedEventID = nil; isChurchToolsConnected = true
            churchToolsStatus = "Verbunden · Kein Event"; addLog("Kein passendes ChurchTools-Event gefunden")
        case .commandSucceeded(let command):
            commandStatus = "\(command) gesendet"; addLog("ChurchTools-Send: \(command)")
        case .commandFailed(let message):
            commandStatus = "Fehler: \(message)"; addLog("ChurchTools-Send fehlgeschlagen: \(message)")
        case .redirectListening(let port):
            redirectStatus = "http://127.0.0.1:\(port)/live"; addLog("Lokale Live-Agenda-URL bereit: \(redirectStatus)")
        }
    }

    func clearLog() { logEntries.removeAll() }

    private func addLog(_ message: String) {
        let timestamp = Self.logTimeFormatter.string(from: Date())
        logEntries.append("[\(timestamp)] \(message)")
        if logEntries.count > 200 { logEntries.removeFirst(logEntries.count - 200) }
    }

    private static let logTimeFormatter: DateFormatter = {
        let formatter = DateFormatter(); formatter.locale = Locale(identifier: "de_DE"); formatter.dateFormat = "HH:mm:ss"; return formatter
    }()

    private static func errorDetail(_ error: Error) -> String {
        error is DecodingError ? String(describing: error) : error.localizedDescription
    }
}
