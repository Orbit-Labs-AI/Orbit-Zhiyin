import AppKit
import Darwin
import Security
import UserNotifications
import WebKit

// Orbit native host: owns process lifetime, windows, the menu-bar item, floating panels and
// system dialogs; the bundled tandem-helper gateway owns all data logic and serves the
// single-file UI at /app. Every surface is the same page: /app?surface=panel|hud|widgets.
let appVersion = "0.0.2"
let bundleID = "ai.actionmesh.orbit"
let nativeFeatures = ["window", "chooseFolder", "save", "openExternal", "reveal", "notify", "openMain",
                      "resizeSurface", "onboarded", "commands", "prefs", "surface:panel", "surface:hud", "surface:widgets"]

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

func jsonLiteral(_ value: Any) -> String {
    guard let data = try? JSONSerialization.data(withJSONObject: value),
          let json = String(data: data, encoding: .utf8) else { return "null" }
    return json
}

/// UI preferences shared by every surface (the web views' own storage is non-persistent and the gateway port
/// changes every launch): <data home>/ui-prefs.json, injected as window.__ORBIT_PREFS__ at document start.
/// The page sends {type: "prefs", set: {key: value | null}}; keys merge (null deletes), the file is written
/// atomically, a corrupt or oversized file starts empty, and a merge that would exceed maxBytes is dropped.
final class UIPrefs {
    static let maxBytes = 256 * 1024
    let url: URL
    private(set) var values: [String: Any] = [:]

    init(home: URL) {
        url = home.appendingPathComponent("ui-prefs.json")
        if let data = try? Data(contentsOf: url), data.count <= UIPrefs.maxBytes,
           let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] { values = object }
    }

    /// Returns the accepted changes, or nil when nothing changed or the result would be too large.
    func merge(_ changes: [String: Any]) -> [String: Any]? {
        var next = values
        var accepted: [String: Any] = [:]
        for (key, value) in changes where !key.isEmpty && key.count <= 128 {
            if value is NSNull { next.removeValue(forKey: key) }
            else if JSONSerialization.isValidJSONObject([value]) { next[key] = value }
            else { continue }
            accepted[key] = value
        }
        guard !accepted.isEmpty,
              let data = try? JSONSerialization.data(withJSONObject: next, options: [.sortedKeys]),
              data.count <= UIPrefs.maxBytes else { return nil }
        values = next
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true,
                                                 attributes: [.posixPermissions: 0o700])
        if (try? data.write(to: url, options: .atomic)) != nil {
            try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
        }
        return accepted
    }
}

enum Surface: String { case main, panel, hud, widgets }

/// WKUserContentController retains its handlers; this proxy keeps that reference weak so
/// every web view shares one handler implementation (AppDelegate.handle) without a cycle.
final class BridgeProxy: NSObject, WKScriptMessageHandler {
    weak var app: AppDelegate?
    init(_ app: AppDelegate) { self.app = app }
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        app?.receive(message)
    }
}

/// One web view showing one surface of the UI.
final class WebHost {
    let surface: Surface
    let webView: WKWebView
    var loaded = false
    init(surface: Surface, webView: WKWebView) { self.surface = surface; self.webView = webView }
}

/// The page's web view: the default WebKit context menu (重新载入, 返回, 检查元素…) is not Orbit's; only text editing
/// items (拷贝 / 粘贴 / 查询…) stay, plus 拷贝链接 on a link.
final class OrbitWebView: WKWebView {
    static let keep: Set<String> = ["WKMenuItemIdentifierCopy", "WKMenuItemIdentifierCut", "WKMenuItemIdentifierPaste",
                                    "WKMenuItemIdentifierLookUp", "WKMenuItemIdentifierSearchWeb", "WKMenuItemIdentifierShareMenu",
                                    "WKMenuItemIdentifierSpellingMenu", "WKMenuItemIdentifierCopyLink",
                                    "WKMenuItemIdentifierTranslate", "WKMenuItemIdentifierSpeechMenu"]
    override func willOpenMenu(_ menu: NSMenu, with event: NSEvent) {
        for item in menu.items.reversed() {
            let id = item.identifier?.rawValue ?? ""
            if item.isSeparatorItem || OrbitWebView.keep.contains(id) { continue }
            menu.removeItem(item)
        }
        while let first = menu.items.first, first.isSeparatorItem { menu.removeItem(first) }
        while let last = menu.items.last, last.isSeparatorItem { menu.removeItem(last) }
        super.willOpenMenu(menu, with: event)
    }
}

