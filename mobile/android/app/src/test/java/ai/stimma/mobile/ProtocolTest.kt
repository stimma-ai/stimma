package ai.stimma.mobile

import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.launch
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.nio.file.Files
import java.util.concurrent.Executors
import java.util.zip.GZIPOutputStream
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate

class ProtocolTest {
    @Test fun connectionMonitorChecksAuthenticatedProfiles() = runBlocking {
        val certificate = HeldCertificate.Builder().commonName("localhost").build()
        MockWebServer().use { server ->
            server.useHttps(HandshakeCertificates.Builder().heldCertificate(certificate).build().sslSocketFactory(), false)
            server.enqueue(MockResponse().setBody("[]"))
            server.enqueue(MockResponse().setResponseCode(401))
            server.start()
            val remote = PinnedServer("127.0.0.1", server.port, sha256(certificate.certificate.encoded), "monitor-session")
            remote.checkConnection()
            val request = server.takeRequest()
            assertEquals("/api/profiles", request.path)
            assertEquals("Bearer monitor-session", request.getHeader("Authorization"))
            try {
                remote.checkConnection()
                fail("An invalid session must trigger recovery")
            } catch (error: RemoteHttpError) { assertEquals(401, error.status) }
        }
    }
    @Test fun cancellingNativeRequestsStopsTheirNetworkCalls() = runBlocking {
        val certificate = HeldCertificate.Builder().commonName("localhost").build()
        MockWebServer().use { server ->
            server.useHttps(HandshakeCertificates.Builder().heldCertificate(certificate).build().sslSocketFactory(), false)
            server.enqueue(MockResponse().setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.NO_RESPONSE))
            server.start()
            val remote = PinnedServer("127.0.0.1", server.port, sha256(certificate.certificate.encoded))
            var delivered = false
            val request = launch { remote.asyncBytes("/health", 100); delivered = true }
            delay(200)
            withTimeout(1000) { request.cancelAndJoin() }
            assertFalse(delivered)
            assertEquals(0, remote.client.dispatcher.queuedCallsCount())
        }
    }
    @Test fun pinnedTlsRejectsWrongCertificateAndRedirects() {
        val certificate = HeldCertificate.Builder().commonName("localhost").addSubjectAlternativeName("127.0.0.1").build()
        val certificates = HandshakeCertificates.Builder().heldCertificate(certificate).build()
        MockWebServer().use { server ->
            server.useHttps(certificates.sslSocketFactory(), false)
            server.start()
            val good = PinnedServer("127.0.0.1", server.port, sha256(certificate.certificate.encoded), "native")
            val bad = PinnedServer("127.0.0.1", server.port, "0".repeat(64))
            assertThrows(Exception::class.java) { bad.bytes("/health", 100) }
            assertThrows(Exception::class.java) { bad.socket().close() }
            server.enqueue(MockResponse().setBody("ok"))
            assertEquals("ok", good.bytes("/health", 100).toString(Charsets.UTF_8))
            assertEquals("Bearer native", server.takeRequest().getHeader("Authorization"))
            server.enqueue(MockResponse().setResponseCode(302).addHeader("Location", "https://example.com"))
            assertThrows(Exception::class.java) { good.bytes("/health", 100) }
        }
    }
    internal fun archive(vararg files: Pair<String, String>, type: Int = 48): ByteArray {
        val tar = ByteArrayOutputStream()
        for ((name, content) in files) {
            val header = ByteArray(512)
            fun field(offset: Int, value: String) { value.toByteArray().copyInto(header, offset) }
            field(0, name); field(100, "0000644"); field(108, "0000000"); field(116, "0000000")
            field(124, content.toByteArray().size.toString(8).padStart(11, '0')); field(136, "00000000000")
            header[156] = type.toByte(); field(257, "ustar"); field(263, "00")
            for (index in 148..155) header[index] = 32
            field(148, header.sumOf { it.toInt() and 255 }.toString(8).padStart(6, '0') + "\u0000 ")
            tar.write(header); tar.write(content.toByteArray())
            tar.write(ByteArray((512 - content.toByteArray().size % 512) % 512))
        }
        tar.write(ByteArray(1024))
        return ByteArrayOutputStream().also { result -> GZIPOutputStream(result).use { it.write(tar.toByteArray()) } }.toByteArray()
    }
    internal fun manifest(archive: ByteArray, expanded: Int) = JSONObject().put("formatVersion", 1).put("bridgeVersion", 1)
        .put("apiVersion", 1).put("entrypoint", "index.html").put("hash", sha256(archive)).put("bytes", archive.size)
        .put("unpackedBytes", expanded).toString().toByteArray()

    @Test fun packageRejectsUnsafeNamesTypesCollisionsAndCorruption() {
        for (name in listOf("../bad", "/bad", "a/./b", "a//b", "a\\b", "a/".repeat(33) + "b", "bad\nname")) {
            val archive = archive("index.html" to "ok", name to "bad")
            assertThrows(Exception::class.java) { UIPackageCache.unpack(archive, PackageManifest.parse(manifest(archive, 5))) }
        }
        for (files in listOf(arrayOf("index.html" to "ok", "INDEX.html" to "no"), arrayOf("index.html" to "ok", "file" to "a", "file/child" to "b"))) {
            val archive = archive(*files)
            assertThrows(Exception::class.java) { UIPackageCache.unpack(archive, PackageManifest.parse(manifest(archive, files.sumOf { it.second.length }))) }
        }
        for (type in listOf(49, 50, 51, 53, 120)) {
            val archive = archive("index.html" to "ok", type = type)
            assertThrows(Exception::class.java) { UIPackageCache.unpack(archive, PackageManifest.parse(manifest(archive, 2))) }
        }
        val good = archive("index.html" to "ok")
        val description = PackageManifest.parse(manifest(good, 2))
        assertEquals("ok", UIPackageCache.unpack(good, description)["index.html"]!!.toString(Charsets.UTF_8))
        assertThrows(Exception::class.java) { UIPackageCache.unpack(good + good, description.copy(hash = sha256(good + good), bytes = good.size * 2)) }
        val corrupt = good.clone().apply { this[lastIndex - 5] = (this[lastIndex - 5].toInt() xor 1).toByte() }
        assertThrows(Exception::class.java) { UIPackageCache.unpack(corrupt, description.copy(hash = sha256(corrupt))) }
    }

    @Test fun cacheVerifiesReuseRepairsCorruptionAndProtectsActivePackage() {
        val root = Files.createTempDirectory("stimma-package").toFile()
        try {
            val archive = archive("index.html" to "ok", "assets/app.js" to "app")
            val manifest = manifest(archive, 5)
            val cache = UIPackageCache(root)
            var downloads = 0
            val content = cache.resolve(manifest) { downloads++; archive }
            assertEquals(content, cache.resolve(manifest) { error("Cache miss") })
            File(content, "assets/app.js").writeText("bad")
            assertThrows(Exception::class.java) { cache.resolve(manifest, setOf(sha256(archive))) { archive } }
            cache.resolve(manifest) { downloads++; archive }
            assertEquals(2, downloads)
            assertEquals("app", File(content, "assets/app.js").readText())
            val tiny = UIPackageCache(root, 1)
            assertThrows(Exception::class.java) { tiny.resolve(manifest) { archive } }
            assertTrue(content.exists())
            assertThrows(Exception::class.java) { cache.resolve(manifest, cancelled = { throw InterruptedException() }) { archive } }
        } finally { root.deleteRecursively() }
    }

    @Test fun cacheEvictsOldVersionsAndRejectsUnsupportedManifests() {
        val root = Files.createTempDirectory("stimma-eviction").toFile()
        try {
            val first = archive("index.html" to "first")
            val second = archive("index.html" to "second")
            val firstManifest = manifest(first, 5)
            val secondManifest = manifest(second, 6)
            val budget = first.size + second.size + firstManifest.size + secondManifest.size + 10L
            val cache = UIPackageCache(root, budget)
            val firstDirectory = cache.resolve(firstManifest) { first }
            assertThrows(Exception::class.java) { cache.resolve(secondManifest, setOf(sha256(first))) { second } }
            assertTrue(firstDirectory.exists())
            val next = cache.resolve(secondManifest) { second }
            assertFalse(firstDirectory.exists())
            assertEquals("second", File(next, "index.html").readText())
            for ((key, value) in listOf("formatVersion" to 2, "bridgeVersion" to 2, "apiVersion" to 2, "bytes" to 67108865, "unpackedBytes" to 134217729, "entrypoint" to "../index.html")) {
                val invalid = JSONObject(firstManifest.toString(Charsets.UTF_8)).put(key, value).toString().toByteArray()
                assertThrows(Exception::class.java) { PackageManifest.parse(invalid) }
            }
        } finally { root.deleteRecursively() }
    }

    @Test fun rejectsAmbiguousHttpFramingAndCrossOriginRequests() {
        MobileTransport { "ok".byteInputStream() }.use { transport ->
            val headers = listOf("host" to "127.0.0.1:${transport.port}", "cookie" to transport.cookie.substringBefore(';'))
            val valid = HttpHead("GET", "/health", "HTTP/1.1", headers)
            transport.authorize(valid)
            for (extra in listOf("host" to "evil", "origin" to "http://evil", "sec-fetch-site" to "cross-site", "sec-fetch-dest" to "iframe", "transfer-encoding" to "chunked", "content-length" to "-1", "content-length" to "1073741825")) {
                assertThrows(Exception::class.java) { transport.authorize(valid.copy(fields = headers + extra)) }
            }
            assertThrows(Exception::class.java) { transport.authorize(valid.copy(method = "POST")) }
            assertThrows(Exception::class.java) { transport.authorize(valid.copy(fields = headers.dropLast(1))) }
            assertThrows(Exception::class.java) { transport.authorize(valid.copy(fields = headers + listOf("content-length" to "0", "content-length" to "0"))) }
            assertThrows(Exception::class.java) { HttpHead.read("GET / HTTP/1.1\r\n folded: bad\r\n\r\n".byteInputStream()) }
        }
    }

    @Test fun callbackChecksStateBothAddressFamiliesAndSingleDelivery() = runBlocking {
        AuthCallback().use { callback ->
            fun request(host: String, query: String): String = Socket(InetAddress.getByName(host), callback.port).use { socket ->
                socket.soTimeout = 3000
                socket.getOutputStream().write("GET /callback?$query HTTP/1.1\r\nHost: localhost:${callback.port}\r\n\r\n".toByteArray())
                socket.getInputStream().bufferedReader().readText()
            }
            assertTrue(request("127.0.0.1", "state=wrong&code=dummy").contains("400 Bad Request"))
            assertTrue(request("::1", "state=${callback.state}&code=dummy&code=other").contains("400 Bad Request"))
            assertTrue(request("::1", "state=${callback.state}&code=dummy").endsWith("Returning to Stimma..."))
            assertEquals("dummy", withTimeout(3000) { callback.code.await() })
            assertTrue(request("127.0.0.1", "state=${callback.state}&code=again").contains("400 Bad Request"))
        }
    }

    @Test fun proxyStreamsUploadsRangesAndBidirectionalWebSocketsWithoutBrowserCredentials() {
        val upstream = ServerSocket(0, 8, InetAddress.getByName("127.0.0.1"))
        val executor = Executors.newSingleThreadExecutor()
        try {
            MobileTransport { "ok".byteInputStream() }.use { transport ->
                transport.target = PinnedServer("127.0.0.1", upstream.localPort, null, "native-session", true)
                for (websocket in listOf(false, true)) {
                    val future = executor.submit {
                        upstream.accept().use { socket ->
                            socket.soTimeout = 5000
                            val input = socket.getInputStream().buffered()
                            val head = HttpHead.read(input)
                            assertEquals("Bearer native-session", head.single("authorization"))
                            assertNull(head.single("cookie")); assertNull(head.single("origin"))
                            if (websocket) {
                                socket.getOutputStream().write("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n".toByteArray())
                                assertEquals(129, input.read())
                                socket.getOutputStream().write(byteArrayOf(129.toByte(), 2, 111, 107))
                            } else {
                                val bytes = ByteArray(200000)
                                var received = 0
                                while (received < bytes.size) { val count = input.read(bytes, received, bytes.size - received); check(count > 0); received += count }
                                assertTrue(bytes.all { it == 7.toByte() })
                                assertEquals("bytes=1-2", head.single("range"))
                                socket.getOutputStream().write("HTTP/1.1 206 Partial Content\r\nContent-Length: 2\r\nContent-Range: bytes 1-2/4\r\nSet-Cookie: secret=bad\r\n\r\nok".toByteArray())
                            }
                        }
                    }
                    Socket("127.0.0.1", transport.port).use { socket ->
                        socket.soTimeout = 5000
                        val output = socket.getOutputStream()
                        output.write(buildString {
                            append("${if (websocket) "GET /ws" else "POST /api/upload"} HTTP/1.1\r\nHost: 127.0.0.1:${transport.port}\r\nCookie: ${transport.cookie.substringBefore(';')}\r\nOrigin: ${transport.origin}\r\nAuthorization: browser-bad\r\n")
                            if (websocket) append("Upgrade: websocket\r\nConnection: Upgrade\r\n") else append("Content-Length: 200000\r\nRange: bytes=1-2\r\n")
                            append("\r\n")
                        }.toByteArray())
                        if (!websocket) output.write(ByteArray(200000) { 7 })
                        val input = socket.getInputStream().buffered()
                        val head = HttpHead.read(input)
                        assertEquals(if (websocket) "101" else "206", head.target)
                        assertNull(head.single("set-cookie"))
                        if (websocket) { output.write(byteArrayOf(129.toByte())); assertEquals(129, input.read()); assertEquals(2, input.read()) }
                        assertEquals("ok", input.readBytes().toString(Charsets.UTF_8))
                    }
                    future.get()
                }
            }
        } finally { upstream.close(); executor.shutdownNow() }
    }
}
