import Foundation
import Network
import Security
import CryptoKit
import UniformTypeIdentifiers

private enum TransportError: Error { case invalidRequest, unavailable, pinMismatch, invalidResponse }

func certificateMatches(_ certificate: SecCertificate, fingerprint: String) -> Bool {
    let expected = fingerprint.lowercased()
    guard expected.count == 64, expected.allSatisfy({ $0.isHexDigit }) else { return false }
    let digest = SHA256.hash(data: SecCertificateCopyData(certificate) as Data)
    return digest.map { String(format: "%02x", $0) }.joined() == expected
}

enum PinnedHTTPError: LocalizedError {
    case responseTooLarge, noReachableRoute
    var errorDescription: String? {
        switch self {
        case .responseTooLarge: return "The server returned a response that is too large."
        case .noReachableRoute: return "Could not reach this server. Check that your Stimma Server is running and Tailscale is connected on both devices."
        }
    }
}

/// Cancellation may arrive before the URLSession task is registered. Remember it
/// and cancel that task as soon as it exists, without invalidating the session
/// while the continuation is still creating its task.
private final class HTTPTaskCancellation: @unchecked Sendable {
    private let lock = NSLock()
    private var task: URLSessionTask?
    private var cancelled = false
    func register(_ task: URLSessionTask) {
        lock.lock()
        let shouldCancel = cancelled
        if !shouldCancel { self.task = task }
        lock.unlock()
        if shouldCancel { task.cancel() }
    }
    func cancel() {
        lock.lock()
        cancelled = true
        let pending = task
        lock.unlock()
        pending?.cancel()
    }
}

private final class PinDelegate: NSObject, URLSessionDataDelegate {
    let fingerprint: String?
    let maximumResponseBytes: Int
    var completion: ((Result<(Data, HTTPURLResponse), Error>) -> Void)?
    private var response: HTTPURLResponse?
    private var received = Data()
    init(_ fingerprint: String?, maximumResponseBytes: Int) {
        self.fingerprint = fingerprint
        self.maximumResponseBytes = maximumResponseBytes
    }

    private func finish(_ result: Result<(Data, HTTPURLResponse), Error>) {
        let pending = completion
        completion = nil
        pending?(result)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        guard let response = response as? HTTPURLResponse else {
            completionHandler(.cancel)
            finish(.failure(TransportError.invalidResponse))
            return
        }
        guard response.expectedContentLength <= Int64(maximumResponseBytes) else {
            completionHandler(.cancel)
            finish(.failure(PinnedHTTPError.responseTooLarge))
            return
        }
        self.response = response
        completionHandler(.allow)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        guard completion != nil else { return }
        // Check before appending. This also bounds decompressed and chunked
        // responses, regardless of an absent or misleading Content-Length.
        guard data.count <= maximumResponseBytes - received.count else {
            dataTask.cancel()
            finish(.failure(PinnedHTTPError.responseTooLarge))
            return
        }
        received.append(data)
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error { finish(.failure(error)) }
        else if let response { finish(.success((received, response))) }
        else { finish(.failure(TransportError.invalidResponse)) }
    }
    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        guard let fingerprint,
              challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              let trust = challenge.protectionSpace.serverTrust,
              let chain = SecTrustCopyCertificateChain(trust) as? [SecCertificate],
              let certificate = chain.first,
              certificateMatches(certificate, fingerprint: fingerprint) else {
            completionHandler(.cancelAuthenticationChallenge, nil); return
        }
        completionHandler(.useCredential, URLCredential(trust: trust))
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil) // Never move a device credential to a redirect destination.
    }
}

