import SwiftUI
import WebKit
import OSLog

@main
struct StimmaMobileApp: App {
    @StateObject private var model = ShellModel()
    @Environment(\.scenePhase) private var scenePhase
    var body: some Scene {
        WindowGroup {
            ShellView(model: model)
                .preferredColorScheme(.dark)
                .task { await model.restore() }
                .onChange(of: scenePhase) { _, phase in
                    if phase == .background { model.suspendConnection() }
                    if phase == .active { Task { await model.checkConnection() } }
                }
        }
    }
}

@MainActor
final class ShellModel: ObservableObject {
    let auth = MobileAuth()
    @Published var devices: [MobileDevice] = []
    @Published var selected: MobileDevice?
    @Published var origin: URL?
    @Published var message: String?
    @Published var busy = false
    @Published var showConnections = false
    @Published var revision = UUID()
    @Published var connectionState = "ready"
    @Published var transportRevision = 0
    @Published var restoring = true
    @Published var interfaceReady = false
    private(set) var transport: MobileTransport?
    private let packageCache = UIPackageCache(directory: FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0].appendingPathComponent("ui-packages"))
    private var activeUIHash: String?
    private var activeRoute: MobileRoute?
    private var activeSession: String?
    private var connectionGeneration = UUID()
    private var monitor: Task<Void, Never>?
    private var connectionTask: Task<Void, Never>?
    private var checkingConnection = false
    private var connectionProbe: Task<Bool, Error>?
    private var resumePending = false
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
        defer { restoring = false }
        #if DEBUG && targetEnvironment(simulator)
        let arguments = ProcessInfo.processInfo.arguments
        if arguments.contains("--auth-network-check") {
            do {
                try await auth.checkAuthNetwork()
                message = "Auth network check passed"
            } catch { message = error.localizedDescription }
            return
        }
        if let index = arguments.firstIndex(of: "--keychain-check"), arguments.indices.contains(index + 1) {
            do {
                try auth.checkKeychain(stage: arguments[index + 1])
                message = "Keychain check passed"
            } catch { message = error.localizedDescription }
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
                transport = preview
                selected = MobileDevice(deviceId: "simulator", name: "Simulator test library", routes: [], certFingerprint: nil, serving: false)
                origin = url
                activeUIHash = package.hash
                startMonitor()
                message = nil
            } catch {
                message = error.localizedDescription
                try? await startInterface()
            }
            return
        }
        #endif
        do { try await startInterface() }
        catch { message = error.localizedDescription; return }
        guard auth.hasSavedSession else { return }
        await refresh()
        guard restoring, generation == connectionGeneration, !Task.isCancelled else { return }
        if let id = UserDefaults.standard.string(forKey: "mobile.selectedServer"),
           let device = devices.first(where: { $0.deviceId == id }) {
            await connect(device)
        }
    }

    func cancelRestore() {
        guard restoring else { return }
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
            message = nil
        } catch {
            if generation == connectionGeneration { message = "Could not load your servers. \(error.localizedDescription)" }
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
    }

    func connect(_ device: MobileDevice, recovering: Bool = false) async {
        connectionProbe?.cancel(); connectionProbe = nil
        checkingConnection = false
        connectionTask?.cancel()
        let generation = UUID()
        connectionGeneration = generation
        busy = true
        let task = Task { await self.performConnect(device, recovering: recovering, generation: generation) }
        connectionTask = task
        await withTaskCancellationHandler {
            await task.value
        } onCancel: { task.cancel() }
        if connectionGeneration == generation { connectionTask = nil; busy = false }
    }

    private func performConnect(_ initialDevice: MobileDevice, recovering: Bool, generation: UUID) async {
        guard connectionGeneration == generation, !Task.isCancelled else { return }
        var device = initialDevice
        connectionState = "connecting"
        message = "Connecting to \(device.name)…"
        defer { if connectionGeneration == generation { busy = false } }
        if recovering {
            // Refresh addresses/certificate after a server restart. A cloud outage
            // must not prevent reconnecting over a previously verified route.
            if let roster = try? await auth.devices() {
                guard connectionGeneration == generation, !Task.isCancelled else { return }
                devices = roster
                if let latest = roster.first(where: { $0.deviceId == device.deviceId }) { device = latest }
            }
        }
        guard connectionGeneration == generation, !Task.isCancelled else { return }
        guard let pin = device.certFingerprint, !pin.isEmpty else {
            message = "This server has no verified certificate. Refresh your servers and try again."
            connectionState = "unreachable"
            return
        }
        do {
            let candidates: [(MobileRoute, URL)] = device.routes.compactMap { route in
                var address = URLComponents()
                address.scheme = "https"; address.host = route.host; address.port = route.port
                address.path = "/multi-device/ping"
                return address.url.map { (route, $0) }
            }
            let reachable = try await PinnedHTTP.firstReachable(urls: candidates.map { $0.1 }, fingerprint: pin, deviceID: device.deviceId)
            guard connectionGeneration == generation else { return }
            guard let route = candidates.first(where: { $0.1 == reachable })?.0 else {
                throw ShellError.message("No reachable server route. Check that Stimma and Tailscale are running.")
            }
            let idToken = try await auth.validIDToken()
            guard connectionGeneration == generation else { return }
            var components = URLComponents()
            components.scheme = "https"
            components.host = route.host
            components.port = route.port
            components.path = "/multi-device/session"
            guard let url = components.url else { throw ShellError.message("Invalid server route") }
            let body = try JSONSerialization.data(withJSONObject: ["idToken": idToken, "deviceId": clientID])
            let (data, response) = try await PinnedHTTP.request(url: url, fingerprint: pin, method: "POST", body: body, session: nil)
            guard connectionGeneration == generation else { return }
            guard response.statusCode == 200,
                  let result = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let session = result["session"] as? String,
                  result["deviceId"] as? String == device.deviceId else {
                throw ShellError.message("The server refused this account or its identity changed.")
            }
            // A network interruption must not reset the page, drafts, or scroll.
            // Resolve package updates on explicit selection or the next app launch.
            if recovering, selected?.deviceId == device.deviceId, let transport, activeUIHash != nil {
                transport.connect(host: route.host, port: route.port, fingerprint: pin, session: session)
                guard try await transport.checkConnection() else {
                    throw ShellError.message("The local connection could not reach the server.")
                }
                guard connectionGeneration == generation, !Task.isCancelled else { return }
                selected = device
                activeRoute = route
                activeSession = session
                message = nil
                connectionState = "ready"
                resumePending = false
                transportRevision += 1
                return
            }
            let package = try await resolveUI { path, limit in
                var address = URLComponents()
                address.scheme = "https"; address.host = route.host; address.port = route.port; address.path = path
                guard let url = address.url else { throw ShellError.message("Invalid server route") }
                return try self.checkedPackageResponse(await PinnedHTTP.request(url: url, fingerprint: pin, session: session, maximumResponseBytes: limit))
            }
            guard connectionGeneration == generation else { return }
            guard let frontend = Bundle.main.url(forResource: "Frontend", withExtension: nil) else {
                throw ShellError.message("The web interface is missing. Rebuild the app with its frontend assets.")
            }
            let next = MobileTransport(frontend: package.directory, shellFrontend: frontend)
            let localOrigin = try await next.start()
            guard connectionGeneration == generation else { next.stop(); return }
            next.connect(host: route.host, port: route.port, fingerprint: pin, session: session)
            transport?.stop()
            transport = next
            interfaceReady = false
            activeUIHash = package.hash
            selected = device
            activeRoute = route
            activeSession = session
            origin = localOrigin
            revision = UUID()
            UserDefaults.standard.set(device.deviceId, forKey: "mobile.selectedServer")
            showConnections = false
            message = nil
            connectionState = "ready"
            startMonitor()
            return
        } catch {
            if connectionGeneration == generation && !Task.isCancelled {
                message = "Could not connect to \(device.name). \(error.localizedDescription)"
                connectionState = "unreachable"
            }
        }
    }

    func retry() async {
        if let selected, activeRoute != nil { await connect(selected, recovering: true) }
        else { revision = UUID() }
    }

    private func startMonitor() {
        guard monitor == nil else { return }
        monitor = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(20))
                guard !Task.isCancelled else { return }
                await self?.checkConnection()
            }
        }
    }

    func suspendConnection() {
        guard selected != nil else { return }
        connectionGeneration = UUID()
        connectionTask?.cancel(); connectionTask = nil
        connectionProbe?.cancel(); connectionProbe = nil
        checkingConnection = false
        busy = false
        resumePending = true
        connectionState = "connecting"
        transport?.suspend()
    }

    func checkConnection() async {
        guard !busy, !checkingConnection, UIApplication.shared.applicationState == .active,
              let selected, let transport else { return }
        let generation = connectionGeneration
        checkingConnection = true
        defer {
            if generation == connectionGeneration {
                checkingConnection = false
                connectionProbe = nil
            }
        }
        let probe = Task { try await transport.checkConnection() }
        connectionProbe = probe
        do {
            let ready = try await withTaskCancellationHandler {
                try await probe.value
            } onCancel: { probe.cancel() }
            guard generation == connectionGeneration, !Task.isCancelled else { return }
            if ready {
                message = nil
                connectionState = "ready"
                if resumePending { resumePending = false; transportRevision += 1 }
                return
            }
        } catch { if generation != connectionGeneration { return } }
        connectionState = "unreachable"
        guard !Task.isCancelled else { return }
        transport.suspend()
        // Release the probe gate before connect() changes the generation.
        checkingConnection = false
        connectionProbe = nil
        if activeRoute != nil { await connect(selected, recovering: true) }
    }

    func logout() {
        auth.logout()
        devices = []
        disconnect()
    }

    func disconnect() {
        connectionGeneration = UUID()
        connectionTask?.cancel(); connectionTask = nil
        restoring = false
        interfaceReady = false
        connectionProbe?.cancel(); connectionProbe = nil
        checkingConnection = false
        resumePending = false
        monitor?.cancel(); monitor = nil
        activeRoute = nil; activeSession = nil; activeUIHash = nil
        busy = false
        transport?.stop()
        transport = nil
        origin = nil
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
            if let origin = model.origin {
                StimmaWebView(model: model, origin: origin, connectionScreen: model.selected == nil)
                    .id(model.revision)
                    .ignoresSafeArea(.container)
                    .accessibilityHidden(!model.interfaceReady)
            }
            if !model.interfaceReady {
                ZStack {
                    Color(red: 11/255, green: 14/255, blue: 20/255).ignoresSafeArea()
                    VStack(spacing: 24) {
                        if model.origin == nil, let message = model.message {
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
