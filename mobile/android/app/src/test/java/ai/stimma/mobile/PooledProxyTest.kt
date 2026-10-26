package ai.stimma.mobile

import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import okhttp3.mockwebserver.SocketPolicy
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import okio.Buffer
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.zip.GZIPOutputStream

/**
 * The WebView proxy over a pooled, pinned upstream client, exercised end to
 * end: raw HTTP into the local listener, TLS to a keep-alive fixture whose
 * certificate is pinned the way a registry pin is.
 */
class PooledProxyTest {
    private val certificate = HeldCertificate.Builder().commonName("localhost").build()
    private val pin = sha256(certificate.certificate.encoded)
    private val servers = mutableListOf<MockWebServer>()
    private val transport = MobileTransport { "ok".byteInputStream() }
    private val executor = Executors.newCachedThreadPool()

    @After fun tearDown() {
        transport.close(); executor.shutdownNow()
        servers.forEach { runCatching { it.shutdown() } }
    }

    private fun tlsServer(): MockWebServer = MockWebServer().also {
        it.useHttps(HandshakeCertificates.Builder().heldCertificate(certificate).build().sslSocketFactory(), false)
        it.start(); servers += it
    }

    private fun attach(server: MockWebServer, session: String = "native-session") =
        PinnedServer("127.0.0.1", server.port, pin, session).also { transport.target = it }

    private val cookie get() = transport.cookie.substringBefore(';')

    private fun open(method: String, target: String, headers: String = "", contentLength: Long? = null): Socket {
        val socket = Socket("127.0.0.1", transport.port)
        socket.soTimeout = 10000
        socket.getOutputStream().write(buildString {
            append("$method $target HTTP/1.1\r\nHost: 127.0.0.1:${transport.port}\r\nCookie: $cookie\r\n")
            if (method !in setOf("GET", "HEAD", "OPTIONS")) append("Origin: ${transport.origin}\r\n")
            if (contentLength != null) append("Content-Length: $contentLength\r\n")
            append(headers)
            append("\r\n")
        }.toByteArray())
        return socket
    }

    private class Reply(val head: HttpHead, val body: ByteArray) {
        val status get() = head.target
        fun header(name: String) = head.single(name)
    }

    /** Read a proxied response, decoding the local framing the way a browser would. */
    private fun read(socket: Socket, head: Boolean = false): Reply = socket.use {
        val input = it.getInputStream().buffered()
        val response = HttpHead.read(input)
        val body = when {
            head || response.target in setOf("204", "304") -> ByteArray(0)
            response.single("transfer-encoding") == "chunked" -> dechunk(input)
            response.single("content-length") != null -> ByteArray(response.single("content-length")!!.toInt()).also { bytes ->
                var offset = 0
                while (offset < bytes.size) { val count = input.read(bytes, offset, bytes.size - offset); check(count > 0) { "truncated" }; offset += count }
            }
            else -> input.readBytes()
        }
        Reply(response, body)
    }

    private fun dechunk(input: InputStream): ByteArray {
        val result = ByteArrayOutputStream()
        fun line() = buildString { while (true) { val c = input.read(); check(c >= 0) { "truncated" }; if (c == '\n'.code) break; if (c != '\r'.code) append(c.toChar()) } }
        while (true) {
            val size = line().toInt(16)
            if (size == 0) { check(line().isEmpty()); return result.toByteArray() }
            val chunk = ByteArray(size)
            var offset = 0
            while (offset < size) { val count = input.read(chunk, offset, size - offset); check(count > 0) { "truncated" }; offset += count }
            result.write(chunk); check(line().isEmpty())
        }
    }

    private fun get(target: String, headers: String = "") = read(open("GET", target, headers))

