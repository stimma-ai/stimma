import Foundation
import Network

/// A raw HTTP exchange with the local proxy, as the WebView has it: one
/// request per connection, read to the end. Exposes exact bytes and framing.
struct RawResponse {
    let status: Int
    let headers: [String: String]
    let body: Data
    let complete: Bool
    func header(_ name: String) -> String? { headers[name.lowercased()] }
    var text: String { String(decoding: body, as: UTF8.self) }
}

final class RawClient: @unchecked Sendable {
    private let connection: NWConnection
    private let queue = DispatchQueue(label: "raw-client")
    private var received = Data()
    private var finished = false

    init(_ origin: URL) {
        connection = NWConnection(host: "127.0.0.1", port: NWEndpoint.Port(rawValue: UInt16(origin.port!))!, using: .tcp)
    }

    func open(_ request: String, body: Data = Data()) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            connection.stateUpdateHandler = { state in
                switch state {
                case .ready:
                    self.connection.stateUpdateHandler = nil
                    var bytes = Data(request.utf8); bytes.append(body)
                    self.connection.send(content: bytes, completion: .contentProcessed { error in
                        if let error { continuation.resume(throwing: error) } else { continuation.resume() }
                    })
                case .failed(let error), .waiting(let error):
                    self.connection.stateUpdateHandler = nil
                    continuation.resume(throwing: error)
                default: break
                }
            }
            connection.start(queue: queue)
        }
    }

    /// Read until at least `count` bytes arrived or the connection ended.
    func read(atLeast count: Int, timeout: TimeInterval = 10) async -> Data {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            let (data, done) = await next()
            if let data { queue.sync { received.append(data) } }
            let (size, ended) = queue.sync { (received.count, finished) }
            if done { queue.sync { finished = true } }
            if size >= count || done || ended { break }
        }
        return queue.sync { received }
    }

    private func next() async -> (Data?, Bool) {
        await withCheckedContinuation { continuation in
            connection.receive(minimumIncompleteLength: 1, maximumLength: 1 << 20) { data, _, complete, error in
                continuation.resume(returning: (data, complete || error != nil))
            }
        }
    }

    func send(_ data: Data) async {
        await withCheckedContinuation { continuation in
            connection.send(content: data, completion: .contentProcessed { _ in continuation.resume() })
        }
    }

    func close() { connection.cancel() }

    /// The whole exchange: send, read to end of stream, parse.
    static func exchange(_ origin: URL, _ request: String, body: Data = Data(), timeout: TimeInterval = 15) async throws -> RawResponse {
        let client = RawClient(origin)
        defer { client.close() }
        try await client.open(request, body: body)
        let bytes = await client.read(atLeast: Int.max, timeout: timeout)
        return parse(bytes)
    }

    static func parse(_ bytes: Data) -> RawResponse {
        guard let end = bytes.range(of: Data("\r\n\r\n".utf8)) else { return RawResponse(status: 0, headers: [:], body: Data(), complete: false) }
        let lines = String(decoding: bytes[..<end.lowerBound], as: UTF8.self).components(separatedBy: "\r\n")
        let status = Int(lines[0].split(separator: " ")[1]) ?? 0
        var headers: [String: String] = [:]
        for line in lines.dropFirst() {
            let parts = line.split(separator: ":", maxSplits: 1)
            let name = parts[0].lowercased()
            let value = parts.count > 1 ? parts[1].trimmingCharacters(in: .whitespaces) : ""
            precondition(headers[name] == nil, "Repeated response header \(name)")
            headers[name] = value
        }
        var body = Data(bytes[end.upperBound...])
        var complete = true
        if headers["transfer-encoding"] == "chunked" {
            var decoded = Data()
            var rest = body
            complete = false
            while let lineEnd = rest.range(of: Data("\r\n".utf8)) {
                guard let size = Int(String(decoding: rest[..<lineEnd.lowerBound], as: UTF8.self), radix: 16) else { break }
                let start = lineEnd.upperBound
                if size == 0 { complete = true; break }
                guard rest.count >= start - rest.startIndex + size + 2 else { break }
                decoded.append(rest[start..<start + size])
                rest = Data(rest[(start + size + 2)...])
            }
            body = decoded
        } else if let length = headers["content-length"].flatMap(Int.init) {
            complete = body.count == length
        }
        return RawResponse(status: status, headers: headers, body: body, complete: complete)
    }
}

final class Reports: @unchecked Sendable {
    private let lock = NSLock()
    private var items: [ProxyFailureReport] = []
    func add(_ report: ProxyFailureReport) { lock.withLock { items.append(report) } }
    var text: String { lock.withLock { items.map(\.description).joined(separator: "\n") } }
}

final class Proofs: @unchecked Sendable {
    private let lock = NSLock()
    private var items: [(UpstreamPool, Int)] = []
    func add(_ session: UpstreamPool, _ generation: Int) { lock.withLock { items.append((session, generation)) } }
    var last: (UpstreamPool, Int)? { lock.withLock { items.last } }
}

