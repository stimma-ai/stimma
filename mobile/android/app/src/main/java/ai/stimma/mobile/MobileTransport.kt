package ai.stimma.mobile

import okhttp3.ConnectionPool
import okhttp3.CookieJar
import okhttp3.Headers
import okhttp3.HttpUrl
import okhttp3.Interceptor
import okhttp3.MediaType
import okhttp3.Protocol
import okio.BufferedSink
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.Call
import okhttp3.Callback
import okhttp3.Response
import kotlinx.coroutines.suspendCancellableCoroutine
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.Closeable
import java.io.File
import java.io.FilterOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.io.IOException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketTimeoutException
import java.net.URI
import java.security.SecureRandom
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.Base64
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.Semaphore
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocket
import javax.net.ssl.X509TrustManager
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

suspend fun Call.awaitBody(limit: Int): Pair<Int, ByteArray> = awaitResponse(limit).let { it.status to it.body }

class FetchedResponse(val status: Int, val headers: Headers, val body: ByteArray)

suspend fun Call.awaitResponse(limit: Int): FetchedResponse = suspendCancellableCoroutine { continuation ->
    continuation.invokeOnCancellation { cancel() }
    enqueue(object : Callback {
        override fun onFailure(call: Call, error: IOException) {
            if (continuation.isActive) continuation.resumeWithException(error)
        }
        override fun onResponse(call: Call, response: Response) {
            try {
                val result = response.use { FetchedResponse(it.code, it.headers, it.body!!.byteStream().bounded(limit)) }
                if (continuation.isActive) continuation.resume(result)
            } catch (error: Exception) {
                if (continuation.isActive) continuation.resumeWithException(error)
            }
        }
    })
}

fun InputStream.bounded(limit: Int): ByteArray {
    val result = ByteArrayOutputStream()
    val buffer = ByteArray(65536)
    while (true) {
        val count = read(buffer, 0, minOf(buffer.size, limit - result.size() + 1))
        if (count < 0) return result.toByteArray()
        require(count <= limit - result.size()) { "Response exceeds the permitted size." }
        result.write(buffer, 0, count)
    }
}

data class HttpHead(val method: String, val target: String, val version: String, val fields: List<Pair<String, String>>) {
    fun single(name: String): String? {
        val values = fields.filter { it.first == name }
        require(values.size <= 1) { "Repeated header." }
        return values.firstOrNull()?.second
    }
    companion object {
        fun read(input: InputStream): HttpHead {
            val buffer = ByteArrayOutputStream()
            var tail = 0
            while (buffer.size() < 32768) {
                val value = input.read()
                require(value >= 0) { "Incomplete HTTP headers." }
                buffer.write(value)
                tail = (tail shl 8) or value
                if (tail == 0x0d0a0d0a) break
            }
            require(tail == 0x0d0a0d0a)
            val lines = buffer.toString("ISO-8859-1").removeSuffix("\r\n\r\n").split("\r\n")
            val parts = lines[0].split(' ', limit = 3)
            require(parts.size == 3)
            val fields = lines.drop(1).map {
                val split = it.indexOf(':')
                require(split > 0)
                val name = it.substring(0, split)
                require(name.matches(Regex("[!#$%&'*+.^_`|~0-9A-Za-z-]+")))
                val value = it.substring(split + 1).trim(' ', '\t')
                require(value.none { character -> character.code < 32 && character != '\t' || character.code == 127 })
                name.lowercase() to value
            }
            return HttpHead(parts[0], parts[1], parts[2], fields)
        }
    }
}

class RemoteHttpError(val status: Int) : Exception("The server request failed (HTTP $status).")

/**
 * How long an idle upstream connection may wait in the pool. A server
 * advertises its own idle limit (`Keep-Alive: timeout=N`); older servers say
 * nothing and close idle connections after uvicorn's default 5 seconds.
 */
object KeepAlive {
    /** For a server that advertises nothing: retire well inside its 5 seconds. */
    const val FALLBACK_MILLIS = 3000L
    /** Advertised timeouts beyond this are treated as this. */
    const val CAP_SECONDS = 60L
    /**
     * However long a server offers, an idle read connection is not reused
     * after this. Mobile carrier NATs and middleboxes can drop idle mappings
     * without telling either end, and a read on such a connection waits out
     * its read timeout instead of failing fast; a short ceiling bounds that.
     */
    const val MAX_IDLE_MILLIS = 25_000L

    /**
     * The advertised timeout in seconds, or null unless the response carries
     * exactly one well-formed Keep-Alive field with exactly one `timeout`.
     * Anything unexpected means "not advertised" and the fallback applies.
     */
    fun parse(values: List<String>): Long? {
        if (values.size != 1) return null
        var timeout: Long? = null
        for (part in values[0].split(',')) {
            val pieces = part.split('=')
            if (pieces.size != 2) return null
            val name = pieces[0].trim().lowercase()
            val value = pieces[1].trim()
            if (!name.matches(Regex("[a-z]+")) || !value.matches(Regex("[0-9]{1,6}"))) return null
            if (name == "timeout") { if (timeout != null) return null; timeout = value.toLong() }
        }
        return timeout
    }

    /**
     * The read pool's idle limit for an advertised timeout: shortened by a
     * margin (at least 2 seconds or a tenth) because the client's idle clock
     * starts after the server's and the request still has to arrive, and
     * never more than [MAX_IDLE_MILLIS]. A shorter server value is kept.
     */
    fun idleMillis(advertisedSeconds: Long?): Long {
        if (advertisedSeconds == null) return FALLBACK_MILLIS
        val limit = minOf(advertisedSeconds, CAP_SECONDS) * 1000
        return maxOf(1L, minOf(MAX_IDLE_MILLIS, limit - maxOf(2000L, limit / 10)))
    }
}

