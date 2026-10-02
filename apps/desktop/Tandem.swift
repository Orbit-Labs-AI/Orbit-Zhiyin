import AppKit
import WebKit
import Security

// The native host owns process lifetime and system dialogs; Python owns all data logic.
final class AppDelegate: NSObject, NSApplicationDelegate, WKScriptMessageHandler, WKNavigationDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var backend: Process?
    var origin: URL?
    var token = ""
    var stopping = false
    var output = Data()
    var bookmarks: [URL] = []

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let menu = NSMenu()
        let item = NSMenuItem(); menu.addItem(item)
        let appMenu = NSMenu(); item.submenu = appMenu
        appMenu.addItem(withTitle: "Quit Tandem", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let editItem = NSMenuItem(); menu.addItem(editItem)
        let edit = NSMenu(title: "Edit"); editItem.submenu = edit
        for (title, action, key) in [("Copy", "copy:", "c"), ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")] {
            edit.addItem(withTitle: title, action: Selector(action), keyEquivalent: key)
        }
        NSApp.mainMenu = menu
        var bytes = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else { return }
        token = bytes.map { String(format: "%02x", $0) }.joined()
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        config.userContentController.add(self, name: "tandem")
        config.userContentController.addUserScript(WKUserScript(source: "window.__TANDEM_TOKEN__ = '\(token)';", injectionTime: .atDocumentStart, forMainFrameOnly: true))
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1320, height: 900), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Tandem"; window.minSize = NSSize(width: 820, height: 650)
        window.contentView = webView; window.center(); window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        restoreBookmarks()
        startBackend()
    }

    func startBackend() {
        guard let resources = Bundle.main.resourceURL else { return }
        let process = Process()
        process.executableURL = resources.appendingPathComponent("backend/tandem-server")
        let selectedHome = argument("--home") ?? ProcessInfo.processInfo.environment["TANDEM_HOME"] ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("Tandem").path
        process.arguments = ["--assets", resources.appendingPathComponent("tandem-demo.html").path, "--home", selectedHome]
        process.environment = ProcessInfo.processInfo.environment.merging(["TANDEM_API_TOKEN": token, "TANDEM_PARENT_PID": String(getpid())]) { _, new in new }
        let pipe = Pipe(); process.standardOutput = pipe
        let logURL = URL(fileURLWithPath: selectedHome).appendingPathComponent("desktop.log")
        try? FileManager.default.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        FileManager.default.createFile(atPath: logURL.path, contents: nil, attributes: [.posixPermissions: 0o600])
        process.standardError = try? FileHandle(forWritingTo: logURL)
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let chunk = handle.availableData
            guard !chunk.isEmpty else { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.output.append(chunk)
                if let newline = self.output.firstIndex(of: 10) {
                    let line = self.output[..<newline]
                    self.output.removeSubrange(...newline)
                    if let data = try? JSONSerialization.jsonObject(with: line) as? [String: Int], let port = data["port"] {
                        self.origin = URL(string: "http://127.0.0.1:\(port)")
                        self.waitUntilReady(attempt: 0)
                    }
                }
            }
        }
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                guard let self = self, !self.stopping else { return }
                self.showFailure("本地后台已停止。重新打开 Tandem 可恢复数据；中断任务会保留并显示为 interrupted。")
            }
        }
        backend = process
        do { try process.run() } catch { showFailure("无法启动随包后台：\(error.localizedDescription)") }
    }

    func waitUntilReady(attempt: Int) {
        guard let origin = origin else { return }
        var request = URLRequest(url: origin.appendingPathComponent("health")); request.timeoutInterval = 2
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        URLSession.shared.dataTask(with: request) { [weak self] _, response, _ in
            DispatchQueue.main.async {
                guard let self = self else { return }
                if (response as? HTTPURLResponse)?.statusCode == 200 {
                    self.webView.load(URLRequest(url: origin.appendingPathComponent("app")))
                } else if attempt < 60 {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.waitUntilReady(attempt: attempt + 1) }
                } else { self.showFailure("本地后台未就绪，请查看数据目录中的 desktop.log。") }
            }
        }.resume()
    }

    func showFailure(_ message: String) {
        let alert = NSAlert(); alert.messageText = "Tandem 后台需要处理"; alert.informativeText = message
        alert.addButton(withTitle: "关闭"); alert.runModal()
    }

    func argument(_ name: String) -> String? {
        let values = CommandLine.arguments
        guard let index = values.firstIndex(of: name), index + 1 < values.count else { return nil }
        return values[index + 1]
    }

    func restoreBookmarks() {
        for data in UserDefaults.standard.array(forKey: "sourceBookmarks") as? [Data] ?? [] {
            var stale = false
            if let url = try? URL(resolvingBookmarkData: data, options: .withSecurityScope, bookmarkDataIsStale: &stale), url.startAccessingSecurityScopedResource() { bookmarks.append(url) }
        }
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, message.frameInfo.request.url?.host == "127.0.0.1", message.frameInfo.request.url?.port == origin?.port, let body = message.body as? [String: String] else { return }
        if body["action"] == "close" { window.close() }
        else if body["action"] == "minimize" { window.miniaturize(nil) }
        else if body["action"] == "fullscreen" { window.toggleFullScreen(nil) }
        else if body["action"] == "chooseFolder" {
            let panel = NSOpenPanel(); panel.canChooseDirectories = true; panel.canChooseFiles = false
            panel.allowsMultipleSelection = false; panel.showsHiddenFiles = true
            if panel.runModal() == .OK, let url = panel.url {
                if let bookmark = try? url.bookmarkData(options: .withSecurityScope, includingResourceValuesForKeys: nil, relativeTo: nil) {
                    var saved = UserDefaults.standard.array(forKey: "sourceBookmarks") as? [Data] ?? []
                    saved.append(bookmark); UserDefaults.standard.set(saved, forKey: "sourceBookmarks")
                }
                if url.startAccessingSecurityScopedResource() { bookmarks.append(url) }
                if let bytes = try? JSONSerialization.data(withJSONObject: [url.path]), let encoded = String(data: bytes, encoding: .utf8) {
                    webView.evaluateJavaScript("document.getElementById('appRoot').value = \(encoded)[0]")
                }
            }
        } else if body["action"] == "save", let text = body["text"], text.utf8.count <= 50_000_000 {
            let panel = NSSavePanel(); panel.nameFieldStringValue = "tandem-analysis.json"
            if panel.runModal() == .OK, let url = panel.url { try? text.write(to: url, atomically: true, encoding: .utf8) }
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if url.host == origin?.host && url.port == origin?.port { decisionHandler(.allow) }
        else {
            if navigationAction.navigationType == .linkActivated && ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
            decisionHandler(.cancel)
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        stopping = true
        guard let process = backend, process.isRunning else { return .terminateNow }
        process.terminate()
        DispatchQueue.global().async {
            process.waitUntilExit()
            DispatchQueue.main.async { NSApp.reply(toApplicationShouldTerminate: true) }
        }
        return .terminateLater
    }
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
application.run()
