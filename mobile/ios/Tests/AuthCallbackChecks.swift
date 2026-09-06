import Foundation

@main
struct AuthCallbackChecks {
    @MainActor
    static func main() async throws {
        for host in ["127.0.0.1", "[::1]", "localhost"] {
            var received: [String] = []
            let listener = AuthCallbackListener(state: "test-state") { received.append($0) }
            let port = try await listener.start()
            let config = URLSessionConfiguration.ephemeral
            config.timeoutIntervalForRequest = 3
            let client = URLSession(configuration: config)
            for suffix in ["code=fake-code&state=wrong", "code=one&code=two&state=test-state", "code=fake-code&state=test-state&state=test-state"] {
                let (_, response) = try await client.data(from: URL(string: "http://\(host):\(port)/callback?\(suffix)")!)
                precondition((response as? HTTPURLResponse)?.statusCode == 400)
                precondition(received.isEmpty, "Invalid callbacks must never reach exchange")
            }
            let (data, response) = try await client.data(from: URL(string: "http://\(host):\(port)/callback?code=fake-code&state=test-state")!)
            precondition((response as? HTTPURLResponse)?.statusCode == 200)
            precondition(String(data: data, encoding: .utf8) == "Signed in. Return to Stimma.")
            // Delivery is scheduled after the completed HTTP response.
            for _ in 0..<100 where received.isEmpty { try await Task.sleep(for: .milliseconds(5)) }
            precondition(received == ["fake-code"])
            let (_, replay) = try await client.data(from: URL(string: "http://\(host):\(port)/callback?code=fake-code&state=test-state")!)
            precondition((replay as? HTTPURLResponse)?.statusCode == 400)
            precondition(received.count == 1)
            listener.stop()
            client.invalidateAndCancel()
        }
        var completed = false
        var closingListener: AuthCallbackListener!
        closingListener = AuthCallbackListener(state: "closing-state") { code in
            precondition(code == "fake-code")
            completed = true
            closingListener.stop() // Mirrors MobileAuth dismissing the browser.
        }
        let closingPort = try await closingListener.start()
        let (closingBody, closingResponse) = try await URLSession.shared.data(from: URL(string: "http://localhost:\(closingPort)/callback?code=fake-code&state=closing-state")!)
        precondition((closingResponse as? HTTPURLResponse)?.statusCode == 200)
        precondition(String(data: closingBody, encoding: .utf8) == "Signed in. Return to Stimma.")
        for _ in 0..<100 where !completed { try await Task.sleep(for: .milliseconds(5)) }
        precondition(completed)
        closingListener = nil
        print("Auth callback checks passed: IPv4, IPv6, localhost, invalid state, duplicate parameters, complete response, single delivery")
    }
}
