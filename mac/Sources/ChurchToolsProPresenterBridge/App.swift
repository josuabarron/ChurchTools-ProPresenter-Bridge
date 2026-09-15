import AppKit
import SwiftUI

@main
private struct ChurchToolsProPresenterBridgeMain {
    @MainActor
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.accessory)
        app.run()
        _ = delegate
    }
}

@MainActor
private final class AppDelegate: NSObject, NSApplicationDelegate, NSPopoverDelegate {
    private let settings = AppSettings()
    private let controller = BridgeController()
    private let popover = NSPopover()
    private var statusItem: NSStatusItem?
    private var diagnosticsWindow: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        self.statusItem = statusItem

        if let button = statusItem.button {
            button.image = NSImage(systemSymbolName: "list.bullet.clipboard", accessibilityDescription: "ChurchTools Bridge")
            button.action = #selector(togglePopover(_:))
            button.target = self
        }

        let content = BridgeMenuView()
            .environmentObject(settings)
            .environmentObject(controller)
            .environment(\.openDiagnosticsWindow, { [weak self] in self?.openDiagnosticsWindow() })
        popover.contentViewController = NSHostingController(rootView: content)
        popover.behavior = .transient
        popover.delegate = self

        startBridgeAtLaunch()
    }

    @objc private func togglePopover(_ sender: AnyObject?) {
        guard let button = statusItem?.button else { return }
        if popover.isShown {
            popover.performClose(sender)
        } else {
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            popover.contentViewController?.view.window?.makeKey()
        }
    }

    private func startBridgeAtLaunch() {
        let token = settings.loadToken()
        guard !token.isEmpty, !controller.isRunning else { return }
        do {
            try settings.save(token: token)
            controller.start(config: settings.makeConfig(token: token))
        } catch {
            // The settings UI shows validation errors when opened.
        }
    }

    private func openDiagnosticsWindow() {
        if let diagnosticsWindow {
            diagnosticsWindow.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        let content = DiagnosticsView()
            .environmentObject(settings)
            .environmentObject(controller)
        let window = NSWindow(contentViewController: NSHostingController(rootView: content))
        window.title = "ChurchTools Bridge Diagnose"
        window.setContentSize(NSSize(width: 560, height: 390))
        window.styleMask = [.titled, .closable, .miniaturizable, .resizable]
        window.isReleasedWhenClosed = false
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        diagnosticsWindow = window
    }
}

private struct OpenDiagnosticsWindowKey: EnvironmentKey {
    static let defaultValue: () -> Void = {}
}

private extension EnvironmentValues {
    var openDiagnosticsWindow: () -> Void {
        get { self[OpenDiagnosticsWindowKey.self] }
        set { self[OpenDiagnosticsWindowKey.self] = newValue }
    }
}

