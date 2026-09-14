import Foundation

/// A client-only subscription to the same account channel servers already use.
/// No device-id header: this phone observes presence, it does not advertise a server.
@MainActor
final class MobilePresence {
    private var task: Task<Void, Never>?
    private var socket: URLSessionWebSocketTask?
    private let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieStorage = nil
        config.urlCredentialStorage = nil
        config.urlCache = nil
        config.timeoutIntervalForRequest = 15
        return URLSession(configuration: config)
    }()

    func stop() {
        task?.cancel(); task = nil
        socket?.cancel(with: .goingAway, reason: nil); socket = nil
    }

    func start(cloudURL: URL, token: @escaping () async throws -> String,
               refresh: @escaping () async throws -> Void,
               state: @escaping (String) -> Void) {
        guard task == nil else { return }
        task = Task {
            var delay = 1.0
            while !Task.isCancelled {
                state("connecting")
                do {
                    var url = URLComponents(url: cloudURL.appendingPathComponent("account-events-v1"), resolvingAgainstBaseURL: false)!
                    url.scheme = cloudURL.scheme == "https" ? "wss" : "ws"
                    var request = URLRequest(url: url.url!)
                    request.setValue("Bearer \(try await token())", forHTTPHeaderField: "Authorization")
                    try Task.checkCancellation()
                    let ws = session.webSocketTask(with: request)
                    ws.maximumMessageSize = 16_384
                    socket = ws
                    ws.resume()
                    var lastPong = Date()
                    let opened = Date()
                    let heartbeat = Task {
                        do {
                            while !Task.isCancelled {
                                // Re-open periodically to revalidate authentication, and
                                // recover half-open connections after a network change.
                                guard Date().timeIntervalSince(lastPong) < 60,
                                      Date().timeIntervalSince(opened) < 45 * 60 else { break }
                                try await ws.send(.string("{\"type\":\"ping\"}"))
                                try await Task.sleep(for: .seconds(25))
                            }
                        } catch { }
                        ws.cancel(with: .goingAway, reason: nil)
                    }
                    defer { heartbeat.cancel(); ws.cancel(with: .goingAway, reason: nil) }
                    try await withTaskCancellationHandler {
                        var synchronized = false
                        while !Task.isCancelled {
                            let message = try await ws.receive()
                            let data: Data
                            switch message {
                            case .string(let text): data = Data(text.utf8)
                            case .data(let bytes): data = bytes
                            @unknown default: continue
                            }
                            guard let event = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
                            if event["type"] as? String == "pong" { lastPong = Date() }
                            // The first received frame proves the subscription is in
                            // place BEFORE fetching, closing the initial snapshot race.
                            if !synchronized || (event["type"] as? String == "account_event" && event["reason"] as? String == "devices") {
                                try await refresh()
                                try Task.checkCancellation()
                                synchronized = true
                                delay = 1
                                state("live")
                            }
                        }
                    } onCancel: { ws.cancel(with: .goingAway, reason: nil) }
                } catch {
                    if Task.isCancelled { return }
                    state("reconnecting")
                }
                do { try await Task.sleep(for: .seconds(delay + Double.random(in: 0...0.5))) }
                catch { return }
                delay = min(delay * 2, 30)
            }
        }
    }
}
