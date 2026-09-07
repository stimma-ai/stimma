package ai.stimma.mobile

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID
import kotlin.coroutines.coroutineContext

class ShellModel(application: Application) : AndroidViewModel(application) {
    val auth = NativeAuth(application)
    val setup = MobileTransport { application.assets.open(it) }
    val updates = MutableStateFlow(0)
    val browserReturns = Channel<Unit>(Channel.CONFLATED)
    private val preferences = application.getSharedPreferences("connection", 0)
    val clientId = preferences.getString("client", null) ?: UUID.randomUUID().toString().also { preferences.edit().putString("client", it).apply() }
    private val cache = UIPackageCache(File(application.cacheDir, "ui-packages"))
    var main: MobileTransport? = null
        private set
    var devices = JSONArray()
        private set
    var selected: JSONObject? = null
        private set
    var busy = false
        private set
    var restoring = false
        private set
    var showConnections = true
    var message: String? = null
        private set
    var connectionState = "unreachable"
        private set
    private var operation: Job? = null
    private var health: Job? = null
    var transportRevision = 0
        private set
    private var generation = 0
    private var started = false
    private var appActive = false
    private val discoveryMutex = Mutex()
    private val healthMutex = Mutex()
    private var activeHash: String? = null
    var callback: AuthCallback? = null
        private set

    fun changed() { updates.value += 1 }
    fun info() = JSONObject().put("authenticated", auth.user != null).put("user", auth.user ?: JSONObject.NULL)
        .put("devices", devices).put("selectedDeviceId", selected?.optString("deviceId") ?: JSONObject.NULL)
        .put("busy", busy).put("restoring", restoring).put("message", message ?: JSONObject.NULL)

    fun start(debugPort: Int?) {
        if (started) return
        started = true
        launchOperation(restore = auth.hasSession || debugPort != null, holdRestore = true) {
            if (debugPort != null) {
                check(BuildConfig.DEBUG && debugPort in 1024..65535)
                val remote = PinnedServer("127.0.0.1", debugPort, null, debugLoopback = true)
                install(remote)
                selected = JSONObject().put("deviceId", "emulator").put("name", "Emulator test library")
                connectionState = "ready"
                showConnections = false
            } else if (auth.hasSession) {
                refreshDevices()
                val id = preferences.getString("selected", null)
                val device = roster().firstOrNull { it.getString("deviceId") == id }
                if (device != null) connect(device, false)
                else if (id != null) error("Saved server unavailable")
            }
        }
    }

    private fun launchOperation(restore: Boolean = false, recovering: Boolean = false, holdRestore: Boolean = false, work: suspend () -> Unit) {
        generation += 1
        val epoch = generation
        operation?.cancel()
        callback?.close(); callback = null
        busy = true; restoring = restore; message = null; changed()
        operation = viewModelScope.launch {
            try { work() }
            catch (error: CancellationException) { throw error }
            catch (error: Exception) {
                if (epoch == generation) {
                    message = when {
                        error is NativeAuthError -> error.message
                        error is UIPackageError -> error.message
                        error is RemoteHttpError && error.status == 404 -> "This server does not provide a mobile interface. Update your Stimma Server and try again."
                        else -> "Could not connect. Check your sign-in, server sharing, and network, then try again."
                    }
                    connectionState = "unreachable"
                    if (!recovering || main == null) showConnections = true
                }
            } finally {
                if (epoch == generation) {
                    busy = false
                    restoring = holdRestore && restore && main == null && preferences.contains("selected")
                    changed()
                }
            }
        }
    }

    fun cancelRestore() {
        generation += 1
        operation?.cancel(); callback?.close(); callback = null
        busy = false; restoring = false; showConnections = true; changed()
    }

    suspend fun refreshDevices(): JSONArray = discoveryMutex.withLock {
        if (!auth.hasSession) return@withLock devices
        val epoch = generation
        val roster = auth.devices()
        coroutineContext.ensureActive()
        check(epoch == generation) { "Discovery cancelled." }
        devices = JSONArray((0 until roster.length()).map { roster.getJSONObject(it) }.filter { it.optBoolean("serving") })
        changed()
        devices
    }

    fun refresh() { launchOperation { refreshDevices() } }
    private fun roster() = (0 until devices.length()).map { devices.getJSONObject(it) }
    fun select(id: String) {
        val device = roster().firstOrNull { it.getString("deviceId") == id } ?: error("Refresh the server list and try again.")
        launchOperation(restore = true) { connect(device, false) }
    }
    fun reload() {
        selected?.let { device -> launchOperation(restore = true) { connect(device, false) } } ?: refresh()
    }

    fun login(openBrowser: (String) -> Unit) {
        launchOperation {
            val listener = withContext(Dispatchers.IO) { AuthCallback() }
            callback = listener
            try {
                openBrowser("https://stimma.ai/auth/desktop-login?port=${listener.port}&state=${listener.state}&mode=sign-in")
                val code = awaitBrowserCode(listener)
                auth.exchange(code)
                refreshDevices()
            } finally { listener.close(); if (callback === listener) callback = null }
        }
    }