private struct BridgeMenuView: View {
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var controller: BridgeController
    @Environment(\.openDiagnosticsWindow) private var openDiagnosticsWindow
    @State private var token = ""
    @State private var message: String?
    @State private var showSettings = false
    @State private var didLoad = false
    @State private var saveTask: Task<Void, Never>?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("ChurchTools Bridge").font(.headline)
                    Text(controller.summary).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button(action: openHelp) { Image(systemName: "questionmark.circle") }
                    .buttonStyle(.borderless)
                    .help("Hilfe öffnen")
            }

            if controller.availableEvents.count > 1 {
                Picker("Agenda", selection: eventSelection) {
                    ForEach(controller.availableEvents) { event in
                        Text(event.displayName).tag(event.id)
                    }
                }
                .pickerStyle(.menu)
            }

            Divider()
            StatusRow(title: "ChurchTools", detail: controller.churchToolsStatus, icon: "network")
            StatusRow(title: "ProPresenter MIDI", detail: controller.midiStatus, icon: "pianokeys")
            HStack(spacing: 10) {
                Image(systemName: "link").frame(width: 18).foregroundStyle(.secondary)
                Text("URLs")
                Spacer()
                Button(action: { copyServerURL(.churchTools) }) { Text("CT").font(.caption).fontWeight(.bold) }
                    .buttonStyle(.borderless)
                    .help("ChurchTools Live-URL kopieren")
                    .disabled(!controller.redirectStatus.hasPrefix("http"))
                Button(action: { copyServerURL(.strip) }) { Image(systemName: "rectangle.split.2x1") }
                    .buttonStyle(.borderless)
                    .help("Line-URL kopieren")
                    .disabled(!controller.redirectStatus.hasPrefix("http"))
                Button(action: { copyServerURL(.notes) }) { Image(systemName: "note.text") }
                    .buttonStyle(.borderless)
                    .help("Notes-URL kopieren")
                    .disabled(!controller.redirectStatus.hasPrefix("http"))
            }

            if let status = controller.commandStatus {
                Text(status).font(.caption)
                    .foregroundStyle(status.hasPrefix("Fehler") ? Color.red : Color.secondary)
            }

            Divider()
            DisclosureGroup("Einstellungen", isExpanded: $showSettings) {
                VStack(alignment: .leading, spacing: 14) {
                    churchToolsSettings
                    Divider()
                    sendsSettings
                }
                .padding(.top, 10)
            }

            if let message { Text(message).font(.caption2).foregroundStyle(.secondary) }

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
                    .onTapGesture(count: 3, perform: openDiagnosticsWindow)
                Button("Beenden") { NSApplication.shared.terminate(nil) }
            }
        }
        .padding(16)
        .frame(width: 440)
        .onAppear {
            token = settings.loadToken()
            didLoad = true
            if !token.isEmpty && !controller.isRunning {
                startBridge()
            }
        }
        .onChange(of: token) { _ in autoSave() }
        .onChange(of: settings.baseURL) { _ in autoSave() }
        .onChange(of: settings.eventNameContains) { _ in autoSave() }
        .onChange(of: settings.liveAgendaUserID) { _ in autoSave() }
        .onChange(of: settings.notesFontSize) { _ in saveDisplaySettings() }
        .onChange(of: settings.sends) { _ in autoSave() }
        .onChange(of: settings.requireLockedAgenda) { _ in autoSave() }
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
                LabeledField("Notes-Größe") {
                    TextField("64", value: $settings.notesFontSize, format: .number.grouping(.never))
                }.frame(width: 96)
                Toggle("Nur gesperrte Agenda", isOn: $settings.requireLockedAgenda).padding(.bottom, 3)
            }
            Button("Verbindung prüfen", action: testConnection)
            Toggle("App bei Anmeldung öffnen", isOn: $settings.launchAtLogin)
        }
    }

    private var sendsSettings: some View {
        VStack(alignment: .leading, spacing: 9) {
            Text("Sends").font(.subheadline).fontWeight(.semibold)
            ForEach($settings.sends) { $send in
                HStack(alignment: .bottom, spacing: 8) {
                    LabeledField("Ziel") { TextField("vor, zurück, 3 oder Titel", text: $send.target) }
                    LabeledField("MIDI-Note") {
                        TextField("60", value: $send.midiNote, format: .number.grouping(.never))
                    }.frame(width: 88)
                    // Diesen einen Send von Hand auslösen – ohne auf MIDI zu warten.
                    Button { sendTest(send) } label: { Image(systemName: "play.fill") }
                        .buttonStyle(.borderless)
                        .help("Diesen Send auslösen")
                        .disabled(controller.isSendingCommand)
                        .padding(.bottom, 5)
                    Button {
                        settings.sends.removeAll { $0.id == send.id }
                    } label: { Image(systemName: "trash") }
                    .buttonStyle(.borderless)
                    .help("Send entfernen")
                    .padding(.bottom, 5)
                }
            }
            Button {
                let used = Set(settings.sends.map(\.midiNote))
                let note = (0...127).first { !used.contains($0) } ?? 0
                settings.sends.append(SendActionSetting(target: "", midiNote: note))
            } label: { Label("Send hinzufügen", systemImage: "plus") }
            Text("Zahlen springen zu einer Position. Jeder andere Text sucht den gleichnamigen Agenda-Titel.")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    private var eventSelection: Binding<Int> {
        Binding(
            get: { controller.selectedEventID ?? controller.availableEvents.first?.id ?? 0 },
            set: { id in
                settings.preferredEventID = id
                startBridge()
            }
        )
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

    private func sendTest(_ send: SendActionSetting) {
        do {
            try settings.save(token: token)
            controller.sendTest(send, config: settings.makeConfig(token: token))
        } catch { message = error.localizedDescription; showSettings = true }
    }

    private func copyLog() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(controller.logText, forType: .string)
        message = "Log kopiert"
    }

    private func copyServerURL(_ kind: LocalURLKind) {
        guard let url = localURL(kind) else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(url, forType: .string)
        message = "\(kind.label) kopiert"
    }

    private func openHelp() {
        if let url = localURL(.help).flatMap(URL.init(string:)) {
            NSWorkspace.shared.open(url)
        }
    }

    private func openNotes() {
        if let url = localURL(.notes).flatMap(URL.init(string:)) {
            NSWorkspace.shared.open(url)
        }
    }

    private func localURL(_ kind: LocalURLKind) -> String? {
        guard controller.redirectStatus.hasPrefix("http") else { return nil }
        let root = controller.redirectStatus.hasSuffix("/live")
            ? String(controller.redirectStatus.dropLast(5))
            : controller.redirectStatus
        switch kind {
        case .churchTools: return controller.redirectStatus
        case .strip: return "\(controller.redirectStatus)/strip"
        case .notes: return "\(controller.redirectStatus)/notes"
        case .help: return "\(root)/help"
        }
    }

    private func saveDisplaySettings() {
        guard didLoad else { return }
        do {
            try settings.saveDisplaySettings()
            message = nil
        } catch {
            message = error.localizedDescription
        }
    }
}

private struct DiagnosticsView: View {
    @EnvironmentObject private var settings: AppSettings
    @EnvironmentObject private var controller: BridgeController
    @State private var token = ""
    @State private var message: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Diagnose & Server").font(.headline)
            Text("Abläufe von Hand auslösen").font(.caption).foregroundStyle(.secondary)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 150))], spacing: 8) {
                Button("Verbindung prüfen") { testConnection() }
                Button("CT-URL kopieren") { copyServerURL(.churchTools) }
                    .disabled(!controller.redirectStatus.hasPrefix("http"))
                Button("Line-URL kopieren") { copyServerURL(.strip) }
                    .disabled(!controller.redirectStatus.hasPrefix("http"))
                Button("Notes-URL kopieren") { copyServerURL(.notes) }
                    .disabled(!controller.redirectStatus.hasPrefix("http"))
                Button("Notizen anzeigen") { openNotes() }
                    .disabled(!controller.redirectStatus.hasPrefix("http"))
                Button("Diagnose-Log kopieren") { copyLog() }
                    .disabled(controller.logEntries.isEmpty)
                Button("Log leeren") { controller.clearLog() }
                    .disabled(controller.logEntries.isEmpty)
                Button("Hilfe öffnen") { openHelp() }
                    .disabled(!controller.redirectStatus.hasPrefix("http"))
                Button("Bridge neu starten") { startBridge() }
            }
            LabeledField("Localhost-Port") {
                TextField("8765", value: $settings.redirectPort, format: .number.grouping(.never))
            }
            ScrollView {
                Text(controller.logText.isEmpty ? "Noch keine Einträge" : controller.logText)
                    .font(.system(.caption2, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(8)
            }
            .frame(minHeight: 140)
            .background(Color(NSColor.textBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 6))
            if let message {
                Text(message).font(.caption2).foregroundStyle(.secondary)
            }
        }
        .padding(16)
        .frame(minWidth: 520, minHeight: 360)
        .onAppear { token = settings.loadToken() }
    }

    private func testConnection() {
        do {
            try settings.save(token: token)
            message = nil
            controller.testConnection(config: settings.makeConfig(token: token))
        } catch { message = error.localizedDescription }
    }

    private func startBridge() {
        do {
            try settings.save(token: token)
            message = nil
            controller.start(config: settings.makeConfig(token: token))
        } catch { message = error.localizedDescription }
    }

    private func copyLog() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(controller.logText, forType: .string)
        message = "Log kopiert"
    }

    private func copyServerURL(_ kind: LocalURLKind) {
        guard let url = localURL(kind) else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(url, forType: .string)
        message = "\(kind.label) kopiert"
    }

    private func openHelp() {
        if let url = localURL(.help).flatMap(URL.init(string:)) {
            NSWorkspace.shared.open(url)
        }
    }

    private func openNotes() {
        if let url = localURL(.notes).flatMap(URL.init(string:)) {
            NSWorkspace.shared.open(url)
        }
    }

    private func localURL(_ kind: LocalURLKind) -> String? {
        guard controller.redirectStatus.hasPrefix("http") else { return nil }
        let root = controller.redirectStatus.hasSuffix("/live")
            ? String(controller.redirectStatus.dropLast(5))
            : controller.redirectStatus
        switch kind {
        case .churchTools: return controller.redirectStatus
        case .strip: return "\(controller.redirectStatus)/strip"
        case .notes: return "\(controller.redirectStatus)/notes"
        case .help: return "\(root)/help"
        }
    }
}

private enum LocalURLKind {
    case churchTools
    case strip
    case notes
    case help

    var label: String {
        switch self {
        case .churchTools: return "CT-URL"
        case .strip: return "Line-URL"
        case .notes: return "Notes-URL"
        case .help: return "Hilfe"
        }
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
