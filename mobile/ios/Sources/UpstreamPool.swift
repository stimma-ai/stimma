import Foundation
import Network
import Security

/// How long an idle upstream connection may wait in the pool. A server
/// advertises its own idle limit (`Keep-Alive: timeout=N`); older servers say
/// nothing and close idle connections after uvicorn's default 5 seconds.
enum KeepAlive {
    /// For a server that advertises nothing: retire well inside its 5 seconds.
    /// Also the limit for mutations, whatever the server advertises.
    static let fallback: TimeInterval = 3
    /// Advertised timeouts beyond this are treated as this.
    static let capSeconds = 60
    /// However long a server offers, an idle read connection is not reused
    /// after this. Mobile carrier NATs and middleboxes can drop idle mappings
    /// without telling either end, and a read on such a connection waits out
    /// its read timeout instead of failing fast; a short ceiling bounds that.
    static let maxIdle: TimeInterval = 25

    /// The advertised timeout in seconds, or nil unless the value has exactly
    /// one well-formed `timeout`. Anything unexpected means "not advertised".
    static func parse(_ value: String?) -> Int? {
        guard let value else { return nil }
        var timeout: Int?
        for part in value.split(separator: ",", omittingEmptySubsequences: false) {
            let pieces = part.split(separator: "=", omittingEmptySubsequences: false)
            guard pieces.count == 2 else { return nil }
            let name = pieces[0].trimmingCharacters(in: .whitespaces).lowercased()
            let number = pieces[1].trimmingCharacters(in: .whitespaces)
            guard !name.isEmpty, name.allSatisfy({ $0.isASCII && $0.isLetter }),
                  (1...6).contains(number.count), number.allSatisfy({ $0.isASCII && $0.isNumber }) else { return nil }
            if name == "timeout" {
                guard timeout == nil else { return nil }
                timeout = Int(number)
            }
        }
        return timeout
    }

    /// The read idle limit for an advertised timeout: shortened by a margin (at
    /// least 2 seconds or a tenth) because the client's idle clock starts after
    /// the server's and the request still has to arrive, and never more than
    /// `maxIdle`. A shorter server value is kept.
    static func idle(advertisedSeconds: Int?) -> TimeInterval {
        guard let advertisedSeconds else { return fallback }
        let limit = Double(min(advertisedSeconds, capSeconds))
        return max(0.001, min(maxIdle, limit - max(2, limit / 10)))
    }
}

/// The verified server a session's WebView traffic goes to.
struct UpstreamTarget {
    let host: String
    let port: UInt16
    let fingerprint: String
    let session: String
    var tls = true
    /// How long an idle connection may be reused for a safe read.
    var idleLimit: TimeInterval = KeepAlive.fallback

    var hostHeader: String { (host.contains(":") ? "[\(host)]" : host) + ":\(port)" }

    /// Connection parameters that pin the server certificate on every
    /// connection. `rejected` is called when the pin refused the server.
    func parameters(queue: DispatchQueue, rejected: @escaping () -> Void) -> NWParameters {
        guard tls else { return .tcp }
        let options = NWProtocolTLS.Options()
        sec_protocol_options_add_tls_application_protocol(options.securityProtocolOptions, "http/1.1")
        let fingerprint = self.fingerprint
        sec_protocol_options_set_verify_block(options.securityProtocolOptions, { _, trust, complete in
            let trust = sec_trust_copy_ref(trust).takeRetainedValue()
            let chain = SecTrustCopyCertificateChain(trust) as? [SecCertificate]
            let accepted = chain?.first.map { certificateMatches($0, fingerprint: fingerprint) } ?? false
            if !accepted { rejected() }
            complete(accepted)
        }, queue)
        let tcp = NWProtocolTCP.Options()
        tcp.noDelay = true
        return NWParameters(tls: options, tcp: tcp)
    }
}

private func monotonicNow() -> TimeInterval {
    // Keeps counting while the device sleeps, unlike the uptime clock.
    TimeInterval(clock_gettime_nsec_np(CLOCK_MONOTONIC)) / 1_000_000_000
}

/// One pinned connection to the server. All access happens on the pool's
/// queue. Exactly one receive is outstanding at a time; whatever it returns
/// goes to the current reader, or, while the connection sits idle in the
/// pool, means the server closed it (or broke protocol) and it is dropped.
final class UpstreamConnection {
    let connection: NWConnection
    fileprivate(set) var reused = false
    fileprivate var idleSince: TimeInterval?
    fileprivate var onIdleEvent: (() -> Void)?
    private var buffered = Data()
    private var receiving = false
    private var ended = false
    private var endError: NWError?
    private var reader: ((Data?, Bool, NWError?) -> Void)?

