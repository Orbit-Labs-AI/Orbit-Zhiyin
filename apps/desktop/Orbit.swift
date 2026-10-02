import AppKit
import Darwin
import Security
import WebKit

// Orbit native host: owns process lifetime, the window and system dialogs; the bundled
// tandem-helper gateway owns all data logic and serves the single-file UI at /app.
let appVersion = "0.0.1"
let bundleID = "ai.actionmesh.orbit"

func dataHome() -> URL {
    if let home = ProcessInfo.processInfo.environment["TANDEM_HOME"], !home.isEmpty {
        return URL(fileURLWithPath: (home as NSString).expandingTildeInPath)
    }
    return FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        .appendingPathComponent("Tandem")
}

/// One Orbit per data directory: the lock is released by the kernel when the process exits.
func acquireLock(home: URL) -> Bool {
    try? FileManager.default.createDirectory(at: home, withIntermediateDirectories: true,
                                             attributes: [.posixPermissions: 0o700])
    let fd = open(home.appendingPathComponent("orbit.lock").path, O_CREAT | O_RDWR, 0o600)
    guard fd >= 0 else { return true }  // Cannot lock: do not block the launch.
    return flock(fd, LOCK_EX | LOCK_NB) == 0  // fd stays open for the process lifetime.
}

func jsString(_ value: String) -> String {
    let data = (try? JSONSerialization.data(withJSONObject: [value])) ?? Data("[\"\"]".utf8)
    let array = String(data: data, encoding: .utf8) ?? "[\"\"]"
    return String(array.dropFirst().dropLast())
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKScriptMessageHandler,
    WKNavigationDelegate, WKUIDelegate
{
    let home = dataHome()
    var window: NSWindow!
    var webView: WKWebView!
    var backend: Process?
    var origin: URL?
    var token = ""
    var stopping = false
    var restarts = 0
    var loaded = false
    var output = Data()
    var bookmarks: [URL] = []

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        buildMenu()
        token = randomToken()
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        config.userContentController.add(self, name: "tandem")
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.setValue(false, forKey: "drawsBackground")  // No white flash before the page paints.
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1320, height: 860),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                          backing: .buffered, defer: false)
        window.title = "Orbit"
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.isMovableByWindowBackground = false
        window.backgroundColor = NSColor(red: 0xf5 / 255, green: 0xf4 / 255, blue: 0xf0 / 255, alpha: 1)
        window.minSize = NSSize(width: 960, height: 640)
        window.contentView = webView
        window.delegate = self
        window.center()
        window.setFrameAutosaveName("OrbitMainWindow")  // Remembers size and position.
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        restoreBookmarks()
        startBackend()
    }

    // MARK: menu

    func buildMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem(); main.addItem(appItem)
        let app = NSMenu(title: "Orbit"); appItem.submenu = app
        app.addItem(withTitle: "About Orbit", action: #selector(showAbout(_:)), keyEquivalent: "")
        app.addItem(.separator())
        app.addItem(withTitle: "Hide Orbit", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        let others = app.addItem(withTitle: "Hide Others", action: #selector(NSApplication.hideOtherApplications(_:)), keyEquivalent: "h")
        others.keyEquivalentModifierMask = [.command, .option]
        app.addItem(withTitle: "Show All", action: #selector(NSApplication.unhideAllApplications(_:)), keyEquivalent: "")
        app.addItem(.separator())
        app.addItem(withTitle: "Quit Orbit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")

        let editItem = NSMenuItem(); main.addItem(editItem)
        let edit = NSMenu(title: "Edit"); editItem.submenu = edit
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(.separator())
        for (title, action, key) in [("Cut", "cut:", "x"), ("Copy", "copy:", "c"), ("Paste", "paste:", "v"),
                                     ("Select All", "selectAll:", "a")] {
            edit.addItem(withTitle: title, action: Selector((action)), keyEquivalent: key)
        }

        let windowItem = NSMenuItem(); main.addItem(windowItem)
        let win = NSMenu(title: "Window"); windowItem.submenu = win
        win.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        win.addItem(withTitle: "Zoom", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        let full = win.addItem(withTitle: "Enter Full Screen", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
        full.keyEquivalentModifierMask = [.command, .control]
        win.addItem(.separator())
        win.addItem(withTitle: "Reload", action: #selector(reloadPage(_:)), keyEquivalent: "r")
        NSApp.windowsMenu = win
        NSApp.mainMenu = main
    }

    @objc func showAbout(_ sender: Any?) {
        NSApp.orderFrontStandardAboutPanel(options: [
            .applicationName: "Orbit", .applicationVersion: appVersion, .version: appVersion,
        ])
    }

    @objc func reloadPage(_ sender: Any?) {
        if let origin = origin { webView.load(URLRequest(url: origin.appendingPathComponent("app"))) }
    }

    // MARK: backend

    func randomToken() -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
            fatalError("SecRandomCopyBytes failed")
        }
        return bytes.map { String(format: "%02x", $0) }.joined()
    }

    func startBackend() {
        guard let resources = Bundle.main.resourceURL else { return }
        let process = Process()
        process.executableURL = resources.appendingPathComponent("backend/tandem-helper")
        process.arguments = ["gateway", "--home", home.path, "--port", "0",
                             "--assets", resources.appendingPathComponent("orbit.html").path]
        process.environment = ProcessInfo.processInfo.environment.merging(
            ["TANDEM_API_TOKEN": token, "TANDEM_PARENT_PID": String(getpid())]) { _, new in new }
        let pipe = Pipe(); process.standardOutput = pipe
        let logURL = home.appendingPathComponent("desktop.log")
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil, attributes: [.posixPermissions: 0o600])
        }
        if let log = try? FileHandle(forWritingTo: logURL) { log.seekToEndOfFile(); process.standardError = log }
        output = Data()
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let chunk = handle.availableData
            guard !chunk.isEmpty else { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async { self?.consume(chunk, from: process) }
        }
        process.terminationHandler = { [weak self] ended in
            DispatchQueue.main.async { self?.backendExited(ended) }
        }
        backend = process
        do { try process.run() } catch { showFailure("无法启动随包后台：\(error.localizedDescription)") }
    }

    func consume(_ chunk: Data, from process: Process) {
        guard process === backend, origin == nil else { return }
        output.append(chunk)
        guard let newline = output.firstIndex(of: 10) else { return }
        let line = output[..<newline]
        output = Data()
        guard let data = try? JSONSerialization.jsonObject(with: line) as? [String: Any],
              let port = data["port"] as? Int else { return }
        origin = URL(string: "http://127.0.0.1:\(port)")
        waitUntilReady(attempt: 0)
    }

    func waitUntilReady(attempt: Int) {
        guard let origin = origin else { return }
        var request = URLRequest(url: origin.appendingPathComponent("v1/status")); request.timeoutInterval = 2
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        URLSession.shared.dataTask(with: request) { [weak self] _, response, _ in
            DispatchQueue.main.async {
                guard let self = self, self.origin == origin else { return }
                if (response as? HTTPURLResponse)?.statusCode == 200 {
                    self.backendReady(origin)
                } else if attempt < 120 {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.waitUntilReady(attempt: attempt + 1) }
                } else {
                    self.showFailure("本地后台未就绪，请查看数据目录中的 desktop.log：\(self.home.path)")
                }
            }
        }.resume()
    }

    func bootstrapScript(_ origin: URL) -> String {
        let endpoint = jsString(origin.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")))
        return "window.__TANDEM_TOKEN__ = \(jsString(token)); window.__TANDEM_ENDPOINT__ = \(endpoint); window.__ORBIT_NATIVE__ = true;"
    }

    func backendReady(_ origin: URL) {
        let controller = webView.configuration.userContentController
        controller.removeAllUserScripts()
        controller.addUserScript(WKUserScript(source: bootstrapScript(origin), injectionTime: .atDocumentStart,
                                              forMainFrameOnly: true))
        if loaded {
            // Helper restarted: keep the page, hand it the new endpoint and token.
            let endpoint = jsString(origin.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")))
            webView.evaluateJavaScript(bootstrapScript(origin) +
                "window.dispatchEvent(new CustomEvent('tandem:endpoint', {detail: {endpoint: \(endpoint), token: \(jsString(token))}}));")
        } else {
            loaded = true
            webView.load(URLRequest(url: origin.appendingPathComponent("app")))
        }
    }

    func backendExited(_ process: Process) {
        guard process === backend, !stopping else { return }
        if restarts == 0 {
            restarts += 1
            origin = nil
            token = randomToken()
            startBackend()
        } else {
            showFailure("本地后台已停止。重新打开 Orbit 可恢复数据；中断的任务会保留并显示为 interrupted。日志：\(home.appendingPathComponent("desktop.log").path)")
        }
    }

    func showFailure(_ message: String) {
        let alert = NSAlert(); alert.messageText = "Orbit 后台需要处理"; alert.informativeText = message
        alert.addButton(withTitle: "好"); alert.runModal()
    }

    // MARK: bridge

    func restoreBookmarks() {
        for data in UserDefaults.standard.array(forKey: "sourceBookmarks") as? [Data] ?? [] {
            var stale = false
            if let url = try? URL(resolvingBookmarkData: data, options: .withSecurityScope, bookmarkDataIsStale: &stale),
               url.startAccessingSecurityScopedResource() { bookmarks.append(url) }
        }
    }

    func dispatch(_ event: String, _ detail: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: detail),
              let json = String(data: data, encoding: .utf8) else { return }
        webView.evaluateJavaScript("window.dispatchEvent(new CustomEvent(\(jsString(event)), {detail: \(json)}));")
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, let origin = origin,
              let url = message.frameInfo.request.url, url.scheme == "http", url.host == origin.host,
              url.port == origin.port, let body = message.body as? [String: Any],
              let action = body["action"] as? String else { return }
        let id = body["id"] ?? NSNull()
        switch action {
        case "close": window.performClose(nil)
        case "minimize": window.miniaturize(nil)
        case "zoom": window.zoom(nil)
        case "fullscreen": window.toggleFullScreen(nil)
        case "chooseFolder": chooseFolder(id: id)
        case "save": save(body, id: id)
        case "openExternal":
            if let raw = body["url"] as? String, let target = URL(string: raw),
               ["http", "https"].contains(target.scheme?.lowercased() ?? "") { NSWorkspace.shared.open(target) }
        case "reveal":
            if let path = body["path"] as? String, FileManager.default.fileExists(atPath: path) {
                NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
            }
        default: break
        }
    }

    func chooseFolder(id: Any) {
        let panel = NSOpenPanel(); panel.canChooseDirectories = true; panel.canChooseFiles = false
        panel.allowsMultipleSelection = false; panel.showsHiddenFiles = true
        panel.beginSheetModal(for: window) { [weak self] response in
            guard let self = self else { return }
            guard response == .OK, let url = panel.url else {
                self.dispatch("tandem:folder", ["id": id, "path": NSNull()]); return
            }
            if let bookmark = try? url.bookmarkData(options: .withSecurityScope, includingResourceValuesForKeys: nil, relativeTo: nil) {
                var saved = UserDefaults.standard.array(forKey: "sourceBookmarks") as? [Data] ?? []
                saved.append(bookmark); UserDefaults.standard.set(saved, forKey: "sourceBookmarks")
            }
            if url.startAccessingSecurityScopedResource() { self.bookmarks.append(url) }
            self.dispatch("tandem:folder", ["id": id, "path": url.path])
        }
    }

    func save(_ body: [String: Any], id: Any) {
        let data: Data
        if let text = body["text"] as? String { data = Data(text.utf8) }
        else if let encoded = body["base64"] as? String, let decoded = Data(base64Encoded: encoded) { data = decoded }
        else { dispatch("tandem:saved", ["id": id, "ok": false, "error": "no content"]); return }
        guard data.count <= 200_000_000 else { dispatch("tandem:saved", ["id": id, "ok": false, "error": "too large"]); return }
        let panel = NSSavePanel()
        let name = (body["filename"] as? String).map { ($0 as NSString).lastPathComponent } ?? "orbit-export"
        panel.nameFieldStringValue = name.isEmpty ? "orbit-export" : name
        panel.beginSheetModal(for: window) { [weak self] response in
            guard response == .OK, let url = panel.url else {
                self?.dispatch("tandem:saved", ["id": id, "ok": false, "path": NSNull()]); return
            }
            do {
                try data.write(to: url, options: .atomic)
                self?.dispatch("tandem:saved", ["id": id, "ok": true, "path": url.path])
            } catch {
                self?.dispatch("tandem:saved", ["id": id, "ok": false, "error": error.localizedDescription])
            }
        }
    }

    // MARK: navigation

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if ["about", "data", "blob"].contains(url.scheme ?? "") || (url.host == origin?.host && url.port == origin?.port) {
            decisionHandler(.allow)
        } else {
            if ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
            decisionHandler(.cancel)
        }
    }

    // target=_blank links and window.open: open in the default browser, never a second WebView.
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = navigationAction.request.url, ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
        return nil
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { reloadPage(nil) }

    // MARK: lifecycle

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { window.makeKeyAndOrderFront(nil) }
        return true
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        stopping = true
        guard let process = backend, process.isRunning else { return .terminateNow }
        process.terminate()  // SIGTERM: the gateway stops workers and exits gracefully.
        DispatchQueue.global().async {
            let deadline = Date().addingTimeInterval(8)
            while process.isRunning && Date() < deadline { usleep(50_000) }
            if process.isRunning { kill(process.processIdentifier, SIGKILL); process.waitUntilExit() }
            DispatchQueue.main.async { NSApp.reply(toApplicationShouldTerminate: true) }
        }
        return .terminateLater
    }
}

// A second launch for the same data directory activates the running Orbit and exits.
if !acquireLock(home: dataHome()) {
    let me = ProcessInfo.processInfo.processIdentifier
    if let other = NSRunningApplication.runningApplications(withBundleIdentifier: bundleID)
        .first(where: { $0.processIdentifier != me }) {
        other.activate()
    }
    exit(0)
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
application.run()
