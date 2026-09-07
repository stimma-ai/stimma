package ai.stimma.mobile

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.IntentFilter
import android.content.pm.ActivityInfo
import android.media.AudioManager
import android.view.WindowManager
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.webkit.CookieManager
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.browser.customtabs.CustomTabsIntent
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID

class MainActivity : ComponentActivity() {
    private val model: ShellModel by viewModels()
    private lateinit var root: FrameLayout
    private lateinit var cover: LinearLayout
    private lateinit var waiting: LinearLayout
    private lateinit var setupView: WebView
    private var mainView: WebView? = null
    private var mainTransport: MobileTransport? = null
    private val ready = mutableSetOf<WebView>()
    private var coverEpoch = 0
    private var recreatingRenderer = false
    private var showingConnections = true
    private var transportRevision = -1
    private var foreground = false
    private var slideshowActive = false
    private var keepAwake = false
    private var shareResult: CompletableDeferred<Boolean>? = null
    private val shareAction by lazy { "$packageName.SHARE_SELECTED.${UUID.randomUUID()}" }
    private val events = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.action) {
                shareAction -> shareResult?.complete(true)
                AudioManager.ACTION_AUDIO_BECOMING_NOISY -> pauseMedia(interruption = true)
            }
        }
    }
    private var eventsRegistered = false
    private val sharePicker = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        val result = shareResult
        // Selection arrives via IntentSender; RESULT_OK is not a delivery receipt.
        lifecycleScope.launch { delay(300); result?.complete(false) }
    }
    private var picker: ValueCallback<Array<Uri>>? = null
    private val filePicker = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        picker?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data)); picker = null
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        ContextCompat.registerReceiver(this, events,
            IntentFilter(shareAction).apply { addAction(AudioManager.ACTION_AUDIO_BECOMING_NOISY) },
            ContextCompat.RECEIVER_NOT_EXPORTED)
        eventsRegistered = true
        root = FrameLayout(this).apply { setBackgroundColor(BACKGROUND) }
        setContentView(root)
        ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout() or WindowInsetsCompat.Type.ime())
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER) ||
            !WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
            root.addView(TextView(this).apply { setText(R.string.update_webview); setTextColor(Color.WHITE) })
            return
        }
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        cover = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER; setBackgroundColor(BACKGROUND)
            addView(ProgressBar(this@MainActivity), LinearLayout.LayoutParams(72, 72))
        }
        waiting = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER; visibility = View.INVISIBLE
            addView(TextView(this@MainActivity).apply { setText(R.string.connecting); setTextColor(Color.LTGRAY); gravity = Gravity.CENTER })
            addView(Button(this@MainActivity).apply {
                setText(R.string.choose_server)
                setOnClickListener { model.cancelRestore(); ready.add(setupView); render() }
            })
        }
        cover.addView(waiting)
        setupView = createWebView(model.setup, "/mobile.html")
        root.addView(setupView, fullSize())
        root.addView(cover, fullSize())
        showCover()
        val debugPort = if (BuildConfig.DEBUG && android.os.Build.HARDWARE in setOf("ranchu", "goldfish")) intent.getIntExtra("localBackendPort", 0).takeIf { it != 0 } else null
        model.start(debugPort)
        lifecycleScope.launch { model.updates.collect { render() } }
        lifecycleScope.launch {
            for (returned in model.browserReturns) {
                startActivity(Intent(this@MainActivity, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP))
            }
        }
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                val view = if (model.showConnections) setupView else mainView
                when {
                    model.restoring -> model.cancelRestore()
                    model.showConnections && mainView != null -> { model.showConnections = false; model.changed() }
                    view != null && !model.showConnections -> view.evaluateJavascript(
                        """(()=>{const layer=Boolean(document.querySelector('[data-modal-layer]'));const event=new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true});window.dispatchEvent(event);return layer||event.defaultPrevented})()"""
                    ) { consumed ->
                        if (consumed != "true" && view === mainView && !model.showConnections) {
                            if (view.canGoBack()) view.goBack()
                            else moveTaskToBack(true)
                        }
                    }
                    view?.canGoBack() == true -> view.goBack()
                    else -> moveTaskToBack(true)
                }
            }
        })
    }

    private fun fullSize() = FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT)
    private fun showCover() {
        if (cover.visibility == View.VISIBLE && coverEpoch > 0) return
        cover.visibility = View.VISIBLE; waiting.visibility = View.INVISIBLE
        val epoch = ++coverEpoch
        lifecycleScope.launch { delay(4500); if (epoch == coverEpoch && cover.visibility == View.VISIBLE) waiting.visibility = View.VISIBLE }
    }
    private fun render() {
        if (!::setupView.isInitialized) return
        if (model.main !== mainTransport) {
            slideshowActive = false; keepAwake = false
            mainTransport?.let { CookieManager.getInstance().setCookie(it.origin, "${it.cookieName}=; Max-Age=0; Path=/", null) }
            mainView?.let { ready.remove(it); root.removeView(it); it.destroy() }
            mainTransport = model.main
            mainView = model.main?.let { createWebView(it, "/").also { view -> root.addView(view, 0, fullSize()) } }
        }
        if (showingConnections != model.showConnections) {
            showingConnections = model.showConnections
            if (showingConnections) pauseMedia()
            else mainView?.evaluateJavascript("window.dispatchEvent(new CustomEvent('stimma:app-active',{detail:$foreground}))", null)
        }
        applyPresentationPolicy()
        setupView.visibility = if (model.showConnections) View.VISIBLE else View.GONE
        mainView?.visibility = if (model.showConnections) View.GONE else View.VISIBLE
        val visible = if (model.showConnections) setupView else mainView
        if (model.restoring || visible !in ready) showCover()
        else { cover.visibility = View.GONE; coverEpoch += 1 }
        mainView?.evaluateJavascript("window.dispatchEvent(new CustomEvent('stimma:connection-state',{detail:${JSONObject.quote(model.connectionState)}}))", null)
        if (transportRevision != model.transportRevision) {
            transportRevision = model.transportRevision
            mainView?.evaluateJavascript("window.dispatchEvent(new Event('stimma:transport-resumed'))", null)
        }
        setupView.evaluateJavascript("window.dispatchEvent(new Event('stimma:connection-info'))", null)
    }

    private fun createWebView(transport: MobileTransport, path: String): WebView {
        check(WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER))
        val view = WebView(this)
        view.setBackgroundColor(BACKGROUND)
        view.settings.apply {
            javaScriptEnabled = true; domStorageEnabled = true
            allowFileAccess = false; allowContentAccess = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            setSupportMultipleWindows(false)
            mediaPlaybackRequiresUserGesture = true
        }
        CookieManager.getInstance().setAcceptThirdPartyCookies(view, false)
        WebViewCompat.addWebMessageListener(view, "stimmaAndroid", setOf(transport.origin)) { source, message, origin, mainFrame, reply ->
            if (!mainFrame || origin.toString() != transport.origin || source !== view || !isAppDocument(source.url) || source.url?.let { Uri.parse(it).let { url -> "${url.scheme}://${url.encodedAuthority}" } } != transport.origin) return@addWebMessageListener
            val request = runCatching { JSONObject(message.data ?: "") }.getOrNull() ?: return@addWebMessageListener
            val id = request.optLong("id", -1)
            if (id < 0) return@addWebMessageListener
            lifecycleScope.launch {
                val response = JSONObject().put("id", id)
                try {
                    val result = command(view, request.getString("method"), request.optJSONObject("args") ?: JSONObject())
                    response.put("result", result ?: JSONObject.NULL)
                } catch (_: Exception) { response.put("error", "The mobile request could not be completed. Please try again.") }
                if (WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) reply.postMessage(response.toString())
            }
        }
        if (transport !== model.setup) {
            val preferences = LocalPreferences(this, model.auth.user?.getString("id") ?: "emulator", model.selected!!.getString("deviceId"))
            var bootstrap = WebViewCompat.addDocumentStartJavaScript(view, preferences.script(transport.origin), setOf(transport.origin))
            WebViewCompat.addWebMessageListener(view, "stimmaPreferences", setOf(transport.origin)) { source, message, origin, mainFrame, _ ->
                if (mainFrame && source === view && isAppDocument(source.url) && origin.toString() == transport.origin &&
                    source.url?.let { sameOrigin(Uri.parse(it), transport) } == true) {
                    runCatching {
                        preferences.save(JSONObject(message.data ?: "{}"))
                        bootstrap.remove()
                        bootstrap = WebViewCompat.addDocumentStartJavaScript(view, preferences.script(transport.origin), setOf(transport.origin))
                    }
                }
            }
        }
        view.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (!request.isForMainFrame && (request.url.scheme == "blob" || sameOrigin(request.url, transport))) return false
                if (request.isForMainFrame && sameOrigin(request.url, transport) && request.url.path.let { it == "/index.html" || it == "/mobile.html" || it == "/" || it?.startsWith("/api/") == false && !it.orEmpty().substringAfterLast('/').contains('.') }) return false
                if (request.isForMainFrame && request.hasGesture() && request.url.scheme in setOf("http", "https")) openExternal(request.url.toString())
                return true
            }
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                if (!sameOrigin(request.url, transport)) return blocked()
                return null
            }
            override fun onReceivedSslError(view: WebView, handler: android.webkit.SslErrorHandler, error: android.net.http.SslError) { handler.cancel() }
            override fun onRenderProcessGone(view: WebView, detail: android.webkit.RenderProcessGoneDetail): Boolean {
                root.removeView(view)
                ready.remove(view)
                view.destroy()
                if (!recreatingRenderer) { recreatingRenderer = true; root.post { recreate() } }
                return true
            }
        }
        view.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(webView: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                picker?.onReceiveValue(null); picker = callback
                return try { filePicker.launch(params.createIntent()); true } catch (_: Exception) { picker = null; false }
            }
        }
        CookieManager.getInstance().setCookie(transport.origin, transport.cookie) { accepted ->
            if (accepted) view.loadUrl(transport.origin + path)
        }
        return view
    }

    private fun isAppDocument(url: String?): Boolean {
        val path = url?.let { Uri.parse(it).path } ?: return false
        return !Regex("^/(api|ws|assets)(/|$)").containsMatchIn(path)
    }
    private fun sameOrigin(uri: Uri, transport: MobileTransport) = uri.scheme == "http" && uri.host == "127.0.0.1" && uri.port == transport.port && uri.userInfo == null
    private fun blocked() = WebResourceResponse("text/plain", "utf-8", 403, "Forbidden", emptyMap(), "Blocked".byteInputStream())
    private fun openExternal(value: String) {
        val uri = Uri.parse(value)
        require(uri.scheme in setOf("https", "http") && uri.host != null && uri.userInfo == null)
        CustomTabsIntent.Builder().build().launchUrl(this, uri)
    }

    private suspend fun command(view: WebView, method: String, args: JSONObject): Any? = when (method) {
        "interfaceReady" -> { ready.add(view); render(); null }
        "setSlideshowActive" -> {
            require(view === mainView && !model.showConnections)
            slideshowActive = args.getBoolean("active")
            if (!slideshowActive) keepAwake = false
            applyPresentationPolicy(); null
        }
        "setKeepAwake" -> {
            require(view === mainView && !model.showConnections)
            keepAwake = args.getBoolean("active")
            applyPresentationPolicy(); null
        }
        "connectionInfo" -> model.info()
        "cancelRestore" -> { model.cancelRestore(); model.info() }
        "signIn" -> { model.login(::openExternal); model.info() }
        "refreshDevices" -> model.refreshDevices()
        "selectServer" -> { model.select(args.getString("deviceId")); "connecting" }
        "showConnections" -> { model.showConnections = true; model.changed(); null }
        "closeConnections" -> { if (mainView != null) model.showConnections = false; model.changed(); null }
        "reload" -> { model.reload(); null }
        "logout" -> { model.logout(); null }
        "disconnect" -> { model.disconnect(); null }
        "getState" -> JSONObject().put("activeDeviceId", model.selected?.optString("deviceId") ?: "none")
            .put("connectionState", model.connectionState).put("localDeviceId", model.clientId).put("devices", model.devices)
        "authStatus" -> JSONObject().put("ok", true).put("status", 200).put("data", JSONObject()
            .put("authenticated", model.auth.user != null).put("privacy_lockdown", false).put("user", model.auth.user ?: JSONObject.NULL))
        "openExternal" -> { openExternal(args.getString("url")); null }
        "share" -> {
            check(shareResult == null) { "A share sheet is already open." }
            val bytes = args.getJSONArray("bytes")
            require(bytes.length() <= 64 * 1024 * 1024)
            val name = args.getString("filename")
            require(name.isNotBlank() && name.length <= 255 && name !in setOf(".", "..") && name.none { it == '/' || it == '\\' || it.code < 32 })
            val file = withContext(Dispatchers.IO) {
                val root = File(cacheDir, "exports").apply { mkdirs() }
                root.listFiles().orEmpty().filter { it.lastModified() < System.currentTimeMillis() - 86400000 }.forEach { it.deleteRecursively() }
                val file = File(File(root, UUID.randomUUID().toString()).apply { mkdirs() }, name)
                file.outputStream().buffered().use { output -> for (index in 0 until bytes.length()) { val value = bytes.getInt(index); require(value in 0..255); output.write(value) } }
                file
            }
            val uri = FileProvider.getUriForFile(this, "$packageName.exports", file)
            val result = CompletableDeferred<Boolean>()
            shareResult = result
            val selected = PendingIntent.getBroadcast(this, 0, Intent(shareAction).setPackage(packageName),
                PendingIntent.FLAG_CANCEL_CURRENT or PendingIntent.FLAG_MUTABLE)
            var handedOff = false
            try {
                sharePicker.launch(Intent.createChooser(Intent(Intent.ACTION_SEND).setType(contentResolver.getType(uri) ?: "application/octet-stream")
                    .putExtra(Intent.EXTRA_STREAM, uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION), "Share", selected.intentSender))
                handedOff = withTimeoutOrNull(600000) { result.await() } ?: false
                handedOff
            } finally {
                selected.cancel()
                shareResult = null
                if (!handedOff) withContext(Dispatchers.IO) { file.parentFile?.deleteRecursively() }
            }
        }
        else -> error("Unsupported native command.")
    }

    private fun applyPresentationPolicy() {
        val presenting = mainView != null && !model.showConnections
        val orientation = if (presenting && slideshowActive) ActivityInfo.SCREEN_ORIENTATION_SENSOR
            else ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
        if (requestedOrientation != orientation) requestedOrientation = orientation
        if (foreground && presenting && slideshowActive && keepAwake) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    private fun pauseMedia(interruption: Boolean = false) {
        val event = if (interruption) "stimma:media-interruption" else "stimma:app-active"
        val script = "document.querySelectorAll('audio,video').forEach(media=>media.pause());window.dispatchEvent(new CustomEvent('$event',{detail:false}))"
        if (::setupView.isInitialized) setupView.evaluateJavascript(script, null)
        mainView?.evaluateJavascript(script, null)
    }

    override fun onResume() {
        super.onResume()
        foreground = true
        if (::setupView.isInitialized) setupView.onResume()
        mainView?.onResume()
        mainView?.evaluateJavascript("window.dispatchEvent(new CustomEvent('stimma:app-active',{detail:${!model.showConnections}}))", null)
        applyPresentationPolicy()
        model.foreground(true)
    }
    override fun onPause() {
        foreground = false
        pauseMedia()
        if (::setupView.isInitialized) setupView.onPause()
        mainView?.onPause()
        applyPresentationPolicy()
        model.foreground(false)
        super.onPause()
    }
    override fun onDestroy() {
        shareResult?.complete(false)
        if (eventsRegistered) unregisterReceiver(events)
        picker?.onReceiveValue(null); picker = null
        if (::setupView.isInitialized) setupView.destroy()
        mainView?.destroy()
        super.onDestroy()
    }
    companion object { private val BACKGROUND = Color.rgb(11, 14, 20) }
}