class PinnedServer(
    val host: String, val port: Int, val pin: String?, val session: String = "", val debugLoopback: Boolean = false,
    private val connectTimeoutMillis: Int = 4000, private val readTimeoutMillis: Int = 30000,
    /** A client for the same route and pin whose connections this session may reuse. */
    shared: OkHttpClient? = null,
    /** How long idle connections stay pooled; fixed for the life of this client's pool. */
    val keepAliveMillis: Long = KeepAlive.FALLBACK_MILLIS,
) {
    private val trust = object : X509TrustManager {
        override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
        override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) { throw CertificateException() }
        override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
            if (chain.isEmpty() || sha256(chain[0].encoded) != pin?.lowercase()) throw CertificateException("Server certificate does not match the registry.")
        }
    }
    private val tls = SSLContext.getInstance("TLS").apply { init(null, arrayOf(trust), SecureRandom()) }
    val base: HttpUrl = HttpUrl.Builder().scheme(if (debugLoopback) "http" else "https").host(host).port(port).build()
    val client: OkHttpClient
    init {
        require(port in 1..65535 && session.none { it.code < 32 || it.code == 127 })
        require(if (debugLoopback) BuildConfig.DEBUG && host == "127.0.0.1" else pin?.matches(Regex("[a-fA-F0-9]{64}")) == true)
        client = shared?.newBuilder()?.build() ?: OkHttpClient.Builder().followRedirects(false).followSslRedirects(false)
            .sslSocketFactory(tls.socketFactory, trust).hostnameVerifier { _, ssl ->
                runCatching { sha256(ssl.peerCertificates[0].encoded) == pin?.lowercase() }.getOrDefault(false)
            }
            // The server speaks HTTP/1.1; one protocol keeps every caller on the same pooled connections.
            .protocols(listOf(Protocol.HTTP_1_1))
            // Idle connections retire before the server's own keep-alive closes them, which makes
            // writing a request onto a connection the server is dropping unlikely. Client and server
            // clocks start at different moments, so it is a margin, not a guarantee; mutations carry
            // one-shot bodies and are never replayed if it loses that race (see KeepAlive).
            .connectionPool(ConnectionPool(8, keepAliveMillis, TimeUnit.MILLISECONDS))
            .cookieJar(CookieJar.NO_COOKIES).cache(null)
            .connectTimeout(4, TimeUnit.SECONDS).readTimeout(5, TimeUnit.SECONDS).callTimeout(20, TimeUnit.SECONDS).build()
    }

    /**
     * The WebView proxy's client. It shares the pin, pool and dispatcher with
     * [client], so all traffic for this session reuses the same connections.
     * There is no overall deadline because downloads and uploads stream; the
     * connect and per-read/write timeouts match the old raw sockets. Calls are
     * made with `execute()` on proxy workers, so the dispatcher's per-host
     * limit never queues them; the proxy's own permits bound concurrency.
     */
    internal val proxyClient: OkHttpClient by lazy { proxied(client) }

    /**
     * Requests that may change server state. A request whose connection dies
     * after it was sent is never replayed, so these must not ride a connection
     * that sat idle long enough for the server or the network to have dropped
     * it unnoticed (OkHttp only probes a connection idle for 10 seconds or
     * more). They get their own pool with the short fallback idle limit; same
     * pin, trust, cookie, redirect and dispatcher configuration as [client],
     * and retired with it. With the fallback limit already, it is [client].
     */
    private val mutationClient: OkHttpClient =
        if (keepAliveMillis <= KeepAlive.FALLBACK_MILLIS) client
        else client.newBuilder().connectionPool(ConnectionPool(8, KeepAlive.FALLBACK_MILLIS, TimeUnit.MILLISECONDS)).build()
    private val proxyMutationClient: OkHttpClient by lazy { if (mutationClient === client) proxyClient else proxied(mutationClient) }

    /** The WebView proxy's client for a request method: long-idle reuse only for safe reads. */
    internal fun proxyClientFor(method: String) = if (method in SAFE_METHODS) proxyClient else proxyMutationClient

    private fun proxied(base: OkHttpClient) = base.newBuilder().callTimeout(0, TimeUnit.MILLISECONDS)
        .connectTimeout(connectTimeoutMillis.toLong(), TimeUnit.MILLISECONDS)
        .readTimeout(readTimeoutMillis.toLong(), TimeUnit.MILLISECONDS)
        .writeTimeout(readTimeoutMillis.toLong(), TimeUnit.MILLISECONDS)
        .addNetworkInterceptor(ProxyWireHeaders).build()

    /**
     * The server's advertised keep-alive, in seconds. Recorded only by [ping]
     * once the route has proven it is the expected device; null otherwise.
     */
    @Volatile var advertisedKeepAlive: Long? = null
        private set

    /**
     * Prove this route reaches the registered device (the pin already proved
     * the certificate) and learn its keep-alive advertisement.
     */
    suspend fun ping(deviceId: String, timeoutSeconds: Long = 5) {
        val call = client.newCall(Request.Builder().url(base.resolve("/multi-device/ping")!!).build())
        call.timeout().timeout(timeoutSeconds, TimeUnit.SECONDS)
        val response = call.awaitResponse(16384)
        if (response.status !in 200..299) throw RemoteHttpError(response.status)
        require(JSONObject(response.body.toString(Charsets.UTF_8)).getString("deviceId") == deviceId) { "A different device answered." }
        advertisedKeepAlive = KeepAlive.parse(response.headers.values("Keep-Alive"))
    }

    /**
     * The authenticated session on this route, with one pool sized from the
     * verified keep-alive advertisement. When that matches this client's own
     * pool (an older server, say) the session reuses the connections that
     * discovered it; otherwise it starts its own pool and this one is emptied.
     */
    fun withSession(session: String): PinnedServer {
        val idle = KeepAlive.idleMillis(advertisedKeepAlive)
        if (idle == keepAliveMillis) return PinnedServer(host, port, pin, session, debugLoopback, connectTimeoutMillis, readTimeoutMillis, client, idle)
        evictIdle()
        return PinnedServer(host, port, pin, session, debugLoopback, connectTimeoutMillis, readTimeoutMillis, null, idle)
    }

    /** Close idle connections, e.g. before they cross a background period or network change. */
    fun evictIdle() { retirement.execute { client.connectionPool.evictAll(); mutationClient.connectionPool.evictAll() } }

    /** A proxied request: what retiring its session must do to stop it. */
    internal fun interface Retirable { fun retire() }

    private val proxyRequests = mutableSetOf<Retirable>()
    private var retired = false

    /**
     * Register a proxied request for this session's lifetime, from before its
     * final admission check until its response is delivered to the WebView.
     * False once the session is retired, so nothing can start afterwards.
     */
    internal fun admit(request: Retirable): Boolean = synchronized(proxyRequests) { if (retired) false else proxyRequests.add(request) }
    internal fun release(request: Retirable) { synchronized(proxyRequests) { proxyRequests.remove(request) } }

    /**
     * This session is finished: stop every proxied request it is serving,
     * including responses still being delivered (OkHttp's dispatcher only
     * tracks a synchronous call until its headers arrive), cancel its other
     * calls, and close its connections.
     */
    fun retire() {
        val active = synchronized(proxyRequests) { retired = true; proxyRequests.toList().also { proxyRequests.clear() } }
        active.forEach { runCatching { it.retire() } }
        client.dispatcher.cancelAll()
        evictIdle()
    }

    internal val pooledConnections get() = client.connectionPool.connectionCount()
    internal val pooledMutationConnections get() = if (mutationClient === client) 0 else mutationClient.connectionPool.connectionCount()

    companion object {
        private val SAFE_METHODS = setOf("GET", "HEAD", "OPTIONS")
        // Closing TLS sockets can write, which Android forbids on the main thread.
        private val retirement = Executors.newSingleThreadExecutor { Thread(it, "stimma-pool-retire").apply { isDaemon = true } }
    }

    fun bytes(path: String, limit: Int, body: RequestBody? = null, timeoutSeconds: Long = 20): ByteArray {
        val request = Request.Builder().url(base.resolve(path)!!)
        if (session.isNotEmpty()) request.header("Authorization", "Bearer $session")
        if (body != null) request.post(body)
        val call = (if (body != null) mutationClient else client).newCall(request.build())
        call.timeout().timeout(timeoutSeconds, TimeUnit.SECONDS)
        call.execute().use { response ->
            check(response.isSuccessful) { "The server request failed (HTTP ${response.code})." }
            return response.body!!.byteStream().bounded(limit)
        }
    }
    fun json(path: String, body: RequestBody? = null) = JSONObject(bytes(path, 16384, body).toString(Charsets.UTF_8))
    suspend fun asyncBytes(path: String, limit: Int, body: RequestBody? = null, timeoutSeconds: Long = 20): ByteArray {
        val request = Request.Builder().url(base.resolve(path)!!)
        if (session.isNotEmpty()) request.header("Authorization", "Bearer $session")
        if (body != null) request.post(body)
        val call = (if (body != null) mutationClient else client).newCall(request.build())
        call.timeout().timeout(timeoutSeconds, TimeUnit.SECONDS)
        val (status, bytes) = call.awaitBody(limit)
        if (status !in 200..299) throw RemoteHttpError(status)
        return bytes
    }
    suspend fun asyncJson(path: String, body: RequestBody? = null, timeoutSeconds: Long = 20) = JSONObject(asyncBytes(path, 16384, body, timeoutSeconds).toString(Charsets.UTF_8))
    /** Set once this server answered the health path with 404: an older server, checked through the profile list instead. */
    @Volatile internal var legacyHealth = false
    fun socket(): Socket {
        val plain = Socket()
        try {
            plain.connect(InetSocketAddress(host, port), connectTimeoutMillis)
            plain.soTimeout = readTimeoutMillis
            if (debugLoopback) return plain
            return (tls.socketFactory.createSocket(plain, host, port, true) as SSLSocket).apply { startHandshake() }
        } catch (error: Exception) { plain.close(); throw error }
    }
}

