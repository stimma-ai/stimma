package ai.stimma.mobile

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException
import java.util.Collections
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.Executors
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket

/**
 * Connection checks exercise the WebView's own path, and recovery runs as one
 * bounded sequence per generation.
 */
class TransportRecoveryTest {
    private val certificate = HeldCertificate.Builder().commonName("localhost").build()
    private val pin = sha256(certificate.certificate.encoded)
    private val servers = mutableListOf<MockWebServer>()
    private val transport = MobileTransport { "ok".byteInputStream() }
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    @After fun tearDown() {
        scope.cancel(); transport.close()
        servers.forEach { runCatching { it.shutdown() } }
    }

    private fun tlsServer(): MockWebServer = MockWebServer().also {
        it.useHttps(HandshakeCertificates.Builder().heldCertificate(certificate).build().sslSocketFactory(), false)
        it.start(); servers += it
    }

    private fun attach(server: MockWebServer, session: String = "native-session") =
        PinnedServer("127.0.0.1", server.port, pin, session).also { transport.target = it }

    // --- the WebView path ------------------------------------------------------------------

    @Test fun aHealthyPathIsCheckedThroughTheProxyWithTheSession() = runBlocking {
        val server = tlsServer()
        attach(server)
        server.enqueue(MockResponse().setBody("{\"status\":\"ok\"}"))
        assertEquals(PathHealth.HEALTHY, transport.checkConnection())
        val request = server.takeRequest()
        assertEquals(HEALTH_PATH, request.path)
        assertEquals("Bearer native-session", request.getHeader("Authorization"))
        // The same pooled upstream the WebView's requests use.
        assertEquals(1, transport.target!!.pooledConnections)
    }

    @Test fun aHealthyDirectRouteWithAFailedLocalProxyIsDetected() = runBlocking {
        val server = tlsServer()
        val remote = attach(server)
        repeat(4) { server.enqueue(MockResponse().setBody("{\"status\":\"ok\"}")) }
        // The direct route answers...
        remote.asyncBytes(HEALTH_PATH, 1024)
        // ...but a proxy that cannot serve the WebView is not healthy.
        transport.beforeServe = { throw IllegalStateException("proxy worker failed") }
        assertEquals(PathHealth.UNREACHABLE, transport.checkConnection())
        transport.beforeServe = null
        transport.setForeground(false)
        assertEquals(PathHealth.UNREACHABLE, transport.checkConnection())
        transport.setForeground(true)
        assertEquals(PathHealth.HEALTHY, transport.checkConnection())
        transport.stopListening()
        remote.asyncBytes(HEALTH_PATH, 1024)
        assertEquals(PathHealth.UNREACHABLE, transport.checkConnection())
        assertEquals(3, server.requestCount)
    }

    @Test fun anExpiredSessionIsToldApartFromAnOrdinaryRejectionAndFromANetworkFailure() = runBlocking {
        val server = tlsServer()
        attach(server)
        server.enqueue(MockResponse().setResponseCode(401).addHeader("X-Stimma-Session-Invalid", "1"))
        assertEquals(PathHealth.SESSION_EXPIRED, transport.checkConnection())
        // An application 401 without the gate's marker does not rotate the session.
        server.enqueue(MockResponse().setResponseCode(401))
        assertEquals(PathHealth.UNREACHABLE, transport.checkConnection())
        server.shutdown()
        assertEquals(PathHealth.UNREACHABLE, transport.checkConnection())
    }

    @Test fun olderServersWithoutTheHealthRouteAreCheckedThroughTheProfileList() = runBlocking {
        val server = tlsServer()
        attach(server)
        server.enqueue(MockResponse().setResponseCode(404))
        server.enqueue(MockResponse().setBody("[]"))
        server.enqueue(MockResponse().setBody("[]"))
        assertEquals(PathHealth.HEALTHY, transport.checkConnection())
        assertEquals(PathHealth.HEALTHY, transport.checkConnection())
        assertEquals(listOf(HEALTH_PATH, LEGACY_HEALTH_PATH, LEGACY_HEALTH_PATH), (0 until 3).map { server.takeRequest().path })
    }