    internal suspend fun awaitBrowserCode(listener: AuthCallback): String {
        return try {
            withTimeout(300000) { listener.code.await() }.also { browserReturns.send(Unit) }
        } catch (_: TimeoutCancellationException) {
            browserReturns.send(Unit)
            throw NativeAuthError("Sign-in expired. Please sign in again.")
        }
    }

    fun logout() {
        disconnect()
        auth.logout()
        devices = JSONArray(); message = null; changed()
    }

    fun disconnect() {
        cancelRestore()
        preferences.edit().remove("selected").apply()
        main?.close(); main = null; selected = null; activeHash = null
        connectionState = "unreachable"; message = null; changed()
    }

    private suspend fun connect(initial: JSONObject, recovering: Boolean) {
        connectionState = "connecting"; changed()
        var device = initial
        if (recovering) {
            val refreshed = try { refreshDevices(); true }
            catch (error: CancellationException) { throw error }
            catch (_: Exception) { coroutineContext.ensureActive(); false }
            if (refreshed) device = roster().firstOrNull { it.getString("deviceId") == initial.getString("deviceId") } ?: error("Server no longer shared.")
        }
        val pin = device.getString("certFingerprint")
        val routes = device.getJSONArray("routes")
        val identity = device.getString("deviceId")
        val reachable = coroutineScope {
            val results = Channel<PinnedServer?>(Channel.UNLIMITED)
            val probes = (0 until routes.length()).map { index ->
                async(Dispatchers.IO) {
                    val result = runCatching {
                        val route = routes.getJSONObject(index)
                        val server = PinnedServer(route.getString("host"), route.getInt("port"), pin)
                        require(server.asyncJson("/multi-device/ping", timeoutSeconds = 5).getString("deviceId") == identity)
                        server
                    }.getOrNull()
                    results.trySend(result)
                }
            }
            var winner: PinnedServer? = null
            repeat(probes.size) {
                if (winner == null) winner = results.receive()
            }
            probes.forEach { it.cancel() }
            winner ?: error("No reachable server route.")
        }
        val token = auth.validToken()
        val session = withContext(Dispatchers.IO) {
            reachable.asyncJson("/multi-device/session", JSONObject().put("idToken", token).put("deviceId", clientId).body())
        }
        coroutineContext.ensureActive()
        check(session.getString("deviceId") == identity)
        val remote = PinnedServer(reachable.host, reachable.port, pin, session.getString("session"))
        if (recovering && main != null && activeHash != null && selected?.getString("deviceId") == identity) {
            main!!.interruptConnections()
            main!!.target = remote
            transportRevision += 1
        } else install(remote)
        selected = device
        preferences.edit().putString("selected", identity).apply()
        connectionState = "ready"; if (!recovering) showConnections = false; message = null; changed()
    }

    private suspend fun install(remote: PinnedServer) {
        val context = coroutineContext
        val manifest = remote.asyncBytes("/api/mobile-ui/manifest", 16384)
        val description = PackageManifest.parse(manifest)
        val protected = setOfNotNull(activeHash)
        val directory = withContext(Dispatchers.IO) { cache.cached(manifest, protected) { context.ensureActive() } } ?: run {
            val archive = remote.asyncBytes("/api/mobile-ui/packages/${description.hash}.tar.gz", description.bytes, timeoutSeconds = 120)
            withContext(Dispatchers.IO) {
                cache.resolve(manifest, protected, { context.ensureActive() }) { archive }
            }
        }
        coroutineContext.ensureActive()
        val next = MobileTransport { getApplication<Application>().assets.open(it) }
        next.directory = directory; next.target = remote
        next.setForeground(appActive)
        val previous = main
        main = next; activeHash = directory.parentFile!!.name
        previous?.close()
    }

    fun foreground(active: Boolean) {
        appActive = active
        main?.setForeground(active)
        health?.cancel(); health = null
        if (!active) return
        health = viewModelScope.launch {
            var resumed = false
            while (true) {
                val remote = main?.target
                if (!busy && remote != null) {
                    try {
                        healthMutex.withLock { remote.checkConnection() }
                        if (!resumed) { resumed = true; transportRevision += 1; changed() }
                        if (connectionState != "ready") { connectionState = "ready"; changed() }
                    } catch (error: CancellationException) { throw error }
                    catch (_: Exception) {
                        coroutineContext.ensureActive()
                        if (!busy && main?.target === remote && selected?.optString("deviceId") != "emulator") {
                            selected?.let { device -> launchOperation(recovering = true) { connect(device, true) } }
                        }
                    }
                }
                delay(20000)
            }
        }
    }

    override fun onCleared() { callback?.close(); setup.close(); main?.close() }
}