/**
 * The response to one WebView request. Records whether any byte reached the
 * WebView, after which no other response may follow, and lets a retired
 * session stop a response that has not been completely delivered.
 */
private class ResponseStream(private val socket: Socket) : FilterOutputStream(socket.getOutputStream()) {
    @Volatile var started = false
        private set
    /** Set once the last byte of the response has been handed to the socket. */
    @Volatile var delivered = false
    @Volatile private var writing = false
    @Volatile private var cut = false
    /** The socket stream itself, for the proxy's own failure response. */
    val raw: OutputStream get() = out

    /**
     * Stop this response for a retired session. Before any byte is written the
     * worker answers 503 instead; once writing has begun the stream is reset,
     * so the WebView sees a failed response rather than a complete old one.
     * Writers mark [writing] before checking [cut], and this sets [cut] before
     * checking [writing], so one side always sees the other.
     */
    fun cutOff() {
        cut = true
        if (writing && !delivered) reset()
    }

    private fun reset() { runCatching { socket.setSoLinger(true, 0) }; runCatching { socket.close() } }

    private fun admit() {
        writing = true
        if (cut) {
            if (!started) throw ProxyException(ProxyFailure.UNAVAILABLE)
            reset(); throw IOException("Session retired.")
        }
        started = true
    }
    override fun write(b: Int) { admit(); out.write(b) }
    override fun write(b: ByteArray, off: Int, len: Int) { admit(); out.write(b, off, len) }
}