    private fun waitFor(condition: () -> Boolean) {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5)
        while (!condition() && System.nanoTime() < deadline) Thread.sleep(10)
        assertTrue(condition())
    }

    @Test fun repeatedRequestsReuseOneUpstreamConnection() {
        val server = tlsServer()
        attach(server)
        repeat(6) { server.enqueue(MockResponse().setBody("item $it")) }
        server.enqueue(MockResponse().setResponseCode(201).setBody("created"))
        repeat(6) { assertEquals("item $it", get("/api/media/$it").body.toString(Charsets.UTF_8)) }
        val post = read(open("POST", "/api/boards", "Content-Type: application/json\r\n", 2).also { it.getOutputStream().write("{}".toByteArray()) })
        assertEquals("201", post.status)
        // Every request, including the upload, went over the first TLS connection.
        val sequence = (0 until 7).map { server.takeRequest().sequenceNumber }
        assertEquals((0 until 7).toList(), sequence)
        assertEquals(1, transport.target!!.pooledConnections)
        waitFor { transport.inFlightCalls == 0 }
    }

    @Test fun aWebViewHangingUpAfterTheLastByteKeepsTheConnectionPooled() {
        // The browser closes its socket as soon as a response is complete; that must not cancel a
        // call whose upstream connection already went back to the pool.
        val server = tlsServer()
        attach(server)
        val rounds = 40
        repeat(rounds) { server.enqueue(if (it % 2 == 0) MockResponse().setBody("fixed") else MockResponse().setChunkedBody("chunked", 3)) }
        repeat(rounds) { get("/api/media/$it/thumbnail") }
        assertEquals((0 until rounds).toList(), (0 until rounds).map { server.takeRequest().sequenceNumber })
    }

    @Test fun headersAreIsolatedAndEncodingIsUntouched() {
        val server = tlsServer()
        attach(server, "alpha-session")
        val gzipped = ByteArrayOutputStream().also { out -> GZIPOutputStream(out).use { it.write("compressed".toByteArray()) } }.toByteArray()
        server.enqueue(MockResponse().setBody(Buffer().write(gzipped)).setHeader("Content-Encoding", "gzip").addHeader("Set-Cookie", "server=secret")
            .addHeader("Access-Control-Allow-Origin", "*").addHeader("Connection", "keep-alive, x-hop").addHeader("X-Hop", "1").addHeader("ETag", "\"v1\""))
        val reply = get("/api/settings?x=1&y=%20", "Authorization: Bearer browser\r\nAccept-Encoding: gzip, deflate, br\r\nReferer: http://127.0.0.1/\r\nSec-Fetch-Site: same-origin\r\nX-Forwarded-For: 1.2.3.4\r\nConnection: keep-alive, x-private\r\nX-Private: hop\r\nTE: trailers\r\nAccept: application/json\r\n")
        val recorded = server.takeRequest()
        assertEquals("/api/settings?x=1&y=%20", recorded.path)
        assertEquals("Bearer alpha-session", recorded.getHeader("Authorization"))
        for (name in listOf("Cookie", "Origin", "Referer", "Sec-Fetch-Site", "X-Forwarded-For", "X-Private", "TE", "User-Agent")) {
            assertNull(name, recorded.getHeader(name))
        }
        assertEquals("application/json", recorded.getHeader("Accept"))
        // Content coding is the WebView's to negotiate; the proxy forwards its offer unchanged.
        assertEquals("gzip, deflate, br", recorded.getHeader("Accept-Encoding"))
        // Compressed bytes pass through untouched: OkHttp did not decode them, and the encoding header survives.
        assertEquals("gzip", reply.header("content-encoding"))
        assertArrayEquals(gzipped, reply.body)
        assertEquals(reply.body.size.toString(), reply.header("content-length"))
        assertEquals("\"v1\"", reply.header("etag"))
        for (name in listOf("set-cookie", "access-control-allow-origin", "x-hop")) assertNull(name, reply.header(name))
        assertEquals("close", reply.header("connection"))

        server.enqueue(MockResponse().setBody("ok"))
        get("/api/profiles", "User-Agent: WebView test\r\n")
        assertEquals("WebView test", server.takeRequest().getHeader("User-Agent"))
    }

    @Test fun headRangeAndConditionalRequestsKeepTheirSemantics() {
        val server = tlsServer()
        attach(server)
        server.enqueue(MockResponse().setBody("").setHeader("Content-Length", "1234").setHeader("Accept-Ranges", "bytes"))
        server.enqueue(MockResponse().setResponseCode(206).setHeader("Content-Range", "bytes 2-5/10").setBody("2345"))
        server.enqueue(MockResponse().setResponseCode(304).setHeader("ETag", "\"v1\""))
        server.enqueue(MockResponse().setBody("after"))

        val head = read(open("HEAD", "/api/media/1/file"), head = true)
        assertEquals("200", head.status)
        assertEquals("1234", head.header("content-length"))
        assertEquals("HEAD", server.takeRequest().method)

        val range = get("/api/media/1/file", "Range: bytes=2-5\r\n")
        assertEquals("206", range.status)
        assertEquals("bytes 2-5/10", range.header("content-range"))
        assertEquals("2345", range.body.toString(Charsets.UTF_8))
        assertEquals("bytes=2-5", server.takeRequest().getHeader("Range"))

        val conditional = get("/api/media/1/thumbnail", "If-None-Match: \"v1\"\r\n")
        assertEquals("304", conditional.status)
        assertEquals(0, conditional.body.size)
        assertEquals("\"v1\"", server.takeRequest().getHeader("If-None-Match"))

        assertEquals("after", get("/api/profiles").body.toString(Charsets.UTF_8))
        assertEquals(3, server.takeRequest().sequenceNumber) // Bodiless responses left the connection reusable.
    }

    @Test fun chunkedResponsesAreReframedForTheWebView() {
        val server = tlsServer()
        attach(server)
        server.enqueue(MockResponse().setChunkedBody("x".repeat(100000), 4096))
        val reply = get("/api/chat/1")
        assertEquals("chunked", reply.header("transfer-encoding"))
        assertNull(reply.header("content-length"))
        assertEquals("x".repeat(100000), reply.body.toString(Charsets.UTF_8))
    }

    private fun gzip(bytes: ByteArray) = ByteArrayOutputStream().also { out -> GZIPOutputStream(out).use { it.write(bytes) } }.toByteArray()
    private fun gunzip(bytes: ByteArray) = java.util.zip.GZIPInputStream(bytes.inputStream()).readBytes()

    /**
     * A server that negotiates like the remote listener: complete JSON is
     * gzipped only for a client that offers gzip, with Vary and a weakened
     * validator; ranges, media and streams stay identity.
     */
    private fun negotiatingServer(json: ByteArray, media: ByteArray) = tlsServer().also { server ->
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val offer = request.getHeader("Accept-Encoding").orEmpty()
                val gzipOk = offer.split(',').any { it.trim().substringBefore(';').trim() == "gzip" && !it.replace(" ", "").contains("q=0") }
                return when (request.path) {
                    "/api/chats/1/items" -> when {
                        request.getHeader("If-None-Match") == "W/\"items-v1\"" -> MockResponse().setResponseCode(304).setHeader("ETag", "W/\"items-v1\"").setHeader("Vary", "Accept-Encoding")
                        gzipOk -> MockResponse().setBody(Buffer().write(gzip(json))).setHeader("Content-Type", "application/json")
                            .setHeader("Content-Encoding", "gzip").setHeader("Vary", "Accept-Encoding").setHeader("ETag", "W/\"items-v1\"")
                        else -> MockResponse().setBody(Buffer().write(json)).setHeader("Content-Type", "application/json")
                            .setHeader("Vary", "Accept-Encoding").setHeader("ETag", "\"items-v1\"")
                    }
                    "/api/media/1/file" -> {
                        val range = request.getHeader("Range")
                        if (range == "bytes=10-19") MockResponse().setResponseCode(206).setHeader("Content-Range", "bytes 10-19/${media.size}")
                            .setHeader("Content-Type", "video/mp4").setBody(Buffer().write(media.copyOfRange(10, 20)))
                        else MockResponse().setHeader("Content-Type", "video/mp4").setHeader("Accept-Ranges", "bytes").setBody(Buffer().write(media))
                    }
                    "/api/export" -> MockResponse().setHeader("Content-Type", "application/json").setChunkedBody(Buffer().write(json), 1024)
                    else -> MockResponse().setResponseCode(404)
                }
            }
        }
    }

    @Test fun compressedJsonReachesTheWebViewEncodedAndCorrectlyFramed() {
        val json = ("""{"items":[""" + (0 until 600).joinToString(",") { """{"id":$it,"text":"a repetitive chat body"}""" } + "]}").toByteArray()
        val media = ByteArray(4096) { (it * 31).toByte() }
        val server = negotiatingServer(json, media)
        attach(server)
        val chromium = "Accept-Encoding: gzip, deflate, br, zstd\r\n"

        // The WebView offers gzip: the compressed body arrives byte for byte, framed by its own
        // length, with the encoding and validator that describe those bytes. The WebView decodes it.
        val compressed = get("/api/chats/1/items", chromium)
        assertEquals("200", compressed.status)
        assertEquals("gzip, deflate, br, zstd", server.takeRequest().getHeader("Accept-Encoding"))
        assertEquals("gzip", compressed.header("content-encoding"))
        assertEquals(compressed.body.size.toString(), compressed.header("content-length"))
        assertNull(compressed.header("transfer-encoding"))
        assertTrue(compressed.body.size < json.size / 5)
        assertArrayEquals(json, gunzip(compressed.body))
        assertEquals("Accept-Encoding", compressed.header("vary"))
        assertEquals("W/\"items-v1\"", compressed.header("etag"))

        // Revalidation with that validator is a bodiless 304 that leaves the connection reusable.
        val revalidated = get("/api/chats/1/items", "${chromium}If-None-Match: W/\"items-v1\"\r\n")
        assertEquals("304", revalidated.status)
        assertNull(revalidated.header("content-encoding"))
        assertEquals(0, revalidated.body.size)
        server.takeRequest()

        // A request without an offer is identity on the wire: OkHttp neither asks for gzip nor decodes.
        val plain = get("/api/chats/1/items")
        assertEquals("identity", server.takeRequest().getHeader("Accept-Encoding"))
        assertNull(plain.header("content-encoding"))
        assertArrayEquals(json, plain.body)
        assertEquals(json.size.toString(), plain.header("content-length"))

        // Media ranges keep Chromium's identity-only offer and their exact bytes.
        val range = get("/api/media/1/file", "Accept-Encoding: identity;q=1, *;q=0\r\nRange: bytes=10-19\r\n")
        val rangeRequest = server.takeRequest()
        assertEquals("identity;q=1, *;q=0", rangeRequest.getHeader("Accept-Encoding"))
        assertEquals("bytes=10-19", rangeRequest.getHeader("Range"))
        assertEquals("206", range.status)
        assertEquals("bytes 10-19/4096", range.header("content-range"))
        assertNull(range.header("content-encoding"))
        assertArrayEquals(media.copyOfRange(10, 20), range.body)
        val whole = get("/api/media/1/file", chromium)
        server.takeRequest()
        assertNull(whole.header("content-encoding"))
        assertArrayEquals(media, whole.body)

        // A streamed body is still re-chunked, not decoded or buffered.
        val streamed = get("/api/export", chromium)
        server.takeRequest()
        assertEquals("chunked", streamed.header("transfer-encoding"))
        assertNull(streamed.header("content-encoding"))
        assertArrayEquals(json, streamed.body)

        // Every exchange shared the one pooled connection.
        assertEquals(1, transport.target!!.pooledConnections)
        waitFor { transport.inFlightCalls == 0 }
    }

    @Test fun nativeCallsDecodeCompressedResponsesTransparently() {
        // The shell's own reads (manifest, profiles) use OkHttp's negotiation; size limits apply to decoded bytes.
        val server = tlsServer()
        val json = """{"profiles":[${(0 until 200).joinToString(",") { """{"id":"p$it"}""" }}]}""".toByteArray()
        server.enqueue(MockResponse().setBody(Buffer().write(gzip(json))).setHeader("Content-Encoding", "gzip"))
        server.enqueue(MockResponse().setBody(Buffer().write(gzip(json))).setHeader("Content-Encoding", "gzip"))
        val session = PinnedServer("127.0.0.1", server.port, pin, "s")
        assertArrayEquals(json, session.bytes("/api/profiles", json.size))
        assertEquals("gzip", server.takeRequest().getHeader("Accept-Encoding"))
        assertThrows(IllegalArgumentException::class.java) { session.bytes("/api/profiles", json.size - 1) }
    }

    @Test fun redirectsAreNeverFollowedAndOnlyProviderPanelsMayRedirectLocally() {
        val server = tlsServer()
        attach(server)
        server.enqueue(MockResponse().setResponseCode(302).setHeader("Location", "https://example.com/steal"))
        val refused = get("/api/profiles")
        assertEquals("502", refused.status)
        assertEquals(ProxyFailure.UPSTREAM_PROTOCOL.category, refused.header("x-stimma-proxy-failure"))
        server.enqueue(MockResponse().setResponseCode(302).setHeader("Location", "/api/provider-manage/elsewhere"))
        assertEquals("502", get("/api/profiles").status) // A local redirect outside a provider panel.
        server.enqueue(MockResponse().setResponseCode(302).setHeader("Location", "https://example.com/"))
        assertEquals("502", get("/api/provider-manage/x/").status)
        server.enqueue(MockResponse().setResponseCode(302).setHeader("Location", "/api/provider-manage/x/next"))
        val allowed = get("/api/provider-manage/x/")
        assertEquals("302", allowed.status)
        assertEquals("/api/provider-manage/x/next", allowed.header("location"))
        assertEquals(4, server.requestCount) // Nothing followed a redirect.
    }

    @Test fun unauthorizedOriginsAreRejectedBeforeAnyUpstreamRequest() {
        val server = tlsServer()
        attach(server)
        val socket = Socket("127.0.0.1", transport.port)
        socket.soTimeout = 5000
        socket.getOutputStream().write("POST /api/boards HTTP/1.1\r\nHost: 127.0.0.1:${transport.port}\r\nCookie: $cookie\r\nOrigin: http://evil.example\r\nContent-Length: 0\r\n\r\n".toByteArray())
        val reply = read(socket)
        assertEquals("403", reply.status)
        assertEquals(ProxyFailure.REJECTED.category, reply.header("x-stimma-proxy-failure"))
        assertEquals("403", read(Socket("127.0.0.1", transport.port).apply {
            getOutputStream().write("GET /api/profiles HTTP/1.1\r\nHost: 127.0.0.1:${transport.port}\r\nCookie: ${transport.cookieName}=forged\r\n\r\n".toByteArray())
        }).status)
        assertEquals(0, server.requestCount)
    }

    @Test fun pinMismatchIsRefusedOnThePooledPath() {
        val server = tlsServer()
        transport.target = PinnedServer("127.0.0.1", server.port, "0".repeat(64), "native")
        val reply = get("/api/profiles")
        assertEquals("502", reply.status)
        assertEquals(ProxyFailure.UPSTREAM_IDENTITY.category, reply.header("x-stimma-proxy-failure"))
        assertEquals(0, server.requestCount)
    }

    @Test fun mutationsAreNeverReplayedButSafeReadsRecoverFromAStaleConnection() {
        val server = tlsServer()
        attach(server)
        // A GET that meets a pooled connection the server dropped is retried once on a fresh connection.
        server.enqueue(MockResponse().setBody("warm"))
        server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST))
        server.enqueue(MockResponse().setBody("recovered"))
        assertEquals("warm", get("/api/profiles").body.toString(Charsets.UTF_8))
        assertEquals("recovered", get("/api/profiles").body.toString(Charsets.UTF_8))
        assertEquals(3, server.requestCount)

        // A POST in the same position reached the server once; whether it ran is unknown, so it is not sent again.
        server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST))
        server.enqueue(MockResponse().setBody("replayed"))
        val post = read(open("POST", "/api/generate", contentLength = 2).also { it.getOutputStream().write("{}".toByteArray()) })
        assertEquals("502", post.status)
        assertEquals(ProxyFailure.UPSTREAM_UNREACHABLE.category, post.header("x-stimma-proxy-failure"))
        assertEquals(4, server.requestCount)

        // Same for a bodiless DELETE.
        val other = tlsServer()
        attach(other)
        other.enqueue(MockResponse().setBody("warm"))
        other.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST))
        other.enqueue(MockResponse().setBody("replayed"))
        assertEquals("warm", get("/api/profiles").body.toString(Charsets.UTF_8))
        assertEquals("502", read(open("DELETE", "/api/boards/1")).status)
        assertEquals(2, other.requestCount)
        other.takeRequest()
        assertEquals("DELETE", other.takeRequest().method)
    }

    @Test fun uploadsAndDownloadsStreamWithoutBuffering() {
        // A raw fixture, so the test can see bytes arrive before a request or response is complete.
        val raw = ServerSocket(0, 8, InetAddress.getByName("127.0.0.1"))
        try {
            transport.target = PinnedServer("127.0.0.1", raw.localPort, null, "native", true)
            val megabyte = 1024 * 1024
            val total = 8L * megabyte
            val firstMegabyte = CountDownLatch(1)
            val received = executor.submit<Long> {
                raw.accept().use { socket ->
                    val input = socket.getInputStream().buffered()
                    assertEquals(total.toString(), HttpHead.read(input).single("content-length"))
                    var count = 0L
                    val buffer = ByteArray(65536)
                    while (count < total) {
                        val read = input.read(buffer); check(read > 0); count += read
                        if (count >= megabyte) firstMegabyte.countDown()
                    }
                    socket.getOutputStream().write("HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok".toByteArray())
                    count
                }
            }
            val upload = open("PUT", "/api/upload", contentLength = total)
            val chunk = ByteArray(megabyte) { 7 }
            upload.getOutputStream().write(chunk)
            // Without streaming, the proxy would hold this first megabyte until the rest arrived.
            assertTrue("upload did not reach the server while the WebView was still sending", firstMegabyte.await(5, TimeUnit.SECONDS))
            repeat(7) { upload.getOutputStream().write(chunk) }
            assertEquals("ok", read(upload).body.toString(Charsets.UTF_8))
            assertEquals(total, received.get(5, TimeUnit.SECONDS))

            // Download: the fixture sends half a large body and waits; the WebView must already have that half.
            val gate = CountDownLatch(1)
            val served = executor.submit {
                raw.accept().use { socket ->
                    HttpHead.read(socket.getInputStream().buffered())
                    val out = socket.getOutputStream()
                    out.write("HTTP/1.1 200 OK\r\nContent-Length: ${2 * 1024 * 1024}\r\n\r\n".toByteArray())
                    out.write(ByteArray(1024 * 1024) { 1 }); out.flush()
                    assertTrue(gate.await(5, TimeUnit.SECONDS))
                    out.write(ByteArray(1024 * 1024) { 2 }); out.flush()
                }
            }
            open("GET", "/api/media/1/file").use { socket ->
                val input = socket.getInputStream().buffered()
                val head = HttpHead.read(input)
                assertEquals((2 * 1024 * 1024).toString(), head.single("content-length"))
                val first = ByteArray(1024 * 1024)
                var offset = 0
                while (offset < first.size) { val count = input.read(first, offset, first.size - offset); check(count > 0); offset += count }
                assertTrue(first.all { it == 1.toByte() })
                gate.countDown()
                assertEquals(1024 * 1024, input.readBytes().size)
            }
            served.get(5, TimeUnit.SECONDS)
        } finally { raw.close() }
    }

    /** A raw upstream that reads one request, never answers, and reports when the proxy hangs up. */
    private fun silentUpstream(): Triple<ServerSocket, CountDownLatch, java.util.concurrent.Future<Boolean>> {
        val raw = ServerSocket(0, 8, InetAddress.getByName("127.0.0.1"))
        val received = CountDownLatch(1)
        val closed = executor.submit<Boolean> {
            raw.accept().use { socket ->
                socket.soTimeout = 5000
                HttpHead.read(socket.getInputStream().buffered())
                received.countDown()
                try { socket.getInputStream().read() < 0 } catch (_: SocketException) { true }
            }
        }
        transport.target = PinnedServer("127.0.0.1", raw.localPort, null, "native", true)
        return Triple(raw, received, closed)
    }

    @Test fun closingTheWebViewSocketCancelsTheUpstreamCall() {
        val (raw, received, upstreamClosed) = silentUpstream()
        try {
            val socket = open("GET", "/api/media/1/thumbnail")
            assertTrue(received.await(5, TimeUnit.SECONDS)) // The server is holding the request.
            socket.close() // An aborted fetch.
            assertTrue(upstreamClosed.get(6, TimeUnit.SECONDS))
            waitFor { transport.inFlightCalls == 0 && transport.availablePermits == 32 }
        } finally { raw.close() }
    }

    @Test fun backgroundingCancelsInFlightCalls() {
        val (raw, received, upstreamClosed) = silentUpstream()
        try {
            val socket = open("GET", "/api/media/1/thumbnail")
            assertTrue(received.await(5, TimeUnit.SECONDS)) // The server is holding the request.
            transport.setForeground(false)
            assertTrue(upstreamClosed.get(6, TimeUnit.SECONDS))
            waitFor { transport.inFlightCalls == 0 }
            socket.close()
        } finally { raw.close() }
    }

    @Test fun longRequestsSurviveTheLocalReadTimeout() {
        // The close watcher's reads time out like any local read; that must not cancel a slow but healthy request.
        val server = tlsServer()
        val remote = attach(server)
        transport.localReadTimeoutMillis = 200
        server.enqueue(MockResponse().setBody("slow").setHeadersDelay(1200, TimeUnit.MILLISECONDS))
        val socket = open("GET", "/api/slow")
        assertEquals("slow", read(socket).body.toString(Charsets.UTF_8))
        assertSame(remote, transport.target)
    }

    @Test fun thumbnailBurstsDoNotQueueApiRequests() {
        val server = tlsServer()
        attach(server)
        val release = CountDownLatch(1)
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                if (request.path!!.startsWith("/api/media/")) release.await(10, TimeUnit.SECONDS)
                return MockResponse().setBody("ok")
            }
        }
        // More stalled thumbnails than OkHttp's default per-host dispatcher limit (5).
        val thumbnails = (0 until 12).map { open("GET", "/api/media/$it/thumbnail") }
        waitFor { transport.inFlightCalls == 12 }
        val started = System.nanoTime()
        assertEquals("ok", get("/api/profiles").body.toString(Charsets.UTF_8))
        assertTrue(TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started) < 3000)
        release.countDown()
        thumbnails.forEach { assertEquals("200", read(it).status) }
    }

    @Test fun serverSwitchRetiresTheOldPoolAndItsCredentials() {
        val first = tlsServer()
        val second = tlsServer()
        val alpha = attach(first, "alpha-session")
        first.enqueue(MockResponse().setBody("a"))
        assertEquals("a", get("/api/profiles").body.toString(Charsets.UTF_8))
        assertEquals(1, alpha.pooledConnections)
        // A request still waiting on the old server when the switch happens.
        first.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))
        val stranded = open("GET", "/api/media/1/thumbnail")
        waitFor { first.requestCount == 2 } // The old server is holding it.

        val bravo = attach(second, "bravo-session")
        val reply = read(stranded)
        assertEquals("503", reply.status)
        assertEquals(ProxyFailure.UNAVAILABLE.category, reply.header("x-stimma-proxy-failure"))
        waitFor { alpha.pooledConnections == 0 }

        second.enqueue(MockResponse().setBody("b"))
        assertEquals("b", get("/api/profiles").body.toString(Charsets.UTF_8))
        assertEquals("Bearer bravo-session", second.takeRequest().getHeader("Authorization"))
        assertEquals(1, bravo.pooledConnections)
        assertEquals(2, first.requestCount)
        first.takeRequest(); assertEquals("Bearer alpha-session", first.takeRequest().getHeader("Authorization"))

        transport.disconnect() // Logout and server removal retire the pool too.
        waitFor { bravo.pooledConnections == 0 }
    }

    @Test fun aRequestAdmittedJustBeforeASwitchNeverReachesTheOldServer() {
        val first = tlsServer()
        val second = tlsServer()
        attach(first, "alpha-session")
        first.enqueue(MockResponse().setBody("must not run"))
        val admitted = CountDownLatch(1)
        val resume = CountDownLatch(1)
        // Pause the worker after it passed the target check but before the call went upstream.
        transport.beforeUpstream = { admitted.countDown(); resume.await(5, TimeUnit.SECONDS) }
        val socket = open("POST", "/api/generate", contentLength = 2).also { it.getOutputStream().write("{}".toByteArray()) }
        assertTrue(admitted.await(5, TimeUnit.SECONDS))
        transport.beforeUpstream = null
        attach(second, "bravo-session")
        resume.countDown()
        val reply = read(socket)
        assertEquals("503", reply.status)
        assertEquals(ProxyFailure.UNAVAILABLE.category, reply.header("x-stimma-proxy-failure"))
        assertEquals(0, first.requestCount) // The old server never saw the mutation or the old bearer.
        assertEquals(0, second.requestCount)
        waitFor { transport.inFlightCalls == 0 }
    }

    @Test fun aSwitchCutsAResponseThatIsStillStreaming() {
        val first = tlsServer()
        val second = tlsServer()
        attach(first)
        val size = 200_000
        // Headers arrive at once; the body trickles in for about 20 seconds.
        first.enqueue(MockResponse().setBody(Buffer().write(ByteArray(size) { 3 })).throttleBody(1024, 100, TimeUnit.MILLISECONDS))
        open("GET", "/api/media/1/file").use { socket ->
            val input = socket.getInputStream().buffered()
            assertEquals(size.toString(), HttpHead.read(input).single("content-length"))
            assertTrue(input.read() >= 0) // The body has started.
            attach(second)
            val started = System.nanoTime()
            var received = 1
            try {
                val buffer = ByteArray(8192)
                while (true) { val count = input.read(buffer); if (count < 0) break; received += count }
            } catch (_: SocketException) { } // A reset: the response was cut, not completed.
            assertTrue("the old response kept streaming", received < size)
            assertTrue(TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started) < 3000)
        }
        waitFor { transport.inFlightCalls == 0 }
    }

    @Test fun aSwitchCutsAResponseReadFromTheServerButNotYetDelivered() {
        // The old server has answered in full, so cancelling its call stops nothing; the
        // delivery to the WebView must itself be cut. Covers both local framings.
        for (chunked in listOf(false, true)) {
            val first = tlsServer()
            val second = tlsServer()
            attach(first)
            val size = 8192
            first.enqueue(if (chunked) MockResponse().setChunkedBody("y".repeat(size), 1024) else MockResponse().setBody("y".repeat(size)))
            val complete = CountDownLatch(1)
            val resume = CountDownLatch(1)
            // Pause the worker after the final upstream read, before the last bytes go to the WebView.
            transport.upstreamComplete = { complete.countDown(); resume.await(5, TimeUnit.SECONDS) }
            open("GET", "/api/media/1/file").use { socket ->
                assertTrue(complete.await(5, TimeUnit.SECONDS))
                transport.upstreamComplete = null
                attach(second) // Returns with the old session retired.
                resume.countDown()
                val input = socket.getInputStream().buffered()
                // A reset may arrive before even the head is read; either way the response must not be whole.
                val body = try { HttpHead.read(input); if (chunked) dechunk(input) else input.readBytes() } catch (_: Exception) { null }
                assertTrue("chunked=$chunked: the old response was delivered complete after the switch", body == null || body.size < size)
            }
            waitFor { transport.inFlightCalls == 0 && transport.availablePermits == 32 }
        }
    }

    @Test fun sessionReusesTheConnectionThatDiscoveredIt() {
        val server = tlsServer()
        server.enqueue(MockResponse().setBody("""{"deviceId":"d"}"""))
        server.enqueue(MockResponse().setBody("manifest"))
        val probe = PinnedServer("127.0.0.1", server.port, pin)
        probe.json("/multi-device/ping")
        val session = probe.withSession("fresh-session")
        assertEquals("manifest", session.bytes("/api/mobile-ui/manifest", 100).toString(Charsets.UTF_8))
        assertNull(server.takeRequest().getHeader("Authorization"))
        val manifest = server.takeRequest()
        assertEquals("Bearer fresh-session", manifest.getHeader("Authorization"))
        assertEquals(1, manifest.sequenceNumber)
    }

    @Test fun anOlderServerKeepsTheShortFallbackAndTheDiscoveryConnection() {
        val server = tlsServer()
        server.enqueue(MockResponse().setBody("""{"deviceId":"d"}"""))
        repeat(3) { server.enqueue(MockResponse().setBody("item $it")) }
        val probe = PinnedServer("127.0.0.1", server.port, pin)
        runBlocking { probe.ping("d") }
        assertNull(probe.advertisedKeepAlive)
        val session = probe.withSession("s").also { transport.target = it }
        assertEquals(KeepAlive.FALLBACK_MILLIS, session.keepAliveMillis)
        assertEquals("item 0", get("/api/profiles").body.toString(Charsets.UTF_8))
        server.takeRequest()
        assertEquals(1, server.takeRequest().sequenceNumber) // Reused the ping's connection.
        // Past the fallback the idle connection is gone, so the next request cannot meet a
        // connection an old server (5 second keep-alive) is closing.
        Thread.sleep(KeepAlive.FALLBACK_MILLIS + 700)
        assertEquals("item 1", get("/api/profiles").body.toString(Charsets.UTF_8))
        assertEquals(0, server.takeRequest().sequenceNumber)
    }

    /** A server that advertises its keep-alive on every response, like the remote listener. */
    private fun advertisingServer(deviceId: String = "d", keepAlive: String = "timeout=65") = tlsServer().also { server ->
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when (request.path) {
                "/multi-device/ping" -> MockResponse().setBody("""{"deviceId":"$deviceId"}""")
                "/api/drop" -> MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST)
                "/api/last" -> MockResponse().setBody("last").setSocketPolicy(SocketPolicy.DISCONNECT_AT_END)
                else -> MockResponse().setBody("ok ${request.method}")
            }.setHeader("Keep-Alive", keepAlive)
        }
    }

    @Test fun aConnectionIdlePastTheReadLimitIsReplacedWhileFreshOnesAreReused() {
        // The read pool's limit is a ceiling on idle time, not on age: a connection kept busy stays
        // in use, and one left idle past the limit is replaced. Scaled down from the 25 s ceiling.
        val server = advertisingServer()
        val session = PinnedServer("127.0.0.1", server.port, pin, "s", keepAliveMillis = 2000).also { transport.target = it }
        get("/api/profiles")
        assertEquals(0, server.takeRequest().sequenceNumber)
        repeat(3) {
            Thread.sleep(1200) // Idle, but within the limit.
            get("/api/profiles")
            assertEquals(it + 1, server.takeRequest().sequenceNumber)
        }
        Thread.sleep(2700) // Idle past the limit: evicted, so the next read opens a new connection.
        get("/api/profiles")
        assertEquals(0, server.takeRequest().sequenceNumber)
        assertEquals(1, session.pooledConnections)
    }

    @Test fun anAdvertisedKeepAliveKeepsTheConnectionAcrossAPause() {
        val server = advertisingServer()
        val probe = PinnedServer("127.0.0.1", server.port, pin)
        runBlocking { probe.ping("d") }
        assertEquals(65L, probe.advertisedKeepAlive)
        val session = probe.withSession("s").also { transport.target = it }
        assertEquals(KeepAlive.MAX_IDLE_MILLIS, session.keepAliveMillis)
        server.takeRequest()
        assertEquals("ok GET", get("/api/profiles").body.toString(Charsets.UTF_8))
        val first = server.takeRequest().sequenceNumber
        // Longer than both the old 3 second pool and uvicorn's default 5 second keep-alive.
        Thread.sleep(6000)
        val started = System.nanoTime()
        assertEquals("ok GET", get("/api/profiles").body.toString(Charsets.UTF_8))
        val elapsedMillis = (System.nanoTime() - started) / 1_000_000
        assertEquals("the request after the pause reused the warm connection", first + 1, server.takeRequest().sequenceNumber)
        assertEquals(1, session.pooledConnections)
        println("request after a 6 s pause reused connection: true, took ${elapsedMillis} ms")
    }

    private fun post(target: String) = read(open("POST", target, contentLength = 2).also { it.getOutputStream().write("{}".toByteArray()) })

    @Test fun mutationsNeverRideALongIdleConnection() {
        val server = advertisingServer()
        val probe = PinnedServer("127.0.0.1", server.port, pin)
        runBlocking { probe.ping("d") }
        val session = probe.withSession("s").also { transport.target = it }
        server.takeRequest()
        // Reads and mutations use separate pools: a mutation never takes a read's warm connection.
        assertEquals("ok GET", get("/api/profiles").body.toString(Charsets.UTF_8))
        val read = server.takeRequest().sequenceNumber
        assertEquals("ok POST", post("/api/boards").body.toString(Charsets.UTF_8))
        assertEquals(0, server.takeRequest().sequenceNumber)
        assertEquals(1, session.pooledConnections)
        assertEquals(1, session.pooledMutationConnections)
        // The server then closes both connections without the client noticing yet (a restart, say).
        assertEquals("last", get("/api/last").body.toString(Charsets.UTF_8))
        assertEquals(read + 1, server.takeRequest().sequenceNumber)
        assertEquals("last", post("/api/last").body.toString(Charsets.UTF_8))
        assertEquals(1, server.takeRequest().sequenceNumber)
        // Six seconds later: inside OkHttp's 10 second window in which it would not probe the
        // connection, and past the mutation pool's 3 second idle limit. The POST goes out once,
        // on a fresh connection, and succeeds.
        Thread.sleep(6000)
        val after = post("/api/boards")
        assertEquals("status=${after.status} failure=${after.header("x-stimma-proxy-failure")}", "ok POST", after.body.toString(Charsets.UTF_8))
        assertEquals(0, server.takeRequest().sequenceNumber)
        // A mutation whose connection dies after the request was sent is reported, never sent again.
        val before = server.requestCount
        val dropped = read(open("POST", "/api/drop", contentLength = 2).also { it.getOutputStream().write("{}".toByteArray()) })
        assertEquals("502", dropped.status)
        assertEquals(before + 1, server.requestCount)
    }

    @Test fun aNetworkChangeEvictsIdleConnectionsOfBothPools() {
        val server = advertisingServer()
        val probe = PinnedServer("127.0.0.1", server.port, pin)
        runBlocking { probe.ping("d") }
        val session = probe.withSession("s").also { transport.target = it }
        get("/api/profiles"); post("/api/boards")
        assertEquals(1, session.pooledConnections)
        assertEquals(1, session.pooledMutationConnections)
        transport.networkChanged()
        waitFor { session.pooledConnections == 0 && session.pooledMutationConnections == 0 }
        // The next read opens a connection on the new network.
        repeat(3) { server.takeRequest() }
        get("/api/profiles")
        assertEquals(0, server.takeRequest().sequenceNumber)
    }

    @Test fun onlyADifferentLostOrReturningDefaultNetworkCountsAsAChange() {
        var changes = 0
        val tracker = NetworkChangeTracker<String> { changes++ }
        tracker.available("wifi")          // Registration reports the current network: not a change.
        assertEquals(0, changes)
        tracker.available("wifi")          // Same network again (capabilities refresh).
        assertEquals(0, changes)
        tracker.available("cellular")      // Handoff.
        assertEquals(1, changes)
        tracker.lost("wifi")               // Losing a network that is no longer the default.
        assertEquals(1, changes)
        tracker.lost("cellular")           // Losing the default.
        assertEquals(2, changes)
        tracker.available("wifi")          // Back from no network: recovery checks the path now, not at its next retry.
        assertEquals(3, changes)
        tracker.available("wifi")
        assertEquals(3, changes)
    }

    @Test fun onlyAVerifiedRouteMayAdvertise() {
        // A route whose certificate matches but that is not the expected device: its advertisement is ignored.
        val impostor = advertisingServer(deviceId = "someone-else")
        val probe = PinnedServer("127.0.0.1", impostor.port, pin)
        assertThrows(IllegalArgumentException::class.java) { runBlocking { probe.ping("d") } }
        assertNull(probe.advertisedKeepAlive)
        assertEquals(KeepAlive.FALLBACK_MILLIS, probe.withSession("s").keepAliveMillis)
        // Ordinary responses never change the advertisement; only the identity-checked ping does.
        val server = advertisingServer(keepAlive = "timeout=30")
        val other = PinnedServer("127.0.0.1", server.port, pin)
        runBlocking { other.asyncBytes("/api/profiles", 100) }
        assertNull(other.advertisedKeepAlive)
        // A malformed advertisement is the same as none.
        val malformed = PinnedServer("127.0.0.1", advertisingServer(keepAlive = "timeout=65, timeout=5").port, pin)
        runBlocking { malformed.ping("d") }
        assertNull(malformed.advertisedKeepAlive)
        assertEquals(KeepAlive.FALLBACK_MILLIS, malformed.withSession("s").keepAliveMillis)
    }

    @Test fun keepAliveAdvertisementsAreParsedConservatively() {
        assertEquals(65L, KeepAlive.parse(listOf("timeout=65")))
        assertEquals(65L, KeepAlive.parse(listOf("timeout=65, max=100")))
        assertEquals(65L, KeepAlive.parse(listOf(" Timeout = 65 ")))
        for (value in listOf("", "timeout", "timeout=", "timeout=-1", "timeout=6.5", "timeout=\"65\"", "timeout=1234567",
            "max=100", "timeout=65; max=100", "timeout=65, timeout=65", "timeout=65=1")) {
            assertNull(value, KeepAlive.parse(listOf(value)))
        }
        assertNull(KeepAlive.parse(emptyList()))
        assertNull(KeepAlive.parse(listOf("timeout=65", "timeout=65")))

        assertEquals(KeepAlive.FALLBACK_MILLIS, KeepAlive.idleMillis(null))
        assertEquals(25_000L, KeepAlive.idleMillis(65))      // The read ceiling, not the server's 65 s.
        assertEquals(25_000L, KeepAlive.idleMillis(999_999))
        assertEquals(25_000L, KeepAlive.idleMillis(30))
        assertEquals(24_300L, KeepAlive.idleMillis(27))      // A shorter server value, less a tenth, is kept.
        assertEquals(18_000L, KeepAlive.idleMillis(20))
        assertEquals(3_000L, KeepAlive.idleMillis(5))        // uvicorn's default, if a server says so.
        assertEquals(1L, KeepAlive.idleMillis(1))            // Shorter than the margin: effectively no idle reuse.
        assertEquals(1L, KeepAlive.idleMillis(0))
    }
}
