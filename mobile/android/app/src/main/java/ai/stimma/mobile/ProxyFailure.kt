package ai.stimma.mobile

import java.io.IOException
import java.io.InterruptedIOException
import java.net.SocketTimeoutException
import java.security.cert.CertificateException
import javax.net.ssl.SSLPeerUnverifiedException

/**
 * Every way the local WebView proxy can fail a request it answers itself.
 *
 * The status tells the UI whether it is looking at a connection problem or an
 * access rejection, so a dropped route is never presented as a bad PIN or an
 * expired sign-in. Proxy-made responses also carry [HEADER] with the category,
 * which separates them from statuses the server returned. The table is the
 * contract in `mobile/contract/proxy-failures.json`; the UI tests read it too.
 */
enum class ProxyFailure(val status: Int, val reason: String, val category: String) {
    /** The request failed the capability, origin, framing or path policy. An access failure. */
    REJECTED(403, "Forbidden", "rejected"),
    /** No server is attached, the app is in the background, or the connection is being replaced. */
    UNAVAILABLE(503, "Service Unavailable", "unavailable"),
    /** The server could not be reached or dropped the connection. */
    UPSTREAM_UNREACHABLE(502, "Bad Gateway", "upstream-unreachable"),
    /**
     * The server's certificate did not match the registry pin. Refused like any
     * unreachable route (native recovery rechecks pin and identity), but kept
     * distinct so logs can tell a wrong server from a dead one.
     */
    UPSTREAM_IDENTITY(502, "Bad Gateway", "upstream-identity"),
    /** The server answered with something the proxy will not forward (malformed head, disallowed redirect). */
    UPSTREAM_PROTOCOL(502, "Bad Gateway", "upstream-protocol"),
    /** The server did not connect or answer in time. */
    UPSTREAM_TIMEOUT(504, "Gateway Timeout", "upstream-timeout");

    companion object {
        const val HEADER = "X-Stimma-Proxy-Failure"

        /**
         * Classify a failure while exchanging data with the server. Accepts the
         * exceptions of raw sockets and of OkHttp calls alike (OkHttp reports its
         * call timeout as an InterruptedIOException("timeout")).
         */
        fun upstream(error: Throwable): ProxyFailure {
            if (error is ProxyException) return error.failure
            val chain = generateSequence(error) { it.cause }.take(8).toList()
            return when {
                chain.any { it is CertificateException || it is SSLPeerUnverifiedException } -> UPSTREAM_IDENTITY
                chain.any { it is SocketTimeoutException || it is InterruptedIOException && it.message == "timeout" } -> UPSTREAM_TIMEOUT
                chain.any { it is IOException } -> UPSTREAM_UNREACHABLE
                else -> UPSTREAM_PROTOCOL
            }
        }
    }
}

/** A request the proxy fails with a known [ProxyFailure]. */
class ProxyException(val failure: ProxyFailure, cause: Throwable? = null) : Exception(failure.category, cause)

/**
 * Content-free diagnostic for one failed proxy request: the category, whether
 * the response had already started (so the stream was cut rather than
 * answered), and the exception type. Never URLs, headers, bodies or messages.
 */
data class ProxyFailureReport(val failure: ProxyFailure, val afterResponseStarted: Boolean, val cause: String) {
    override fun toString() = "proxy failure ${failure.category} (${failure.status}) ${if (afterResponseStarted) "mid-stream" else "before response"} cause=$cause"
}