/** The WebView side of a request went away; there is nobody left to answer. */
private class LocalClosed(cause: Throwable? = null) : Exception(cause)

/** The WebView stopped sending an upload; an IOException so OkHttp abandons the exchange like any I/O failure. */
private class LocalUploadAborted(cause: Throwable? = null) : IOException(cause)

/** Marks a request built by the proxy and records what the WebView itself sent. */
private class ProxiedRequest(val userAgent: Boolean)

/**
 * Keeps the proxied wire request what the WebView asked for: OkHttp's default
 * User-Agent is removed when the WebView sent none. Accept-Encoding is always
 * set explicitly by the proxy (see [MobileTransport]), so OkHttp never adds
 * gzip of its own and never decodes a body behind the WebView's back.
 */
internal object ProxyWireHeaders : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val tag = chain.request().tag(ProxiedRequest::class.java) ?: return chain.proceed(chain.request())
        if (tag.userAgent) return chain.proceed(chain.request())
        return chain.proceed(chain.request().newBuilder().removeHeader("User-Agent").build())
    }
}

/**
 * Streams a WebView upload straight to the server. One-shot, so OkHttp never
 * replays it: a mutation whose outcome is unknown is not sent twice.
 */
private class UploadBody(private val input: InputStream, private val length: Long, private val localGone: AtomicBoolean, private val sent: CountDownLatch) : RequestBody() {
    override fun contentType(): MediaType? = null
    override fun contentLength() = length
    override fun isOneShot() = true
    override fun writeTo(sink: BufferedSink) {
        val buffer = ByteArray(65536)
        var remaining = length
        while (remaining > 0) {
            val count = try { input.read(buffer, 0, minOf(buffer.size.toLong(), remaining).toInt()) }
                catch (error: IOException) { localGone.set(true); throw LocalUploadAborted(error) }
            if (count <= 0) { localGone.set(true); throw LocalUploadAborted() }
            sink.write(buffer, 0, count); remaining -= count
        }
        sink.flush()
        sent.countDown()
    }
}

private val CRLF = "\r\n".toByteArray()
/** Never forwarded upstream: browser credentials and context, hop-by-hop fields, and framing OkHttp writes itself. */
private val REQUEST_EXCLUDED = setOf("host", "authorization", "cookie", "origin", "proxy-connection", "proxy-authorization", "forwarded", "referer",
    "connection", "keep-alive", "te", "trailer", "transfer-encoding", "upgrade", "content-length")
/** Never forwarded to the WebView: server cookies and policy the proxy sets itself, and hop-by-hop fields. */
private val RESPONSE_EXCLUDED = setOf("set-cookie", "content-security-policy", "access-control-allow-origin", "access-control-allow-credentials",
    "connection", "keep-alive", "proxy-connection", "te", "trailer", "transfer-encoding", "upgrade")

/** Small authenticated answer on current servers; see the server's multi-device routes. */
const val HEALTH_PATH = "/api/multi-device/health"
/** Present on every server, but returns the profile list: used only when [HEALTH_PATH] is missing. */
const val LEGACY_HEALTH_PATH = "/api/profiles"
/** Set by the server's session gate when the device session itself was refused. */
private const val SESSION_INVALID_HEADER = "x-stimma-session-invalid"

