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
        guard timeout.isFinite, timeout > 0, !deviceID.isEmpty else { throw TransportError.invalidRequest }
        try Task.checkCancellation()
        return try await withThrowingTaskGroup(of: URL?.self) { group in
            for url in Set(urls) {
                group.addTask {
                    do {
                        let (data, response) = try await request(url: url, fingerprint: fingerprint,
                                                               maximumResponseBytes: 16_384, timeout: timeout)
                        guard response.statusCode == 200,
                              let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                              object["deviceId"] as? String == deviceID else { return nil }
                        try Task.checkCancellation()
                        return url
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
                    return winner
                }
            }
            try Task.checkCancellation()
            throw PinnedHTTPError.noReachableRoute
        }
    }

    private static func boundedRequest(_ request: URLRequest, fingerprint: String?, maximumResponseBytes: Int, timeout: TimeInterval) async throws -> (Data, HTTPURLResponse) {
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

/// Deliberately one HTTP request per TCP connection. Uploads require Content-Length;
/// WebSocket upgrades become bounded, backpressured raw tunnels after the handshake.
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

final class MobileTransport: @unchecked Sendable {
    let cookieName = "stimma_native"
    let cookieValue = UUID().uuidString + UUID().uuidString
    private let frontend: URL
    private let shellFrontend: URL
    private let queue = DispatchQueue(label: "ai.stimma.mobile.transport")
    private var listener: NWListener?
    private var origin: URL?
    private struct Target { let host: String; let port: UInt16; let fingerprint: String; let session: String; var tls = true }
    private var target: Target?
    private var peers: [UUID: Peer] = [:]
    init(frontend: URL, shellFrontend: URL? = nil) {
        self.frontend = frontend.resolvingSymlinksInPath().standardizedFileURL
        self.shellFrontend = (shellFrontend ?? frontend).resolvingSymlinksInPath().standardizedFileURL
    }

    func start() async throws -> URL {
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                if let origin = self.origin { continuation.resume(returning: origin); return }
                do {
                    let parameters = NWParameters.tcp
                    parameters.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: .any)
                    let listener = try NWListener(using: parameters)
                    self.listener = listener
                    var resolved = false
                    listener.stateUpdateHandler = { state in
                        switch state {
                        case .ready:
                            guard !resolved, let port = listener.port else { return }; resolved = true
                            let origin = URL(string: "http://127.0.0.1:\(port.rawValue)")!
                            self.origin = origin; continuation.resume(returning: origin)
                        case .failed(let error):
                            if !resolved { resolved = true; continuation.resume(throwing: error) }
                        default: break
                        }
                    }
                    listener.newConnectionHandler = { connection in
                        guard self.peers.count < 96 else { connection.cancel(); return }
                        let peer = Peer(connection, owner: self)
                        self.peers[peer.id] = peer; peer.start()
                    }
                    listener.start(queue: self.queue)
                } catch { continuation.resume(throwing: error) }
            }
        }
    }
    func connect(host: String, port: Int, fingerprint: String, session: String) {
        queue.sync {
            for peer in Array(peers.values) { peer.close() }
            guard let port = UInt16(exactly: port), port > 0, !host.isEmpty,
                  !host.contains(where: { $0.isWhitespace || $0 == "/" || $0 == "@" }),
                  !session.contains(where: { $0.isNewline }) else { target = nil; return }
            target = Target(host: host, port: port, fingerprint: fingerprint, session: session)
        }
    }
    #if DEBUG && targetEnvironment(simulator)
    /// Simulator development only: cannot select a non-loopback unencrypted host.
    func connectLocal(port: Int) {
        queue.sync {
            for peer in Array(peers.values) { peer.close() }
            guard let port = UInt16(exactly: port), port > 0 else { target = nil; return }
            target = Target(host: "127.0.0.1", port: port, fingerprint: "", session: "", tls: false)
        }
    }
    #endif

    func stop() {
        queue.sync {
            listener?.cancel(); listener = nil; origin = nil; target = nil
            for peer in Array(peers.values) { peer.close() }
        }
    }

    private final class Peer {
        let id = UUID()
        let local: NWConnection
        unowned let owner: MobileTransport
        var upstream: NWConnection?
        var timer: DispatchWorkItem?
        var closed = false
        init(_ local: NWConnection, owner: MobileTransport) { self.local = local; self.owner = owner }
        func close() {
            guard !closed else { return }; closed = true
            timer?.cancel(); timer = nil
            local.cancel(); upstream?.cancel(); owner.peers.removeValue(forKey: id)
        }
        func timeout() {
            timer?.cancel()
            let timer = DispatchWorkItem { [weak self] in self?.close() }
            self.timer = timer; owner.queue.asyncAfter(deadline: .now() + 15, execute: timer)
        }
        func start() {
            local.stateUpdateHandler = { [weak self] state in if case .failed = state { self?.close() } }
            local.start(queue: owner.queue); timeout(); readHeader(Data())
        }
        func readHeader(_ buffer: Data) {
            local.receive(minimumIncompleteLength: 1, maximumLength: 32_768) { [weak self] data, _, done, error in
                guard let self, !self.closed else { return }
                var buffer = buffer; if let data { buffer.append(data) }
                if let end = buffer.range(of: Data("\r\n\r\n".utf8)) {
                    do {
                        let request = try MobileHTTPRequest.parse(Data(buffer[..<end.upperBound]))
                        self.handle(request, body: Data(buffer[end.upperBound...]))
                    } catch { self.reply(400, "Bad Request") }
                } else if buffer.count >= 32_768 || done || error != nil { self.close() }
                else { self.readHeader(buffer) }
            }
        }
        func reply(_ status: Int, _ message: String, data: Data? = nil, type: String = "text/plain", head: Bool = false) {
            let body = data ?? Data(message.utf8)
            var output = Data("HTTP/1.1 \(status) \(message)\r\nContent-Length: \(body.count)\r\nContent-Type: \(type)\r\nConnection: close\r\nX-Content-Type-Options: nosniff\r\nCache-Control: no-cache\r\n\r\n".utf8)
            if !head { output.append(body) }
            local.send(content: output, completion: .contentProcessed { [weak self] _ in self?.close() })
        }
        func handle(_ request: MobileHTTPRequest, body: Data) {
            guard let origin = owner.origin,
                  request.headers["host"] == "127.0.0.1:\(origin.port!)",
                  request.headers["origin"].map({ $0 == origin.absoluteString }) ?? true,
                  request.headers["sec-fetch-site"].map({ ["same-origin", "none"].contains($0) }) ?? true,
                  request.headers["cookie"]?.components(separatedBy: ";").contains(where: {
                      $0.trimmingCharacters(in: .whitespaces) == "\(owner.cookieName)=\(owner.cookieValue)"
                  }) == true else { reply(403, "Forbidden"); return }
            guard body.count <= request.contentLength else { reply(400, "Bad Request"); return }
            let path = request.path.components(separatedBy: "?")[0]
            if path.hasPrefix("/api/") || path == "/api" || path == "/ws" || path.hasPrefix("/ws/") || path == "/health" {
                forward(request, body: body); return
            }
            guard ["GET", "HEAD"].contains(request.method), request.contentLength == 0, !request.websocket,
                  let decoded = path.removingPercentEncoding, !decoded.contains("\\"), !decoded.contains("\0"),
                  !decoded.components(separatedBy: "/").contains("..") else { reply(400, "Bad Request"); return }
            var file = owner.frontend.appendingPathComponent(String(decoded.dropFirst())).resolvingSymlinksInPath().standardizedFileURL
            guard file.path.hasPrefix(owner.frontend.path + "/") || file == owner.frontend else { reply(403, "Forbidden"); return }
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
        func forward(_ request: MobileHTTPRequest, body: Data) {
            guard let target = owner.target else { reply(503, "No active device"); return }
            if request.websocket && (request.method != "GET" || request.contentLength != 0 || request.path.components(separatedBy: "?")[0] != "/ws") {
                reply(400, "Bad Request"); return
            }
            let tls = NWProtocolTLS.Options()
            sec_protocol_options_add_tls_application_protocol(tls.securityProtocolOptions, "http/1.1")
            sec_protocol_options_set_verify_block(tls.securityProtocolOptions, { _, trust, complete in
                let trust = sec_trust_copy_ref(trust).takeRetainedValue()
                let chain = SecTrustCopyCertificateChain(trust) as? [SecCertificate]
                complete(chain?.first.map { certificateMatches($0, fingerprint: target.fingerprint) } ?? false)
            }, owner.queue)
            let connection = NWConnection(host: NWEndpoint.Host(target.host), port: NWEndpoint.Port(rawValue: target.port)!, using: target.tls ? NWParameters(tls: tls) : NWParameters.tcp)
            upstream = connection
            var excluded: Set<String> = ["host", "authorization", "cookie", "content-length", "connection", "upgrade", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "expect"]
            for token in (request.headers["connection"] ?? "").split(separator: ",") { excluded.insert(token.trimmingCharacters(in: .whitespaces).lowercased()) }
            let host = target.host.contains(":") ? "[\(target.host)]" : target.host
            var header = "\(request.method) \(request.path) HTTP/1.1\r\nHost: \(host):\(target.port)\r\nConnection: \(request.websocket ? "Upgrade" : "close")\r\n"
            if !target.session.isEmpty { header += "Authorization: Bearer \(target.session)\r\n" }
            for (key, value) in request.headers where !excluded.contains(key) { header += "\(key): \(value)\r\n" }
            if request.headers["content-length"] != nil { header += "Content-Length: \(request.contentLength)\r\n" }
            if request.websocket { header += "Upgrade: websocket\r\n" }
            header += "\r\n"
            var initial = Data(header.utf8); initial.append(body)
            connection.stateUpdateHandler = { [weak self] state in
                guard let self, !self.closed else { return }
                switch state {
                case .ready:
                    self.timer?.cancel(); self.timer = nil
                    connection.send(content: initial, completion: .contentProcessed { [weak self] error in
                        guard let self, !self.closed else { return }
                        if error != nil { self.close(); return }
                        if request.websocket { self.readUpgrade(Data()) }
                        else {
                            self.pump(connection, to: self.local)
                            self.upload(remaining: request.contentLength - body.count)
                        }
                    })
                case .failed: self.close()
                default: break
                }
            }
            timeout(); connection.start(queue: owner.queue)
        }
        func upload(remaining: Int) {
            guard remaining > 0, let upstream else { return }
            local.receive(minimumIncompleteLength: 1, maximumLength: min(65_536, remaining)) { [weak self] data, _, done, error in
                guard let self, !self.closed else { return }
                guard let data, !data.isEmpty, error == nil else { self.close(); return }
                upstream.send(content: data, completion: .contentProcessed { [weak self] error in
                    guard let self else { return }
                    if error != nil || (done && data.count < remaining) { self.close() }
                    else { self.upload(remaining: remaining - data.count) }
                })
            }
        }
        func readUpgrade(_ buffer: Data) {
            guard let upstream else { return }; timeout()
            upstream.receive(minimumIncompleteLength: 1, maximumLength: 32_768) { [weak self] data, _, done, error in
                guard let self, !self.closed else { return }
                var buffer = buffer; if let data { buffer.append(data) }
                if let end = buffer.range(of: Data("\r\n\r\n".utf8)) {
                    guard end.upperBound <= 32_768, let header = String(data: buffer[..<end.upperBound], encoding: .utf8), header.hasPrefix("HTTP/1.1 101 ") else {
                        self.reply(502, "WebSocket upgrade failed"); return
                    }
                    self.timer?.cancel(); self.timer = nil
                    self.local.send(content: buffer, completion: .contentProcessed { [weak self] error in
                        guard let self else { return }
                        if error != nil { self.close(); return }
                        self.pump(upstream, to: self.local); self.pump(self.local, to: upstream)
                    })
                } else if buffer.count >= 32_768 || done || error != nil { self.close() }
                else { self.readUpgrade(buffer) }
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
