package ai.stimma.mobile

import okhttp3.HttpUrl
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
import java.net.URI
import java.security.SecureRandom
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.Base64
import java.util.Collections
import java.util.concurrent.Executors
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
        client = OkHttpClient.Builder().followRedirects(false).followSslRedirects(false)
            .sslSocketFactory(tls.socketFactory, trust).hostnameVerifier { _, ssl ->
                runCatching { sha256(ssl.peerCertificates[0].encoded) == pin?.lowercase() }.getOrDefault(false)
            }.connectTimeout(4, TimeUnit.SECONDS).readTimeout(5, TimeUnit.SECONDS).callTimeout(20, TimeUnit.SECONDS).build()
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
    @Volatile var target: PinnedServer? = null
    /** Test seam: runs on the worker before it touches the accepted socket. Debug builds only. */
    @Volatile internal var beforeServe: ((Socket) -> Unit)? = null
    internal val availablePermits get() = permits.availablePermits()
    internal val openSockets get() = sockets.size
    @Volatile private var suspended = false
    fun setForeground(active: Boolean) {
        suspended = !active
        if (!active) interruptConnections()
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

    /** Run upstream I/O, classifying its failures. Interruptions caused by backgrounding or a target swap are unavailability. */
    private inline fun <T> fromServer(remote: PinnedServer, block: () -> T): T = try { block() }
        catch (error: ProxyException) { throw error }
        catch (error: Exception) {
            throw ProxyException(if (suspended || target !== remote) ProxyFailure.UNAVAILABLE else ProxyFailure.upstream(error), error)
        }

    private inline fun <T> toClient(block: () -> T): T = try { block() } catch (error: IOException) { throw LocalClosed(error) }

    private fun serve(socket: Socket, output: ResponseStream) {
        socket.soTimeout = 30000
        val input = socket.getInputStream().buffered()
        val request = HttpHead.read(input)
        authorize(request)
        val path = URI(request.target).path
        require(path.split('/').none { it == ".." || it == "." } && '\\' !in path && path.none { it.code < 32 })
        val remote = target
        if (path == "/health" || path == "/api" || path.startsWith("/api/") || path == "/ws" || path.startsWith("/ws/")) {
            if (remote == null || suspended) throw ProxyException(ProxyFailure.UNAVAILABLE)
            proxy(socket, input, output, request, remote)
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

    private fun proxy(local: Socket, input: InputStream, destination: OutputStream, request: HttpHead, remote: PinnedServer) {
        val websocket = request.single("upgrade")?.lowercase() == "websocket"
        if (websocket) require(request.method == "GET" && request.single("origin") == origin && request.single("content-length").let { it == null || it == "0" })
        val providerPanel = URI(request.target).path.startsWith("/api/provider-manage/")
        fromServer(remote) { remote.socket() }.use { upstream ->
            sockets.add(upstream)
            try {
                if (suspended || local.isClosed) throw ProxyException(ProxyFailure.UNAVAILABLE)
                val output = fromServer(remote) { upstream.getOutputStream() }
                val excluded = setOf("host", "authorization", "cookie", "origin", "connection", "proxy-connection", "proxy-authorization", "forwarded", "referer", "upgrade", "accept-encoding")
                val headers = request.fields.filter { it.first !in excluded && !it.first.startsWith("sec-fetch-") && !it.first.startsWith("x-forwarded-") }
                val text = buildString {
                    append("${request.method} ${request.target} HTTP/1.1\r\nHost: ${remote.base.host.let { if (':' in it) "[$it]" else it }}:${remote.port}\r\n")
                    append("Connection: ${if (websocket) "Upgrade" else "close"}\r\n")
                    if (websocket) append("Upgrade: websocket\r\n")
                    if (remote.session.isNotEmpty()) append("Authorization: Bearer ${remote.session}\r\n")
                    for ((name, value) in headers) append("$name: $value\r\n")
                    append("\r\n")
                }
                fromServer(remote) { output.write(text.toByteArray(Charsets.ISO_8859_1)) }
                var remaining = request.single("content-length")?.toLong() ?: 0
                val buffer = ByteArray(65536)
                while (remaining > 0) {
                    val count = toClient { input.read(buffer, 0, minOf(buffer.size.toLong(), remaining).toInt()) }
                    if (count <= 0) throw LocalClosed()
                    fromServer(remote) { output.write(buffer, 0, count) }; remaining -= count
                }
                fromServer(remote) { output.flush() }
                val responseInput = fromServer(remote) { upstream.getInputStream().buffered() }
                val response = fromServer(remote) {
                    val head = HttpHead.read(responseInput)
                    require(head.method == "HTTP/1.1" && head.target.toInt() in 100..599)
                    val localRedirect = head.single("location")?.let { value ->
                        val uri = URI(value)
                        !uri.isAbsolute && uri.rawAuthority == null && uri.path.startsWith("/api/provider-manage/") &&
                            uri.path.split('/').none { it == "." || it == ".." } && '\\' !in value
                    } == true
                    require(head.target.toInt() !in 300..399 || head.target == "304" || providerPanel && localRedirect)
                    head
                }
                toClient {
                    destination.write(buildString {
                        append("${response.method} ${response.target} ${response.version}\r\n")
                        for ((name, value) in response.fields) if (name !in setOf("set-cookie", "content-security-policy", "access-control-allow-origin", "access-control-allow-credentials", "connection")) append("$name: $value\r\n")
                        append("Connection: ${if (websocket && response.target == "101") "Upgrade" else "close"}\r\n")
                        val responsePolicy = if (providerPanel)
                            "sandbox allow-scripts allow-same-origin allow-forms; default-src 'self' data: blob:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'self'; object-src 'none'; base-uri 'self'; form-action 'self'"
                            else "sandbox; default-src 'none'"
                        append("Content-Security-Policy: $responsePolicy\r\nX-Content-Type-Options: nosniff\r\n\r\n")
                    }.toByteArray(Charsets.ISO_8859_1))
                    destination.flush()
                }
                if (websocket && response.target == "101") {
                    local.soTimeout = 0; upstream.soTimeout = 0
                    executor.execute { try { input.copyTo(output) } catch (_: Exception) { } finally { upstream.close(); local.close() } }
                }
                while (true) {
                    val count = fromServer(remote) { responseInput.read(buffer) }
                    if (count < 0) break
                    toClient { destination.write(buffer, 0, count) }
                }
                toClient { destination.flush() }
            } finally { sockets.remove(upstream) }
        }
    }

    fun interruptConnections() {
        synchronized(sockets) { sockets.toList().forEach { runCatching { it.close() } } }
    }
    fun disconnect() { target = null; interruptConnections() }
    override fun close() { listener.close(); disconnect(); executor.shutdownNow() }
}
