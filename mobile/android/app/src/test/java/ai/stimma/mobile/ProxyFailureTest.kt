package ai.stimma.mobile

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InterruptedIOException
import java.net.ConnectException
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import java.net.SocketTimeoutException
import java.util.concurrent.Executors
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLHandshakeException

class ProxyFailureTest {
    private val reports = LinkedBlockingQueue<ProxyFailureReport>()
    private fun transport() = MobileTransport(report = { reports.add(it) }) { "ok".byteInputStream() }
    private fun nextReport() = reports.poll(5, TimeUnit.SECONDS) ?: error("No failure was reported")

    /** Send a raw request to the proxy and read everything until EOF or reset. */
    private fun exchange(transport: MobileTransport, target: String = "/api/profiles?pin=2468", cookie: String = transport.cookie.substringBefore(';')): String =
        Socket("127.0.0.1", transport.port).use { socket ->
            socket.soTimeout = 5000
            socket.getOutputStream().write("GET $target HTTP/1.1\r\nHost: 127.0.0.1:${transport.port}\r\nCookie: $cookie\r\n\r\n".toByteArray())
            val received = ByteArrayOutputStream()
            val buffer = ByteArray(8192)
            try {
                while (true) {
                    val count = socket.getInputStream().read(buffer)
                    if (count < 0) break
                    received.write(buffer, 0, count)
                }
            } catch (_: SocketException) { }
            received.toString("ISO-8859-1")
        }

    private fun statusAndMarker(response: String): String {
        val head = HttpHead.read(response.byteInputStream(Charsets.ISO_8859_1))
        return "${head.target} ${head.single("x-stimma-proxy-failure").orEmpty()}".trim()
    }

    @Test fun nativeTableMatchesTheSharedContract() {
        val contract = JSONObject(javaClass.getResourceAsStream("/proxy-failures.json")!!.reader().readText())
        assertEquals(ProxyFailure.HEADER, contract.getString("header"))
        val failures = contract.getJSONObject("failures")
        assertEquals(ProxyFailure.entries.map { it.category }.toSet(), failures.keys().asSequence().toSet())
        for (failure in ProxyFailure.entries) {
            val entry = failures.getJSONObject(failure.category)
            assertEquals(failure.category, failure.status, entry.getInt("status"))
            // Only the policy rejection may look like an access failure to the UI.
            assertEquals(failure.category, failure == ProxyFailure.REJECTED, entry.isNull("connection"))
        }
    }

    @Test fun classifierSeparatesTimeoutsFromConnectionAndProtocolFailures() {
        assertEquals(ProxyFailure.UPSTREAM_TIMEOUT, ProxyFailure.upstream(SocketTimeoutException("connect timed out")))
        assertEquals(ProxyFailure.UPSTREAM_TIMEOUT, ProxyFailure.upstream(InterruptedIOException("timeout")))
        assertEquals(ProxyFailure.UPSTREAM_TIMEOUT, ProxyFailure.upstream(IOException("wrapped", SocketTimeoutException())))
        assertEquals(ProxyFailure.UPSTREAM_UNREACHABLE, ProxyFailure.upstream(ConnectException("refused")))
        assertEquals(ProxyFailure.UPSTREAM_UNREACHABLE, ProxyFailure.upstream(SocketException("Connection reset")))
        assertEquals(ProxyFailure.UPSTREAM_UNREACHABLE, ProxyFailure.upstream(SSLHandshakeException("pin mismatch")))
        assertEquals(ProxyFailure.UPSTREAM_PROTOCOL, ProxyFailure.upstream(IllegalArgumentException("bad status line")))
        assertEquals(ProxyFailure.UNAVAILABLE, ProxyFailure.upstream(ProxyException(ProxyFailure.UNAVAILABLE)))
    }