enum PinnedHTTP {
    static func request(url: URL, fingerprint: String, method: String = "GET", body: Data? = nil,
                        session: String? = nil, maximumResponseBytes: Int = 1_048_576, timeout: TimeInterval = 30) async throws -> (Data, HTTPURLResponse) {
        guard url.scheme == "https", url.user == nil, url.password == nil else { throw TransportError.invalidRequest }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.httpBody = body
        if body != nil { request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        if let session { request.setValue("Bearer \(session)", forHTTPHeaderField: "Authorization") }
        return try await boundedRequest(request, fingerprint: fingerprint, maximumResponseBytes: maximumResponseBytes, timeout: timeout)
    }

    #if (DEBUG && targetEnvironment(simulator)) || os(macOS)
    /// Development/test fixture access. Never accepts credentials or follows
    /// redirects, and cannot be pointed at a LAN or public HTTP endpoint.
    static func localRequest(url: URL, maximumResponseBytes: Int = 1_048_576, timeout: TimeInterval = 30) async throws -> (Data, HTTPURLResponse) {
        guard url.scheme == "http", ["127.0.0.1", "[::1]", "::1"].contains(url.host ?? ""),
              url.user == nil, url.password == nil else { throw TransportError.invalidRequest }
        return try await boundedRequest(URLRequest(url: url), fingerprint: nil, maximumResponseBytes: maximumResponseBytes, timeout: timeout)
    }
    #endif

    /// Probe all candidate routes together. A certificate match alone is not
    /// enough: the serving device must also match the authenticated registry ID.
    static func firstReachable(urls: [URL], fingerprint: String, deviceID: String,
                               timeout: TimeInterval = 5) async throws -> URL {
        try await firstReachableRoute(urls: urls, fingerprint: fingerprint, deviceID: deviceID, timeout: timeout).url
    }

    /// As `firstReachable`, also reporting the idle timeout the winning route
    /// advertised (`Keep-Alive: timeout=N`). Only this verified answer may set
    /// how long the session keeps idle connections.
    static func firstReachableRoute(urls: [URL], fingerprint: String, deviceID: String,
                                    timeout: TimeInterval = 5) async throws -> (url: URL, keepAlive: Int?) {
        guard timeout.isFinite, timeout > 0, !deviceID.isEmpty else { throw TransportError.invalidRequest }
        try Task.checkCancellation()
        return try await withThrowingTaskGroup(of: (URL, Int?)?.self) { group in
            for url in Set(urls) {
                group.addTask {
                    do {
                        let (data, response) = try await request(url: url, fingerprint: fingerprint,
                                                               maximumResponseBytes: 16_384, timeout: timeout)
                        guard response.statusCode == 200,
                              let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                              object["deviceId"] as? String == deviceID else { return nil }
                        try Task.checkCancellation()
                        return (url, KeepAlive.parse(response.value(forHTTPHeaderField: "Keep-Alive")))
                    } catch {
                        try Task.checkCancellation()
                        return nil
                    }
                }
            }
            while let result = try await group.next() {
                if let winner = result {
                    try Task.checkCancellation()
                    group.cancelAll()
                    return (url: winner.0, keepAlive: winner.1)
                }
            }
            try Task.checkCancellation()
            throw PinnedHTTPError.noReachableRoute
        }
    }

    fileprivate static func boundedRequest(_ request: URLRequest, fingerprint: String?, maximumResponseBytes: Int, timeout: TimeInterval) async throws -> (Data, HTTPURLResponse) {
        guard maximumResponseBytes >= 0, timeout.isFinite, timeout > 0 else { throw TransportError.invalidRequest }
        try Task.checkCancellation()
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieStorage = nil
        config.urlCache = nil
        config.timeoutIntervalForRequest = min(15, timeout)
        config.timeoutIntervalForResource = timeout
        let delegate = PinDelegate(fingerprint, maximumResponseBytes: maximumResponseBytes)
        let client = URLSession(configuration: config, delegate: delegate, delegateQueue: nil)
        defer { client.invalidateAndCancel() }
        let cancellation = HTTPTaskCancellation()
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                delegate.completion = { continuation.resume(with: $0) }
                let task = client.dataTask(with: request)
                cancellation.register(task)
                task.resume()
            }
        } onCancel: {
            cancellation.cancel()
        }
    }
}

/// One request per WebView connection; the proxy reuses pooled upstream
/// connections (see UpstreamPool). Uploads require Content-Length; WebSocket
/// upgrades become bounded, backpressured raw tunnels after the handshake.
struct MobileHTTPRequest {
    let method: String
    let path: String
    let headers: [String: String]
    let contentLength: Int
    var websocket: Bool { headers["upgrade"]?.lowercased() == "websocket" }
    static func parse(_ data: Data) throws -> MobileHTTPRequest {
        guard data.count <= 32_768, let text = String(data: data, encoding: .utf8), text.hasSuffix("\r\n\r\n") else {
            throw TransportError.invalidRequest
        }
        let lines = text.components(separatedBy: "\r\n")
        let parts = lines[0].split(separator: " ", omittingEmptySubsequences: false)
        guard parts.count == 3, parts[2] == "HTTP/1.1", ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"].contains(String(parts[0])),
              parts[1].hasPrefix("/"), !parts[1].hasPrefix("//"), !parts[1].contains("\\"),
              !parts[1].contains("#"), parts[1].allSatisfy({ $0.asciiValue.map { $0 > 32 && $0 < 127 } ?? false }) else {
            throw TransportError.invalidRequest
        }
        var headers: [String: String] = [:]
        let allowed = Set("!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyz")
        for line in lines.dropFirst().dropLast(2) {
            guard let colon = line.firstIndex(of: ":") else { throw TransportError.invalidRequest }
            let name = String(line[..<colon]).lowercased()
            let value = line[line.index(after: colon)...].trimmingCharacters(in: .whitespaces)
            guard !name.isEmpty, name.allSatisfy({ allowed.contains($0) }), headers[name] == nil,
                  value.unicodeScalars.allSatisfy({ $0.value >= 32 && $0.value != 127 }),
                  name != "transfer-encoding", name != "expect" else { throw TransportError.invalidRequest }
            headers[name] = value
        }
        let rawLength = headers["content-length"] ?? "0"
        guard !rawLength.isEmpty, rawLength.allSatisfy({ $0.isASCII && $0.isNumber }),
              let length = Int(rawLength), length <= 1_073_741_824 else { throw TransportError.invalidRequest }
        return MobileHTTPRequest(method: String(parts[0]), path: String(parts[1]), headers: headers, contentLength: length)
    }
}
/// Never forwarded upstream: browser credentials and context, hop-by-hop
/// fields, and framing the proxy writes itself.
private let requestExcluded: Set<String> = ["host", "authorization", "cookie", "origin", "proxy-connection", "proxy-authorization",
    "forwarded", "referer", "connection", "keep-alive", "te", "trailer", "transfer-encoding", "upgrade", "content-length", "expect"]
