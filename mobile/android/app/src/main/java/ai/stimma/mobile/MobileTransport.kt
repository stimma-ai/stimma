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

suspend fun Call.awaitBody(limit: Int): Pair<Int, ByteArray> = suspendCancellableCoroutine { continuation ->
    continuation.invokeOnCancellation { cancel() }
    enqueue(object : Callback {
        override fun onFailure(call: Call, error: IOException) {
            if (continuation.isActive) continuation.resumeWithException(error)
        }
        override fun onResponse(call: Call, response: Response) {
            try {
                val result = response.use { it.code to it.body!!.byteStream().bounded(limit) }
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

class PinnedServer(
    val host: String, val port: Int, val pin: String?, val session: String = "", val debugLoopback: Boolean = false,
    private val connectTimeoutMillis: Int = 4000, private val readTimeoutMillis: Int = 30000,
    /** A client for the same route and pin whose connections this session may reuse. */
    shared: OkHttpClient? = null,
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
            // Idle connections retire before the server's own 5 second keep-alive closes them,
            // so a request is never written onto a connection the server is about to drop.
            .connectionPool(ConnectionPool(8, IDLE_KEEP_ALIVE_MILLIS, TimeUnit.MILLISECONDS))
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
    internal val proxyClient: OkHttpClient by lazy {
        client.newBuilder().callTimeout(0, TimeUnit.MILLISECONDS)
            .connectTimeout(connectTimeoutMillis.toLong(), TimeUnit.MILLISECONDS)
            .readTimeout(readTimeoutMillis.toLong(), TimeUnit.MILLISECONDS)
            .writeTimeout(readTimeoutMillis.toLong(), TimeUnit.MILLISECONDS)
            .addNetworkInterceptor(ProxyWireHeaders).build()
    }

    /** The authenticated session on this route, reusing the connections that discovered it. */
    fun withSession(session: String) = PinnedServer(host, port, pin, session, debugLoopback, connectTimeoutMillis, readTimeoutMillis, client)

    /** Close idle connections, e.g. before they cross a background period or network change. */
    fun evictIdle() { retirement.execute { client.connectionPool.evictAll() } }

    /** This session is finished: cancel every call it is making and close its connections. */
    fun retire() {
        client.dispatcher.cancelAll()
        evictIdle()
    }

    internal val pooledConnections get() = client.connectionPool.connectionCount()

    companion object {
        const val IDLE_KEEP_ALIVE_MILLIS = 3000L
        // Closing TLS sockets can write, which Android forbids on the main thread.
        private val retirement = Executors.newSingleThreadExecutor { Thread(it, "stimma-pool-retire").apply { isDaemon = true } }
    }

    fun bytes(path: String, limit: Int, body: RequestBody? = null, timeoutSeconds: Long = 20): ByteArray {
        val request = Request.Builder().url(base.resolve(path)!!)
        if (session.isNotEmpty()) request.header("Authorization", "Bearer $session")
        if (body != null) request.post(body)
        val call = client.newCall(request.build())
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
        val call = client.newCall(request.build())
        call.timeout().timeout(timeoutSeconds, TimeUnit.SECONDS)
        val (status, bytes) = call.awaitBody(limit)
        if (status !in 200..299) throw RemoteHttpError(status)
        return bytes
    }
    suspend fun asyncJson(path: String, body: RequestBody? = null, timeoutSeconds: Long = 20) = JSONObject(asyncBytes(path, 16384, body, timeoutSeconds).toString(Charsets.UTF_8))
    suspend fun checkConnection() { asyncBytes("/api/profiles", 1024 * 1024, timeoutSeconds = 5) }
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

/** Records whether any byte of a response reached the WebView, after which no other response may follow. */
private class ResponseStream(output: OutputStream) : FilterOutputStream(output) {
    @Volatile var started = false
        private set
    override fun write(b: Int) { started = true; out.write(b) }
    override fun write(b: ByteArray, off: Int, len: Int) { started = true; out.write(b, off, len) }
}

/** The WebView side of a request went away; there is nobody left to answer. */
private class LocalClosed(cause: Throwable? = null) : Exception(cause)

/** The WebView stopped sending an upload; an IOException so OkHttp abandons the exchange like any I/O failure. */
private class LocalUploadAborted(cause: Throwable? = null) : IOException(cause)

/** Marks a request built by the proxy and records what the WebView itself sent. */
private class ProxiedRequest(val userAgent: Boolean)

/**
 * Keeps the proxied wire request what the proxy asked for. The proxy sets
 * `Accept-Encoding: identity` only so OkHttp neither adds gzip nor decodes
 * transparently; the header itself is removed, as the proxy has always done.
 * OkHttp's default User-Agent is removed when the WebView sent none.
 */
internal object ProxyWireHeaders : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val tag = chain.request().tag(ProxiedRequest::class.java) ?: return chain.proceed(chain.request())
        val request = chain.request().newBuilder().removeHeader("Accept-Encoding")
        if (!tag.userAgent) request.removeHeader("User-Agent")
        return chain.proceed(request.build())
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
    "accept-encoding", "connection", "keep-alive", "te", "trailer", "transfer-encoding", "upgrade", "content-length")
/** Never forwarded to the WebView: server cookies and policy the proxy sets itself, and hop-by-hop fields. */
private val RESPONSE_EXCLUDED = setOf("set-cookie", "content-security-policy", "access-control-allow-origin", "access-control-allow-credentials",
    "connection", "keep-alive", "proxy-connection", "te", "trailer", "transfer-encoding", "upgrade")

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
                        output = ResponseStream(socket.getOutputStream())
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
        runCatching { respond(output, failure.status, "text/plain", "Request unavailable".byteInputStream(), 19, failure = failure) }
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
        headers.set("Accept-Encoding", "identity")
        val url = remote.base.newBuilder().encodedPath(request.target.substringBefore('?'))
            .encodedQuery(if ('?' in request.target) request.target.substringAfter('?') else null).build()
        val call = remote.proxyClient.newCall(Request.Builder().url(url).headers(headers.build())
            .method(request.method, uploadLength?.let { UploadBody(input, it, localGone, bodySent) })
            .tag(ProxiedRequest::class.java, ProxiedRequest(request.single("user-agent") != null)).build())
        calls.add(call)
        try {
            if (suspended || target !== remote || local.isClosed) throw ProxyException(ProxyFailure.UNAVAILABLE)
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
                    while (true) {
                        val count = fromServer(remote, localGone) { source.read(buffer) }
                        if (count < 0) break
                        if (count == 0) continue
                        toClient {
                            if (!fixedLength) destination.write("${count.toString(16)}\r\n".toByteArray())
                            destination.write(buffer, 0, count)
                            if (!fixedLength) destination.write(CRLF)
                        }
                    }
                    if (!fixedLength) toClient { destination.write("0\r\n\r\n".toByteArray()) }
                }
                toClient { destination.flush() }
                finished.set(true)
            }
        } catch (error: Throwable) {
            finished.set(true); call.cancel(); throw error
        } finally {
            finished.set(true); bodySent.countDown(); calls.remove(call)
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
            sockets.add(upstream)
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
            } finally { sockets.remove(upstream) }
        }
    }

    /** Drop every request in progress: cancel upstream calls and close local and WebSocket sockets. */
    fun interruptConnections() {
        synchronized(calls) { calls.toList() }.forEach { it.cancel() }
        synchronized(sockets) { sockets.toList().forEach { runCatching { it.close() } } }
    }
    fun disconnect() { target = null; interruptConnections() }
    override fun close() { listener.close(); disconnect(); executor.shutdownNow() }
}
