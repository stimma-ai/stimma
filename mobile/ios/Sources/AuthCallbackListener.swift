import Foundation
import Network

/// The cloud browser flow returns to localhost, which can resolve to either
/// loopback address family. Neither listener is exposed to the local network.
@MainActor
final class AuthCallbackListener {
    private var listeners: [NWListener] = []
    private var connections: [UUID: NWConnection] = [:]
    private var readiness: CheckedContinuation<UInt16, Error>?
    private var readyCount = 0
    private var port: UInt16 = 0
    private let state: String
    private let onCode: (String) -> Void
    private var delivered = false

    init(state: String, onCode: @escaping (String) -> Void) {
        self.state = state
        self.onCode = onCode
    }

    func start() async throws -> UInt16 {
        let parameters = NWParameters.tcp
        parameters.allowLocalEndpointReuse = true
        (parameters.defaultProtocolStack.internetProtocol as? NWProtocolIP.Options)?.version = .v4
        parameters.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: .any)
        let ipv4 = try NWListener(using: parameters)
        listeners = [ipv4]
        return try await withCheckedThrowingContinuation { continuation in
            readiness = continuation
            configure(ipv4, isFirst: true)
        }
    }

    private func configure(_ listener: NWListener, isFirst: Bool) {
        listener.newConnectionHandler = { [weak self] connection in
            Task { @MainActor in
                guard let self else { connection.cancel(); return }
                let id = UUID()
                self.connections[id] = connection
                connection.start(queue: .main)
                self.read(connection, id: id, bytes: Data())
            }
        }
        listener.stateUpdateHandler = { [weak self, weak listener] event in
            Task { @MainActor in
                guard let self, self.readiness != nil else { return }
                switch event {
                case .ready:
                    self.readyCount += 1
                    if isFirst, let firstPort = listener?.port {
                        self.port = firstPort.rawValue
                        let parameters = NWParameters.tcp
                        parameters.allowLocalEndpointReuse = true
                        (parameters.defaultProtocolStack.internetProtocol as? NWProtocolIP.Options)?.version = .v6
                        parameters.requiredLocalEndpoint = .hostPort(host: "::1", port: firstPort)
                        do {
                            let ipv6 = try NWListener(using: parameters)
                            self.listeners.append(ipv6)
                            self.configure(ipv6, isFirst: false)
                        } catch { self.fail(error) }
                    }
                    if self.readyCount == 2 {
                        let pending = self.readiness
                        self.readiness = nil
                        pending?.resume(returning: self.port)
                    }
                case .failed(let failure): self.fail(failure)
                default: break
                }
            }
        }
        listener.start(queue: .main)
    }

    private func fail(_ error: Error) {
        let pending = readiness
        readiness = nil
        stop()
        pending?.resume(throwing: error)
    }

    func stop() {
        listeners.forEach { $0.cancel() }
        listeners = []
        connections.values.forEach { $0.cancel() }
        connections = [:]
        let pending = readiness
        readiness = nil
        pending?.resume(throwing: CancellationError())
    }

    private func read(_ connection: NWConnection, id: UUID, bytes: Data) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 8192) { [weak self] data, _, complete, failure in
            Task { @MainActor in
                guard let self else { connection.cancel(); return }
                var bytes = bytes
                if let data { bytes.append(data) }
                guard failure == nil, bytes.count <= 16384 else { self.close(id); return }
                guard let text = String(data: bytes, encoding: .utf8), text.contains("\r\n\r\n") else {
                    if complete { self.close(id) } else { self.read(connection, id: id, bytes: bytes) }
                    return
                }
                let lines = text.components(separatedBy: "\r\n")
                let parts = lines[0].split(separator: " ")
                let target = parts.count == 3 ? String(parts[1]) : ""
                let url = URLComponents(string: "http://localhost" + target)
                let items = url?.queryItems ?? []
                let codes = items.filter { $0.name == "code" }
                let states = items.filter { $0.name == "state" }
                let hosts = lines.dropFirst().filter { $0.lowercased().hasPrefix("host:") }
                    .map { $0.dropFirst(5).trimmingCharacters(in: .whitespaces).lowercased() }
                let validHost = hosts.count == 1 && ["localhost:\(self.port)", "127.0.0.1:\(self.port)", "[::1]:\(self.port)"].contains(hosts[0])
                let code = codes.first?.value ?? ""
                let valid = !self.delivered && validHost && parts.first == "GET" && target.hasPrefix("/callback?") && url?.path == "/callback" && codes.count == 1 && states.count == 1 && states.first?.value == self.state && !code.isEmpty && code.count <= 512
                let body = valid ? "Signed in. Return to Stimma." : "Invalid sign-in callback."
                let response = "HTTP/1.1 \(valid ? "200 OK" : "400 Bad Request")\r\nContent-Type: text/plain; charset=utf-8\r\nCache-Control: no-store\r\nConnection: close\r\nContent-Length: \(body.utf8.count)\r\n\r\n\(body)"
                if valid { self.delivered = true }
                // Send the complete HTTP response before telling the owner to
                // dismiss its authentication browser and stop the listeners.
                connection.send(content: Data(response.utf8), contentContext: .finalMessage, isComplete: true,
                                completion: .contentProcessed { [weak self] failure in
                    Task { @MainActor in
                        guard let self else { return }
                        self.close(id)
                        if valid {
                            if failure == nil { self.onCode(code) }
                            else { self.delivered = false }
                        }
                    }
                })
            }
        }
    }

    private func close(_ id: UUID) {
        connections.removeValue(forKey: id)?.cancel()
    }
}