    @Test fun classifierUnderstandsOkHttpFailures() {
        val client = OkHttpClient.Builder().callTimeout(300, TimeUnit.MILLISECONDS).build()
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))
            server.start()
            val error = assertThrows(IOException::class.java) { client.newCall(Request.Builder().url(server.url("/")).build()).execute() }
            assertEquals(ProxyFailure.UPSTREAM_TIMEOUT, ProxyFailure.upstream(error))
        }
        val closed = ServerSocket(0).let { val port = it.localPort; it.close(); port }
        val error = assertThrows(IOException::class.java) { client.newCall(Request.Builder().url("http://127.0.0.1:$closed/").build()).execute() }
        assertEquals(ProxyFailure.UPSTREAM_UNREACHABLE, ProxyFailure.upstream(error))
    }

    @Test fun injectedConnectionFailuresAreNotAccessFailures() {
        val silent = ServerSocket(0, 8, InetAddress.getByName("127.0.0.1")) // Accepts at the OS level, never answers.
        val refused = ServerSocket(0).let { val port = it.localPort; it.close(); port }
        try {
            transport().use { transport ->
                transport.target = PinnedServer("127.0.0.1", refused, null, "native-secret", true)
                assertEquals("502 upstream-unreachable", statusAndMarker(exchange(transport)))
                assertEquals(ProxyFailure.UPSTREAM_UNREACHABLE, nextReport().failure)

                transport.target = PinnedServer("127.0.0.1", silent.localPort, null, "native-secret", true, readTimeoutMillis = 300)
                assertEquals("504 upstream-timeout", statusAndMarker(exchange(transport)))
                val timeout = nextReport()
                assertEquals(ProxyFailure.UPSTREAM_TIMEOUT, timeout.failure)
                assertFalse(timeout.afterResponseStarted)
                // Diagnostics carry the category, never the request or credentials.
                for (secret in listOf("2468", "profiles", "native-secret", "127.0.0.1")) assertFalse(timeout.toString().contains(secret))

                transport.target = null
                assertEquals("503 unavailable", statusAndMarker(exchange(transport)))
                assertEquals(ProxyFailure.UNAVAILABLE, nextReport().failure)
            }
        } finally { silent.close() }
    }

    @Test fun genuineAccessFailuresKeepTheirStatus() {
        MockWebServer().use { upstream ->
            upstream.enqueue(MockResponse().setResponseCode(403).setBody("""{"detail":"Invalid PIN"}""").setSocketPolicy(SocketPolicy.DISCONNECT_AT_END))
            upstream.start()
            transport().use { transport ->
                transport.target = PinnedServer("127.0.0.1", upstream.port, null, "native", true)
                // The server's own rejection passes through unmarked, so the UI reads it as before.
                val server = exchange(transport)
                assertEquals("403", statusAndMarker(server))
                assertTrue(server.endsWith("""{"detail":"Invalid PIN"}"""))
                // A request without the capability cookie is refused locally, still as an access failure.
                assertEquals("403 rejected", statusAndMarker(exchange(transport, cookie = "stimma_0=wrong")))
                assertEquals(ProxyFailure.REJECTED, nextReport().failure)
                assertEquals(1, upstream.requestCount)
            }
        }
    }

    @Test fun midStreamFailureResetsTheStreamInsteadOfAppendingAResponse() {
        val upstream = ServerSocket(0, 8, InetAddress.getByName("127.0.0.1"))
        val executor = Executors.newSingleThreadExecutor()
        try {
            transport().use { transport ->
                for (reset in listOf(true, false)) {
                    transport.target = PinnedServer("127.0.0.1", upstream.localPort, null, "native", true, readTimeoutMillis = 300)
                    val server = executor.submit {
                        upstream.accept().use { socket ->
                            HttpHead.read(socket.getInputStream().buffered())
                            socket.getOutputStream().write("HTTP/1.1 200 OK\r\nContent-Length: 100000\r\n\r\n".toByteArray() + ByteArray(1000) { 7 })
                            socket.getOutputStream().flush()
                            if (reset) { Thread.sleep(100); socket.setSoLinger(true, 0) }
                            else Thread.sleep(1000) // Stall past the proxy's read timeout.
                        }
                    }
                    val response = exchange(transport)
                    server.get(5, TimeUnit.SECONDS)
                    assertEquals(1, Regex("HTTP/1\\.1 ").findAll(response).count())
                    assertTrue(response.startsWith("HTTP/1.1 200"))
                    assertFalse(response.contains("Request unavailable"))
                    assertFalse(response.contains("x-stimma-proxy-failure", ignoreCase = true))
                    val report = nextReport()
                    assertTrue(report.afterResponseStarted)
                    assertEquals(if (reset) ProxyFailure.UPSTREAM_UNREACHABLE else ProxyFailure.UPSTREAM_TIMEOUT, report.failure)
                }
            }
        } finally { upstream.close(); executor.shutdownNow() }
    }
}