/// Never forwarded to the WebView: server cookies and policy, hop-by-hop
/// fields, and framing the proxy writes itself.
private let responseExcluded: Set<String> = ["set-cookie", "access-control-allow-origin", "access-control-allow-credentials",
    "connection", "keep-alive", "proxy-connection", "te", "trailer", "upgrade", "transfer-encoding"]
private let headEnd = Data("\r\n\r\n".utf8)

/// Whether a header from the WebView may go to the server.
private func forwardable(_ name: String, connectionTokens: Set<String>, excluded: Set<String>) -> Bool {
    !excluded.contains(name) && !connectionTokens.contains(name) && !name.hasPrefix("sec-fetch-") && !name.hasPrefix("x-forwarded-")
}

private func tokens(_ value: String?) -> Set<String> {
    Set((value ?? "").split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces).lowercased() })
}

final class MobileTransport: @unchecked Sendable {
    let cookieName = "stimma_native"
    let cookieValue = UUID().uuidString + UUID().uuidString
    private let frontend: URL
    private let shellFrontend: URL
    private let queue = DispatchQueue(label: "ai.stimma.mobile.transport")
    private var listener: NWListener?
    private var retiringListeners: [ObjectIdentifier: NWListener] = [:]
    private var listenerShutdownWaiters: [CheckedContinuation<Void, Never>] = []
    private var origin: URL?
    /// The current session's pooled upstream. Replacing it retires the old
    /// session: its idle connections close and its requests are cut.
    private var pool: UpstreamPool?
    private var peers: [UUID: Peer] = [:]
    /// How long the server may stay silent while a response is awaited or streaming.
    var upstreamReadTimeout: TimeInterval = 30
    /// How long the WebView may stay silent in the middle of an upload.
    var localReadTimeout: TimeInterval = 30
    /// Category-only diagnostics for requests the proxy failed.
    var report: (ProxyFailureReport) -> Void = ProxyFailureReport.log

    init(frontend: URL, shellFrontend: URL? = nil) {
        self.frontend = frontend.resolvingSymlinksInPath().standardizedFileURL
        self.shellFrontend = (shellFrontend ?? frontend).resolvingSymlinksInPath().standardizedFileURL
    }

    var isListening: Bool { queue.sync { listener?.state == .ready } }
    /// Test seams: the current session pool's idle and opened connection counts.
    var idleUpstreamConnections: Int { queue.sync { pool?.idleCount ?? 0 } }
    var openedUpstreamConnections: Int { queue.sync { pool?.opened ?? 0 } }