    fileprivate init(_ connection: NWConnection) { self.connection = connection }

    /// The next bytes from the server, or end of stream (`true`) with any error.
    func read(_ handler: @escaping (Data?, Bool, NWError?) -> Void) {
        if !buffered.isEmpty {
            let data = buffered
            buffered = Data()
            handler(data, false, nil)
            return
        }
        if ended { handler(nil, true, endError); return }
        reader = handler
        if !receiving { receive() }
    }

    func send(_ data: Data, completion: @escaping (NWError?) -> Void) {
        connection.send(content: data, completion: .contentProcessed(completion))
    }

    fileprivate func watchIdle() {
        if !receiving && !ended { receive() }
    }

    private func receive() {
        receiving = true
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65_536) { [weak self] data, _, complete, error in
            guard let self else { return }
            self.receiving = false
            if complete || error != nil { self.ended = true; self.endError = error }
            if let reader = self.reader {
                self.reader = nil
                reader(data, self.ended, error)
            } else {
                // Nobody asked: the connection is idle in the pool.
                if let data { self.buffered.append(data) }
                self.onIdleEvent?()
            }
        }
    }

    fileprivate var usable: Bool { !ended && buffered.isEmpty }

    func cancel() { onIdleEvent = nil; reader = nil; connection.cancel() }
    /// An abortive close, for a connection whose exchange did not finish.
    func reset() { onIdleEvent = nil; reader = nil; connection.forceCancel() }
}

/// Long-lived pinned connections for one session's WebView traffic.
///
/// Connections are kept after a complete exchange and reused while they are
/// fresh: up to the session's idle limit (from the verified route's keep-alive
/// advertisement, at most 25 s) for safe reads, and only up to the 3 s
/// fallback for anything that may change server state, so a mutation never
/// rides a connection that sat idle long enough to have been dropped
/// unnoticed. An idle connection keeps a read pending, so a server that closes
/// it is noticed at once and it is never handed out. Nothing here retries a
/// request; that decision is the proxy's, and it never replays a mutation.
final class UpstreamPool {
    let target: UpstreamTarget
    private let queue: DispatchQueue
    private var idle: [UpstreamConnection] = []
    private var connecting: [ObjectIdentifier: NWConnection] = [:]
    private(set) var retired = false
    /// Test seam: how many connections this pool has opened.
    private(set) var opened = 0
    var connectTimeout: TimeInterval = 4
    static let maximumIdle = 8

    init(target: UpstreamTarget, queue: DispatchQueue) {
        self.target = target
        self.queue = queue
    }

    var idleCount: Int { idle.count }

    /// A connection for one exchange: a fresh idle one when the method allows,
    /// otherwise a new one. `reused` tells the caller it may be stale.
    func acquire(safe: Bool, fresh: Bool = false, _ completion: @escaping (Result<UpstreamConnection, ProxyFailure>) -> Void) {
        guard !retired else { completion(.failure(.unavailable)); return }
        let now = monotonicNow()
        prune(now: now)
        let limit = safe ? target.idleLimit : min(target.idleLimit, KeepAlive.fallback)
        if !fresh, let index = idle.lastIndex(where: { $0.usable && now - ($0.idleSince ?? 0) < limit }) {
            let connection = idle.remove(at: index)
            connection.idleSince = nil
            connection.onIdleEvent = nil
            connection.reused = true
            completion(.success(connection))
            return
        }
        open(completion)
    }

