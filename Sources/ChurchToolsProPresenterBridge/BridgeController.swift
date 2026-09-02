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

    private var bridgeTask: Task<Void, Never>?
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

    var menuBarIcon: String {
        isChurchToolsConnected && isProPresenterConnected
            ? "checkmark.circle.fill"
            : "circle.fill"
    }

    var menuBarColor: Color {
        switch (isChurchToolsConnected, isProPresenterConnected) {
        case (true, true): return .green
        case (true, false): return .blue
        case (false, true): return .orange
        case (false, false): return .red
        }
    }

    var statusColor: Color { menuBarColor }

    var logText: String { logEntries.joined(separator: "\n") }

    func testConnection(config: BridgeConfig) {
        connectionTask?.cancel()
        churchToolsStatus = "Prüfe..."
        isChurchToolsConnected = false
        addLog("ChurchTools-Verbindung wird geprüft")
        hasCheckedConnection = true
        connectionTask = Task {
            do {
                let client = ChurchToolsClient(
                    baseURL: config.churchToolsBaseURL,
                    token: config.churchToolsToken,
                    csrfToken: config.churchToolsCSRFToken
                )
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
        stop()
        isRunning = true
        addLog("Bridge wird gestartet")
        churchToolsStatus = "Prüfe..."
        midiStatus = "Starte..."
        isProPresenterConnected = false

        bridgeTask = Task {
            let bridge = Bridge(config: config) { [weak self] status in
                Task { @MainActor in self?.apply(status) }
            }
            do {
                try await bridge.run()
            } catch is CancellationError {
                // Normal stop.
            } catch {
                isRunning = false
                midiStatus = "Fehler: \(error.localizedDescription)"
                addLog("Bridge gestoppt: \(error.localizedDescription)")
            }
        }
    }

    func sendTestCommand(_ kind: AgendaCommand.Kind, config: BridgeConfig) {
        commandTask?.cancel()
        isSendingCommand = true
        commandStatus = kind == .next ? "Sende Weiter..." : "Sende Zurück..."

        commandTask = Task {
            defer { isSendingCommand = false }
            do {
                let client = ChurchToolsClient(
                    baseURL: config.churchToolsBaseURL,
                    token: config.churchToolsToken,
                    csrfToken: config.churchToolsCSRFToken
                )
                try await client.checkConnection()
                guard let event = try await client.selectEvent(
                    searchDays: config.eventSearchDays,
                    nameContains: config.eventNameContains,
                    requireLockedAgenda: config.requireLockedAgenda
                ) else {
                    throw BridgeError.noMatchingEvent
                }
                try await client.triggerLiveAgenda(kind, eventId: event.id)
                guard !Task.isCancelled else { return }
                isChurchToolsConnected = true
                churchToolsStatus = "Verbunden · \(event.name)"
                commandStatus = kind == .next ? "Weiter gesendet" : "Zurück gesendet"
                addLog("Testkommando \(kind.rawValue) für Event #\(event.id) gesendet")
            } catch {
                guard !Task.isCancelled else { return }
                let detail = Self.errorDetail(error)
                commandStatus = "Fehler: \(detail)"
                addLog("Testkommando fehlgeschlagen: \(detail)")
            }
        }
    }

    func sendTestPosition(config: BridgeConfig) {
        commandTask?.cancel()
        isSendingCommand = true
        commandStatus = "Gehe zu Position \(config.goToPosition)..."
        commandTask = Task {
            defer { isSendingCommand = false }
            do {
                let client = ChurchToolsClient(
                    baseURL: config.churchToolsBaseURL,
                    token: config.churchToolsToken,
                    csrfToken: config.churchToolsCSRFToken
                )
                guard let event = try await client.selectEvent(
                    searchDays: config.eventSearchDays,
                    nameContains: config.eventNameContains,
                    requireLockedAgenda: config.requireLockedAgenda
                ) else { throw BridgeError.noMatchingEvent }
                try await client.setLiveAgendaPosition(eventId: event.id, position: config.goToPosition)
                commandStatus = "Position \(config.goToPosition) gesetzt"
                addLog("Testkommando Position \(config.goToPosition) für Event #\(event.id) gesendet")
            } catch {
                let detail = Self.errorDetail(error)
                commandStatus = "Fehler: \(detail)"
                addLog("Positionskommando fehlgeschlagen: \(detail)")
            }
        }
    }

    func stop() {
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

    private func apply(_ status: BridgeRuntimeStatus) {
        switch status {
        case .churchToolsConnected:
            hasCheckedConnection = true
            churchToolsStatus = "Verbunden"
            isChurchToolsConnected = true
            addLog("ChurchTools verbunden")
        case .churchToolsFailed(let message):
            hasCheckedConnection = true
            churchToolsStatus = "Fehler: \(message)"
            isChurchToolsConnected = false
            addLog("ChurchTools-Fehler: \(message)")
        case .midiListening(let previousNote, let nextNote, let goToNote):
            midiStatus = "Bereit · Noten \(previousNote)/\(nextNote)/\(goToNote)"
            addLog("MIDI bereit: Zurück=\(previousNote), Weiter=\(nextNote), Position=\(goToNote)")
        case .midiMessageReceived(let note, let channel):
            isProPresenterConnected = true
            midiStatus = "Note \(note) · Kanal \(channel)"
            addLog("MIDI Note On empfangen: Note \(note), Kanal \(channel)")
        case .eventSelected(let name):
            isChurchToolsConnected = true
            churchToolsStatus = "Verbunden · \(name)"
        case .noEvent:
            isChurchToolsConnected = true
            churchToolsStatus = "Verbunden · Kein Event"
            addLog("Kein passendes ChurchTools-Event gefunden")
        case .commandSucceeded(let command):
            commandStatus = "\(command) gesendet"
            addLog("ChurchTools-Kommando gesendet: \(command)")
        case .commandFailed(let message):
            commandStatus = "Fehler: \(message)"
            addLog("ChurchTools-Kommando fehlgeschlagen: \(message)")
        case .redirectListening(let port):
            redirectStatus = "http://127.0.0.1:\(port)/live"
            addLog("Lokale Live-Agenda-URL bereit: \(redirectStatus)")
        }
    }

    func clearLog() {
        logEntries.removeAll()
    }

    private func addLog(_ message: String) {
        let timestamp = Self.logTimeFormatter.string(from: Date())
        logEntries.append("[\(timestamp)] \(message)")
        if logEntries.count > 200 {
            logEntries.removeFirst(logEntries.count - 200)
        }
    }

    private static let logTimeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "de_DE")
        formatter.dateFormat = "HH:mm:ss"
        return formatter
    }()

    private static func errorDetail(_ error: Error) -> String {
        if error is DecodingError { return String(describing: error) }
        return error.localizedDescription
    }
}