    func start() async throws -> URL {
        // cancel() is asynchronous. Wait for the old listener's cancellation
        // callback before rebinding its port, including rapid background/resume.
        await withCheckedContinuation { continuation in
            queue.async {
                if self.retiringListeners.isEmpty { continuation.resume() }
                else { self.listenerShutdownWaiters.append(continuation) }
            }
        }
        try Task.checkCancellation()
        return try await withCheckedThrowingContinuation { continuation in
            queue.async {
                if self.listener != nil, let origin = self.origin { continuation.resume(returning: origin); return }
                do {
                    let parameters = NWParameters.tcp
                    // Keep the WebView origin and capability cookie across suspension.
                    parameters.allowLocalEndpointReuse = true
                    let port = (self.origin?.port).flatMap { NWEndpoint.Port(rawValue: UInt16($0)) } ?? .any
                    parameters.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: port)
                    let listener = try NWListener(using: parameters)
                    self.listener = listener
                    var resolved = false
                    listener.stateUpdateHandler = { [weak listener] state in
                        guard let listener else { return }
                        if case .cancelled = state {
                            self.retiringListeners.removeValue(forKey: ObjectIdentifier(listener))
                            if self.retiringListeners.isEmpty {
                                let waiters = self.listenerShutdownWaiters
                                self.listenerShutdownWaiters.removeAll()
                                for waiter in waiters { waiter.resume() }
                            }
                        }
                        guard self.listener === listener else {
                            if !resolved { resolved = true; continuation.resume(throwing: CancellationError()) }
                            return
                        }
                        switch state {
                        case .ready:
                            guard !resolved, let port = listener.port else { return }; resolved = true
                            let origin = URL(string: "http://127.0.0.1:\(port.rawValue)")!
                            self.origin = origin; continuation.resume(returning: origin)
                        case .failed(let error):
                            self.listener = nil
                            listener.cancel()
                            if !resolved { resolved = true; continuation.resume(throwing: error) }
                        case .cancelled:
                            self.listener = nil
                            if !resolved { resolved = true; continuation.resume(throwing: CancellationError()) }
                        default: break
                        }
                    }
                    listener.newConnectionHandler = { [weak listener] connection in
                        guard let listener, self.listener === listener, self.peers.count < 96 else { connection.cancel(); return }
                        let peer = Peer(connection, owner: self)
                        self.peers[peer.id] = peer; peer.start()
                    }
                    listener.start(queue: self.queue)
                    self.queue.asyncAfter(deadline: .now() + 5) {
                        guard !resolved else { return }
                        resolved = true
                        if self.listener === listener { self.listener = nil }
                        listener.cancel()
                        continuation.resume(throwing: URLError(.timedOut))
                    }
                } catch { continuation.resume(throwing: error) }
            }
        }
    }

    /// Attach a verified session. `keepAlive` is the idle timeout the route
    /// advertised when it proved the device identity; nil keeps the short
    /// fallback that is safe for any server.
    func connect(host: String, port: Int, fingerprint: String, session: String, keepAlive: Int? = nil) {
        queue.sync {
            guard let port = UInt16(exactly: port), port > 0, !host.isEmpty,
                  !host.contains(where: { $0.isWhitespace || $0 == "/" || $0 == "@" }),
                  !session.contains(where: { $0.isNewline }) else { replace(with: nil); return }
            replace(with: UpstreamTarget(host: host, port: port, fingerprint: fingerprint, session: session,
                                         idleLimit: KeepAlive.idle(advertisedSeconds: keepAlive)))
        }
    }
    #if DEBUG && targetEnvironment(simulator)
    /// Simulator development only: cannot select a non-loopback unencrypted host.
    func connectLocal(port: Int) {
        queue.sync {
            guard let port = UInt16(exactly: port), port > 0 else { replace(with: nil); return }
            replace(with: UpstreamTarget(host: "127.0.0.1", port: port, fingerprint: "", session: "", tls: false))
        }
    }
    #endif

    /// On the queue: install a new session (or none) and retire the previous
    /// one, cutting every request it was still serving.
    private func replace(with target: UpstreamTarget?) {
        let previous = pool
        pool = target.map { UpstreamPool(target: $0, queue: queue) }
        guard let previous else { return }
        previous.retire()
        for peer in Array(peers.values) where peer.pool === previous { peer.retire() }
    }

    /// iOS may invalidate network resources while suspended. Discard them
    /// deliberately: in-flight requests and tunnels end and idle upstream
    /// connections close. The target, package, cookie, and loopback port stay.
    func suspend() {
        queue.sync {
            if let listener {
                retiringListeners[ObjectIdentifier(listener)] = listener
                listener.cancel()
                self.listener = nil
            }
            for peer in Array(peers.values) { peer.close() }
            pool?.evictIdle()
            pool?.abandonConnecting()
        }
    }

    /// Exercise the SAME listener, pinned upstream and session as the WebView.
    /// A direct server probe cannot detect a dead local listener or peer pool.
    func checkConnection() async throws -> Bool {
        try Task.checkCancellation()
        let address = try await start()
        try Task.checkCancellation()
        var request = URLRequest(url: address.appendingPathComponent("api/profiles"))
        request.setValue("\(cookieName)=\(cookieValue)", forHTTPHeaderField: "Cookie")
        let (_, response) = try await PinnedHTTP.boundedRequest(request, fingerprint: nil,
            maximumResponseBytes: 1_048_576, timeout: 5)
        return response.statusCode == 200 && response.value(forHTTPHeaderField: ProxyFailure.header) == nil
    }

    func stop() {
        queue.sync {
            listener?.cancel(); listener = nil; origin = nil
            replace(with: nil)
            for peer in Array(peers.values) { peer.close() }
        }
    }

    /// One WebView connection: a static file, one proxied HTTP exchange, or a
    /// WebSocket tunnel. Everything runs on the transport queue.
    private final class Peer {
        let id = UUID()
        let local: NWConnection
        unowned let owner: MobileTransport
        /// The session this request was admitted to; nil for static files.
        var pool: UpstreamPool?
        var upstream: UpstreamConnection?
        var tunnel: NWConnection?
        var timer: DispatchWorkItem?
        var uploadTimer: DispatchWorkItem?
        var closed = false
        /// A byte of the response has been queued for the WebView: no other response may follow.
        var responseStarted = false
        /// The whole response was handed to the WebView connection.
        var delivered = false
        /// The server's side of the exchange is over and its connection released.
        var upstreamDone = false
        /// The whole request, body included, has been written upstream.
        var requestSent = false
        /// Whether the server will keep the connection after this response.
        var reusable = false
        var framing: ResponseFraming?
        /// Bodies without a length are re-chunked so the WebView can tell complete from truncated.
        var rechunk = false
        var request: MobileHTTPRequest?
        var initial = Data()

        init(_ local: NWConnection, owner: MobileTransport) { self.local = local; self.owner = owner }

        func close() {
            guard !closed else { return }; closed = true
            timer?.cancel(); timer = nil
            uploadTimer?.cancel(); uploadTimer = nil
            local.cancel()
            if let upstream { self.upstream = nil; upstream.reset() }
            tunnel?.cancel(); tunnel = nil
            owner.peers.removeValue(forKey: id)
        }

        /// End the WebView connection abortively: a response that has started
        /// can only be cut, never followed by a second one.
        func reset() {
            guard !closed else { return }
            local.forceCancel()
            close()
        }

        /// Answer a failed request once, or cut it if its response already began.
        func fail(_ failure: ProxyFailure, cause: String) {
            guard !closed else { return }
            owner.report(ProxyFailureReport(failure: failure, afterResponseStarted: responseStarted, cause: cause))
            if responseStarted { reset(); return }
            timer?.cancel(); timer = nil
            uploadTimer?.cancel(); uploadTimer = nil
            if let upstream { self.upstream = nil; upstream.reset() }
            tunnel?.cancel(); tunnel = nil
            reply(failure.status, failure.reason, data: Data("Request unavailable".utf8), failure: failure)
        }

        /// The session this request belongs to was replaced or ended.
        func retire() {
            guard !closed, !delivered else { return }
            fail(.unavailable, cause: "SessionRetired")
        }

        func timeout(_ seconds: TimeInterval = 15, _ action: @escaping (Peer) -> Void = { $0.close() }) {
            timer?.cancel()
            let timer = DispatchWorkItem { [weak self] in if let self, !self.closed { action(self) } }
            self.timer = timer; owner.queue.asyncAfter(deadline: .now() + seconds, execute: timer)
        }
        func start() {
            local.stateUpdateHandler = { [weak self] state in if case .failed = state { self?.close() } }
            local.start(queue: owner.queue); timeout(); readHeader(Data())
        }
        func readHeader(_ buffer: Data) {
            local.receive(minimumIncompleteLength: 1, maximumLength: 32_768) { [weak self] data, _, done, error in
                guard let self, !self.closed else { return }
                var buffer = buffer; if let data { buffer.append(data) }
                if let end = buffer.range(of: headEnd) {
                    self.timer?.cancel(); self.timer = nil
                    do {
                        let request = try MobileHTTPRequest.parse(Data(buffer[..<end.upperBound]))
                        self.handle(request, body: Data(buffer[end.upperBound...]))
                    } catch { self.fail(.rejected, cause: "Framing") }
                } else if buffer.count >= 32_768 || done || error != nil { self.close() }
                else { self.readHeader(buffer) }
            }
        }
        func reply(_ status: Int, _ message: String, data: Data? = nil, type: String = "text/plain", head: Bool = false, failure: ProxyFailure? = nil) {
            responseStarted = true
            let body = data ?? Data(message.utf8)
            var text = "HTTP/1.1 \(status) \(message)\r\nContent-Length: \(body.count)\r\nContent-Type: \(type)\r\nConnection: close\r\nX-Content-Type-Options: nosniff\r\n"
            if let failure { text += "Cache-Control: no-store\r\n\(ProxyFailure.header): \(failure.category)\r\n\r\n" }
            else { text += "Cache-Control: no-cache\r\n\r\n" }
            var output = Data(text.utf8)
            if !head { output.append(body) }
            local.send(content: output, completion: .contentProcessed { [weak self] _ in
                self?.delivered = true
                self?.close()
            })
        }
        func handle(_ request: MobileHTTPRequest, body: Data) {
            guard let origin = owner.origin,
                  request.headers["host"] == "127.0.0.1:\(origin.port!)",
                  request.headers["origin"].map({ $0 == origin.absoluteString }) ?? true,
                  request.headers["sec-fetch-site"].map({ ["same-origin", "none"].contains($0) }) ?? true,
                  request.headers["cookie"]?.components(separatedBy: ";").contains(where: {
                      $0.trimmingCharacters(in: .whitespaces) == "\(owner.cookieName)=\(owner.cookieValue)"
                  }) == true else { fail(.rejected, cause: "Capability"); return }
            guard body.count <= request.contentLength else { fail(.rejected, cause: "Framing"); return }
            let path = request.path.components(separatedBy: "?")[0]
            if path.hasPrefix("/api/") || path == "/api" || path == "/ws" || path.hasPrefix("/ws/") || path == "/health" {
                forward(request, body: body); return
            }
            guard ["GET", "HEAD"].contains(request.method), request.contentLength == 0, !request.websocket,
                  let decoded = path.removingPercentEncoding, !decoded.contains("\\"), !decoded.contains("\0"),
                  !decoded.components(separatedBy: "/").contains("..") else { fail(.rejected, cause: "Path"); return }
            var file = owner.frontend.appendingPathComponent(String(decoded.dropFirst())).resolvingSymlinksInPath().standardizedFileURL
            guard file.path.hasPrefix(owner.frontend.path + "/") || file == owner.frontend else { fail(.rejected, cause: "Path"); return }
            let shellFile = owner.shellFrontend.appendingPathComponent(String(decoded.dropFirst())).resolvingSymlinksInPath().standardizedFileURL
            if decoded != "/", decoded != "/index.html", shellFile.path.hasPrefix(owner.shellFrontend.path + "/"),
               FileManager.default.fileExists(atPath: shellFile.path) { file = shellFile }
            var isDirectory: ObjCBool = false
            if !FileManager.default.fileExists(atPath: file.path, isDirectory: &isDirectory) || isDirectory.boolValue {
                guard !(decoded.split(separator: "/").last.map({ $0.contains(".") }) ?? false) else { reply(404, "Not Found"); return }
                file = owner.frontend.appendingPathComponent("index.html")
            }
            guard let data = try? Data(contentsOf: file) else { reply(404, "Not Found"); return }
            let type = file.pathExtension == "js" ? "application/javascript" : UTType(filenameExtension: file.pathExtension)?.preferredMIMEType ?? "application/octet-stream"
            reply(200, "OK", data: data, type: type, head: request.method == "HEAD")
        }

        // MARK: Proxied HTTP

        var safe: Bool { ["GET", "HEAD", "OPTIONS"].contains(request?.method ?? "") }

        func forward(_ request: MobileHTTPRequest, body: Data) {
            guard let pool = owner.pool, !pool.retired else { fail(.unavailable, cause: "NoSession"); return }
            self.pool = pool
            if request.websocket { openTunnel(request, pool: pool); return }
            if ["GET", "HEAD"].contains(request.method) && request.contentLength != 0 { fail(.rejected, cause: "Framing"); return }
            self.request = request
            let target = pool.target
            let connectionTokens = tokens(request.headers["connection"])
            var head = "\(request.method) \(request.path) HTTP/1.1\r\nHost: \(target.hostHeader)\r\n"
            if !target.session.isEmpty { head += "Authorization: Bearer \(target.session)\r\n" }
            for (name, value) in request.headers.sorted(by: { $0.key < $1.key })
            where forwardable(name, connectionTokens: connectionTokens, excluded: requestExcluded) {
                head += "\(name): \(value)\r\n"
            }
            // Mutations always state their length, even zero, so the server never waits for a body.
            if !safe || request.headers["content-length"] != nil { head += "Content-Length: \(request.contentLength)\r\n" }
            head += "\r\n"
            initial = Data(head.utf8); initial.append(body)
            // Content coding is negotiated end to end: Accept-Encoding passes
            // through and encoded bytes pass back untouched for the WebView to
            // decode, so Content-Encoding, Content-Length and ETag stay true.
            exchange(remaining: request.contentLength - body.count, mayRetry: safe && request.contentLength == 0, fresh: false)
        }

        /// One attempt at the exchange. Only a safe, bodiless request whose
        /// reused connection failed before any response byte may try again,
        /// once, on a new connection: a mutation whose outcome is unknown is
        /// never sent twice.
        func exchange(remaining: Int, mayRetry: Bool, fresh: Bool) {
            guard let pool else { return }
            pool.acquire(safe: safe, fresh: fresh) { [weak self] result in
                guard let self, !self.closed, !pool.retired else {
                    // Nothing was sent on it: an unused connection is still good.
                    if case .success(let connection) = result { pool.release(connection, reusable: true) }
                    return
                }
                switch result {
                case .failure(let failure): self.fail(failure, cause: "Connect")
                case .success(let connection):
                    self.upstream = connection
                    let retry = mayRetry && connection.reused
                    // Counted as sent once queued: a response can complete before the send callback runs.
                    self.requestSent = remaining == 0
                    connection.send(self.initial) { [weak self] error in
                        guard let self, !self.closed, self.upstream === connection else { return }
                        if error != nil { self.upstreamFailed(connection, error: error, retry: retry); return }
                        self.upload(remaining: remaining, connection)
                    }
                    self.awaitHead(Data(), connection, retry: retry)
                }
            }
        }

        func upstreamFailed(_ connection: UpstreamConnection, error: NWError?, retry: Bool) {
            guard !closed, upstream === connection else { return }
            if retry && !responseStarted {
                // A pooled connection the server had already dropped: nothing reached it.
                upstream = nil; connection.reset()
                requestSent = false
                exchange(remaining: 0, mayRetry: false, fresh: true)
                return
            }
            fail(UpstreamPool.classify(error), cause: error == nil ? "Closed" : "Network")
        }

        func upload(remaining: Int, _ connection: UpstreamConnection) {
            guard remaining > 0 else { watchLocal(); return }
            uploadTimer?.cancel()
            let timer = DispatchWorkItem { [weak self] in self?.close() }
            uploadTimer = timer; owner.queue.asyncAfter(deadline: .now() + owner.localReadTimeout, execute: timer)
            local.receive(minimumIncompleteLength: 1, maximumLength: min(65_536, remaining)) { [weak self] data, _, done, error in
                guard let self, !self.closed else { return }
                self.uploadTimer?.cancel(); self.uploadTimer = nil
                guard self.upstream === connection, !self.upstreamDone else { return }
                // The WebView stopped sending: abandon the exchange.
                guard let data, !data.isEmpty, error == nil else { self.close(); return }
                if data.count >= remaining { self.requestSent = true }
                connection.send(data) { [weak self] error in
                    guard let self, !self.closed, self.upstream === connection else { return }
                    if error != nil { self.upstreamFailed(connection, error: error, retry: false) }
                    else if done && data.count < remaining { self.close() }
                    else { self.upload(remaining: remaining - data.count, connection) }
                }
            }
        }

        /// Once the request is sent the WebView has nothing more to say, so
        /// end of stream or an error means it gave up (an aborted fetch, a
        /// thumbnail scrolled away): stop the upstream exchange too.
        func watchLocal() {
            local.receive(minimumIncompleteLength: 1, maximumLength: 1) { [weak self] data, _, done, error in
                guard let self, !self.closed else { return }
                if let data, !data.isEmpty { return } // Unexpected pipelined bytes: stop watching.
                if done || error != nil { self.close() }
            }
        }

        func readTimeout() {
            timeout(owner.upstreamReadTimeout) { $0.fail(.upstreamTimeout, cause: "ReadTimeout") }
        }

        func awaitHead(_ buffer: Data, _ connection: UpstreamConnection, retry: Bool) {
            if let end = buffer.range(of: headEnd) {
                let head: UpstreamResponseHead
                do { head = try UpstreamResponseHead.parse(Data(buffer[..<end.upperBound])) }
                catch { fail(.upstreamProtocol, cause: "Head"); return }
                let rest = Data(buffer[end.upperBound...])
                if (100...199).contains(head.status) {
                    // Interim responses carry nothing for the WebView; a 101 here was never asked for.
                    guard head.status != 101 else { fail(.upstreamProtocol, cause: "Upgrade"); return }
                    awaitHead(rest, connection, retry: false)
                    return
                }
                respond(head, rest: rest, connection)
                return
            }
            guard buffer.count < 32_768 else { fail(.upstreamProtocol, cause: "Head"); return }
            readTimeout()
            connection.read { [weak self] data, ended, error in
                guard let self, !self.closed, self.upstream === connection else { return }
                self.timer?.cancel(); self.timer = nil
                var buffer = buffer; if let data { buffer.append(data) }
                if ended && buffer.range(of: headEnd) == nil {
                    self.upstreamFailed(connection, error: error, retry: retry && buffer.isEmpty)
                    return
                }
                self.awaitHead(buffer, connection, retry: retry && buffer.isEmpty)
            }
        }

        /// Redirects are never followed and normally refused: a device
        /// credential must not move to another destination. Provider panels may
        /// redirect within their own local path.
        func redirectAllowed(_ head: UpstreamResponseHead) -> Bool {
            let locations = head.values("location")
            guard locations.count <= 1 else { return false }
            guard (300...399).contains(head.status), head.status != 304 else { return true }
            guard let path = request?.path.components(separatedBy: "?")[0], path.hasPrefix("/api/provider-manage/"),
                  let value = locations.first, !value.contains("\\"), let location = URLComponents(string: value),
                  location.scheme == nil, location.host == nil, location.path.hasPrefix("/api/provider-manage/"),
                  !location.path.split(separator: "/").contains(where: { $0 == "." || $0 == ".." }) else { return false }
            return true
        }

        func respond(_ head: UpstreamResponseHead, rest: Data, _ connection: UpstreamConnection) {
            guard let request else { return }
            guard redirectAllowed(head) else { fail(.upstreamProtocol, cause: "Redirect"); return }
            let framing: ResponseFraming
            do { framing = try ResponseFraming.of(head, method: request.method) }
            catch { fail(.upstreamProtocol, cause: "Framing"); return }
            let connectionTokens = head.connectionTokens
            reusable = head.minor == 1 && !connectionTokens.contains("close") && framing.kind != .untilClose
            rechunk = framing.kind == .untilClose
            var text = "HTTP/1.1 \(head.status) \(head.reason)\r\n"
            for (name, value) in head.fields where !responseExcluded.contains(name) && !connectionTokens.contains(name) {
                if name == "content-length", framing.kind == .chunked || framing.kind == .untilClose { continue }
                text += "\(name): \(value)\r\n"
            }
            if framing.kind == .chunked || rechunk { text += "Transfer-Encoding: chunked\r\n" }
            text += "Connection: close\r\n\r\n"
            self.framing = framing
            responseStarted = true
            local.send(content: Data(text.utf8), completion: .contentProcessed { [weak self] error in
                guard let self, !self.closed, error != nil else { return }
                self.close()
            })
            deliver(rest, ended: false, error: nil)
        }

        func deliver(_ chunk: Data, ended: Bool, error: NWError?) {
            guard var framing else { return }
            var payload = Data()
            if !chunk.isEmpty {
                let used: Int
                do { used = try framing.feed(chunk) } catch { fail(.upstreamProtocol, cause: "Framing"); return }
                if used < chunk.count { reusable = false } // Bytes after the response: do not trust this connection.
                payload = used == chunk.count ? chunk : Data(chunk.prefix(used))
            }
            self.framing = framing
            var finished = framing.complete
            if !finished && ended {
                guard framing.kind == .untilClose && error == nil else {
                    fail(UpstreamPool.classify(error), cause: "Truncated"); return
                }
                finished = true
            }
            if finished { finishUpstream() }
            var output = payload
            if rechunk {
                output = Data()
                if !payload.isEmpty {
                    output.append(Data((String(payload.count, radix: 16) + "\r\n").utf8))
                    output.append(payload)
                    output.append(Data("\r\n".utf8))
                }
                if finished { output.append(Data("0\r\n\r\n".utf8)) }
            }
            guard !output.isEmpty else {
                if finished { complete() } else { readBody() }
                return
            }
            local.send(content: output, completion: .contentProcessed { [weak self] error in
                guard let self, !self.closed else { return }
                if error != nil { self.close(); return } // The WebView went away: nobody to answer.
                if finished { self.complete() } else { self.readBody() }
            })
        }

        func readBody() {
            guard let connection = upstream else { return }
            readTimeout()
            connection.read { [weak self] data, ended, error in
                guard let self, !self.closed, self.upstream === connection else { return }
                self.timer?.cancel(); self.timer = nil
                self.deliver(data ?? Data(), ended: ended, error: error)
            }
        }

        /// The server's response is complete. Release its connection before the
        /// WebView sees the last byte, so a WebView that hangs up right after
        /// cannot discard a connection that is already back in the pool.
        func finishUpstream() {
            upstreamDone = true
            timer?.cancel(); timer = nil
            guard let connection = upstream else { return }
            upstream = nil
            pool?.release(connection, reusable: reusable && requestSent)
        }

        /// Every byte of the response is queued: end the WebView connection
        /// after them (cancelling at once would discard queued bytes).
        func complete() {
            delivered = true
            local.send(content: nil, contentContext: .finalMessage, isComplete: true, completion: .contentProcessed { [weak self] _ in
                self?.close()
            })
        }

        // MARK: WebSocket tunnels

        /// WebSocket upgrades keep their own raw pinned connection for the life of the socket.
        func openTunnel(_ request: MobileHTTPRequest, pool: UpstreamPool) {
            guard request.method == "GET", request.contentLength == 0, request.path.components(separatedBy: "?")[0] == "/ws" else {
                fail(.rejected, cause: "Upgrade"); return
            }
            let target = pool.target
            var pinRejected = false
            let connection = NWConnection(host: NWEndpoint.Host(target.host), port: NWEndpoint.Port(rawValue: target.port)!,
                                          using: target.parameters(queue: owner.queue, rejected: { pinRejected = true }))
            tunnel = connection
            let connectionTokens = tokens(request.headers["connection"]).subtracting(["upgrade"])
            var header = "GET \(request.path) HTTP/1.1\r\nHost: \(target.hostHeader)\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n"
            if !target.session.isEmpty { header += "Authorization: Bearer \(target.session)\r\n" }
            for (name, value) in request.headers.sorted(by: { $0.key < $1.key })
            where forwardable(name, connectionTokens: connectionTokens, excluded: requestExcluded.union(["accept-encoding"])) {
                header += "\(name): \(value)\r\n"
            }
            header += "\r\n"
            let initial = Data(header.utf8)
            connection.stateUpdateHandler = { [weak self] state in
                guard let self, !self.closed, self.tunnel === connection else { return }
                switch state {
                case .ready:
                    self.timer?.cancel(); self.timer = nil
                    connection.send(content: initial, completion: .contentProcessed { [weak self] error in
                        guard let self, !self.closed else { return }
                        if error != nil { self.fail(UpstreamPool.classify(error), cause: "Send"); return }
                        self.readUpgrade(Data(), connection)
                    })
                case .waiting(let error), .failed(let error):
                    self.fail(pinRejected ? .upstreamIdentity : UpstreamPool.classify(error), cause: "Connect")
                default: break
                }
            }
            timeout(pool.connectTimeout) { $0.fail(pinRejected ? .upstreamIdentity : .upstreamTimeout, cause: "Connect") }
            connection.start(queue: owner.queue)
        }

        func readUpgrade(_ buffer: Data, _ upstream: NWConnection) {
            timeout(owner.upstreamReadTimeout) { $0.fail(.upstreamTimeout, cause: "ReadTimeout") }
            upstream.receive(minimumIncompleteLength: 1, maximumLength: 32_768) { [weak self] data, _, done, error in
                guard let self, !self.closed else { return }
                var buffer = buffer; if let data { buffer.append(data) }
                if let end = buffer.range(of: headEnd) {
                    guard end.upperBound <= 32_768, let header = String(data: buffer[..<end.upperBound], encoding: .utf8), header.hasPrefix("HTTP/1.1 101 ") else {
                        self.fail(.upstreamProtocol, cause: "Upgrade"); return
                    }
                    self.timer?.cancel(); self.timer = nil
                    self.responseStarted = true
                    self.local.send(content: buffer, completion: .contentProcessed { [weak self] error in
                        guard let self else { return }
                        if error != nil { self.close(); return }
                        self.pump(upstream, to: self.local); self.pump(self.local, to: upstream)
                    })
                } else if buffer.count >= 32_768 { self.fail(.upstreamProtocol, cause: "Upgrade") }
                else if done || error != nil { self.fail(UpstreamPool.classify(error), cause: "Closed") }
                else { self.readUpgrade(buffer, upstream) }
            }
        }
        func pump(_ source: NWConnection, to destination: NWConnection) {
            guard !closed else { return }
            source.receive(minimumIncompleteLength: 1, maximumLength: 65_536) { [weak self] data, _, done, error in
                guard let self, !self.closed else { return }
                guard let data, !data.isEmpty else { self.close(); return }
                destination.send(content: data, completion: .contentProcessed { [weak self] sendError in
                    guard let self else { return }
                    if done || error != nil || sendError != nil { self.close() }
                    else { self.pump(source, to: destination) }
                })
            }
        }
    }
}
