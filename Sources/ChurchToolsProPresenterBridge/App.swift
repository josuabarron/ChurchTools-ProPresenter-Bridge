import SwiftUI

@main
struct ChurchToolsProPresenterBridgeApp: App {
    @StateObject private var settings = AppSettings()
    @StateObject private var controller = BridgeController()

    var body: some Scene {
        MenuBarExtra {
            BridgeMenuView().environmentObject(settings).environmentObject(controller)
        } label: {
            Image(systemName: "list.bullet.clipboard")
                .accessibilityLabel("ChurchTools Bridge: \(controller.summary)")
        }
        .menuBarExtraStyle(.window)
    }
}

private struct BridgeMenuView: View {
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var controller: BridgeController
    @State private var token = ""
    @State private var message: String?
    @State private var showSettings = false
    @State private var showDiagnostics = false
    @State private var didLoad = false
    @State private var saveTask: Task<Void, Never>?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 2) {
                Text("ChurchTools Bridge").font(.headline)
                Text(controller.summary).font(.caption).foregroundStyle(.secondary)
            }

            Divider()
            StatusRow(title: "ChurchTools", detail: controller.churchToolsStatus, icon: "network")
            StatusRow(title: "ProPresenter MIDI", detail: controller.midiStatus, icon: "pianokeys")
            HStack(spacing: 8) {
                StatusRow(title: "Lokale Live-URL", detail: controller.redirectStatus, icon: "link")
                Button(action: copyServerURL) { Image(systemName: "doc.on.doc") }
                    .buttonStyle(.borderless)
                    .help("Lokale Live-Agenda-URL kopieren")
                    .disabled(!controller.redirectStatus.hasPrefix("http"))
            }

            Divider()
            HStack {
                Text("Live-Agenda testen").font(.subheadline)
                Spacer()
                Button { send(.previous) } label: { Label("Zurück", systemImage: "chevron.left") }
                Button { send(.next) } label: { Label("Weiter", systemImage: "chevron.right") }
                Button(action: sendPosition) { Label("Pos. \(settings.goToPosition)", systemImage: "scope") }
            }
            .disabled(controller.isSendingCommand)

            if let status = controller.commandStatus {
                Text(status).font(.caption)
                    .foregroundStyle(status.hasPrefix("Fehler") ? Color.red : Color.secondary)
            }

            Divider()
            DisclosureGroup("Einstellungen", isExpanded: $showSettings) {
                VStack(alignment: .leading, spacing: 14) {
                    churchToolsSettings
                    Divider()
                    proPresenterSettings
                }
                .padding(.top, 10)
            }

            if let message { Text(message).font(.caption2).foregroundStyle(.secondary) }
            if showDiagnostics { diagnostics }

            Divider()
            HStack {
                Button(action: startBridge) {
                    Image(systemName: "arrow.clockwise")
                }
                .keyboardShortcut(.defaultAction)
                .help("Server neu starten")
                Spacer()
                    .frame(maxWidth: .infinity)
                    .frame(minHeight: 24)
                    .contentShape(Rectangle())
                    .onTapGesture(count: 3) {
                        withAnimation { showDiagnostics.toggle() }
                    }
                Button("Beenden") { NSApplication.shared.terminate(nil) }
            }
        }
        .padding(16)
        .frame(width: 440)
        .onAppear {
            token = settings.loadToken()
            didLoad = true
            if !token.isEmpty {
                startBridge()
            }
        }
        .onChange(of: token) { _ in autoSave() }
        .onChange(of: settings.baseURL) { _ in autoSave() }
        .onChange(of: settings.eventNameContains) { _ in autoSave() }
        .onChange(of: settings.liveAgendaUserID) { _ in autoSave() }
        .onChange(of: settings.goToPosition) { _ in autoSave() }
        .onChange(of: settings.requireLockedAgenda) { _ in autoSave() }
        .onChange(of: settings.midiPreviousNote) { _ in autoSave() }
        .onChange(of: settings.midiNextNote) { _ in autoSave() }
        .onChange(of: settings.midiGoToNote) { _ in autoSave() }
        .onChange(of: settings.redirectPort) { _ in autoSave() }
        .onChange(of: settings.launchAtLogin) { enabled in updateLaunchAtLogin(enabled) }
    }

    private var churchToolsSettings: some View {
        VStack(alignment: .leading, spacing: 9) {
            Text("ChurchTools").font(.subheadline).fontWeight(.semibold)
            LabeledField("Server-URL") { TextField("https://…church.tools/api", text: $settings.baseURL) }
            LabeledField("Login-Token") { SecureField("Token", text: $token) }
            LabeledField("Event-Filter") { TextField("Optional", text: $settings.eventNameContains) }
            HStack(alignment: .bottom, spacing: 10) {
                LabeledField("User-ID") {
                    TextField("0", value: $settings.liveAgendaUserID, format: .number.grouping(.never))
                }.frame(width: 82)
                LabeledField("Startposition") {
                    TextField("3", value: $settings.goToPosition, format: .number.grouping(.never))
                }.frame(width: 100)
                Toggle("Nur gesperrte Agenda", isOn: $settings.requireLockedAgenda).padding(.bottom, 3)
            }
            Button("Verbindung prüfen", action: testConnection)
            Toggle("App bei Anmeldung öffnen", isOn: $settings.launchAtLogin)
        }
    }

    private var proPresenterSettings: some View {
        VStack(alignment: .leading, spacing: 9) {
            Text("ProPresenter").font(.subheadline).fontWeight(.semibold)
            HStack(spacing: 10) {
                LabeledField("Zurück") {
                    TextField("60", value: $settings.midiPreviousNote, format: .number.grouping(.never))
                }
                LabeledField("Weiter") {
                    TextField("61", value: $settings.midiNextNote, format: .number.grouping(.never))
                }
                LabeledField("Zur Position") {
                    TextField("62", value: $settings.midiGoToNote, format: .number.grouping(.never))
                }
            }
            Text("MIDI-Noten auf Kanal 1 mit Intensität größer 0 senden. ProPresenter nach dem ersten Start der Bridge neu starten, damit der MIDI-Port sichtbar wird.")
                .font(.caption).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var diagnostics: some View {
        VStack(alignment: .leading, spacing: 9) {
            Divider()
            Text("Diagnose & Server").font(.subheadline).fontWeight(.semibold)
            LabeledField("Localhost-Port") {
                TextField("8765", value: $settings.redirectPort, format: .number.grouping(.never))
            }
            ScrollView {
                Text(controller.logText.isEmpty ? "Noch keine Einträge" : controller.logText)
                    .font(.system(.caption2, design: .monospaced)).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }.frame(height: 110)
            HStack {
                Button(action: copyLog) { Label("Log kopieren", systemImage: "doc.on.doc") }
                    .disabled(controller.logEntries.isEmpty)
                Button { controller.clearLog() } label: { Image(systemName: "trash") }
                    .help("Diagnose-Log leeren").disabled(controller.logEntries.isEmpty)
                Spacer()
            }
        }
    }

    private func autoSave() {
        guard didLoad else { return }
        saveTask?.cancel()
        saveTask = Task {
            try? await Task.sleep(nanoseconds: 600_000_000)
            guard !Task.isCancelled else { return }
            do { try settings.save(token: token); message = nil }
            catch { message = error.localizedDescription }
        }
    }

    private func testConnection() {
        do {
            try settings.save(token: token)
            message = nil
            controller.testConnection(config: settings.makeConfig(token: token))
        } catch { message = error.localizedDescription }
    }

    private func updateLaunchAtLogin(_ enabled: Bool) {
        guard didLoad else { return }
        do {
            try settings.setLaunchAtLogin(enabled)
            message = enabled ? "Autostart aktiviert" : "Autostart deaktiviert"
        } catch {
            message = "Autostart: \(error.localizedDescription)"
        }
    }

    private func startBridge() {
        do {
            try settings.save(token: token)
            message = nil
            controller.start(config: settings.makeConfig(token: token))
        } catch { message = error.localizedDescription }
    }

    private func send(_ kind: AgendaCommand.Kind) {
        do {
            try settings.save(token: token)
            controller.sendTestCommand(kind, config: settings.makeConfig(token: token))
        } catch { message = error.localizedDescription; showSettings = true }
    }

    private func sendPosition() {
        do {
            try settings.save(token: token)
            controller.sendTestPosition(config: settings.makeConfig(token: token))
        } catch { message = error.localizedDescription; showSettings = true }
    }

    private func copyLog() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(controller.logText, forType: .string)
        message = "Log kopiert"
    }

    private func copyServerURL() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(controller.redirectStatus, forType: .string)
        message = "Lokale URL kopiert"
    }
}

private struct LabeledField<Content: View>: View {
    let label: String
    let content: Content

    init(_ label: String, @ViewBuilder content: () -> Content) {
        self.label = label
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label).font(.caption).foregroundStyle(.secondary)
            content.textFieldStyle(.roundedBorder)
        }
    }
}

private struct StatusRow: View {
    let title: String
    let detail: String
    let icon: String

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: icon).frame(width: 18).foregroundStyle(.secondary)
            Text(title)
            Spacer()
            Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(1)
        }
    }
}