/// Borderless floating panel (HUD, widgets): may take key for text input without activating
/// Orbit; drag with ⌘ held, or by the top 12 pt strip, to move it (the page fills the rest).
final class FloatingPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
    override func sendEvent(_ event: NSEvent) {
        if event.type == .leftMouseDown,
           event.modifierFlags.contains(.command) || event.locationInWindow.y > frame.height - 12 {
            performDrag(with: event)
            return
        }
        super.sendEvent(event)
    }
}

/// Main window: the page fills the whole frame (transparent title bar), so the host decides where a press moves the window.
/// A ring 3–8 pt inside every edge (the outer 3 pt stay with the system's resize) and the title-bar strip drag the window;
/// the page reports rects that must keep their clicks (buttons, fields, scroll bars) and extra blank rects that should
/// drag (page header, sidebar top) through the "dragRegions" bridge message. Double-click in the title area follows the
/// system "double-click a window's title bar" setting. Full screen keeps every event for the page.
final class MainWindow: NSWindow {
    static let edgeOuter: CGFloat = 3, edgeInner: CGFloat = 8, titleBand: CGFloat = 38
    var noDragRects: [NSRect] = []  // page coordinates (top-left origin, CSS px = points)
    var dragRects: [NSRect] = []
    weak var dragView: NSView?

    func updateRegions(_ body: [String: Any]) {
        func rects(_ key: String) -> [NSRect] {
            ((body[key] as? [Any]) ?? []).prefix(400).compactMap { raw in
                guard let a = raw as? [NSNumber], a.count == 4 else { return nil }
                let r = NSRect(x: a[0].doubleValue, y: a[1].doubleValue, width: a[2].doubleValue, height: a[3].doubleValue)
                return r.width > 0 && r.height > 0 && r.width.isFinite && r.height.isFinite ? r : nil
            }
        }
        noDragRects = rects("noDrag")
        dragRects = rects("drag")
    }

    /// nil = leave the event alone; true = title area (double-click applies), false = edge ring only.
    func dragZone(_ event: NSEvent) -> Bool? {
        guard !styleMask.contains(.fullScreen), let content = contentView, let view = dragView else { return nil }
        // Traffic lights and any other title-bar control sit above the page: never take their clicks.
        guard let hit = content.superview?.hitTest(event.locationInWindow) ?? content.hitTest(event.locationInWindow),
              hit === view || hit.isDescendant(of: view) else { return nil }
        let size = content.bounds.size
        let p = NSPoint(x: event.locationInWindow.x, y: size.height - event.locationInWindow.y)
        let edge = min(p.x, p.y, size.width - p.x, size.height - p.y)
        if edge < Self.edgeOuter { return nil }
        if noDragRects.contains(where: { $0.contains(p) }) { return nil }
        if p.y <= Self.titleBand || dragRects.contains(where: { $0.contains(p) }) { return true }
        return edge <= Self.edgeInner ? false : nil
    }

    override func sendEvent(_ event: NSEvent) {
        if event.type == .leftMouseDown, event.modifierFlags.intersection([.command, .control, .option, .shift]).isEmpty,
           let title = dragZone(event) {
            if event.clickCount == 2 {
                if title { titleDoubleClick() }
                return
            }
            performDrag(with: event)
            return
        }
        super.sendEvent(event)
    }

