import Foundation

@main
struct TransportChecks {
    static func main() async throws {
        let valid = "GET /api/media?x=1 HTTP/1.1\r\nHost: 127.0.0.1:1234\r\n\r\n"
        precondition(tryParse(valid))
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
        func check(_ path: String, status: Int, authorized: Bool = true, requestOrigin: String? = nil) async throws {
            var request = URLRequest(url: URL(string: origin.absoluteString + path)!)
            if authorized { request.setValue("\(transport.cookieName)=\(transport.cookieValue)", forHTTPHeaderField: "Cookie") }
            if let requestOrigin { request.setValue(requestOrigin, forHTTPHeaderField: "Origin") }
            let (_, response) = try await client.data(for: request)
            precondition((response as! HTTPURLResponse).statusCode == status)
        }
        try await check("/", status: 403, authorized: false)
        try await check("/", status: 200)
        try await check("/library", status: 200)
        for _ in 0..<3 {
            transport.suspend()
            let resumedOrigin = try await transport.start()
            precondition(resumedOrigin == origin, "Resume must preserve the WebView origin")
            try await check("/library", status: 200)
            try await check("/", status: 403, authorized: false)
        }
        try await check("/missing.js", status: 404)
        try await check("/api/test", status: 503)
        try await check("/", status: 403, requestOrigin: "https://example.com")
        try await check("/%2e%2e/secret", status: 400)
        if CommandLine.arguments.count == 3 {
            try await checkUpstream(port: Int(CommandLine.arguments[1])!, fingerprint: CommandLine.arguments[2])
        }
        print("Transport parser, loopback, TLS pinning, HTTP streaming and WebSocket checks passed")
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
        transport.connect(host: "127.0.0.1", port: port, fingerprint: fingerprint, session: "fixture-session")
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
        let resumedOrigin = try await transport.start()
        precondition(resumedOrigin == origin)
        do { _ = try await socket.receive(); fatalError("Suspended tunnel stayed open") } catch {}
        let healthy = try await transport.checkConnection()
        precondition(healthy, "Resume probe must traverse the local proxy")
        request.setValue(nil, forHTTPHeaderField: "Range")
        let (resumed, resumedResponse) = try await client.data(for: request)
        precondition((resumedResponse as! HTTPURLResponse).statusCode == 200 && String(data: resumed, encoding: .utf8) == "fixture-ok")
        let resumedSocket = client.webSocketTask(with: websocketRequest)
        resumedSocket.resume()
        guard case .string("ok") = try await resumedSocket.receive() else { fatalError("Resumed WebSocket greeting failed") }
        try await resumedSocket.send(.string("after-resume"))
        guard case .string("after-resume") = try await resumedSocket.receive() else { fatalError("Resumed WebSocket duplex failed") }
        resumedSocket.cancel(with: .normalClosure, reason: nil)
        transport.connect(host: "127.0.0.1", port: port, fingerprint: String(repeating: "0", count: 64), session: "fixture-session")
        request.timeoutInterval = 2
        do { _ = try await client.data(for: request); fatalError("Proxy accepted incorrect certificate pin") } catch {}
    }
    static func checkRouteSelection(port: Int, fingerprint: String) async throws {
        let base = "https://127.0.0.1:\(port)"
        func ping(_ mode: String) -> URL { URL(string: base + "/multi-device/ping?mode=" + mode)! }
        let start = Date()
        let winner = try await PinnedHTTP.firstReachable(
            urls: [ping("slow-first"), ping("wrong"), ping("status"), ping("malformed"), ping("good")],
            fingerprint: fingerprint, deviceID: "fixture-device", timeout: 4)
        precondition(winner == ping("good"))
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
