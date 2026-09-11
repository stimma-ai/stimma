import SwiftUI
import WebKit

struct StimmaWebView: UIViewRepresentable {
    @ObservedObject var model: ShellModel
    let origin: URL
    var connectionScreen = false

    func makeCoordinator() -> Coordinator { Coordinator(model: model, origin: origin, connectionScreen: connectionScreen) }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        // Session data stays temporary. localStorage is restored separately by
        // account/server because this transport's origin changes on reconnect.
        configuration.websiteDataStore = .nonPersistent()
        configuration.allowsInlineMediaPlayback = true
        configuration.mediaTypesRequiringUserActionForPlayback = []
        configuration.userContentController.addScriptMessageHandler(context.coordinator, contentWorld: .page, name: "stimma")
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.isOpaque = false
        webView.backgroundColor = UIColor(red: 11/255, green: 14/255, blue: 20/255, alpha: 1)
        webView.scrollView.backgroundColor = webView.backgroundColor
        webView.underPageBackgroundColor = webView.backgroundColor!
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.isInspectable = _isDebugAssertConfiguration()
        webView.allowsBackForwardNavigationGestures = true
        context.coordinator.webView = webView
        do {
            try context.coordinator.installStorageScript(configuration.userContentController)
        } catch {
            Task { @MainActor in
                model.message = "Could not restore local preferences. \(error.localizedDescription)"
                model.showConnections = true
            }
            return webView
        }
        #if DEBUG
        if !connectionScreen, model.devServerURL == origin {
            webView.load(URLRequest(url: origin, cachePolicy: .reloadIgnoringLocalCacheData))
            return webView
        }
        #endif
        if let transport = model.transport,
           let cookie = HTTPCookie(properties: [
            .domain: "127.0.0.1", .path: "/", .name: transport.cookieName,
            .value: transport.cookieValue, HTTPCookiePropertyKey("HttpOnly"): "TRUE",
            HTTPCookiePropertyKey("SameSite"): "Strict",
           ]) {
            // Cookies are host-scoped, not port-scoped. A generated image or
            // stylesheet must not send our HttpOnly cookie to another app's
            // loopback listener. Install the restriction before loading HTML.
            let allowedOrigin = NSRegularExpression.escapedPattern(for: origin.absoluteString)
            let rules: [[String: Any]] = [
                ["trigger": ["url-filter": "^https?://127\\.0\\.0\\.1(:[0-9]+)?/"], "action": ["type": "block"]],
                ["trigger": ["url-filter": "^\(allowedOrigin)/"], "action": ["type": "ignore-previous-rules"]],
            ]
            let encoded = try! JSONSerialization.data(withJSONObject: rules)
            WKContentRuleListStore.default().compileContentRuleList(forIdentifier: "stimma-loopback-\(origin.port!)",
                encodedContentRuleList: String(decoding: encoded, as: UTF8.self)) { list, error in
                guard let list, error == nil else {
                    model.message = "Could not protect the local connection. Please relaunch Stimma."
                    model.showConnections = true
                    return
                }
                configuration.userContentController.add(list)
                configuration.websiteDataStore.httpCookieStore.setCookie(cookie) {
                    webView.load(URLRequest(url: connectionScreen ? origin.appendingPathComponent("mobile.html") : origin))
                }
            }
        }
        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {
        if context.coordinator.lastTransportRevision != model.transportRevision {
            context.coordinator.lastTransportRevision = model.transportRevision
            uiView.evaluateJavaScript("window.dispatchEvent(new Event('stimma:transport-resumed'))")
        }
        if context.coordinator.lastState != model.connectionState {
            context.coordinator.lastState = model.connectionState
            let state = ["ready", "connecting", "unreachable"].contains(model.connectionState) ? model.connectionState : "unreachable"
            uiView.evaluateJavaScript("window.dispatchEvent(new CustomEvent('stimma:connection-state', {detail:'\(state)'}))")
        }
    }

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandlerWithReply {
        let model: ShellModel
        let origin: URL
        weak var webView: WKWebView?
        private let storage: LocalStoragePersistence?
        private let connectionScreen: Bool
        var lastState = "ready"
        var lastTransportRevision = 0
        init(model: ShellModel, origin: URL, connectionScreen: Bool) {
            self.model = model; self.origin = origin
            self.connectionScreen = connectionScreen
            if !connectionScreen, let server = model.selected {
                let directory = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
                    .appendingPathComponent("local-preferences")
                storage = LocalStoragePersistence(directory: directory,
                    accountID: model.auth.user?.id ?? "simulator", serverID: server.deviceId)
            } else { storage = nil }
            super.init()
            NotificationCenter.default.addObserver(self, selector: #selector(pauseForInterruption), name: UIApplication.willResignActiveNotification, object: nil)
            NotificationCenter.default.addObserver(self, selector: #selector(resumeInterface), name: UIApplication.didBecomeActiveNotification, object: nil)
        }

        @objc private func pauseForInterruption() {
            // Native pausing covers subframes and does not depend on the JS
            // event being delivered before the WebContent process suspends.
            webView?.pauseAllMediaPlayback(completionHandler: nil)
            webView?.evaluateJavaScript("window.dispatchEvent(new CustomEvent('stimma:app-active', {detail:false}))")
        }

        @objc private func resumeInterface() {
            webView?.evaluateJavaScript("window.dispatchEvent(new CustomEvent('stimma:app-active', {detail:true}))")
        }

        deinit { NotificationCenter.default.removeObserver(self) }

        func installStorageScript(_ controller: WKUserContentController) throws {
            guard let storage else { return }
            let source = try LocalStoragePersistence.script(values: storage.load(), origin: origin)
            // Update the seed after every save as well, so reloads and WebContent
            // process recovery cannot replay the WebView's original preferences.
            controller.removeAllUserScripts()
            controller.addUserScript(WKUserScript(source: source, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        }

        func userContentController(_ userContentController: WKUserContentController,
                                   didReceive message: WKScriptMessage,
                                   replyHandler: @escaping (Any?, String?) -> Void) {
            guard isCurrentOrigin, message.frameInfo.isMainFrame,
                  message.frameInfo.securityOrigin.protocol == origin.scheme,
                  message.frameInfo.securityOrigin.host == origin.host,
                  message.frameInfo.securityOrigin.port == (origin.port ?? (origin.scheme == "https" ? 443 : 80)),
                  let documentURL = message.frameInfo.request.url, isAppDocument(documentURL),
                  let body = message.body as? [String: Any],
                  let method = body["method"] as? String else {
                replyHandler(nil, "This frame cannot access the native shell")
                return
            }
            let args = body["args"] as? [String: Any] ?? [:]
            if method == "saveLocalStorage" {
                // Handle in delivery order, before async navigation operations.
                // The coordinator owns the scope; JS cannot choose another server.
                do {
                    guard let storage, let values = args["values"] as? [String: String] else {
                        throw ShellError.message("Invalid local preferences")
                    }
                    try storage.save(values)
                    try installStorageScript(userContentController)
                    replyHandler(NSNull(), nil)
                } catch { replyHandler(nil, error.localizedDescription) }
                return
            }
            Task { @MainActor in
                do {
                    let result: Any
                    switch method {
                    case "connectionInfo": result = try connectionInfo()
                    case "setSlideshowActive":
                        guard !connectionScreen, let active = args["active"] as? Bool else {
                            throw ShellError.message("Invalid slideshow state")
                        }
                        model.setSlideshowActive(active)
                        result = NSNull()
                    case "setKeepAwake":
                        guard !connectionScreen, let active = args["active"] as? Bool else {
                            throw ShellError.message("Invalid playback state")
                        }
                        model.setKeepAwake(active)
                        result = NSNull()
                    case "interfaceReady":
                        // A setup sheet must not reveal a still-loading app.
                        if (documentURL.path == "/mobile.html") == (model.selected == nil) {
                            model.interfaceReady = true
                        }
                        result = NSNull()
                    case "cancelRestore": model.cancelRestore(); result = try connectionInfo()
                    case "signIn":
                        await model.login()
                        result = try connectionInfo()
                    case "closeConnections": model.showConnections = false; result = NSNull()
                    case "getState":
                        result = ["activeDeviceId": model.selected?.deviceId ?? "none",
                                  "connectionState": model.connectionState,
                                  "localDeviceId": model.clientID,
                                  "devices": try object(model.devices)]
                    case "authStatus":
                        var data: [String: Any] = ["authenticated": model.auth.user != nil, "privacy_lockdown": false]
                        if let user = model.auth.user { data["user"] = try object(user) }
                        result = ["ok": true, "status": 200, "data": data]
                    case "refreshDevices":
                        await model.refresh()
                        result = try object(model.devices)
                    #if DEBUG
                    case "connectDevServer":
                        guard connectionScreen, let address = args["address"] as? String else {
                            throw ShellError.message("Open the connection screen to choose a dev server.")
                        }
                        try await model.connectDevServer(address)
                        result = NSNull()
                    #endif
                    case "selectServer":
                        guard let id = args["deviceId"] as? String,
                              let device = model.devices.first(where: { $0.deviceId == id }) else {
                            throw ShellError.message("Unknown server")
                        }
                        await model.connect(device)
                        result = model.selected?.deviceId == id ? model.connectionState : "unreachable"
                    case "showConnections": model.showConnections = true; result = NSNull()
                    case "reload":
                        replyHandler(NSNull(), nil)
                        await model.retry()
                        return
                    case "logout":
                        replyHandler(NSNull(), nil)
                        model.logout()
                        return
                    case "disconnect":
                        replyHandler(NSNull(), nil)
                        model.disconnect()
                        return
                    case "openExternal":
                        guard let value = args["url"] as? String, let url = URL(string: value),
                              ["https", "http"].contains(url.scheme?.lowercased() ?? "") else {
                            throw ShellError.message("Unsupported link")
                        }
                        await UIApplication.shared.open(url)
                        result = NSNull()
                    case "share":
                        guard let name = args["filename"] as? String,
                              let values = args["bytes"] as? [UInt8], values.count <= 64 * 1024 * 1024 else {
                            throw ShellError.message("This export is too large for the share sheet")
                        }
                        let safeName = URL(fileURLWithPath: name).lastPathComponent
                        guard !safeName.isEmpty, safeName != ".", safeName != ".." else { throw ShellError.message("Invalid filename") }
                        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
                        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
                        let file = directory.appendingPathComponent(safeName)
                        try Data(values).write(to: file, options: .atomic)
                        let activity = UIActivityViewController(activityItems: [file], applicationActivities: nil)
                        guard var presenter = webView?.window?.rootViewController else {
                            try? FileManager.default.removeItem(at: directory)
                            throw ShellError.message("Cannot open share sheet")
                        }
                        while let presented = presenter.presentedViewController { presenter = presented }
                        guard !presenter.isBeingDismissed else {
                            try? FileManager.default.removeItem(at: directory)
                            throw ShellError.message("Please close the current sheet and try exporting again.")
                        }
                        activity.popoverPresentationController?.sourceView = webView
                        // Resolve after the user completes or cancels sharing;
                        // presenting a sheet alone is not a successful export.
                        result = await withCheckedContinuation { continuation in
                            activity.completionWithItemsHandler = { _, completed, _, _ in
                                try? FileManager.default.removeItem(at: directory)
                                continuation.resume(returning: completed)
                            }
                            presenter.present(activity, animated: true)
                        }
                    default: throw ShellError.message("Unsupported native operation")
                    }
                    replyHandler(result, nil)
                } catch { replyHandler(nil, error.localizedDescription) }
            }
        }

        private func object<T: Encodable>(_ value: T) throws -> Any {
            try JSONSerialization.jsonObject(with: JSONEncoder().encode(value))
        }

        private func connectionInfo() throws -> [String: Any] {
            var info: [String: Any] = [
                "authenticated": model.auth.user != nil || model.auth.hasSavedSession,
                "devices": try object(model.devices),
                "selectedDeviceId": model.selected?.deviceId ?? "",
                "busy": model.busy,
                "restoring": model.restoring,
                "message": model.message ?? "",
            ]
            #if DEBUG
            info["devServerAvailable"] = true
            info["devServerAddress"] = UserDefaults.standard.string(forKey: "mobile.devServerAddress") ?? ""
            #endif
            if let user = model.auth.user { info["user"] = try object(user) }
            return info
        }

        private var isCurrentOrigin: Bool {
            connectionScreen ? model.origin == origin : model.appOrigin == origin
        }

        private func sameOrigin(_ url: URL) -> Bool {
            url.scheme == origin.scheme && url.host == origin.host && url.port == origin.port
        }

        private func isAppDocument(_ url: URL) -> Bool {
            guard sameOrigin(url) else { return false }
            let path = url.path.removingPercentEncoding ?? url.path
            return !["/api", "/ws", "/assets"].contains(where: { path == $0 || path.hasPrefix($0 + "/") })
                && !path.contains("\\") && !path.components(separatedBy: "/").contains("..")
        }

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let url = action.request.url else { decisionHandler(.cancel); return }
            if sameOrigin(url) {
                decisionHandler(action.targetFrame?.isMainFrame == true && !isAppDocument(url) ? .cancel : .allow)
            } else if action.targetFrame?.isMainFrame == true || action.targetFrame == nil {
                decisionHandler(.cancel)
                if ["https", "http"].contains(url.scheme ?? "") { UIApplication.shared.open(url) }
            } else {
                // Untrusted content remains unprivileged; native calls reject subframes.
                decisionHandler(["https", "blob", "about", "data"].contains(url.scheme ?? "") ? .allow : .cancel)
            }
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            if !connectionScreen, isCurrentOrigin { model.setSlideshowActive(false) }
        }
        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            if !connectionScreen, isCurrentOrigin { model.setSlideshowActive(false) }
            webView.reload()
        }
        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            guard (error as NSError).code != NSURLErrorCancelled, isCurrentOrigin else { return }
            model.message = "Connection interrupted. \(error.localizedDescription)"
            if model.selected != nil { model.showConnections = true }
        }
        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            if let url = navigationAction.request.url, ["https", "http"].contains(url.scheme ?? "") {
                UIApplication.shared.open(url)
            }
            return nil
        }
    }
}
