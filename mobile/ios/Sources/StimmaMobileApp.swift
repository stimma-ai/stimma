import SwiftUI
import WebKit
import OSLog
import Network

@main
struct StimmaMobileApp: App {
    @UIApplicationDelegateAdaptor(MobileAppDelegate.self) private var appDelegate
    @StateObject private var model = ShellModel()
    @Environment(\.scenePhase) private var scenePhase
    var body: some Scene {
        WindowGroup {
            ShellView(model: model)
                .preferredColorScheme(.dark)
                .task { await model.restore() }
                .onChange(of: scenePhase) { _, phase in
                    model.setAppActive(phase == .active)
                    if phase == .background { model.suspendConnection() }
                    if phase == .active { model.resumeConnection() }
                }
        }
    }
}

@MainActor
final class ShellModel: ObservableObject {
    let auth = MobileAuth()
    @Published var devices: [MobileDevice] = []
    @Published var discoveryState = "connecting"
    @Published var discoveryError: String?
    private let presence = MobilePresence()
    @Published var selected: MobileDevice?
    @Published var origin: URL?
    @Published private(set) var devServerURL: URL?
    var appOrigin: URL? { devServerURL ?? origin }

    #if DEBUG
    func connectDevServer(_ address: String) async throws {
        let url = try DevServerAddress.parse(address)
        guard let frontend = Bundle.main.url(forResource: "Frontend", withExtension: nil) else {
            throw ShellError.message("The bundled connection screen is missing.")
        }
        let next = MobileTransport(frontend: frontend)
        let localOrigin = try await next.start()
        connectionGeneration = UUID()
        connectionTask?.cancel(); connectionTask = nil
        recovery.cancel()
        activeRoute = nil; activeSession = nil; activeUIHash = nil
        // Keep the bundled connection screen available on its own loopback origin.
        transport?.stop()
        transport = next
        origin = localOrigin
        resetPresentation()
        devServerURL = url
        selected = MobileDevice(deviceId: "dev:" + url.absoluteString, name: "Dev server", routes: [], certFingerprint: nil, serving: false)
        UserDefaults.standard.set(url.absoluteString, forKey: "mobile.devServerAddress")
        interfaceReady = false
        restoring = false
        busy = false
        message = nil
        connectionState = "ready"
        showConnections = false
        revision = UUID()
        recovery.reset()
    }
    #endif
    @Published var message: String?
    @Published var busy = false
    @Published var showConnections = false {
        didSet { updateOrientation() }
    }
    private var slideshowActive = false
    private var keepAwakeRequested = false
    private var appActive = true
    @Published var revision = UUID()
    @Published var connectionState = "ready"
    /// Bumped once per recovery generation that ends ready after a disruption;
    /// older UI packages replace their socket and refresh on it.
    @Published var transportRevision = 0
    /// The recovery generation, phase and budget published to the page.
    @Published private(set) var recoveryState = RecoveryState(generation: 0, phase: .ready, budget: 0)
    @Published var restoring = true
    @Published var interfaceReady = false
    private(set) var transport: MobileTransport?
    private let packageCache = UIPackageCache(directory: FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0].appendingPathComponent("ui-packages"))
    private var activeUIHash: String?
    private var activeRoute: MobileRoute?
    private var activeSession: String?
    private var connectionGeneration = UUID()
    private var connectionTask: Task<Void, Never>?
    private var routineChecks: Task<Void, Never>?
    /// The single recovery sequence for the WebView's connection. Its state is
    /// published to the page so request admission, socket replacement and the
    /// visible reconnecting state all follow the same generation and budgets.
    private(set) lazy var recovery = TransportRecovery(
        probe: { [weak self] in await self?.transport?.checkConnection() ?? .unreachable },
        reconnect: { [weak self] in
            guard let self else { throw CancellationError() }
            try await self.recoverSession()
        },
        publish: { [weak self] state, resumed, failure in self?.recoveryChanged(state, resumed: resumed, failure: failure) },
        // A revoked sign-in cannot recover by retrying; the connection screen asks to sign in.
        terminal: { [weak self] _ in self?.signInRevoked ?? true })
    /// The one default-network watcher (see `networkChanged`).
    private let pathMonitor = NWPathMonitor()
    private lazy var networkChanges = NetworkChangeTracker<String> { [weak self] in self?.networkChanged() }

    init() {
        pathMonitor.pathUpdateHandler = { [weak self] path in
            let network = path.status == .satisfied ? Self.defaultNetwork(path) : nil
            // In order, on the main actor: each update is compared with the last.
            DispatchQueue.main.async { MainActor.assumeIsolated { self?.pathChanged(network) } }
        }
        pathMonitor.start(queue: DispatchQueue(label: "ai.stimma.mobile.network"))
    }

    /// The physical network carrying the default path. A VPN such as Tailscale
    /// stays first across a Wi-Fi/cellular handoff, so it does not identify it.
    nonisolated static func defaultNetwork(_ path: NWPath) -> String {
        let interfaces = path.availableInterfaces
        let physical = interfaces.first { [.wifi, .cellular, .wiredEthernet].contains($0.type) }
        return (physical ?? interfaces.first)?.name ?? "default"
    }

    private func pathChanged(_ network: String?) {
        if let network { networkChanges.available(network) } else { networkChanges.unavailable() }
    }

    /// A handoff, losing the default network with no successor, or the
    /// network returning drops what the old network carried (idle pooled
    /// connections, then WebSocket tunnels) and, in the foreground, starts a
    /// recovery generation so the page finds out now rather than when a stale
    /// socket times out.
    private func networkChanged() {
        transport?.networkChanged()
        if appActive && recoverable { recovery.disrupted() }
    }

    /// Recovery applies to an established in-app connection, not dev-server pages or a connection still being made.
    private var recoverable: Bool {
        transport != nil && selected != nil && devServerURL == nil && !busy && activeUIHash != nil
    }

    /// The account sign-in behind a remote connection is gone; only the user can fix that.
    private var signInRevoked: Bool { activeRoute != nil && !auth.hasSavedSession }
    func setSlideshowActive(_ active: Bool) {
        slideshowActive = active
        updateOrientation()
    }

    // A new page or server starts with no slideshow and no keep-awake.
    func resetPresentation() {
        slideshowActive = false
        keepAwakeRequested = false
        updateOrientation()
    }

    func setKeepAwake(_ active: Bool) {
        keepAwakeRequested = active
        updateOrientation()
    }

    func setAppActive(_ active: Bool) {
        appActive = active
        if active { startPresence() }
        else { presence.stop(); discoveryState = "paused" }
        updateOrientation()
    }

    private func startPresence() {
        guard appActive, auth.hasSavedSession else { return }
        presence.start(cloudURL: auth.cloudURL, token: { [weak self] in
            guard let self else { throw CancellationError() }
            return try await self.auth.validIDToken()
        }, refresh: { [weak self] in
            guard let self else { throw CancellationError() }
            let roster = try await self.auth.devices()
            try Task.checkCancellation()
            self.devices = roster
            self.discoveryError = nil
        }, state: { [weak self] state in
            guard let self else { return }
            self.discoveryState = state
            if !self.auth.hasSavedSession {
                self.presence.stop()
                self.devices = []
                self.discoveryState = "paused"
            }
        })
    }

    private func updateOrientation() {
        MobileAppDelegate.setSlideshowActive(slideshowActive && selected != nil && !showConnections)
        UIApplication.shared.isIdleTimerDisabled = keepAwakeRequested && appActive && selected != nil && !showConnections
    }
    let clientID: String = {
        if let saved = UserDefaults.standard.string(forKey: "mobile.clientID") { return saved }
        let id = UUID().uuidString
        UserDefaults.standard.set(id, forKey: "mobile.clientID")
        return id
    }()

    private func startInterface() async throws {
        guard transport == nil else { return }
        guard let frontend = Bundle.main.url(forResource: "Frontend", withExtension: nil) else {
            throw ShellError.message("The web interface is missing. Rebuild the app with its frontend assets.")
        }
        let next = MobileTransport(frontend: frontend)
        let localOrigin = try await next.start()
        transport = next
        origin = localOrigin
    }

    private func resolveUI(fetch: @escaping (String, Int) async throws -> Data) async throws -> UIPackageResolution {
        message = "Checking the server interface…"
        let manifest = try await fetch("/api/mobile-ui/manifest", 65_536)
        guard let fields = try JSONSerialization.jsonObject(with: manifest) as? [String: Any],
              let hash = fields["hash"] as? String, hash.count == 64,
              hash.allSatisfy({ "0123456789abcdef".contains($0) }) else {
            throw ShellError.message("The server returned an invalid interface manifest.")
        }
        let protected = Set([activeUIHash].compactMap { $0 })
        let resolved = try await packageCache.resolve(manifest: manifest, download: {
            await MainActor.run { self.message = "Downloading the server interface…" }
            return try await fetch("/api/mobile-ui/packages/\(hash).tar.gz", 64 * 1024 * 1024)
        }, protectedHashes: protected)
        Logger(subsystem: "ai.stimma.mobile", category: "ui-packages").notice("interface_ready hash=\(resolved.hash, privacy: .public) cache_hit=\(resolved.cacheHit)")
        return resolved
    }

    private func checkedPackageResponse(_ value: (Data, HTTPURLResponse)) throws -> Data {
        guard value.1.statusCode == 200 else {
            if [404, 503].contains(value.1.statusCode) {
                throw ShellError.message("This server has no mobile interface package. Update your Stimma Server.")
            }
            throw ShellError.message("Could not download the server interface (HTTP \(value.1.statusCode)).")
        }
        return value.0
    }

    func restore() async {
        let generation = connectionGeneration
        #if DEBUG && targetEnvironment(simulator)
        let arguments = ProcessInfo.processInfo.arguments
        if arguments.contains("--auth-network-check") {
            do {
                try await auth.checkAuthNetwork()
                message = "Auth network check passed"
            } catch { message = error.localizedDescription }
            restoring = false
            return
        }
        if let index = arguments.firstIndex(of: "--keychain-check"), arguments.indices.contains(index + 1) {
            do {
                try auth.checkKeychain(stage: arguments[index + 1])
                message = "Keychain check passed"
            } catch { message = error.localizedDescription }
            restoring = false
            return
        }
        if let index = arguments.firstIndex(of: "--local-backend-port"),
           arguments.indices.contains(index + 1), let port = Int(arguments[index + 1]),
           (1024...65535).contains(port) {
            do {
                guard let frontend = Bundle.main.url(forResource: "Frontend", withExtension: nil) else {
                    throw ShellError.message("The web interface is missing. Rebuild the app with its frontend assets.")
                }
                let package = try await resolveUI { path, limit in
                    let address = URL(string: "http://127.0.0.1:\(port)\(path)")!
                    return try self.checkedPackageResponse(await PinnedHTTP.localRequest(url: address, maximumResponseBytes: limit))
                }
                transport?.stop()
                let preview = MobileTransport(frontend: package.directory, shellFrontend: frontend)
                let url = try await preview.start()
                preview.connectLocal(port: port)
                watchTunnels(preview)
                transport = preview
                selected = MobileDevice(deviceId: "simulator", name: "Simulator test library", routes: [], certFingerprint: nil, serving: false)
                origin = url
                activeUIHash = package.hash
                recovery.reset()
                message = nil
            } catch {
                message = error.localizedDescription
                try? await startInterface()
            }
            restoring = false
            return
        }
        #endif
        do { try await startInterface() }
        catch { message = error.localizedDescription; restoring = false; return }
        guard auth.hasSavedSession else { restoring = false; return }
        let rememberedServerID = UserDefaults.standard.string(forKey: "mobile.selectedServer")
        await refresh()
        startPresence()
        guard restoring, generation == connectionGeneration, !Task.isCancelled else { return }
        if let id = rememberedServerID,
           let device = devices.first(where: { $0.deviceId == id }) {
            await connect(device)
            if selected?.deviceId == id, connectionState == "ready" { restoring = false }
            return
        }
        if rememberedServerID != nil {
            if message == nil { message = "Your saved Stimma Server is not currently available." }
            connectionState = "unreachable"
            return
        }
        restoring = false
    }

    func cancelRestore() {
        guard restoring else { return }
        recovery.cancel()
        connectionGeneration = UUID()
        connectionTask?.cancel(); connectionTask = nil
        restoring = false
        busy = false
        connectionState = "ready"
        message = nil
    }

    func refresh() async {
        guard !busy else { return }
        let generation = connectionGeneration
        busy = true
        defer { if generation == connectionGeneration { busy = false } }
        do {
            let roster = try await auth.devices()
            guard generation == connectionGeneration else { return }
            devices = roster
            discoveryError = nil
        } catch {
            if generation == connectionGeneration { discoveryError = "Could not load your servers. \(error.localizedDescription)" }
        }
    }

    func login() async {
        guard !busy else { return }
        let generation = connectionGeneration
        guard let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene })
            .flatMap(\.windows).first(where: \.isKeyWindow) else { return }
        busy = true
        await auth.login(presentationAnchor: window)
        guard generation == connectionGeneration else { return }
        busy = false
        if let error = auth.error { message = error; return }
        await refresh()
        startPresence()
    }

    func connect(_ device: MobileDevice) async {
        // An explicit operation takes over from any recovery in progress.
        recovery.cancel()
        connectionTask?.cancel()
        let generation = UUID()
        connectionGeneration = generation
        busy = true
        let task = Task { await self.performConnect(device, generation: generation) }
        connectionTask = task
        await withTaskCancellationHandler {
            await task.value
        } onCancel: { task.cancel() }
        if connectionGeneration == generation { connectionTask = nil; busy = false }
    }

    private struct EstablishedSession {
        let device: MobileDevice
        let route: MobileRoute
        let pin: String
        let session: String
        let keepAlive: Int?
    }

    /// Find a verified route to `initialDevice` and open a device session on it.
    /// Recovery first refreshes the device's addresses and certificate, bounded
    /// so a slow account service cannot consume the recovery budget; a network
    /// failure there leaves the remembered roster usable, a revoked sign-in does not.
    private func establishSession(_ initialDevice: MobileDevice, recovering: Bool, generation: UUID) async throws -> EstablishedSession {
        func checkCurrent() throws {
            guard connectionGeneration == generation, !Task.isCancelled else { throw CancellationError() }
        }
        var device = initialDevice
        if recovering {
            var roster: [MobileDevice]?
            do { roster = try await withBudget(Self.discoveryRefresh) { @MainActor in try await self.auth.devices() } }
            catch {
                try checkCurrent()
                if !auth.hasSavedSession { throw error }
            }
            try checkCurrent()
            if let roster {
                devices = roster
                guard let latest = roster.first(where: { $0.deviceId == device.deviceId }) else {
                    throw ShellError.message("This server is no longer shared with your account.")
                }
                device = latest
            }
        }
        try checkCurrent()
        guard let pin = device.certFingerprint, !pin.isEmpty else {
            throw ShellError.message("This server has no verified certificate. Refresh your servers and try again.")
        }
        let candidates: [(MobileRoute, URL)] = device.routes.compactMap { route in
            var address = URLComponents()
            address.scheme = "https"; address.host = route.host; address.port = route.port
            address.path = "/multi-device/ping"
            return address.url.map { (route, $0) }
        }
        let (reachable, keepAlive) = try await PinnedHTTP.firstReachableRoute(urls: candidates.map { $0.1 }, fingerprint: pin, deviceID: device.deviceId)
        try checkCurrent()
        guard let route = candidates.first(where: { $0.1 == reachable })?.0 else {
            throw ShellError.message("No reachable server route. Check that Stimma and Tailscale are running.")
        }
        let idToken = try await auth.validIDToken()
        try checkCurrent()
        var components = URLComponents()
        components.scheme = "https"
        components.host = route.host
        components.port = route.port
        components.path = "/multi-device/session"
        guard let url = components.url else { throw ShellError.message("Invalid server route") }
        let body = try JSONSerialization.data(withJSONObject: ["idToken": idToken, "deviceId": clientID])
        let (data, response) = try await PinnedHTTP.request(url: url, fingerprint: pin, method: "POST", body: body, session: nil)
        try checkCurrent()
        guard response.statusCode == 200,
              let result = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let session = result["session"] as? String,
              result["deviceId"] as? String == device.deviceId else {
            throw ShellError.message("The server refused this account or its identity changed.")
        }
        return EstablishedSession(device: device, route: route, pin: pin, session: session, keepAlive: keepAlive)
    }

    private func performConnect(_ device: MobileDevice, generation: UUID) async {
        guard connectionGeneration == generation, !Task.isCancelled else { return }
        connectionState = "connecting"
        message = "Connecting to \(device.name)…"
        defer { if connectionGeneration == generation { busy = false } }
        do {
            let established = try await establishSession(device, recovering: false, generation: generation)
            let route = established.route
            let package = try await resolveUI { path, limit in
                var address = URLComponents()
                address.scheme = "https"; address.host = route.host; address.port = route.port; address.path = path
                guard let url = address.url else { throw ShellError.message("Invalid server route") }
                return try self.checkedPackageResponse(await PinnedHTTP.request(url: url, fingerprint: established.pin, session: established.session, maximumResponseBytes: limit))
            }
            guard connectionGeneration == generation else { return }
            guard let frontend = Bundle.main.url(forResource: "Frontend", withExtension: nil) else {
                throw ShellError.message("The web interface is missing. Rebuild the app with its frontend assets.")
            }
            let next = MobileTransport(frontend: package.directory, shellFrontend: frontend)
            let localOrigin = try await next.start()
            guard connectionGeneration == generation else { next.stop(); return }
            next.connect(host: route.host, port: route.port, fingerprint: established.pin, session: established.session, keepAlive: established.keepAlive)
            watchTunnels(next)
            transport?.stop()
            transport = next
            resetPresentation()
            interfaceReady = false
            devServerURL = nil
            activeUIHash = package.hash
            selected = established.device
            activeRoute = route
            activeSession = established.session
            origin = localOrigin
            revision = UUID()
            UserDefaults.standard.set(established.device.deviceId, forKey: "mobile.selectedServer")
            showConnections = false
            message = nil
            connectionState = "ready"
            // After the selection: publishing renders, and the new page needs to know its server.
            recovery.reset()
        } catch {
            if connectionGeneration == generation && !Task.isCancelled {
                message = "Could not connect to \(device.name). \(error.localizedDescription)"
                connectionState = "unreachable"
            }
        }
    }

    /// Re-establish the session in place for `recovery`: the page, package,
    /// local address and drafts stay. Recovery confirms the new session through
    /// the WebView's own path before it reports ready.
    private func recoverSession() async throws {
        guard let device = selected, devServerURL == nil, let transport, activeUIHash != nil, activeRoute != nil else {
            throw ShellError.message("Nothing to recover.")
        }
        let established = try await establishSession(device, recovering: true, generation: connectionGeneration)
        guard self.transport === transport, selected?.deviceId == established.device.deviceId else { throw CancellationError() }
        transport.connect(host: established.route.host, port: established.route.port, fingerprint: established.pin,
                          session: established.session, keepAlive: established.keepAlive)
        selected = established.device
        activeRoute = established.route
        activeSession = established.session
        UserDefaults.standard.set(established.device.deviceId, forKey: "mobile.selectedServer")
    }

    /// The page's socket upgrading through this transport proves the path;
    /// recovery need not wait for its own check.
    private func watchTunnels(_ next: MobileTransport) {
        next.onTunnelOpened { [weak self, weak next] session, generation in
            // Captured when the upgrade succeeded; by the time this runs a newer check or session may have taken over.
            DispatchQueue.main.async {
                MainActor.assumeIsolated {
                    guard let self, let next, self.transport === next, next.isCurrent(session) else { return }
                    self.recovery.pathProven(generation: generation)
                }
            }
        }
    }

    private func recoveryChanged(_ state: RecoveryState, resumed: Bool, failure: Error?) {
        recoveryState = state
        transport?.setRecoveryGeneration(state.generation)
        connectionState = state.phase.connectionState
        switch state.phase {
        case .ready:
            message = nil
            if resumed { transportRevision += 1 }
        case .unavailable:
            let name = selected?.name ?? "your Stimma Server"
            message = failure.map { "Could not connect to \(name). \($0.localizedDescription)" }
                ?? "Could not connect to \(name). Check your sign-in, server sharing, and network, then try again."
            // Only a sign-in that is genuinely gone needs the connection screen; a network failure keeps the page.
            if failure != nil && signInRevoked { showConnections = true }
        case .checking, .reconnecting: break
        }
    }

    /// Cadence of the silent check that catches a server that went away while the app sat in the foreground.
    static let routineCheck: Duration = .seconds(20)
    /// How long recovery waits for a fresh server list before using the remembered one.
    static let discoveryRefresh: TimeInterval = 4

    /// The page's "retry": start a recovery generation now.
    func retry() async {
        if recoverable { recovery.disrupted() }
        else if selected == nil || activeRoute == nil { revision = UUID() }
    }

    /// Sockets close while backgrounded; the page must not treat the connection as ready until it is checked again.
    func suspendConnection() {
        routineChecks?.cancel(); routineChecks = nil
        guard selected != nil, devServerURL == nil else { return }
        connectionGeneration = UUID()
        connectionTask?.cancel(); connectionTask = nil
        busy = false
        if recoverable { recovery.suspend() } else { recovery.cancel() }
        transport?.suspend()
    }

    /// Foreground: check the path now, then routinely while active.
    func resumeConnection() {
        if recoverable { recovery.disrupted() }
        routineChecks?.cancel()
        routineChecks = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: Self.routineCheck)
                guard !Task.isCancelled, let self else { return }
                if self.recoverable { self.recovery.routine() }
            }
        }
    }

    func logout() {
        presence.stop()
        discoveryState = "paused"
        discoveryError = nil
        auth.logout()
        devices = []
        disconnect()
    }

    func disconnect() {
        resetPresentation()
        connectionGeneration = UUID()
        connectionTask?.cancel(); connectionTask = nil
        recovery.cancel()
        restoring = false
        interfaceReady = false
        activeRoute = nil; activeSession = nil; activeUIHash = nil
        busy = false
        transport?.stop()
        transport = nil
        origin = nil
        devServerURL = nil
        selected = nil
        UserDefaults.standard.removeObject(forKey: "mobile.selectedServer")
        message = nil
        showConnections = false
        revision = UUID()
        Task {
            do { try await startInterface() }
            catch { message = error.localizedDescription }
        }
    }
}