    func titleDoubleClick() {
        let defaults = UserDefaults.standard
        let action = defaults.string(forKey: "AppleActionOnDoubleClick")
            ?? (defaults.bool(forKey: "AppleMiniaturizeOnDoubleClick") ? "Minimize" : "Maximize")
        switch action {
        case "Minimize": performMiniaturize(nil)
        case "None": break
        default: performZoom(nil)  // "Maximize" and "Fill" (macOS 15) both zoom.
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate,
    NSPopoverDelegate, NSMenuItemValidation, UNUserNotificationCenterDelegate
{
    let home = dataHome()
    var window: MainWindow!
    var hosts: [Surface: WebHost] = [:]
    var statusItem: NSStatusItem?
    var popover: NSPopover?
    var hudPanel: FloatingPanel?
    var widgetsPanel: FloatingPanel?
    var backend: Process?
    var origin: URL?
    var token = ""
    var stopping = false
    var restarts = 0
    var output = Data()
    var bookmarks: [URL] = []
    var notificationsAsked = false
    lazy var bridge = BridgeProxy(self)

    var mainWebView: WKWebView { hosts[.main]!.webView }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        buildMenu()
        token = randomToken()
        let main = makeHost(.main)
        window = MainWindow(contentRect: NSRect(x: 0, y: 0, width: 1320, height: 860),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                          backing: .buffered, defer: false)
        window.title = "Orbit"
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.isMovableByWindowBackground = false
        window.isReleasedWhenClosed = false  // Closing hides it; the menu-bar item keeps Orbit running.
        window.backgroundColor = NSColor(red: 0xf5 / 255, green: 0xf4 / 255, blue: 0xf0 / 255, alpha: 1)
        window.minSize = NSSize(width: 960, height: 640)
        window.contentView = main.webView
        window.dragView = main.webView
        window.delegate = self
        window.center()
        window.setFrameAutosaveName("OrbitMainWindow")  // Remembers size and position.
        resetFrameIfOffscreen(window)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        if Bundle.main.bundleIdentifier != nil { UNUserNotificationCenter.current().delegate = self }
        buildStatusItem()
        // First launch keeps the HUD hidden until the page reports onboarding done ("onboarded").
        if UserDefaults.standard.bool(forKey: "hudVisible") { setPanel(.hud, visible: true) }
        if UserDefaults.standard.bool(forKey: "widgetsVisible") { setPanel(.widgets, visible: true) }
        // Smoke checks without Accessibility access: ORBIT_DEBUG_SURFACES=panel,hud,widgets opens
        // those surfaces at launch without persisting their visibility.
        for name in (ProcessInfo.processInfo.environment["ORBIT_DEBUG_SURFACES"] ?? "").split(separator: ",") {
            switch Surface(rawValue: name.trimmingCharacters(in: .whitespaces)) {
            case .hud: (hudPanel ?? makePanel(.hud)).orderFrontRegardless()
            case .widgets: (widgetsPanel ?? makePanel(.widgets)).orderFrontRegardless()
            case .panel:
                DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
                    if let button = self.statusItem?.button { self.statusClicked(button) }
                }
            default: break
            }
        }
        restoreBookmarks()
        startBackend()
    }

    // MARK: web views

    func makeHost(_ surface: Surface) -> WebHost {
        if let existing = hosts[surface] { return existing }
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        config.userContentController.add(bridge, name: "tandem")
        let webView = OrbitWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.setValue(false, forKey: "drawsBackground")  // No white flash; surfaces stay transparent.
        webView.underPageBackgroundColor = .clear
        let host = WebHost(surface: surface, webView: webView)
        hosts[surface] = host
        if let origin = origin { load(host, origin) }
        return host
    }

    func host(of webView: WKWebView?) -> WebHost? { hosts.values.first { $0.webView === webView } }

    func pageURL(_ origin: URL, _ surface: Surface) -> URL {
        var parts = URLComponents(url: origin.appendingPathComponent("app"), resolvingAgainstBaseURL: false)!
        if surface != .main { parts.queryItems = [URLQueryItem(name: "surface", value: surface.rawValue)] }
        return parts.url!
    }

    func endpoint(_ origin: URL) -> String {
        origin.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    }

    func bootstrapScript(_ origin: URL) -> String {
        let native: [String: Any] = ["v": 1, "app": appVersion, "platform": "macos", "features": nativeFeatures]
        return "window.__TANDEM_TOKEN__ = \(jsString(token)); window.__TANDEM_ENDPOINT__ = \(jsString(endpoint(origin)));" +
            " window.__ORBIT_NATIVE__ = \(jsonLiteral(native)); window.__ORBIT_PREFS__ = \(jsonLiteral(prefs.values));"
    }

    /// Installs the document-start bootstrap and loads the page, or (after a helper restart)
    /// keeps the page and hands it the new endpoint and token.
    func load(_ host: WebHost, _ origin: URL) {
        let controller = host.webView.configuration.userContentController
        controller.removeAllUserScripts()
        controller.addUserScript(WKUserScript(source: bootstrapScript(origin), injectionTime: .atDocumentStart,
                                              forMainFrameOnly: true))
        if host.loaded {
            host.webView.evaluateJavaScript(bootstrapScript(origin))
            dispatch("tandem:endpoint", ["endpoint": endpoint(origin), "token": token], to: host)
        } else {
            host.loaded = true
            host.webView.load(URLRequest(url: pageURL(origin, host.surface)))
        }
    }

    func dispatch(_ event: String, _ detail: [String: Any], to host: WebHost?) {
        guard let host = host else { return }
        host.webView.evaluateJavaScript(
            "window.dispatchEvent(new CustomEvent(\(jsString(event)), {detail: \(jsonLiteral(detail))}));")
    }

    // MARK: menu

    func buildMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem(); main.addItem(appItem)
        let app = NSMenu(title: "Orbit"); appItem.submenu = app
        app.addItem(command("关于 Orbit", "about"))
        app.addItem(.separator())
        app.addItem(command("设置…", "settings", key: ","))
        app.addItem(.separator())
        let servicesItem = app.addItem(withTitle: "服务", action: nil, keyEquivalent: "")
        let services = NSMenu(title: "服务"); servicesItem.submenu = services
        NSApp.servicesMenu = services
        app.addItem(.separator())
        app.addItem(withTitle: "隐藏 Orbit", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        let others = app.addItem(withTitle: "隐藏其他", action: #selector(NSApplication.hideOtherApplications(_:)), keyEquivalent: "h")
        others.keyEquivalentModifierMask = [.command, .option]
        app.addItem(withTitle: "全部显示", action: #selector(NSApplication.unhideAllApplications(_:)), keyEquivalent: "")
        app.addItem(.separator())
        app.addItem(withTitle: "退出 Orbit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")

        // 文件: the demo's file menu (exports + close); exports open the page's export sheets.
        let fileItem = NSMenuItem(); main.addItem(fileItem)
        let file = NSMenu(title: "文件"); fileItem.submenu = file
        file.addItem(command("导出报告…", "report", key: "e", mods: [.command, .shift]))
        file.addItem(command("导出分享卡…", "share", key: "s", mods: [.command, .shift]))
        file.addItem(command("导出工具明细 CSV…", "csv"))
        file.addItem(.separator())
        file.addItem(withTitle: "关闭窗口", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")

        let editItem = NSMenuItem(); main.addItem(editItem)
        let edit = NSMenu(title: "编辑"); editItem.submenu = edit
        edit.addItem(withTitle: "撤销", action: #selector(undoAction(_:)), keyEquivalent: "z").target = self
        let redo = edit.addItem(withTitle: "重做", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(.separator())
        for (title, action, key) in [("剪切", "cut:", "x"), ("拷贝", "copy:", "c"), ("粘贴", "paste:", "v"),
                                     ("全选", "selectAll:", "a")] {
            edit.addItem(withTitle: title, action: Selector((action)), keyEquivalent: key)
        }
        edit.addItem(.separator())
        edit.addItem(command("查找", "find", key: "f"))

        let viewItem = NSMenuItem(); main.addItem(viewItem)
        let view = NSMenu(title: "显示"); viewItem.submenu = view
        view.addItem(command("命令面板", "palette", key: "k"))
        view.addItem(command("切换 Lite / Advance", "toggleEdition", key: "l", mods: [.command, .control]))
        view.addItem(command("隐藏侧边栏", "sidebar", key: "s", mods: [.command, .control]))  // title follows menuState
        view.addItem(command("图表 / 表格", "chartTable", key: "t"))
        view.addItem(.separator())
        view.addItem(command("刷新", "refresh", key: "r"))
        let reload = view.addItem(withTitle: "重新载入页面", action: #selector(reloadPage(_:)), keyEquivalent: "r")
        reload.keyEquivalentModifierMask = [.command, .shift]

        // 前往: the edition's pages (⌘1–9, titles from the page's menuState), back and the page's main action.
        let goItem = NSMenuItem(); main.addItem(goItem)
        let go = NSMenu(title: "前往"); goItem.submenu = go
        for n in 1...9 { go.addItem(pageItem(n)) }
        go.addItem(.separator())
        go.addItem(command("返回", "back", key: "["))
        go.addItem(command("当前页主操作", "mainAction", key: "\r"))
        goMenu = go
        applyPageTitles()

        let windowItem = NSMenuItem(); main.addItem(windowItem)
        let win = NSMenu(title: "窗口"); windowItem.submenu = win
        win.addItem(withTitle: "最小化", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        win.addItem(withTitle: "缩放", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        let full = win.addItem(withTitle: "进入全屏幕", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
        full.keyEquivalentModifierMask = [.command, .control]
        win.addItem(.separator())
        win.addItem(withTitle: "Orbit 主窗口", action: #selector(showMain(_:)), keyEquivalent: "0")
        // ⌥⌘P matches the page's HUD key (85-keyboard.js); ⌥⌘H stays with 隐藏其他 and ⌥⌘W with the system's 全部关闭.
        let hud = win.addItem(withTitle: "显示 HUD", action: #selector(toggleHUD(_:)), keyEquivalent: "p")
        hud.keyEquivalentModifierMask = [.command, .option]
        let widgets = win.addItem(withTitle: "桌面小组件", action: #selector(toggleWidgets(_:)), keyEquivalent: "d")
        widgets.keyEquivalentModifierMask = [.command, .option]
        win.addItem(.separator())
        win.addItem(withTitle: "前置全部窗口", action: #selector(NSApplication.arrangeInFront(_:)), keyEquivalent: "")
        NSApp.windowsMenu = win

        // 帮助: setting helpMenu gives the system search field at the top of this menu.
        let helpItem = NSMenuItem(); main.addItem(helpItem)
        let help = NSMenu(title: "帮助"); helpItem.submenu = help
        help.addItem(command("键盘快捷键", "keys", key: "?"))
        help.addItem(command("重新打开导入向导", "onboarding"))
        help.addItem(command("播放人格揭晓", "reveal"))
        help.addItem(.separator())
        help.addItem(command("关于 Orbit", "about"))
        NSApp.helpMenu = help
        NSApp.mainMenu = main
    }

    static let defaultPages = ["概览", "协作画像", "会话轨迹", "优化建议", "", "", "", "", ""]  // Lite, the App's first edition
    var pageTitles: [String] = AppDelegate.defaultPages
    var sidebarVisible = true
    weak var goMenu: NSMenu?

    func pageItem(_ n: Int) -> NSMenuItem {
        let item = NSMenuItem(title: "页面 \(n)", action: #selector(sendCommand(_:)), keyEquivalent: String(n))
        item.keyEquivalentModifierMask = .command
        item.representedObject = ["cmd": "page", "n": n] as [String: Any]
        item.target = self
        item.tag = n
        return item
    }

    /// Page titles of the edition in use; pages the edition does not have are hidden (Lite has four).
    func applyPageTitles() {
        guard let go = goMenu else { return }
        for item in go.items where item.tag >= 1 && item.tag <= 9 {
            let title = item.tag <= pageTitles.count ? pageTitles[item.tag - 1] : ""
            item.title = title.isEmpty ? "页面 \(item.tag)" : title
            item.isHidden = title.isEmpty
        }
    }

    /// {type: "menuState", sidebar: Bool, pages: [String]} from the main window's page.
    func updateMenuState(_ body: [String: Any]) {
        if let side = body["sidebar"] as? Bool { sidebarVisible = side }
        if let pages = body["pages"] as? [String] { pageTitles = Array(pages.prefix(9)); applyPageTitles() }
    }

    /// Edit › 撤销: the page's undo-install when it has one and no text field owns ⌘Z; otherwise the responder chain.
    @objc func undoAction(_ sender: Any?) {
        let key = NSApp.keyWindow
        guard key === window, let main = hosts[.main], main.loaded else {
            NSApp.sendAction(Selector(("undo:")), to: nil, from: sender); return
        }
        main.webView.evaluateJavaScript("typeof LVN !== 'undefined' && !!LVN.canUndo && LVN.canUndo()") { [weak self] result, _ in
            if (result as? Bool) == true { self?.dispatch("tandem:command", ["cmd": "undo"], to: main) }
            else { NSApp.sendAction(Selector(("undo:")), to: nil, from: sender) }
        }
    }

    func command(_ title: String, _ cmd: String, key: String = "", mods: NSEvent.ModifierFlags = .command) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: #selector(sendCommand(_:)), keyEquivalent: key)
        item.keyEquivalentModifierMask = mods
        item.representedObject = cmd
        item.target = self
        return item
    }

    /// Menu commands go to the main window's page as tandem:command.
    @objc func sendCommand(_ sender: NSMenuItem) {
        let detail: [String: Any]
        if let cmd = sender.representedObject as? String { detail = ["cmd": cmd] }
        else if let object = sender.representedObject as? [String: Any], object["cmd"] is String { detail = object }
        else { return }
        showMain(nil)
        dispatch("tandem:command", detail, to: hosts[.main])
    }

    @objc func reloadPage(_ sender: Any?) {
        guard let origin = origin else { return }
        let target = hosts.values.first { $0.webView.window?.isKeyWindow == true } ?? hosts[.main]!
        target.webView.load(URLRequest(url: pageURL(origin, target.surface)))
    }

    /// A restored frame can sit on a display that is gone (or fully off every visible area):
    /// recentre it at the default size on the main screen so the window is never lost.
    func resetFrameIfOffscreen(_ win: NSWindow) {
        let frame = win.frame
        let visible = NSScreen.screens.contains { screen in
            let overlap = screen.visibleFrame.intersection(frame)
            return !overlap.isNull && overlap.width >= 120 && overlap.height >= 60
        }
        guard !visible, let screen = NSScreen.main ?? NSScreen.screens.first else { return }
        let area = screen.visibleFrame
        let size = NSSize(width: min(1320, area.width), height: min(860, area.height))
        win.setFrame(NSRect(x: area.midX - size.width / 2, y: area.midY - size.height / 2,
                            width: size.width, height: size.height), display: false)
    }

    @objc func showMain(_ sender: Any?) {
        popover?.performClose(nil)
        if window.isMiniaturized { window.deminiaturize(nil) }
        resetFrameIfOffscreen(window)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc func toggleHUD(_ sender: Any?) { setPanel(.hud, visible: !(hudPanel?.isVisible ?? false)) }
    @objc func toggleWidgets(_ sender: Any?) { setPanel(.widgets, visible: !(widgetsPanel?.isVisible ?? false)) }

    func validateMenuItem(_ item: NSMenuItem) -> Bool {
        if item.action == #selector(toggleHUD(_:)) { item.state = hudPanel?.isVisible == true ? .on : .off }
        if item.action == #selector(toggleWidgets(_:)) { item.state = widgetsPanel?.isVisible == true ? .on : .off }
        if item.action == #selector(sendCommand(_:)), item.representedObject as? String == "sidebar" {
            item.title = sidebarVisible ? "隐藏侧边栏" : "显示侧边栏"
        }
        return true
    }

    // MARK: menu-bar item and floating panels

    func buildStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let image = NSImage(named: "StatusIcon") {
            image.isTemplate = true  // orbit-mark-small.svg rendered verbatim; the menu bar tints it.
            image.size = NSSize(width: image.size.width * 16 / max(image.size.height, 1), height: 16)
            item.button?.image = image
        } else {
            item.button?.title = "Orbit"
        }
        item.button?.toolTip = "Orbit"
        item.button?.target = self
        item.button?.action = #selector(statusClicked(_:))
        item.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])
        statusItem = item
    }

    @objc func statusClicked(_ sender: NSStatusBarButton) {
        if NSApp.currentEvent?.type == .rightMouseUp || NSApp.currentEvent?.modifierFlags.contains(.control) == true {
            let menu = NSMenu()
            menu.addItem(withTitle: "打开 Orbit", action: #selector(showMain(_:)), keyEquivalent: "").target = self
            menu.addItem(withTitle: "显示 HUD", action: #selector(toggleHUD(_:)), keyEquivalent: "").target = self
            menu.addItem(withTitle: "桌面小组件", action: #selector(toggleWidgets(_:)), keyEquivalent: "").target = self
            menu.addItem(.separator())
            menu.addItem(withTitle: "退出 Orbit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "")
            statusItem?.menu = menu
            sender.performClick(nil)  // Shows the menu; detach it so left clicks open the popover again.
            statusItem?.menu = nil
            return
        }
        if let popover = popover, popover.isShown { popover.performClose(nil); return }
        let pop = popover ?? makePopover()
        pop.show(relativeTo: sender.bounds, of: sender, preferredEdge: .minY)
        pop.contentViewController?.view.window?.makeKey()
    }

    func makePopover() -> NSPopover {
        let host = makeHost(.panel)
        let controller = NSViewController()
        controller.view = host.webView
        let pop = NSPopover()
        pop.behavior = .transient
        pop.animates = true
        pop.contentSize = NSSize(width: 360, height: 560)
        pop.contentViewController = controller
        pop.delegate = self
        popover = pop
        return pop
    }

    func setPanel(_ surface: Surface, visible: Bool) {
        guard surface == .hud || surface == .widgets else { return }
        UserDefaults.standard.set(visible, forKey: surface == .hud ? "hudVisible" : "widgetsVisible")
        let existing = surface == .hud ? hudPanel : widgetsPanel
        if !visible { existing?.orderOut(nil); return }
        let panel = existing ?? makePanel(surface)
        panel.orderFrontRegardless()
    }

    func makePanel(_ surface: Surface) -> FloatingPanel {
        let screen = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        // Start at the surface's own size: the HUD pill is ~80 pt tall and the widgets column is 364 pt wide (98-live-ops.js
        // body.surface-widgets #widgets), so no transparent margin covers other windows before the first resizeSurface.
        let size = surface == .hud ? NSSize(width: 340, height: 80) : NSSize(width: AppDelegate.widgetsWidth, height: 480)
        let offset: CGFloat = surface == .hud ? 0 : 360  // Widgets sit left of the HUD by default.
        let frame = NSRect(x: screen.maxX - size.width - 20 - offset, y: screen.maxY - size.height - 20,
                           width: size.width, height: size.height)
        let panel = FloatingPanel(contentRect: frame, styleMask: [.borderless, .nonactivatingPanel],
                                  backing: .buffered, defer: false)
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.hasShadow = false  // The page draws its own card shadow on a transparent body.
        panel.hidesOnDeactivate = false
        panel.becomesKeyOnlyIfNeeded = true
        panel.isReleasedWhenClosed = false
        panel.contentView = makeHost(surface).webView
        panel.setFrameAutosaveName(surface == .hud ? "OrbitHUD" : "OrbitWidgets")  // Remembers position.
        if surface == .widgets, panel.frame.width != AppDelegate.widgetsWidth {  // an older build saved 320 pt
            var f = panel.frame; f.size.width = AppDelegate.widgetsWidth; panel.setFrame(f, display: false)
        }
        if surface == .hud { hudPanel = panel } else { widgetsPanel = panel }
        return panel
    }

    static let widgetsWidth: CGFloat = 364

    /// The page reports its component's size; the HUD also reports its width so the panel never extends past the pill
    /// (the transparent rest of a wider window would swallow clicks meant for the windows below).
    func resizeSurface(_ host: WebHost, height raw: Double, width rawWidth: Double? = nil) {
        let height = CGFloat(min(max(raw, host.surface == .hud ? 32 : 80), 900))
        switch host.surface {
        case .panel: popover?.contentSize = NSSize(width: popover?.contentSize.width ?? 360, height: height)
        case .hud, .widgets:
            guard let panel = host.webView.window else { return }
            var frame = panel.frame
            frame.origin.y += frame.height - height  // Keep the top edge where the user put it.
            frame.size.height = height
            if host.surface == .hud, let w = rawWidth, w.isFinite {
                let width = CGFloat(min(max(w, 120), 520))
                frame.origin.x += frame.width - width  // Keep the right edge (the HUD sits at the top right).
                frame.size.width = width
            }
            panel.setFrame(frame, display: true, animate: false)
        case .main: break
        }
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
                    for host in self.hosts.values { self.load(host, origin) }
                } else if attempt < 120 {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.waitUntilReady(attempt: attempt + 1) }
                } else {
                    self.showFailure("本地后台未就绪，请查看数据目录中的 desktop.log：\(self.home.path)")
                }
            }
        }.resume()
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

    // MARK: bridge (page -> host)

    func restoreBookmarks() {
        for data in UserDefaults.standard.array(forKey: "sourceBookmarks") as? [Data] ?? [] {
            var stale = false
            if let url = try? URL(resolvingBookmarkData: data, options: .withSecurityScope, bookmarkDataIsStale: &stale),
               url.startAccessingSecurityScopedResource() { bookmarks.append(url) }
        }
    }

    lazy var prefs = UIPrefs(home: home)

    /// Saves a surface's changed preference keys, passes them to the other surfaces and refreshes every
    /// document-start bootstrap so a reload sees the current values.
    func savePrefs(_ body: [String: Any], from host: WebHost) {
        guard let changes = body["set"] as? [String: Any], let accepted = prefs.merge(changes) else { return }
        for other in hosts.values where other !== host { dispatch("tandem:prefs", ["set": accepted], to: other) }
        guard let origin = origin else { return }
        for each in hosts.values where each.loaded {
            let controller = each.webView.configuration.userContentController
            controller.removeAllUserScripts()
            controller.addUserScript(WKUserScript(source: bootstrapScript(origin), injectionTime: .atDocumentStart,
                                                  forMainFrameOnly: true))
        }
    }

    /// The one message handler for every web view: only the gateway's own pages may call it.
    func receive(_ message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, let origin = origin, let host = host(of: message.webView),
              let url = message.frameInfo.request.url, url.scheme == "http", url.host == origin.host,
              url.port == origin.port, let body = message.body as? [String: Any],
              let type = (body["type"] ?? body["action"]) as? String else { return }
        let id = body["id"] ?? NSNull()
        switch type {
        case "close", "minimize", "zoom", "fullscreen": windowOp(type, host)
        case "chooseFolder": chooseFolder(body, id: id, host: host)
        case "save": save(body, id: id, host: host)
        case "openExternal":
            if let raw = body["url"] as? String, let target = URL(string: raw),
               ["http", "https"].contains(target.scheme?.lowercased() ?? "") { NSWorkspace.shared.open(target) }
        case "reveal":
            if let path = body["path"] as? String, FileManager.default.fileExists(atPath: path) {
                NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
            }
        case "notify": notify(body)
        case "prefs": savePrefs(body, from: host)
        case "openMain": openMain(route: body["route"] as? String)
        case "onboarded":
            // Show the HUD once onboarding finishes, unless the user has already hidden it.
            if UserDefaults.standard.object(forKey: "hudVisible") == nil { setPanel(.hud, visible: true) }
        case "dragRegions": if host.surface == .main { window.updateRegions(body) }
        case "menuState": if host.surface == .main { updateMenuState(body) }
        case "resizeSurface":
            if let height = (body["height"] as? NSNumber)?.doubleValue {
                resizeSurface(host, height: height, width: (body["width"] as? NSNumber)?.doubleValue)
            }
        default: break
        }
    }

    func windowOp(_ op: String, _ host: WebHost) {
        switch host.surface {
        case .main:
            switch op {
            case "close": window.performClose(nil)
            case "minimize": window.miniaturize(nil)
            case "zoom": window.zoom(nil)
            default: window.toggleFullScreen(nil)
            }
        case .panel: if op == "close" { popover?.performClose(nil) }
        case .hud, .widgets: if op == "close" { setPanel(host.surface, visible: false) }
        }
    }

    func openMain(route: String?) {
        showMain(nil)
        if let route = route, !route.isEmpty {
            dispatch("tandem:command", ["cmd": "route", "route": route], to: hosts[.main])
        }
    }

    /// Sheet on the main window; a free-standing panel for the popover and floating surfaces.
    func present(_ panel: NSSavePanel, for host: WebHost, _ done: @escaping (NSApplication.ModalResponse) -> Void) {
        if host.surface == .main, window.isVisible {
            panel.beginSheetModal(for: window, completionHandler: done)
        } else {
            NSApp.activate(ignoringOtherApps: true)
            panel.begin(completionHandler: done)
        }
    }

    func chooseFolder(_ body: [String: Any], id: Any, host: WebHost) {
        let panel = NSOpenPanel(); panel.canChooseDirectories = true; panel.canChooseFiles = false
        panel.allowsMultipleSelection = false; panel.showsHiddenFiles = true
        panel.prompt = "选择"
        if let purpose = body["purpose"] as? String, !purpose.isEmpty {
            let agent = (body["agent"] as? String).map { " · \($0)" } ?? ""
            panel.message = purpose + agent
        }
        if let raw = body["defaultPath"] as? String, !raw.isEmpty {
            panel.directoryURL = URL(fileURLWithPath: (raw as NSString).expandingTildeInPath, isDirectory: true)
        }
        present(panel, for: host) { [weak self] response in
            guard let self = self else { return }
            guard response == .OK, let url = panel.url else {
                self.dispatch("tandem:folder", ["id": id, "path": NSNull(), "cancelled": true], to: host); return
            }
            if let bookmark = try? url.bookmarkData(options: .withSecurityScope, includingResourceValuesForKeys: nil, relativeTo: nil) {
                var saved = UserDefaults.standard.array(forKey: "sourceBookmarks") as? [Data] ?? []
                saved.append(bookmark); UserDefaults.standard.set(saved, forKey: "sourceBookmarks")
            }
            if url.startAccessingSecurityScopedResource() { self.bookmarks.append(url) }
            self.dispatch("tandem:folder", ["id": id, "path": url.path, "cancelled": false], to: host)
        }
    }

    func save(_ body: [String: Any], id: Any, host: WebHost) {
        let data: Data
        if let text = body["text"] as? String { data = Data(text.utf8) }
        else if let encoded = body["base64"] as? String, let decoded = Data(base64Encoded: encoded) { data = decoded }
        else { dispatch("tandem:saved", ["id": id, "ok": false, "error": "no content"], to: host); return }
        guard data.count <= 200_000_000 else {
            dispatch("tandem:saved", ["id": id, "ok": false, "error": "too large"], to: host); return
        }
        let panel = NSSavePanel()
        let name = (body["filename"] as? String).map { ($0 as NSString).lastPathComponent } ?? "orbit-export"
        panel.nameFieldStringValue = name.isEmpty ? "orbit-export" : name
        present(panel, for: host) { [weak self] response in
            guard response == .OK, let url = panel.url else {
                self?.dispatch("tandem:saved", ["id": id, "ok": false, "cancelled": true], to: host); return
            }
            do {
                try data.write(to: url, options: .atomic)
                self?.dispatch("tandem:saved", ["id": id, "ok": true, "path": url.path], to: host)
            } catch {
                self?.dispatch("tandem:saved", ["id": id, "ok": false, "error": error.localizedDescription], to: host)
            }
        }
    }

    // MARK: notifications

    /// System notification; authorization is requested on first use and denial is silent.
    func notify(_ body: [String: Any]) {
        guard Bundle.main.bundleIdentifier != nil, let title = body["title"] as? String else { return }
        let center = UNUserNotificationCenter.current()
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body["body"] as? String ?? ""
        if let route = body["route"] as? String { content.userInfo = ["route": route] }
        let id = (body["id"] as? String) ?? (body["id"] as? NSNumber)?.stringValue ?? UUID().uuidString
        let request = UNNotificationRequest(identifier: "orbit.\(id)", content: content, trigger: nil)
        let post = { center.add(request) { _ in } }
        if notificationsAsked { post(); return }
        center.requestAuthorization(options: [.alert, .sound]) { [weak self] granted, _ in
            DispatchQueue.main.async { self?.notificationsAsked = true }
            if granted { post() }
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .list, .sound])
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        let route = response.notification.request.content.userInfo["route"] as? String
        DispatchQueue.main.async { self.openMain(route: route) }
        completionHandler()
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

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        guard let host = host(of: webView), let origin = origin else { return }
        webView.load(URLRequest(url: pageURL(origin, host.surface)))
    }

    // MARK: lifecycle

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showMain(nil)
        return true
    }

    // Closing the main window hides it; Orbit keeps running in the menu bar until ⌘Q.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

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