class MobileTransport(
    private val report: (ProxyFailureReport) -> Unit = {},
    private val assets: (String) -> InputStream,
) : Closeable {
    private val listener = ServerSocket(0, 32, InetAddress.getByName("127.0.0.1"))
    val port = listener.localPort
    val origin = "http://127.0.0.1:$port"
    private val capability = ByteArray(32).also { SecureRandom().nextBytes(it) }.let { Base64.getUrlEncoder().withoutPadding().encodeToString(it) }
    val cookieName = "stimma_$port"
    val cookie = "$cookieName=$capability; HttpOnly; SameSite=Strict; Path=/"
    private val executor = Executors.newCachedThreadPool()
    private val permits = Semaphore(32)
    private val sockets = Collections.synchronizedSet(mutableSetOf<Socket>())
    /** Upstream WebSocket connections: long-lived, so the first to go stale when the network changes. */
    private val tunnels = Collections.synchronizedSet(mutableSetOf<Socket>())
    private val calls = Collections.synchronizedSet(mutableSetOf<Call>())
    /** The server session WebView traffic goes to. Replacing it retires the previous session's calls and connections. */
    @Volatile var target: PinnedServer? = null
        set(value) {
            val previous = field
            field = value
            if (previous != null && previous !== value) previous.retire()
        }
    /** Test seam: runs on the worker before it touches the accepted socket. Debug builds only. */
    @Volatile internal var beforeServe: ((Socket) -> Unit)? = null
    /** Test seam: runs after a proxied call passes admission, just before it goes upstream. Debug builds only. */
    @Volatile internal var beforeUpstream: (() -> Unit)? = null
    /** Test seam: runs once a proxied response has been read completely from the server, before its last bytes go to the WebView. Debug builds only. */
    @Volatile internal var upstreamComplete: (() -> Unit)? = null
    /** Test seam: stop accepting local connections while keeping the session attached, as a dead listener would. */
    internal fun stopListening() { listener.close() }
    internal val availablePermits get() = permits.availablePermits()
    internal val openSockets get() = sockets.size
    internal val inFlightCalls get() = calls.size
    /** How long the WebView side may stay silent mid-request. A test seam; the app keeps 30 seconds. */
    @Volatile internal var localReadTimeoutMillis = 30000
    @Volatile private var suspended = false
    fun setForeground(active: Boolean) {
        suspended = !active
        if (!active) { interruptConnections(); target?.evictIdle() }
    }
    @Volatile private var inlineScriptHashes = ""
    @Volatile var directory: File? = null
        set(value) {
            inlineScriptHashes = value?.let { root ->
                Regex("<script\\b[^>]*>([\\s\\S]*?)</script\\s*>", RegexOption.IGNORE_CASE)
                    .findAll(File(root, "index.html").readText()).map { it.groupValues[1] }.filter { it.isNotBlank() }
                    .joinToString(" ") { "'sha256-${Base64.getEncoder().encodeToString(MessageDigest.getInstance("SHA-256").digest(it.toByteArray()))}'" }
            }.orEmpty()
            field = value
        }

    init {
        executor.execute {
            while (!listener.isClosed) {
                val socket = try { listener.accept() } catch (_: Exception) { break }
                if (!permits.tryAcquire()) { socket.close(); continue }
                sockets.add(socket)
                executor.execute {
                    // Backgrounding can close the socket before this runs; every
                    // step that can throw must sit inside the permit cleanup.
                    var output: ResponseStream? = null
                    try {
                        if (BuildConfig.DEBUG) beforeServe?.invoke(socket)
                        output = ResponseStream(socket)
                        serve(socket, output)
                    } catch (error: Exception) { output?.let { fail(socket, it, error) } }
                    finally { runCatching { socket.close() }; sockets.remove(socket); permits.release() }
                }
            }
        }
    }

    fun authorize(request: HttpHead) {
        require(request.version == "HTTP/1.1" && request.single("host") == "127.0.0.1:$port")
        require(request.target.startsWith('/') && !request.target.startsWith("//") && request.target.none { it.code < 33 || it == '\\' })
        val cookies = request.single("cookie").orEmpty().split(';').map { it.trim() }
        require(cookies.count { it == "$cookieName=$capability" } == 1)
        require(request.single("origin").let { it == null || it == origin })
        require(request.single("sec-fetch-site").let { it == null || it in setOf("same-origin", "none") })
        val destination = request.single("sec-fetch-dest")
        val providerPanel = URI(request.target).path.startsWith("/api/provider-manage/")
        require(destination !in setOf("object", "embed", "worker", "sharedworker", "serviceworker"))
        require(destination !in setOf("iframe", "frame") || providerPanel)
        require(request.single("transfer-encoding") == null && request.single("expect") == null)
        val length = request.single("content-length")
        require(length == null || length.matches(Regex("[0-9]+")) && length.toLong() in 0..1024L * 1024 * 1024)
        require(request.method in setOf("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"))
        if (request.method !in setOf("GET", "HEAD", "OPTIONS")) require(request.single("origin") == origin)
    }

    /**
     * Answer a failed request once. Anything not explicitly classified is a
     * local policy rejection. If the response already started, a second status
     * line would be spliced into the body, so the stream is reset instead and
     * the WebView sees a network error it can recover from.
     */
    private fun fail(socket: Socket, output: ResponseStream, error: Exception) {
        if (error is LocalClosed || socket.isClosed) return
        val failure = (error as? ProxyException)?.failure ?: ProxyFailure.REJECTED
        runCatching { report(ProxyFailureReport(failure, output.started, (error.cause ?: error).javaClass.simpleName)) }
        if (output.started) { runCatching { socket.setSoLinger(true, 0) }; return }
        runCatching { respond(output.raw, failure.status, "text/plain", "Request unavailable".byteInputStream(), 19, failure = failure) }
    }

    /**
     * Run upstream I/O, classifying its failures. Interruptions caused by
     * backgrounding or a target swap are unavailability; a call cancelled
     * because the WebView went away has nobody to answer.
     */
    private inline fun <T> fromServer(remote: PinnedServer, localGone: AtomicBoolean? = null, block: () -> T): T = try { block() }
        catch (error: ProxyException) { throw error }
        catch (error: LocalClosed) { throw error }
        catch (error: Exception) {
            if (localGone?.get() == true) throw LocalClosed(error)
            throw ProxyException(if (suspended || target !== remote) ProxyFailure.UNAVAILABLE else ProxyFailure.upstream(error), error)
        }

    private inline fun <T> toClient(block: () -> T): T = try { block() } catch (error: IOException) { throw LocalClosed(error) }

    private fun serve(socket: Socket, output: ResponseStream) {
        socket.soTimeout = localReadTimeoutMillis
        val input = socket.getInputStream().buffered()
        val request = HttpHead.read(input)
        authorize(request)
        val path = URI(request.target).path
        require(path.split('/').none { it == ".." || it == "." } && '\\' !in path && path.none { it.code < 32 })
        val remote = target
        if (path == "/health" || path == "/api" || path.startsWith("/api/") || path == "/ws" || path.startsWith("/ws/")) {
            if (remote == null || suspended) throw ProxyException(ProxyFailure.UNAVAILABLE)
            if (request.single("upgrade")?.lowercase() == "websocket") tunnel(socket, input, output, request, remote)
            else forward(socket, input, output, request, remote)
            return
        }
        require(request.method in setOf("GET", "HEAD"))
        val name = if (path == "/") "index.html" else path.removePrefix("/")
        val root = directory
        val body: InputStream
        val size: Long
        val actualName: String
        if (root != null && name != "mobile.html" && !name.startsWith("setup/")) {
            val candidate = File(root, name)
            val file = if (candidate.isFile) candidate else if ('.' !in name.substringAfterLast('/')) File(root, "index.html") else error("Missing asset")
            require(file.canonicalPath.startsWith(root.canonicalPath + File.separator))
            body = file.inputStream(); size = file.length(); actualName = file.name
        } else {
            val data = assets(name.removePrefix("setup/")).use { it.bounded(16 * 1024 * 1024) }
            body = data.inputStream(); size = data.size.toLong(); actualName = name
        }
        val mime = when (actualName.substringAfterLast('.')) {
            "html" -> "text/html; charset=utf-8"; "js" -> "text/javascript"; "css" -> "text/css"
            "json" -> "application/json"; "svg" -> "image/svg+xml"; "png" -> "image/png"
            "woff2" -> "font/woff2"; "wasm" -> "application/wasm"; else -> "application/octet-stream"
        }
        body.use { respond(output, 200, mime, it, size, request.method == "HEAD") }
    }

    private val policy get() = "default-src 'self'; script-src 'self' 'wasm-unsafe-eval' $inlineScriptHashes; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self' data:; connect-src 'self' ws://127.0.0.1:$port; frame-src 'self' blob:; worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"

    private fun respond(output: OutputStream, status: Int, mime: String, body: InputStream, size: Long, head: Boolean = false, failure: ProxyFailure? = null) {
        val marker = failure?.let { "${ProxyFailure.HEADER}: ${it.category}\r\n" }.orEmpty()
        output.write(("HTTP/1.1 $status ${failure?.reason ?: "OK"}\r\nContent-Type: $mime\r\nContent-Length: $size\r\nConnection: close\r\nCache-Control: no-store\r\n${marker}Content-Security-Policy: $policy\r\nX-Content-Type-Options: nosniff\r\nReferrer-Policy: no-referrer\r\n\r\n").toByteArray())
        if (!head) body.copyTo(output)
        output.flush()
    }

    /**
     * Forward one HTTP request over the session's pooled OkHttp client. The
     * WebView side keeps its one-request-per-connection bridge; only the
     * upstream connection is reused. Bodies stream in both directions. If the
     * WebView closes its socket, or the app is backgrounded or the session
     * replaced, the upstream call is cancelled.
     */
    private fun forward(local: Socket, input: InputStream, destination: ResponseStream, request: HttpHead, remote: PinnedServer) {
        val providerPanel = URI(request.target).path.startsWith("/api/provider-manage/")
        require('#' !in request.target)
        val length = request.single("content-length")?.toLong()
        val uploadLength = when (request.method) {
            "GET", "HEAD" -> { require(length == null || length == 0L); null }
            "OPTIONS" -> length
            // Mutations always carry a one-shot body, even an empty one, so OkHttp never replays them.
            else -> length ?: 0
        }
        val localGone = AtomicBoolean()
        val finished = AtomicBoolean()
        val bodySent = CountDownLatch(if (uploadLength == null) 0 else 1)
        val connectionTokens = request.fields.filter { it.first == "connection" }.flatMap { field -> field.second.split(',').map { it.trim().lowercase() } }
        val headers = Headers.Builder()
        for ((name, value) in request.fields) {
            if (name in REQUEST_EXCLUDED || name in connectionTokens || name.startsWith("sec-fetch-") || name.startsWith("x-forwarded-")) continue
            // HttpHead decoded the bytes as Latin-1; OkHttp writes UTF-8. Round-trip so the server sees the WebView's bytes.
            headers.addUnsafeNonAscii(name, value.toByteArray(Charsets.ISO_8859_1).toString(Charsets.UTF_8))
        }
        if (remote.session.isNotEmpty()) headers.set("Authorization", "Bearer ${remote.session}")
        // Content coding is negotiated end to end between the WebView and the server, and encoded
        // bytes pass through as they are: the WebView decodes them, so Content-Encoding,
        // Content-Length and ETag stay true of the bytes it receives, and ranged media keeps the
        // identity coding the WebView asks for. OkHttp only decodes transparently when it chose the
        // coding itself; an explicit header (identity when the WebView sent none) rules that out.
        if (request.fields.none { it.first == "accept-encoding" }) headers.set("Accept-Encoding", "identity")
        val url = remote.base.newBuilder().encodedPath(request.target.substringBefore('?'))
            .encodedQuery(if ('?' in request.target) request.target.substringAfter('?') else null).build()
        val call = remote.proxyClientFor(request.method).newCall(Request.Builder().url(url).headers(headers.build())
            .method(request.method, uploadLength?.let { UploadBody(input, it, localGone, bodySent) })
            .tag(ProxiedRequest::class.java, ProxiedRequest(request.single("user-agent") != null)).build())
        calls.add(call)
        // Retiring the session stops both legs: the upstream call and any delivery to the WebView not yet complete.
        val registration = PinnedServer.Retirable { destination.cutOff(); call.cancel() }
        try {
            // Registered with the session before the final check, so a session retired after this point stops the request.
            if (!remote.admit(registration) || suspended || target !== remote || local.isClosed) throw ProxyException(ProxyFailure.UNAVAILABLE)
            if (BuildConfig.DEBUG) beforeUpstream?.invoke()
            watchForClose(input, bodySent, finished, localGone, call)
            fromServer(remote, localGone) { call.execute() }.use { response ->
                val locations = response.headers("Location")
                val localRedirect = locations.singleOrNull()?.let { value ->
                    val uri = runCatching { URI(value) }.getOrNull()
                    uri != null && !uri.isAbsolute && uri.rawAuthority == null && uri.path.startsWith("/api/provider-manage/") &&
                        uri.path.split('/').none { it == "." || it == ".." } && '\\' !in value
                } == true
                if (locations.size > 1 || response.code in 300..399 && response.code != 304 && !(providerPanel && localRedirect)) {
                    throw ProxyException(ProxyFailure.UPSTREAM_PROTOCOL)
                }
                val bodiless = request.method == "HEAD" || response.code in 100..199 || response.code == 204 || response.code == 304
                val responseTokens = response.headers("Connection").flatMap { field -> field.split(',').map { it.trim().lowercase() } }
                val declaredLength = response.headers("Content-Length").singleOrNull()
                // OkHttp has removed the upstream framing. A known length is kept; anything else is
                // re-chunked so the WebView can still tell a complete body from a truncated one.
                val fixedLength = bodiless || response.header("Transfer-Encoding") == null && declaredLength != null
                // Mark the exchange complete before the WebView can see its last byte: a WebView that hangs up
                // right after must not cancel a call whose connection has already gone back to the pool.
                fun complete() { finished.set(true); if (BuildConfig.DEBUG) upstreamComplete?.invoke() }
                if (bodiless) complete()
                toClient {
                    destination.write(buildString {
                        append("HTTP/1.1 ${response.code} ${response.message}\r\n")
                        for ((name, value) in response.headers) {
                            val key = name.lowercase()
                            if (key !in RESPONSE_EXCLUDED && key !in responseTokens && (key != "content-length" || fixedLength)) append("$key: $value\r\n")
                        }
                        if (!fixedLength) append("Transfer-Encoding: chunked\r\n")
                        append("Connection: close\r\n")
                        val responsePolicy = if (providerPanel)
                            "sandbox allow-scripts allow-same-origin allow-forms; default-src 'self' data: blob:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'self'; object-src 'none'; base-uri 'self'; form-action 'self'"
                            else "sandbox; default-src 'none'"
                        append("Content-Security-Policy: $responsePolicy\r\nX-Content-Type-Options: nosniff\r\n\r\n")
                    }.toByteArray(Charsets.UTF_8))
                }
                if (!bodiless) {
                    val source = response.body!!.byteStream()
                    val buffer = ByteArray(65536)
                    val expected = if (fixedLength) declaredLength?.toLongOrNull() else null
                    var total = 0L
                    while (true) {
                        val count = fromServer(remote, localGone) { source.read(buffer) }
                        if (count < 0) { if (!finished.get()) complete(); break }
                        if (count == 0) continue
                        total += count
                        if (total == expected) complete()
                        toClient {
                            if (!fixedLength) destination.write("${count.toString(16)}\r\n".toByteArray())
                            destination.write(buffer, 0, count)
                            if (!fixedLength) destination.write(CRLF)
                        }
                    }
                    if (!fixedLength) toClient { destination.write("0\r\n\r\n".toByteArray()) }
                }
                toClient { destination.flush() }
                destination.delivered = true
                finished.set(true)
            }
        } catch (error: Throwable) {
            if (!finished.getAndSet(true)) call.cancel()
            throw error
        } finally {
            finished.set(true); bodySent.countDown(); calls.remove(call); remote.release(registration)
        }
    }

    /**
     * Once the request is sent the WebView has nothing more to say on this
     * connection, so end-of-stream or an error means it gave up (an aborted
     * fetch, a thumbnail scrolled away): stop the upstream call too.
     */
    private fun watchForClose(input: InputStream, bodySent: CountDownLatch, finished: AtomicBoolean, localGone: AtomicBoolean, call: Call) {
        executor.execute {
            try {
                bodySent.await()
                while (!finished.get()) {
                    try { if (input.read() >= 0) return@execute; break } // Unexpected pipelined bytes: stop watching.
                    catch (_: SocketTimeoutException) { }
                }
            } catch (_: Exception) { }
            if (!finished.get()) { localGone.set(true); call.cancel() }
        }
    }

    /** WebSocket upgrades keep their own raw pinned connection for the life of the socket. */
    private fun tunnel(local: Socket, input: InputStream, destination: OutputStream, request: HttpHead, remote: PinnedServer) {
        require(request.method == "GET" && request.single("origin") == origin && request.single("content-length").let { it == null || it == "0" })
        fromServer(remote) { remote.socket() }.use { upstream ->
            sockets.add(upstream); tunnels.add(upstream)
            try {
                if (suspended || local.isClosed) throw ProxyException(ProxyFailure.UNAVAILABLE)
                val output = fromServer(remote) { upstream.getOutputStream() }
                val excluded = setOf("host", "authorization", "cookie", "origin", "connection", "proxy-connection", "proxy-authorization", "forwarded", "referer", "upgrade", "accept-encoding")
                val headers = request.fields.filter { it.first !in excluded && !it.first.startsWith("sec-fetch-") && !it.first.startsWith("x-forwarded-") }
                val text = buildString {
                    append("${request.method} ${request.target} HTTP/1.1\r\nHost: ${remote.base.host.let { if (':' in it) "[$it]" else it }}:${remote.port}\r\n")
                    append("Connection: Upgrade\r\nUpgrade: websocket\r\n")
                    if (remote.session.isNotEmpty()) append("Authorization: Bearer ${remote.session}\r\n")
                    for ((name, value) in headers) append("$name: $value\r\n")
                    append("\r\n")
                }
                fromServer(remote) { output.write(text.toByteArray(Charsets.ISO_8859_1)); output.flush() }
                val responseInput = fromServer(remote) { upstream.getInputStream().buffered() }
                val response = fromServer(remote) {
                    val head = HttpHead.read(responseInput)
                    require(head.method == "HTTP/1.1" && head.target.toInt() in 100..599)
                    require(head.target.toInt() !in 300..399 || head.target == "304")
                    head
                }
                val upgraded = response.target == "101"
                toClient {
                    destination.write(buildString {
                        append("${response.method} ${response.target} ${response.version}\r\n")
                        for ((name, value) in response.fields) if (name !in setOf("set-cookie", "content-security-policy", "access-control-allow-origin", "access-control-allow-credentials", "connection")) append("$name: $value\r\n")
                        append("Connection: ${if (upgraded) "Upgrade" else "close"}\r\n")
                        append("Content-Security-Policy: sandbox; default-src 'none'\r\nX-Content-Type-Options: nosniff\r\n\r\n")
                    }.toByteArray(Charsets.ISO_8859_1))
                    destination.flush()
                }
                if (upgraded) {
                    local.soTimeout = 0; upstream.soTimeout = 0
                    executor.execute { try { input.copyTo(output) } catch (_: Exception) { } finally { upstream.close(); local.close() } }
                }
                val buffer = ByteArray(65536)
                while (true) {
                    val count = fromServer(remote) { responseInput.read(buffer) }
                    if (count < 0) break
                    toClient { destination.write(buffer, 0, count) }
                }
                toClient { destination.flush() }
            } finally { sockets.remove(upstream); tunnels.remove(upstream) }
        }
    }

    /**
     * Check the path a WebView request takes, end to end: this listener and
     * its capability check, the proxy, the session's pooled pinned upstream,
     * the server's session gate and the app behind it. A direct request to
     * the server could succeed while any of the first three is broken.
     * Servers without the small health route answer 404 once; they are then
     * checked through the profile list, which every server has.
     */
    suspend fun checkConnection(timeoutMillis: Int = TransportRecovery.PROBE_BUDGET_MILLIS.toInt()): PathHealth {
        val remote = target ?: return PathHealth.UNREACHABLE
        if (!remote.legacyHealth) {
            val health = checkPath(HEALTH_PATH, timeoutMillis)
            if (health != PathHealth.MISSING) return health
            remote.legacyHealth = true
        }
        return checkPath(LEGACY_HEALTH_PATH, timeoutMillis).let { if (it == PathHealth.MISSING) PathHealth.UNREACHABLE else it }
    }

    internal suspend fun checkPath(path: String, timeoutMillis: Int): PathHealth = suspendCancellableCoroutine { continuation ->
        val socket = Socket()
        // Blocking socket I/O ignores coroutine cancellation; closing the socket ends it at once.
        continuation.invokeOnCancellation { runCatching { socket.close() } }
        val check = Runnable {
            val health = try { socket.use { checkPath(it, path, timeoutMillis) } } catch (_: Exception) { PathHealth.UNREACHABLE }
            if (continuation.isActive) continuation.resume(health)
        }
        try { executor.execute(check) } catch (_: Exception) { socket.close(); continuation.resume(PathHealth.UNREACHABLE) }
    }

    private fun checkPath(socket: Socket, path: String, timeoutMillis: Int): PathHealth {
        socket.connect(InetSocketAddress(InetAddress.getByName("127.0.0.1"), port), timeoutMillis)
        socket.soTimeout = timeoutMillis
        socket.getOutputStream().write(("GET $path HTTP/1.1\r\nHost: 127.0.0.1:$port\r\nCookie: $cookieName=$capability\r\n" +
            "Sec-Fetch-Site: same-origin\r\nAccept: application/json\r\n\r\n").toByteArray(Charsets.ISO_8859_1))
        val head = HttpHead.read(socket.getInputStream().buffered())
        val status = head.target.toIntOrNull() ?: return PathHealth.UNREACHABLE
        return when {
            // Answered by this proxy, not the server: the server was not reached.
            head.single(ProxyFailure.HEADER.lowercase()) != null -> PathHealth.UNREACHABLE
            status in 200..299 -> PathHealth.HEALTHY
            status == 401 && head.single(SESSION_INVALID_HEADER) == "1" -> PathHealth.SESSION_EXPIRED
            status == 404 -> PathHealth.MISSING
            else -> PathHealth.UNREACHABLE
        }
    }

    /** Drop every request in progress: cancel upstream calls and close local and WebSocket sockets. */
    fun interruptConnections() {
        synchronized(calls) { calls.toList() }.forEach { it.cancel() }
        synchronized(sockets) { sockets.toList().forEach { runCatching { it.close() } } }
    }
    /**
     * The single hook for a change of default network ([DefaultNetworkChanges]
     * calls it). Other reactions to a network change belong here too.
     *
     * Idle pooled connections were made on the old network and may be dead
     * without either side knowing, so none is reused. WebSocket tunnels may be
     * bound to that network and would sit silent until a timeout, so they end
     * now; the page reconnects its socket when recovery reports the new path
     * ready. Requests in flight are left to finish or fail on their own.
     */
    fun networkChanged() {
        target?.evictIdle()
        synchronized(tunnels) { tunnels.toList() }.forEach { runCatching { it.close() } }
    }
    fun disconnect() { target = null; interruptConnections() }
    override fun close() { listener.close(); disconnect(); executor.shutdownNow() }
}