enum ShellError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let value) = self { return value }; return nil }
}

struct ShellView: View {
    @ObservedObject var model: ShellModel
    @State private var slowOpening = false
    var body: some View {
        ZStack {
            if let origin = model.appOrigin {
                StimmaWebView(model: model, origin: origin, connectionScreen: model.selected == nil)
                    .id(model.revision)
                    .accessibilityHidden(!model.interfaceReady)
            }
            if !model.interfaceReady {
                ZStack {
                    Color(red: 11/255, green: 14/255, blue: 20/255).ignoresSafeArea()
                    VStack(spacing: 24) {
                        if model.connectionState == "unreachable", let message = model.message {
                            Text(message).font(.subheadline).padding()
                        } else {
                            ProgressView().tint(.gray).accessibilityLabel("Connecting to your Stimma Server")
                        }
                        VStack(spacing: 12) {
                            Text("Connecting to your Stimma Server…").font(.subheadline).foregroundStyle(.secondary)
                            Button("Choose another server") {
                                if model.selected == nil { model.cancelRestore() }
                                else { model.showConnections = true }
                            }.tint(.teal).frame(minHeight: 44)
                        }
                        .opacity(slowOpening ? 1 : 0)
                        .allowsHitTesting(slowOpening)
                        .accessibilityHidden(!slowOpening)
                    }
                }
                .task {
                    slowOpening = false
                    do { try await Task.sleep(for: .milliseconds(4500)); slowOpening = true }
                    catch { }
                }
            }
        }
        .background(Color(red: 11/255, green: 14/255, blue: 20/255).ignoresSafeArea())
        .sheet(isPresented: $model.showConnections) {
            if let origin = model.origin {
                StimmaWebView(model: model, origin: origin, connectionScreen: true)
            }
        }
    }
}