    private func open(_ completion: @escaping (Result<UpstreamConnection, ProxyFailure>) -> Void) {
        var pinRejected = false
        let connection = NWConnection(host: NWEndpoint.Host(target.host), port: NWEndpoint.Port(rawValue: target.port)!,
                                      using: target.parameters(queue: queue, rejected: { pinRejected = true }))
        opened += 1
        let key = ObjectIdentifier(connection)
        connecting[key] = connection
        var resolved = false
        func finish(_ result: Result<UpstreamConnection, ProxyFailure>) {
            guard !resolved else { return }
            resolved = true
            connecting.removeValue(forKey: key)
            if case .failure = result { connection.stateUpdateHandler = nil; connection.forceCancel() }
            completion(result)
        }
        connection.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                guard let self, !self.retired else { finish(.failure(.unavailable)); return }
                connection.stateUpdateHandler = nil
                finish(.success(UpstreamConnection(connection)))
            case .waiting(let error), .failed(let error):
                // Waiting means no route right now (refused, no network): fail fast, recovery retries.
                finish(.failure(pinRejected ? .upstreamIdentity : Self.classify(error)))
            case .cancelled:
                finish(.failure(.unavailable))
            default: break
            }
        }
        connection.start(queue: queue)
        queue.asyncAfter(deadline: .now() + connectTimeout) { finish(.failure(pinRejected ? .upstreamIdentity : .upstreamTimeout)) }
    }

    static func classify(_ error: NWError?) -> ProxyFailure {
        switch error {
        case .posix(let code)? where code == .ETIMEDOUT: return .upstreamTimeout
        case .tls?: return .upstreamIdentity
        default: return .upstreamUnreachable
        }
    }

    /// Return a connection after its exchange. Only one whose request and
    /// response were both complete and that the server will keep may be pooled.
    func release(_ connection: UpstreamConnection, reusable: Bool) {
        guard reusable, !retired, connection.usable else { connection.reset(); return }
        let now = monotonicNow()
        prune(now: now)
        if idle.count >= Self.maximumIdle { idle.removeFirst().cancel() }
        connection.idleSince = now
        connection.onIdleEvent = { [weak self, weak connection] in
            guard let self, let connection else { return }
            self.drop(connection)
        }
        idle.append(connection)
        connection.watchIdle()
        // Retire it once it can no longer be used, rather than holding the socket.
        queue.asyncAfter(deadline: .now() + target.idleLimit) { [weak self] in self?.prune(now: monotonicNow()) }
    }

    private func drop(_ connection: UpstreamConnection) {
        idle.removeAll { $0 === connection }
        connection.cancel()
    }

    private func prune(now: TimeInterval) {
        let limit = target.idleLimit
        let expired = idle.filter { !$0.usable || now - ($0.idleSince ?? 0) >= limit }
        guard !expired.isEmpty else { return }
        idle.removeAll { connection in expired.contains { $0 === connection } }
        for connection in expired { connection.cancel() }
    }

    /// Close idle connections, e.g. before they cross a background period or network change.
    func evictIdle() {
        let closing = idle
        idle.removeAll()
        for connection in closing { connection.cancel() }
    }

    /// Abandon connections still being opened (their requests are gone), e.g. on backgrounding.
    func abandonConnecting() {
        let pending = connecting.values
        connecting.removeAll()
        for connection in pending { connection.forceCancel() }
    }

    /// This session is finished: no new connections, idle ones closed, and
    /// connections still being opened abandoned. In-flight exchanges are cut
    /// by their owners.
    func retire() {
        retired = true
        evictIdle()
        abandonConnecting()
    }
}

/// An HTTP/1.1 response head read from the server.
struct UpstreamResponseHead {
    let status: Int
    let reason: String
    let minor: Int
    let fields: [(name: String, value: String)]

    func values(_ name: String) -> [String] { fields.filter { $0.name == name }.map(\.value) }
    var connectionTokens: Set<String> {
        Set(values("connection").flatMap { $0.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces).lowercased() } })
    }

    /// Parse a head ending in CRLFCRLF. Throws `ProxyFailure.upstreamProtocol` for anything malformed.
    static func parse(_ data: Data) throws -> UpstreamResponseHead {
        guard let text = String(data: data, encoding: .isoLatin1), text.hasSuffix("\r\n\r\n") else { throw ProxyFailure.upstreamProtocol }
        var lines = text.components(separatedBy: "\r\n")
        lines.removeLast(2)
        guard let first = lines.first else { throw ProxyFailure.upstreamProtocol }
        let parts = first.split(separator: " ", maxSplits: 2, omittingEmptySubsequences: false)
        guard parts.count >= 2, parts[0] == "HTTP/1.1" || parts[0] == "HTTP/1.0",
              parts[1].count == 3, parts[1].allSatisfy({ $0.isASCII && $0.isNumber }),
              let status = Int(parts[1]), (100...599).contains(status) else { throw ProxyFailure.upstreamProtocol }
        let reason = parts.count == 3 ? String(parts[2]) : ""
        guard reason.unicodeScalars.allSatisfy({ $0.value >= 32 && $0.value != 127 || $0 == "\t" }) else { throw ProxyFailure.upstreamProtocol }
        let token = Set("!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyz")
        var fields: [(String, String)] = []
        for line in lines.dropFirst() {
            guard let colon = line.firstIndex(of: ":") else { throw ProxyFailure.upstreamProtocol }
            let name = line[..<colon].lowercased()
            let value = line[line.index(after: colon)...].trimmingCharacters(in: CharacterSet(charactersIn: " \t"))
            guard !name.isEmpty, name.allSatisfy({ token.contains($0) }),
                  value.unicodeScalars.allSatisfy({ $0.value >= 32 && $0.value != 127 || $0 == "\t" }) else { throw ProxyFailure.upstreamProtocol }
            fields.append((name, value))
        }
        return UpstreamResponseHead(status: status, reason: reason, minor: parts[0] == "HTTP/1.1" ? 1 : 0, fields: fields)
    }
}