@main
struct TransportChecks {
    static func main() async throws {
        try checkContract()
        try checkKeepAliveParsing()
        try checkFraming()
        let valid = "GET /api/media?x=1 HTTP/1.1\r\nHost: 127.0.0.1:1234\r\n\r\n"
        require(tryParse(valid))
        for invalid in [
            "GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n",
            "GET //example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n",
            "GET / HTTP/1.1\r\nHost: a\r\nHost: b\r\n\r\n",
            "POST /api/x HTTP/1.1\r\nContent-Length: -1\r\n\r\n",
            "POST /api/x HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n",
            "GET / HTTP/1.1\r\n Host: example.com\r\n\r\n"
        ] { precondition(!tryParse(invalid)) }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        try Data("<html>transport-ok</html>".utf8).write(to: directory.appendingPathComponent("index.html"))
        let transport = MobileTransport(frontend: directory)
        let origin = try await transport.start()
        defer { transport.stop() }
        let client = URLSession(configuration: .ephemeral)
        defer { client.invalidateAndCancel() }
        func check(_ path: String, status: Int, authorized: Bool = true, requestOrigin: String? = nil, failure: ProxyFailure? = nil) async throws {
            var request = URLRequest(url: URL(string: origin.absoluteString + path)!)
            if authorized { request.setValue("\(transport.cookieName)=\(transport.cookieValue)", forHTTPHeaderField: "Cookie") }
            if let requestOrigin { request.setValue(requestOrigin, forHTTPHeaderField: "Origin") }
            let (_, response) = try await client.data(for: request)
            let http = response as! HTTPURLResponse
            precondition(http.statusCode == status, "\(path): \(http.statusCode) != \(status)")
            precondition(http.value(forHTTPHeaderField: ProxyFailure.header) == failure?.category, "\(path): wrong failure marker")
        }
        try await check("/", status: 403, authorized: false, failure: .rejected)
        try await check("/", status: 200)
        try await check("/library", status: 200)
        for _ in 0..<3 {
            transport.suspend()
            precondition(!transport.isListening)
            let resumedOrigin = try await transport.start()
            precondition(transport.isListening)
            precondition(resumedOrigin == origin, "Resume must preserve the WebView origin")
            try await check("/library", status: 200)
            try await check("/", status: 403, authorized: false, failure: .rejected)
        }
        try await check("/missing.js", status: 404)
        try await check("/api/test", status: 503, failure: .unavailable)
        try await check("/api/test", status: 403, authorized: false, failure: .rejected)
        try await check("/", status: 403, requestOrigin: "https://example.com", failure: .rejected)
        try await check("/%2e%2e/secret", status: 403, failure: .rejected)
        if CommandLine.arguments.count == 3 {
            try await checkUpstream(port: Int(CommandLine.arguments[1])!, fingerprint: CommandLine.arguments[2])
        }
        print("Transport parser, loopback, TLS pinning, pooled HTTP, failure taxonomy and WebSocket checks passed")
    }

    /// `precondition` for values that need `try`/`await` to compute.
    static func require(_ condition: Bool, _ message: @autoclosure () -> String = "", file: StaticString = #file, line: UInt = #line) {
        if !condition { fatalError(message(), file: file, line: line) }
    }

    /// The shared contract and this shell agree on every failure.
    static func checkContract() throws {
        let file = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("../../contract/proxy-failures.json").standardizedFileURL
        let contract = try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as! [String: Any]
        precondition(contract["header"] as? String == ProxyFailure.header)
        let failures = contract["failures"] as! [String: [String: Any]]
        precondition(Set(failures.keys) == Set(ProxyFailure.allCases.map(\.category)), "Contract and shell list different failures")
        for (category, entry) in failures {
            let failure = ProxyFailure(rawValue: category)!
            precondition(entry["status"] as? Int == failure.status, "\(category) status")
            precondition((entry["connection"] as? String) == failure.connection, "\(category) connection")
        }
        print("Proxy failure contract checks passed")
    }

    static func checkKeepAliveParsing() throws {
        precondition(KeepAlive.parse("timeout=65") == 65)
        precondition(KeepAlive.parse("timeout=5, max=100") == 5)
        for bad in [nil, "", "timeout=", "timeout=abc", "timeout=1, timeout=2", "timeout=1234567", "time out=5", "timeout=5;x"] as [String?] {
            precondition(KeepAlive.parse(bad) == nil, "Accepted \(bad ?? "nil")")
        }
        precondition(KeepAlive.idle(advertisedSeconds: nil) == KeepAlive.fallback)
        precondition(KeepAlive.idle(advertisedSeconds: 65) == KeepAlive.maxIdle)
        precondition(KeepAlive.idle(advertisedSeconds: 10) == 8)
        precondition(KeepAlive.idle(advertisedSeconds: 1) > 0 && KeepAlive.idle(advertisedSeconds: 1) < 1)
    }