/**
 * Reports a change of default network: a different network becoming the
 * default, the default being lost with no successor, or a network returning
 * after the default was lost (sockets from before the loss are suspect, and
 * recovery should not wait for its next retry). The first network seen is the
 * starting point, not a change. Generic so the decision is testable without
 * Android's network types.
 */
class NetworkChangeTracker<T : Any>(private val changed: () -> Unit) {
    private var current: T? = null
    private var lost = false
    @Synchronized fun available(network: T) {
        val change = lost || current != null && current != network
        current = network; lost = false
        if (change) changed()
    }
    @Synchronized fun lost(network: T) { if (network == current) { current = null; lost = true; changed() } }
}

/** Watches the system default network for [NetworkChangeTracker]; unregister with [close]. */
class DefaultNetworkChanges(context: android.content.Context, changed: () -> Unit) : Closeable {
    private val connectivity = context.getSystemService(android.net.ConnectivityManager::class.java)
    private val tracker = NetworkChangeTracker<android.net.Network>(changed)
    private val callback = object : android.net.ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: android.net.Network) = tracker.available(network)
        override fun onLost(network: android.net.Network) = tracker.lost(network)
    }
    private val registered = runCatching { connectivity?.registerDefaultNetworkCallback(callback) }.isSuccess && connectivity != null
    override fun close() { if (registered) runCatching { connectivity?.unregisterNetworkCallback(callback) } }
}
