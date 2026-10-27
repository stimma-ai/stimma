import Foundation
import OSLog

/// Every way the local WebView proxy can fail a request it answers itself.
///
/// The status tells the page whether it is looking at a connection problem or
/// an access rejection, so a dropped route is never presented as a bad PIN or
/// an expired sign-in. Proxy-made responses also carry `header` with the
/// category, which separates them from statuses the server returned. The table
/// is the contract in `mobile/contract/proxy-failures.json`, shared with the
/// Android shell and the page; the transport checks read it too.
enum ProxyFailure: String, CaseIterable, Error {
    /// The request failed the capability, origin, framing or path policy. An access failure.
    case rejected = "rejected"
    /// No server is attached, the app is in the background, or the connection is being replaced.
    case unavailable = "unavailable"
    /// The server could not be reached or dropped the connection.
    case upstreamUnreachable = "upstream-unreachable"
    /// The server's certificate did not match the registry pin. Refused like any
    /// unreachable route (native recovery rechecks pin and identity), but kept
    /// distinct so logs can tell a wrong server from a dead one.
    case upstreamIdentity = "upstream-identity"
    /// The server answered with something the proxy will not forward (malformed head, disallowed redirect).
    case upstreamProtocol = "upstream-protocol"
    /// The server did not connect or answer in time.
    case upstreamTimeout = "upstream-timeout"

    static let header = "X-Stimma-Proxy-Failure"

    var category: String { rawValue }

    var status: Int {
        switch self {
        case .rejected: return 403
        case .unavailable: return 503
        case .upstreamUnreachable, .upstreamIdentity, .upstreamProtocol: return 502
        case .upstreamTimeout: return 504
        }
    }

    var reason: String {
        switch status {
        case 403: return "Forbidden"
        case 503: return "Service Unavailable"
        case 504: return "Gateway Timeout"
        default: return "Bad Gateway"
        }
    }

    /// What the page's connection state becomes, as in the contract; nil for an access failure.
    var connection: String? {
        switch self {
        case .rejected: return nil
        case .unavailable: return "unavailable"
        case .upstreamUnreachable, .upstreamIdentity, .upstreamProtocol: return "unreachable"
        case .upstreamTimeout: return "timeout"
        }
    }
}

/// Content-free diagnostic for one failed proxy request: the category, whether
/// the response had already started (so the stream was cut rather than
/// answered), and the cause's type. Never URLs, headers, bodies or messages.
struct ProxyFailureReport: CustomStringConvertible {
    let failure: ProxyFailure
    let afterResponseStarted: Bool
    let cause: String
    var description: String {
        "proxy failure \(failure.category) (\(failure.status)) \(afterResponseStarted ? "mid-stream" : "before response") cause=\(cause)"
    }

    private static let logger = Logger(subsystem: "ai.stimma.mobile", category: "proxy")

    static func log(_ report: ProxyFailureReport) {
        let text = report.description
        if report.failure == .rejected { logger.info("\(text, privacy: .public)") }
        else { logger.notice("\(text, privacy: .public)") }
    }
}