    static func checkFraming() throws {
        func head(_ text: String) throws -> UpstreamResponseHead { try UpstreamResponseHead.parse(Data((text + "\r\n").utf8)) }
        var chunked = try ResponseFraming.of(try head("HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n"), method: "GET")
        let wire = Data("4;ext=1\r\nabcd\r\n0\r\nX-Trailer: 1\r\n\r\nNEXT".utf8)
        var used = 0
        for byte in wire { used += try chunked.feed(Data([byte])); if chunked.complete { break } }
        precondition(chunked.complete && used == wire.count - 4, "Chunked framing found the wrong end")
        require(try ResponseFraming.of(try head("HTTP/1.1 304 Not Modified\r\nContent-Length: 10\r\n"), method: "GET").complete)
        require(try ResponseFraming.of(try head("HTTP/1.1 200 OK\r\nContent-Length: 10\r\n"), method: "HEAD").complete)
        require(try ResponseFraming.of(try head("HTTP/1.1 200 OK\r\n"), method: "GET").kind == .untilClose)
        for bad in ["HTTP/1.1 200 OK\r\nContent-Length: 1\r\nContent-Length: 2\r\n", "HTTP/1.1 200 OK\r\nTransfer-Encoding: gzip\r\n"] {
            do { _ = try ResponseFraming.of(try head(bad), method: "GET"); fatalError("Accepted \(bad)") } catch ProxyFailure.upstreamProtocol {}
        }
        do { _ = try head("HTTP/1.1 2x0 Nope\r\n"); fatalError("Accepted a malformed status") } catch ProxyFailure.upstreamProtocol {}
    }

    static func checkUpstream(port: Int, fingerprint: String) async throws {
        try await checkRouteSelection(port: port, fingerprint: fingerprint)
        let direct = URL(string: "https://127.0.0.1:\(port)/api/test")!
        let (data, response) = try await PinnedHTTP.request(url: direct, fingerprint: fingerprint, session: "fixture-session")
        precondition(response.statusCode == 200 && String(data: data, encoding: .utf8) == "fixture-ok")
        do {
            _ = try await PinnedHTTP.request(url: direct, fingerprint: String(repeating: "0", count: 64), session: "fixture-session")
            fatalError("Incorrect certificate pin accepted")
        } catch {}
        let (_, redirect) = try await PinnedHTTP.request(url: direct.deletingLastPathComponent().appendingPathComponent("redirect"), fingerprint: fingerprint, session: "fixture-session")
        precondition(redirect.statusCode == 302)
        let (exact, _) = try await PinnedHTTP.request(url: direct, fingerprint: fingerprint, session: "fixture-session", maximumResponseBytes: 10)
        precondition(exact.count == 10)
        for endpoint in ["test", "declared-large", "chunked-large", "compressed-large"] {
            do {
                _ = try await PinnedHTTP.request(url: direct.deletingLastPathComponent().appendingPathComponent(endpoint),
                    fingerprint: fingerprint, session: "fixture-session", maximumResponseBytes: endpoint == "test" ? 9 : 32)
                fatalError("Oversized \(endpoint) response accepted")
            } catch PinnedHTTPError.responseTooLarge { }
        }
        do {
            _ = try await PinnedHTTP.localRequest(url: URL(string: "http://example.invalid/")!)
            fatalError("Local fixture request accepted a non-loopback endpoint")
        } catch { }
        let transport = MobileTransport(frontend: FileManager.default.temporaryDirectory)
        let origin = try await transport.start()
        defer { transport.stop() }
        let reports = Reports()
        transport.report = reports.add
        transport.connect(host: "127.0.0.1", port: port, fingerprint: fingerprint, session: "fixture-session", keepAlive: 30)
        let client = URLSession(configuration: .ephemeral)
        defer { client.invalidateAndCancel() }
        var request = URLRequest(url: origin.appendingPathComponent("api/test"))
        request.setValue("\(transport.cookieName)=\(transport.cookieValue)", forHTTPHeaderField: "Cookie")
        let (proxied, result) = try await client.data(for: request)
        precondition((result as! HTTPURLResponse).statusCode == 200 && String(data: proxied, encoding: .utf8) == "fixture-ok")
        request.httpMethod = "POST"
        request.httpBody = Data(repeating: 42, count: 200_000)
        let (upload, _) = try await client.data(for: request)
        precondition(String(data: upload, encoding: .utf8) == "200000")
        request.httpBody = nil; request.httpMethod = "GET"
        request.setValue("bytes=0-2", forHTTPHeaderField: "Range")
        let (range, rangedResponse) = try await client.data(for: request)
        precondition((rangedResponse as! HTTPURLResponse).statusCode == 206 && String(data: range, encoding: .utf8) == "fix")
        request.setValue(nil, forHTTPHeaderField: "Range")

        try await checkPooling(origin: origin, transport: transport, port: port, fingerprint: fingerprint)

        var websocketRequest = URLRequest(url: URL(string: origin.absoluteString.replacingOccurrences(of: "http:", with: "ws:") + "/ws")!)
        websocketRequest.setValue("\(transport.cookieName)=\(transport.cookieValue)", forHTTPHeaderField: "Cookie")
        websocketRequest.setValue(origin.absoluteString, forHTTPHeaderField: "Origin")
        let socket = client.webSocketTask(with: websocketRequest)
        socket.resume()
        guard case .string("ok") = try await socket.receive() else { fatalError("WebSocket greeting failed") }
        try await socket.send(.string("echo-me"))
        guard case .string("echo-me") = try await socket.receive() else { fatalError("WebSocket duplex failed") }
        // A suspended OPEN tunnel must close, while a fresh HTTP request and
        // WebSocket work on the SAME origin with the SAME capability cookie.
        transport.suspend()
        precondition(transport.idleUpstreamConnections == 0, "Suspension must drop idle upstream connections")
        let resumedOrigin = try await transport.start()
        precondition(resumedOrigin == origin)
        do { _ = try await socket.receive(); fatalError("Suspended tunnel stayed open") } catch {}
        let healthy = await transport.checkConnection()
        precondition(healthy == .healthy, "Resume probe must traverse the local proxy")
        let (resumed, resumedResponse) = try await client.data(for: request)
        precondition((resumedResponse as! HTTPURLResponse).statusCode == 200 && String(data: resumed, encoding: .utf8) == "fixture-ok")
        let resumedSocket = client.webSocketTask(with: websocketRequest)
        resumedSocket.resume()
        guard case .string("ok") = try await resumedSocket.receive() else { fatalError("Resumed WebSocket greeting failed") }
        try await resumedSocket.send(.string("after-resume"))
        guard case .string("after-resume") = try await resumedSocket.receive() else { fatalError("Resumed WebSocket duplex failed") }
        resumedSocket.cancel(with: .normalClosure, reason: nil)

        try await checkHealth(origin: origin, transport: transport, port: port, fingerprint: fingerprint, client: client, websocket: websocketRequest)
        try await checkFailures(origin: origin, transport: transport, port: port, fingerprint: fingerprint)
        let logged = reports.text
        // Diagnostics name categories and exception types only, never request content.
        for secret in ["fixture-session", "/api/", "127.0.0.1", transport.cookieValue] {
            precondition(!logged.contains(secret), "A failure report leaked request content")
        }
        precondition(logged.contains("upstream-identity") && logged.contains("unavailable"))
    }