/// Where a response body ends, so the connection can be reused afterwards.
/// Bytes are relayed to the WebView exactly as the server framed them.
struct ResponseFraming {
    enum Kind: Equatable { case none, length(Int64), chunked, untilClose }
    let kind: Kind
    private var remaining: Int64 = 0
    private enum ChunkState { case size, data, dataEnd, trailer }
    private var chunkState = ChunkState.size
    private var line = Data()
    private(set) var complete = false

    init(_ kind: Kind) {
        self.kind = kind
        switch kind {
        case .none: complete = true
        case .length(let length): remaining = length; complete = length == 0
        default: break
        }
    }

    /// The framing for a response to `method`. Throws `upstreamProtocol` for
    /// conflicting or unsupported framing.
    static func of(_ head: UpstreamResponseHead, method: String) throws -> ResponseFraming {
        if method == "HEAD" || (100...199).contains(head.status) || head.status == 204 || head.status == 304 { return ResponseFraming(.none) }
        let encodings = head.values("transfer-encoding")
        if !encodings.isEmpty {
            let tokens = encodings.flatMap { $0.split(separator: ",") }.map { $0.trimmingCharacters(in: .whitespaces).lowercased() }
            guard tokens == ["chunked"] else { throw ProxyFailure.upstreamProtocol }
            return ResponseFraming(.chunked)
        }
        let lengths = Set(head.values("content-length").flatMap { $0.split(separator: ",") }.map { $0.trimmingCharacters(in: .whitespaces) })
        if lengths.isEmpty { return ResponseFraming(.untilClose) }
        guard lengths.count == 1, let value = lengths.first, (1...18).contains(value.count),
              value.allSatisfy({ $0.isASCII && $0.isNumber }), let length = Int64(value) else { throw ProxyFailure.upstreamProtocol }
        return ResponseFraming(.length(length))
    }

    /// Consume server bytes; returns how many belong to this response.
    /// Throws `upstreamProtocol` for malformed chunked framing.
    mutating func feed(_ data: Data) throws -> Int {
        guard !complete else { return 0 }
        switch kind {
        case .none: return 0
        case .untilClose: return data.count
        case .length:
            let used = Int(min(Int64(data.count), remaining))
            remaining -= Int64(used)
            if remaining == 0 { complete = true }
            return used
        case .chunked:
            var index = data.startIndex
            while index < data.endIndex && !complete {
                switch chunkState {
                case .data:
                    let used = Int(min(Int64(data.endIndex - index), remaining))
                    index += used
                    remaining -= Int64(used)
                    if remaining == 0 { chunkState = .dataEnd }
                case .size, .dataEnd, .trailer:
                    let byte = data[index]
                    index += 1
                    line.append(byte)
                    guard line.count <= 4096 else { throw ProxyFailure.upstreamProtocol }
                    guard byte == 0x0a else { continue }
                    guard line.count >= 2, line[line.endIndex - 2] == 0x0d else { throw ProxyFailure.upstreamProtocol }
                    let text = String(decoding: line.dropLast(2), as: UTF8.self)
                    line.removeAll(keepingCapacity: true)
                    switch chunkState {
                    case .size:
                        let digits = text.split(separator: ";", maxSplits: 1, omittingEmptySubsequences: false)[0]
                            .trimmingCharacters(in: CharacterSet(charactersIn: " \t"))
                        guard (1...15).contains(digits.count), let size = Int64(digits, radix: 16), size >= 0 else { throw ProxyFailure.upstreamProtocol }
                        if size == 0 { chunkState = .trailer } else { remaining = size; chunkState = .data }
                    case .dataEnd:
                        guard text.isEmpty else { throw ProxyFailure.upstreamProtocol }
                        chunkState = .size
                    case .trailer:
                        if text.isEmpty { complete = true }
                    case .data: break
                    }
                }
            }
            return index - data.startIndex
        }
    }
}