    @Test fun aHungCheckEndsWithItsBudget() = runBlocking {
        val server = tlsServer()
        attach(server)
        server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))
        val started = System.nanoTime()
        assertEquals(PathHealth.UNREACHABLE, transport.checkConnection(timeoutMillis = 300))
        assertTrue(TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started) < 3000)
        // Cancellation closes the local socket instead of waiting on blocking I/O.
        server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))
        val cancelled = System.nanoTime()
        try { withTimeout(200) { transport.checkConnection(timeoutMillis = 30000) }; fail() } catch (_: TimeoutCancellationException) { }
        assertTrue(TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - cancelled) < 3000)
    }

    @Test fun aNetworkChangeEndsWebSocketTunnelsPromptly() {
        val upstream = ServerSocket(0, 8, InetAddress.getByName("127.0.0.1"))
        val executor = Executors.newSingleThreadExecutor()
        try {
            transport.target = PinnedServer("127.0.0.1", upstream.localPort, null, "native-session", true)
            val serverSide = executor.submit<Int> {
                upstream.accept().use { socket ->
                    socket.soTimeout = 5000
                    val input = socket.getInputStream().buffered()
                    HttpHead.read(input)
                    socket.getOutputStream().write("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n".toByteArray())
                    runCatching { input.read() }.getOrDefault(-1)
                }
            }
            Socket("127.0.0.1", transport.port).use { socket ->
                socket.soTimeout = 5000
                socket.getOutputStream().write(("GET /ws HTTP/1.1\r\nHost: 127.0.0.1:${transport.port}\r\nCookie: ${transport.cookie.substringBefore(';')}\r\n" +
                    "Origin: ${transport.origin}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n").toByteArray())
                val input = socket.getInputStream().buffered()
                assertEquals("101", HttpHead.read(input).target)
                transport.networkChanged()
                // The tunnel ends promptly instead of idling on a socket bound to the old network.
                assertEquals(-1, runCatching { input.read() }.getOrDefault(-1))
            }
            assertEquals(-1, serverSide.get(5, TimeUnit.SECONDS))
        } finally { upstream.close(); executor.shutdownNow() }
    }

    // --- one bounded sequence per generation ------------------------------------------------

    private class Recorder {
        val states: MutableList<Pair<RecoveryState, Boolean>> = Collections.synchronizedList(mutableListOf())
        val resumed get() = synchronized(states) { states.count { it.second } }
        val phases get() = synchronized(states) { states.map { it.first.phase } }
        fun last() = synchronized(states) { states.last().first }
    }

    private fun recovery(recorder: Recorder, probe: suspend () -> PathHealth, reconnect: suspend () -> Unit = {}) =
        TransportRecovery(scope, probe, reconnect, { state, resumed, _ -> recorder.states += state to resumed },
            probeBudgetMillis = 300, reconnectBudgetMillis = 800, retryDelaysMillis = listOf(30, 60))

    private fun waitFor(condition: () -> Boolean) {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5)
        while (!condition() && System.nanoTime() < deadline) Thread.sleep(5)
        assertTrue(condition())
    }

    @Test fun aShortOutageResumesOnceWithoutReconnecting() {
        val recorder = Recorder()
        val reconnects = AtomicInteger()
        val subject = recovery(recorder, { PathHealth.HEALTHY }, { reconnects.incrementAndGet() })
        subject.suspend()
        assertEquals(RecoveryPhase.CHECKING, subject.state.phase)
        subject.disrupted()
        waitFor { subject.state.phase == RecoveryPhase.READY }
        Thread.sleep(100)
        assertEquals(listOf(RecoveryPhase.CHECKING, RecoveryPhase.CHECKING, RecoveryPhase.READY), recorder.phases)
        assertEquals(1, recorder.resumed)
        assertEquals(0, reconnects.get())
        // Routine checks while ready stay silent.
        subject.routine(); Thread.sleep(100)
        assertEquals(3, recorder.states.size)
    }

    @Test fun anExpiredSessionIsReestablishedNotSentToSignIn() {
        val recorder = Recorder()
        val reconnects = AtomicInteger()
        val subject = recovery(recorder, { if (reconnects.get() == 0) PathHealth.SESSION_EXPIRED else PathHealth.HEALTHY }, { reconnects.incrementAndGet() })
        subject.disrupted()
        waitFor { subject.state.phase == RecoveryPhase.READY }
        assertEquals(listOf(RecoveryPhase.CHECKING, RecoveryPhase.RECONNECTING, RecoveryPhase.READY), recorder.phases)
        assertEquals(1, reconnects.get())
        assertEquals(1, recorder.resumed)
        assertEquals(1, recorder.states.map { it.first.generation }.distinct().size)
    }

    @Test fun aLongOutageRetriesWithinOneGenerationAndResumesOnce() {
        val recorder = Recorder()
        val up = AtomicBoolean(false)
        val reconnects = AtomicInteger()
        val subject = recovery(recorder, { if (up.get()) PathHealth.HEALTHY else PathHealth.UNREACHABLE },
            { reconnects.incrementAndGet(); if (!up.get()) throw IOException("no route") })
        subject.disrupted()
        waitFor { reconnects.get() >= 3 }
        assertEquals(RecoveryPhase.UNAVAILABLE, subject.state.phase)
        assertEquals(0, recorder.resumed)
        up.set(true)
        waitFor { subject.state.phase == RecoveryPhase.READY }
        Thread.sleep(150)
        assertEquals(1, recorder.resumed)
        assertEquals(1, recorder.states.map { it.first.generation }.distinct().size)
        assertFalse(subject.running)
    }

    @Test fun aRestartedServerThatKeptTheSessionIsNotReauthenticated() {
        val recorder = Recorder()
        val probes = AtomicInteger()
        val reconnects = AtomicInteger()
        // Down for the first check and the first reconnect, back before the retry.
        val subject = recovery(recorder, { if (probes.incrementAndGet() <= 1) PathHealth.UNREACHABLE else PathHealth.HEALTHY },
            { reconnects.incrementAndGet(); throw IOException("connection refused") })
        subject.disrupted()
        waitFor { subject.state.phase == RecoveryPhase.READY }
        assertEquals(1, reconnects.get())
        assertEquals(1, recorder.resumed)
    }

    @Test fun aHalfOpenPathThatNeverAnswersIsBoundedByTheBudget() {
        val recorder = Recorder()
        val reconnects = AtomicInteger()
        val subject = recovery(recorder, { if (reconnects.get() == 0) awaitCancellation() else PathHealth.HEALTHY }, { reconnects.incrementAndGet() })
        val started = System.nanoTime()
        subject.disrupted()
        waitFor { subject.state.phase == RecoveryPhase.READY }
        assertTrue(TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started) < 2000)
        assertEquals(listOf(RecoveryPhase.CHECKING, RecoveryPhase.RECONNECTING, RecoveryPhase.READY), recorder.phases)
    }

    @Test fun aNetworkHandoffSupersedesTheCheckInProgress() = runBlocking {
        val recorder = Recorder()
        val calls = AtomicInteger()
        // The first check is on the network being left: slow, and it would fail.
        val subject = recovery(recorder, { if (calls.incrementAndGet() == 1) { delay(250); PathHealth.UNREACHABLE } else PathHealth.HEALTHY })
        subject.disrupted()
        delay(50)
        subject.disrupted()
        waitFor { subject.state.phase == RecoveryPhase.READY }
        delay(400)
        assertEquals(listOf(RecoveryPhase.CHECKING, RecoveryPhase.CHECKING, RecoveryPhase.READY), recorder.phases)
        assertEquals(1, recorder.resumed)
        assertEquals(2, recorder.last().generation)
    }

    @Test fun backgroundingCancelsRecoveryAndAFailedRoutineCheckOpensAGeneration() = runBlocking {
        val recorder = Recorder()
        val health = AtomicReference(PathHealth.UNREACHABLE)
        val subject = recovery(recorder, { health.get() }, { throw IOException("down") })
        subject.disrupted()
        waitFor { subject.state.phase == RecoveryPhase.UNAVAILABLE }
        subject.suspend()
        assertFalse(subject.running)
        val before = recorder.states.size
        delay(200)
        assertEquals(before, recorder.states.size)
        health.set(PathHealth.HEALTHY)
        subject.disrupted()
        waitFor { subject.state.phase == RecoveryPhase.READY }
        val ready = subject.state.generation
        health.set(PathHealth.UNREACHABLE)
        subject.routine()
        waitFor { subject.state.phase == RecoveryPhase.RECONNECTING || subject.state.phase == RecoveryPhase.UNAVAILABLE }
        assertEquals(ready + 1, subject.state.generation)
    }

    @Test fun aRevokedSignInStopsRetryingInsteadOfLoopingForever() {
        val recorder = Recorder()
        val reconnects = AtomicInteger()
        val failures = Collections.synchronizedList(mutableListOf<Exception?>())
        val subject = TransportRecovery(scope, { PathHealth.SESSION_EXPIRED },
            { reconnects.incrementAndGet(); throw NativeAuthError("Please sign in.") },
            { state, resumed, failure -> recorder.states += state to resumed; failures += failure },
            probeBudgetMillis = 300, reconnectBudgetMillis = 800, retryDelaysMillis = listOf(20),
            terminal = { it is NativeAuthError })
        subject.disrupted()
        waitFor { subject.state.phase == RecoveryPhase.UNAVAILABLE }
        Thread.sleep(200)
        assertEquals(1, reconnects.get())
        assertFalse(subject.running)
        assertTrue(failures.last() is NativeAuthError)
        // A network failure, by contrast, keeps retrying.
        val retries = AtomicInteger()
        val network = TransportRecovery(scope, { PathHealth.UNREACHABLE }, { retries.incrementAndGet(); throw IOException("down") },
            { _, _, _ -> }, probeBudgetMillis = 300, reconnectBudgetMillis = 800, retryDelaysMillis = listOf(20),
            terminal = { it is NativeAuthError })
        network.disrupted()
        waitFor { retries.get() >= 3 }
        assertTrue(network.running)
    }

    @Test fun retryDelaysAreJitteredWithinTheirStep() {
        val low = TransportRecovery(scope, { PathHealth.HEALTHY }, {}, { _, _, _ -> }, random = { 0.0 })
        val high = TransportRecovery(scope, { PathHealth.HEALTHY }, {}, { _, _, _ -> }, random = { 0.999 })
        val steps = TransportRecovery.RETRY_DELAYS_MILLIS
        for (attempt in 0..6) {
            val step = steps[minOf(attempt, steps.size - 1)]
            assertEquals(step / 2, low.retryDelay(attempt))
            assertTrue(high.retryDelay(attempt) in (step * 9 / 10)..step)
        }
    }

    @Test fun losingTheNetworkWithoutASuccessorAndItsReturnEachStartRecovery() {
        val disruptions = AtomicInteger()
        val watch = NetworkChangeTracker<String> { disruptions.incrementAndGet() }
        watch.available("wifi")
        assertEquals("the network the app started on is not a change", 0, disruptions.get())
        watch.available("wifi")
        assertEquals("a repeated report of the same network is not a change", 0, disruptions.get())
        watch.lost("cellular")
        assertEquals("losing a network that is not the default changes nothing", 0, disruptions.get())
        watch.lost("wifi")
        assertEquals("losing the default network with no successor disrupts at once", 1, disruptions.get())
        watch.lost("wifi")
        assertEquals(1, disruptions.get())
        watch.available("wifi")
        assertEquals("the same network returning disrupts again", 2, disruptions.get())
        watch.available("cellular")
        assertEquals("a handoff to another network disrupts", 3, disruptions.get())
    }

    @Test fun oneNetworkChangeEvictsIdleConnectionsAndEndsTunnels() {
        val server = tlsServer()
        val remote = attach(server)
        server.enqueue(MockResponse().setBody("{}"))
        server.enqueue(MockResponse().withWebSocketUpgrade(object : okhttp3.WebSocketListener() {}))
        assertEquals(PathHealth.HEALTHY, runBlocking { transport.checkConnection() })
        // The probe returns once it has the answer's head; its connection goes back to the pool
        // when the proxy finishes the exchange, so wait for that rather than assume it.
        waitFor { remote.pooledConnections == 1 }
        Socket("127.0.0.1", transport.port).use { socket ->
            socket.soTimeout = 5000
            socket.getOutputStream().write(("GET /ws HTTP/1.1\r\nHost: 127.0.0.1:${transport.port}\r\nCookie: ${transport.cookie.substringBefore(';')}\r\n" +
                "Origin: ${transport.origin}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n").toByteArray())
            val input = socket.getInputStream().buffered()
            assertEquals("101", HttpHead.read(input).target)
            transport.networkChanged()
            // Both what the old network carried are gone: the idle pooled connection and the tunnel.
            assertEquals(-1, runCatching { input.read() }.getOrDefault(-1))
            waitFor { remote.pooledConnections == 0 }
        }
    }

    @Test fun thePagesOwnUpgradeEndsACheckEarlyAndReadyStillComesOnce() = runBlocking {
        val recorder = Recorder()
        val probeFinished = AtomicInteger()
        val health = AtomicReference(PathHealth.HEALTHY)
        val subject = recovery(recorder, { delay(150); probeFinished.incrementAndGet(); health.get() })
        subject.disrupted()
        subject.pathProven()
        assertEquals(RecoveryPhase.READY, subject.state.phase)
        delay(300)
        assertEquals("the slower check was cancelled", 0, probeFinished.get())
        assertEquals(listOf(RecoveryPhase.CHECKING, RecoveryPhase.READY), recorder.phases)
        assertEquals(1, recorder.resumed)
        // Outside a check it changes nothing: ready stays ready, reconnecting confirms itself.
        subject.pathProven()
        health.set(PathHealth.SESSION_EXPIRED)
        subject.disrupted()
        waitFor { subject.state.phase == RecoveryPhase.RECONNECTING }
        val before = recorder.states.size
        subject.pathProven()
        assertEquals(RecoveryPhase.RECONNECTING, subject.state.phase)
        assertEquals(before, recorder.states.size)
    }

    @Test fun aCheckThatFinishesAfterTheUpgradeProvedThePathIsIgnored() {
        val recorder = Recorder()
        val release = java.util.concurrent.CountDownLatch(1)
        // A check that will come back failed after the page's socket already proved the path.
        val subject = recovery(recorder, { kotlinx.coroutines.runInterruptible { release.await() }; PathHealth.UNREACHABLE })
        subject.disrupted()
        Thread.sleep(50)
        subject.pathProven()
        release.countDown()
        Thread.sleep(200)
        assertEquals(listOf(RecoveryPhase.CHECKING, RecoveryPhase.READY), recorder.phases)
    }

    @Test fun aSuccessfulUpgradeThroughTheProxyReportsThePathProven() {
        val upstream = ServerSocket(0, 8, InetAddress.getByName("127.0.0.1"))
        val executor = Executors.newSingleThreadExecutor()
        val proven = AtomicInteger()
        transport.tunnelOpened = { proven.incrementAndGet() }
        try {
            transport.target = PinnedServer("127.0.0.1", upstream.localPort, null, "native-session", true)
            for (status in listOf("401 Unauthorized", "101 Switching Protocols")) {
                val serverSide = executor.submit {
                    upstream.accept().use { socket ->
                        socket.soTimeout = 5000
                        HttpHead.read(socket.getInputStream().buffered())
                        socket.getOutputStream().write("HTTP/1.1 $status\r\n${if (status.startsWith("101")) "Upgrade: websocket\r\nConnection: Upgrade\r\n" else "Content-Length: 0\r\n"}\r\n".toByteArray())
                        socket.getOutputStream().flush()
                        Thread.sleep(200)
                    }
                }
                Socket("127.0.0.1", transport.port).use { socket ->
                    socket.soTimeout = 5000
                    socket.getOutputStream().write(("GET /ws HTTP/1.1\r\nHost: 127.0.0.1:${transport.port}\r\nCookie: ${transport.cookie.substringBefore(';')}\r\n" +
                        "Origin: ${transport.origin}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n").toByteArray())
                    assertEquals(status.substringBefore(' '), HttpHead.read(socket.getInputStream().buffered()).target)
                }
                serverSide.get(5, TimeUnit.SECONDS)
                assertEquals(if (status.startsWith("101")) 1 else 0, proven.get())
            }
        } finally { upstream.close(); executor.shutdownNow() }
    }

    @Test fun nativeTimingMatchesTheSharedContract() {
        val contract = JSONObject(javaClass.getResourceAsStream("/transport-recovery.json")!!.reader().readText())
        assertEquals(HEALTH_PATH, contract.getString("healthPath"))
        assertEquals(LEGACY_HEALTH_PATH, contract.getString("legacyHealthPath"))
        val budgets = contract.getJSONObject("budgetsMs")
        assertEquals(TransportRecovery.PROBE_BUDGET_MILLIS, budgets.getLong("checking"))
        assertEquals(TransportRecovery.RECONNECT_BUDGET_MILLIS, budgets.getLong("reconnecting"))
        val phases = contract.getJSONObject("phases")
        assertEquals(RecoveryPhase.entries.map { it.wire }.toSet(), phases.keys().asSequence().toSet())
        for (phase in RecoveryPhase.entries) assertEquals(phase.connectionState, phases.getJSONObject(phase.wire).getString("connectionState"))
        val state = RecoveryState(3, RecoveryPhase.CHECKING, 5000).toJson()
        assertEquals(setOf("generation", "phase", "budgetMs"), state.keys().asSequence().toSet())
    }
}