    static func stats(_ port: Int, _ fingerprint: String) async throws -> [String: Int] {
        let (data, _) = try await PinnedHTTP.request(url: URL(string: "https://127.0.0.1:\(port)/fixture-stats")!, fingerprint: fingerprint)
        return try JSONSerialization.jsonObject(with: data) as! [String: Int]
    }

    static func waitFor(_ timeout: TimeInterval = 3, _ condition: () async throws -> Bool) async throws -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if try await condition() { return true }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        return try await condition()
    }

    /// Reuse, keep-alive limits, mutations, streaming and HTTP semantics over the pooled path.
    static func checkPooling(origin: URL, transport: MobileTransport, port: Int, fingerprint: String) async throws {
        let cookie = "Cookie: \(transport.cookieName)=\(transport.cookieValue)\r\n"
        let host = "Host: 127.0.0.1:\(origin.port!)\r\n"
        func get(_ path: String, _ extra: String = "", method: String = "GET") async throws -> RawResponse {
            try await RawClient.exchange(origin, "\(method) \(path) HTTP/1.1\r\n\(host)\(cookie)\(extra)\r\n")
        }
        func post(_ path: String, _ body: Data = Data("payload".utf8)) async throws -> RawResponse {
            try await RawClient.exchange(origin, "POST \(path) HTTP/1.1\r\n\(host)\(cookie)Origin: \(origin.absoluteString)\r\nContent-Length: \(body.count)\r\n\r\n", body: body)
        }

        // Repeated requests share one upstream connection.
        let first = try await get("/api/test")
        precondition(first.status == 200 && first.text == "fixture-ok" && first.header("connection") == "close")
        precondition(first.header("keep-alive") == nil, "Hop-by-hop fields must not reach the WebView")
        let connection = first.header("x-fixture-connection")!
        let opened = transport.openedUpstreamConnections
        for _ in 0..<5 { require(try await get("/api/test").header("x-fixture-connection") == connection, "A request did not reuse the pooled connection") }
        precondition(transport.openedUpstreamConnections == opened)

        // Headers: browser credentials and context stay local; the session and coding offer go upstream.
        let echoed = try await get("/api/echo-headers?x=1", "Authorization: Bearer browser\r\nAccept-Encoding: gzip, deflate, br\r\nReferer: http://127.0.0.1/\r\nSec-Fetch-Site: same-origin\r\nX-Forwarded-For: 1.2.3.4\r\nConnection: keep-alive, x-private\r\nX-Private: hop\r\nAccept: application/json\r\n")
        let seen = try JSONSerialization.jsonObject(with: echoed.body) as! [String: String]
        precondition(seen["authorization"] == "Bearer fixture-session" && seen["accept-encoding"] == "gzip, deflate, br" && seen["accept"] == "application/json")
        for name in ["cookie", "referer", "sec-fetch-site", "x-forwarded-for", "x-private"] { precondition(seen[name] == nil, "\(name) leaked upstream") }
        for name in ["set-cookie", "x-hop", "keep-alive"] { precondition(echoed.header(name) == nil, "\(name) leaked to the WebView") }

        // Encoded bytes pass through untouched, framed by their own length; the WebView decodes them.
        let compressed = try await get("/api/gzip", "Accept-Encoding: gzip, deflate\r\n")
        precondition(compressed.header("content-encoding") == "gzip" && compressed.header("etag") == "W/\"g1\"")
        precondition(compressed.header("content-length") == String(compressed.body.count) && compressed.body.starts(with: [0x1f, 0x8b]))
        let plain = try await get("/api/gzip")
        precondition(plain.header("content-encoding") == nil && plain.text.hasPrefix("{\"items\""))

        // HEAD, Range, 304 keep their semantics and leave the connection reusable.
        let head = try await get("/api/test", method: "HEAD")
        precondition(head.status == 200 && head.header("content-length") == "10" && head.body.isEmpty)
        let range = try await get("/api/test", "Range: bytes=0-2\r\n")
        precondition(range.status == 206 && range.header("content-range") == "bytes 0-2/10" && range.text == "fix")
        let tagged = try await get("/api/etag")
        precondition(tagged.status == 200 && tagged.header("etag") == "\"v1\"")
        let notModified = try await get("/api/etag", "If-None-Match: \"v1\"\r\n")
        precondition(notModified.status == 304 && notModified.body.isEmpty)
        require(try await get("/api/test").header("x-fixture-connection") == connection, "Bodiless responses must leave the connection reusable")

        // Chunked responses pass through chunked; bodies without length are re-chunked.
        let chunked = try await get("/api/chunked")
        precondition(chunked.header("transfer-encoding") == "chunked" && chunked.complete && chunked.body.count == 50 * 2048)
        require(try await get("/api/test").header("x-fixture-connection") == chunked.header("x-fixture-connection"))
        let untilClose = try await get("/api/until-close")
        precondition(untilClose.header("transfer-encoding") == "chunked" && untilClose.complete && untilClose.text == "no-length-body")

        // Downloads stream: the first bytes arrive before the server finishes.
        let streaming = RawClient(origin)
        try await streaming.open("GET /api/stream HTTP/1.1\r\n\(host)\(cookie)\r\n")
        let started = Date()
        let early = await streaming.read(atLeast: 1, timeout: 5)
        var partial = early
        while !String(decoding: partial, as: UTF8.self).contains("first") && Date().timeIntervalSince(started) < 1.2 {
            partial = await streaming.read(atLeast: partial.count + 1, timeout: 1.2)
        }
        precondition(String(decoding: partial, as: UTF8.self).contains("first") && Date().timeIntervalSince(started) < 1.2, "The proxy buffered a streamed response")
        let streamed = RawClient.parse(await streaming.read(atLeast: Int.max))
        streaming.close()
        precondition(streamed.complete && streamed.text == "firstlast")
        let large = try await get("/api/large")
        precondition(large.complete && large.body.count == 4 * 1024 * 1024)
        // Uploads stream too, with backpressure, at any size.
        let bigUpload = try await post("/api/test", Data(repeating: 7, count: 8 * 1024 * 1024))
        precondition(bigUpload.text == String(8 * 1024 * 1024))

        // An advertised keep-alive keeps a read connection across a pause;
        // a mutation after the same pause gets a fresh connection.
        let beforePause = try await get("/api/test").header("x-fixture-connection")
        try await Task.sleep(nanoseconds: 6_000_000_000)
        let afterPause = try await get("/api/test").header("x-fixture-connection")
        precondition(afterPause == beforePause, "A read did not reuse a connection idle within the advertised keep-alive")
        try await Task.sleep(nanoseconds: 3_500_000_000)
        let mutation = try await post("/api/test")
        precondition(mutation.status == 200 && mutation.header("x-fixture-connection") != afterPause, "A mutation rode a long-idle connection")

        // The server closing an idle connection is noticed: the next mutation goes once, on a new connection.
        let closing = try await get("/api/close-after")
        precondition(closing.text == "closing-soon")
        let before = try await stats(port, fingerprint)["POST /api/test"] ?? 0
        try await Task.sleep(nanoseconds: 1_000_000_000)
        let afterClose = try await post("/api/test")
        precondition(afterClose.status == 200 && afterClose.header("x-fixture-connection") != closing.header("x-fixture-connection"))
        require(try await stats(port, fingerprint)["POST /api/test"] == before + 1, "The mutation was not sent exactly once")

        // A mutation whose connection drops after sending is never replayed, even on a reused connection.
        _ = try await get("/api/test")
        let dropped = try await post("/api/drop")
        precondition(dropped.status == 502 && dropped.header(ProxyFailure.header) == "upstream-unreachable")
        try await Task.sleep(nanoseconds: 300_000_000)
        require(try await stats(port, fingerprint)["POST /api/drop"] == 1, "A mutation with an unknown outcome was replayed")
        // A safe read on a reused connection that dropped before answering is retried once.
        _ = try await get("/api/test")
        let retried = try await get("/api/drop-once?key=read")
        precondition(retried.status == 200 && retried.text == "fixture-ok", "A safe read was not retried on a fresh connection")
        require(try await stats(port, fingerprint)["GET /api/drop-once"] == 2)

        // Without an advertisement the short fallback applies.
        transport.connect(host: "127.0.0.1", port: port, fingerprint: fingerprint, session: "fixture-session")
        let fallback = try await get("/api/test").header("x-fixture-connection")
        try await Task.sleep(nanoseconds: 3_500_000_000)
        require(try await get("/api/test").header("x-fixture-connection") != fallback, "An unadvertised connection outlived the fallback idle limit")
        transport.connect(host: "127.0.0.1", port: port, fingerprint: fingerprint, session: "fixture-session", keepAlive: 30)

        // Closing the WebView socket cancels the upstream exchange.
        let hangsBefore = try await stats(port, fingerprint)["closed /api/hang"] ?? 0
        let abandoned = RawClient(origin)
        try await abandoned.open("GET /api/hang HTTP/1.1\r\n\(host)\(cookie)\r\n")
        require(try await waitFor { (try await stats(port, fingerprint)["GET /api/hang"] ?? 0) >= 1 })
        abandoned.close()
        require(try await waitFor { (try await stats(port, fingerprint)["closed /api/hang"] ?? 0) > hangsBefore }, "Upstream exchange outlived its WebView socket")

        // Backgrounding cancels in-flight exchanges and drops idle connections.
        let suspended = RawClient(origin)
        let hangs = try await stats(port, fingerprint)["GET /api/hang"] ?? 0
        try await suspended.open("GET /api/hang HTTP/1.1\r\n\(host)\(cookie)\r\n")
        require(try await waitFor { (try await stats(port, fingerprint)["GET /api/hang"] ?? 0) > hangs })
        let closedBefore = try await stats(port, fingerprint)["closed /api/hang"] ?? 0
        transport.suspend()
        precondition(transport.idleUpstreamConnections == 0)
        require(try await waitFor { (try await stats(port, fingerprint)["closed /api/hang"] ?? 0) > closedBefore }, "Suspension left an exchange running")
        suspended.close()
        _ = try await transport.start()
        print("Pooled upstream reuse, keep-alive limits, mutation safety, streaming and HTTP semantics passed")
    }

    /// The recovery probe crosses the WebView's own path and tells a healthy
    /// path, an expired session and a network failure apart.
    static func checkHealth(origin: URL, transport: MobileTransport, port: Int, fingerprint: String,
                            client: URLSession, websocket: URLRequest) async throws {
        func control(_ health: String) async throws {
            _ = try await PinnedHTTP.request(url: URL(string: "https://127.0.0.1:\(port)/fixture-control?health=\(health)")!, fingerprint: fingerprint)
        }
        func count(_ key: String) async throws -> Int { try await stats(port, fingerprint)[key] ?? 0 }
        transport.connect(host: "127.0.0.1", port: port, fingerprint: fingerprint, session: "fixture-session", keepAlive: 30)
        let checks = try await count("GET /api/multi-device/health")
        require(await transport.checkConnection() == .healthy)
        require(try await count("GET /api/multi-device/health") == checks + 1, "The check did not use the health path")
        require(transport.idleUpstreamConnections >= 1, "A check must leave its pooled connection reusable")
        try await control("expired")
        require(await transport.checkConnection() == .sessionExpired, "An expired device session must be told apart")
        try await control("rejected")
        require(await transport.checkConnection() == .unreachable, "An ordinary 401 is not an expired device session")
        try await control("hang")
        let started = Date()
        require(await transport.checkConnection(timeout: 0.5) == .unreachable)
        require(Date().timeIntervalSince(started) < 2, "A hung check must end with its budget")
        // An older server without the health route is checked through the profile list, from then on.
        try await control("missing")
        let profiles = try await count("GET /api/profiles")
        require(await transport.checkConnection() == .healthy)
        let afterFallback = try await count("GET /api/multi-device/health")
        require(await transport.checkConnection() == .healthy)
        require(try await count("GET /api/multi-device/health") == afterFallback, "The missing health route was asked again")
        require(try await count("GET /api/profiles") == profiles + 2)
        try await control("ok")
        // A failure the proxy answered itself means the server was not reached.
        transport.connect(host: "127.0.0.1", port: port, fingerprint: String(repeating: "0", count: 64), session: "fixture-session")
        require(await transport.checkConnection() == .unreachable)
        transport.connect(host: "127.0.0.1", port: port, fingerprint: fingerprint, session: "fixture-session", keepAlive: 30)

        // A successful page upgrade reports the session and the generation it happened in.
        let proofs = Proofs()
        transport.setRecoveryGeneration(7)
        transport.onTunnelOpened(proofs.add)
        let socket = client.webSocketTask(with: websocket)
        socket.resume()
        guard case .string("ok") = try await socket.receive() else { fatalError("WebSocket greeting failed") }
        require(try await waitFor { proofs.last != nil }, "The upgrade was not reported")
        let proof = proofs.last!
        require(proof.1 == 7 && transport.isCurrent(proof.0))
        require(transport.openTunnels == 1)
        _ = try await RawClient.exchange(origin, "GET /api/test HTTP/1.1\r\nHost: 127.0.0.1:\(origin.port!)\r\nCookie: \(transport.cookieName)=\(transport.cookieValue)\r\n\r\n")
        require(transport.idleUpstreamConnections >= 1)
        // A network change ends tunnels at once and drops idle connections; requests still work after.
        transport.networkChanged()
        require(transport.idleUpstreamConnections == 0 && transport.openTunnels == 0)
        do { _ = try await socket.receive(); fatalError("A tunnel survived a network change") } catch {}
        require(try await RawClient.exchange(origin, "GET /api/test HTTP/1.1\r\nHost: 127.0.0.1:\(origin.port!)\r\nCookie: \(transport.cookieName)=\(transport.cookieValue)\r\n\r\n").text == "fixture-ok")
        transport.connect(host: "127.0.0.1", port: port, fingerprint: fingerprint, session: "fixture-session", keepAlive: 30)
        require(!transport.isCurrent(proof.0), "A replaced session must no longer count as current")
        transport.onTunnelOpened(nil)
        print("Path health checks, upgrade proof and network change handling passed")
    }

    static func checkFailures(origin: URL, transport: MobileTransport, port: Int, fingerprint: String) async throws {
        let cookie = "Cookie: \(transport.cookieName)=\(transport.cookieValue)\r\n"
        let host = "Host: 127.0.0.1:\(origin.port!)\r\n"
        func get(_ path: String) async throws -> RawResponse {
            try await RawClient.exchange(origin, "GET \(path) HTTP/1.1\r\n\(host)\(cookie)\r\n")
        }
        func expect(_ response: RawResponse, _ failure: ProxyFailure) {
            precondition(response.status == failure.status && response.header(ProxyFailure.header) == failure.category,
                         "Expected \(failure.category), got \(response.status) \(response.header(ProxyFailure.header) ?? "-")")
        }
        transport.connect(host: "127.0.0.1", port: port, fingerprint: fingerprint, session: "fixture-session", keepAlive: 30)
        expect(try await get("/api/redirect"), .upstreamProtocol)
        expect(try await get("/api/bad-head"), .upstreamProtocol)
        expect(try await RawClient.exchange(origin, "GET /api/test HTTP/1.1\r\n\(host)\r\n"), .rejected)
        transport.upstreamReadTimeout = 1
        expect(try await get("/api/hang"), .upstreamTimeout)
        transport.upstreamReadTimeout = 30

        // Replacing the session cuts its responses: one not yet started is answered unavailable...
        let waiting = RawClient(origin)
        let hangs = try await stats(port, fingerprint)["GET /api/hang"] ?? 0
        try await waiting.open("GET /api/hang HTTP/1.1\r\n\(host)\(cookie)\r\n")
        require(try await waitFor { (try await stats(port, fingerprint)["GET /api/hang"] ?? 0) > hangs })
        // ...and one already streaming is cut, never completed from the old session.
        let streaming = RawClient(origin)
        try await streaming.open("GET /api/slow-body HTTP/1.1\r\n\(host)\(cookie)\r\n")
        let firstBytes = await streaming.read(atLeast: 1, timeout: 5)
        precondition(!firstBytes.isEmpty)
        transport.connect(host: "127.0.0.1", port: port, fingerprint: fingerprint, session: "fixture-session", keepAlive: 30)
        expect(RawClient.parse(await waiting.read(atLeast: Int.max)), .unavailable)
        let cut = RawClient.parse(await streaming.read(atLeast: Int.max))
        precondition(cut.status == 200 && !cut.complete && cut.body.count < 100_000, "A retired session's response was delivered")
        waiting.close(); streaming.close()
        require(try await get("/api/test").text == "fixture-ok", "The new session must serve requests")

        // Unreachable server.
        let closed = try NWListener(using: .tcp, on: .any)
        closed.newConnectionHandler = { $0.cancel() }
        closed.start(queue: .global())
        require(try await waitFor { closed.port != nil && closed.port?.rawValue != 0 })
        let closedPort = Int(closed.port!.rawValue)
        closed.cancel()
        try await Task.sleep(nanoseconds: 200_000_000)
        transport.connect(host: "127.0.0.1", port: closedPort, fingerprint: fingerprint, session: "fixture-session")
        expect(try await get("/api/test"), .upstreamUnreachable)

        // A pin mismatch is refused before any request reaches the server.
        let before = try await stats(port, fingerprint).values.reduce(0, +)
        transport.connect(host: "127.0.0.1", port: port, fingerprint: String(repeating: "0", count: 64), session: "fixture-session")
        expect(try await get("/api/test"), .upstreamIdentity)
        var websocket = URLRequest(url: URL(string: origin.absoluteString.replacingOccurrences(of: "http:", with: "ws:") + "/ws")!)
        websocket.setValue("\(transport.cookieName)=\(transport.cookieValue)", forHTTPHeaderField: "Cookie")
        let refused = try await RawClient.exchange(origin, "GET /ws HTTP/1.1\r\n\(host)\(cookie)Origin: \(origin.absoluteString)\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n")
        expect(refused, .upstreamIdentity)
        require(try await stats(port, fingerprint).values.reduce(0, +) == before, "A request reached the server despite a pin mismatch")
        print("Proxy failure taxonomy and session retirement checks passed")
    }

    static func checkRouteSelection(port: Int, fingerprint: String) async throws {
        let base = "https://127.0.0.1:\(port)"
        func ping(_ mode: String) -> URL { URL(string: base + "/multi-device/ping?mode=" + mode)! }
        let start = Date()
        let winner = try await PinnedHTTP.firstReachableRoute(
            urls: [ping("slow-first"), ping("wrong"), ping("status"), ping("malformed"), ping("good")],
            fingerprint: fingerprint, deviceID: "fixture-device", timeout: 4)
        precondition(winner.url == ping("good"))
        precondition(winner.keepAlive == 30, "The verified route's keep-alive advertisement was not reported")
        precondition(Date().timeIntervalSince(start) < 2, "Winning route waited for a losing probe")
        // Confirm cancellation reached the fixture socket, not just its Swift task.
        var cancelled = 0
        for _ in 0..<20 {
            let (data, _) = try await PinnedHTTP.request(url: URL(string: base + "/probe-stats")!, fingerprint: fingerprint)
            cancelled = (try JSONSerialization.jsonObject(with: data) as! [String: Int])["cancelled"]!
            if cancelled > 0 { break }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        precondition(cancelled > 0, "Losing probe connection was not cancelled")
        let failuresStart = Date()
        do {
            _ = try await PinnedHTTP.firstReachable(urls: [ping("slow-timeout-a"), ping("slow-timeout-b"), ping("wrong")],
                fingerprint: fingerprint, deviceID: "fixture-device", timeout: 0.5)
            fatalError("No matching route should have succeeded")
        } catch PinnedHTTPError.noReachableRoute {}
        precondition(Date().timeIntervalSince(failuresStart) < 2, "Failure timeout accumulated across routes")
        do {
            _ = try await PinnedHTTP.firstReachable(urls: [ping("good")], fingerprint: String(repeating: "0", count: 64), deviceID: "fixture-device", timeout: 0.5)
            fatalError("Wrong certificate pin won route selection")
        } catch PinnedHTTPError.noReachableRoute {}
        let cancellationStart = Date()
        let pending = Task {
            try await PinnedHTTP.firstReachable(urls: [ping("slow-cancel")], fingerprint: fingerprint, deviceID: "fixture-device", timeout: 4)
        }
        try await Task.sleep(nanoseconds: 150_000_000)
        pending.cancel()
        do { _ = try await pending.value; fatalError("Cancelled route selection succeeded") }
        catch { precondition(error is CancellationError) }
        precondition(Date().timeIntervalSince(cancellationStart) < 2)
        for invalid in [0.0, -1, Double.infinity, Double.nan] {
            do {
                _ = try await PinnedHTTP.request(url: ping("good"), fingerprint: fingerprint, timeout: invalid)
                fatalError("Invalid timeout accepted")
            } catch {}
        }
        print("Parallel pinned route selection, identity checks, timeout and socket cancellation passed")
    }
    static func tryParse(_ request: String) -> Bool {
        (try? MobileHTTPRequest.parse(Data(request.utf8))) != nil
    }
}
