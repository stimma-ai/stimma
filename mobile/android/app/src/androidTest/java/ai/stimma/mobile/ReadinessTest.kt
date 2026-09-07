package ai.stimma.mobile

import android.content.Intent
import android.content.pm.ActivityInfo
import android.content.res.Configuration
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.WebView
import androidx.lifecycle.Lifecycle
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import okio.Buffer
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/** A downloaded interface fixture exercises the real native bridge and WebView. */
class ReadinessTest {
    private val html = """
        <!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
        <body>Phone readiness fixture<audio></audio><iframe src="/api/provider-manage/test/"></iframe><script>
        window.initialPreference=localStorage.getItem('readiness-test');
        window.replies={};let sequence=0;
        stimmaAndroid.onmessage=e=>{const r=JSON.parse(e.data);replies[r.id]=r};
        window.native=(method,args={})=>{const id=++sequence;stimmaAndroid.postMessage(JSON.stringify({id,method,args}));return id};
        window.events=[];
        for(const name of ['app-active','media-interruption','transport-resumed'])
          window.addEventListener('stimma:'+name,e=>events.push([name,e.detail]));
        native('interfaceReady');
        </script></body>
    """.trimIndent()

    private fun fixture(work: (ActivityScenario<MainActivity>) -> Unit) {
        val panel = "<html><body>Provider controls<button>Manage</button></body></html>"
        val helpers = ProtocolTest()
        val archive = helpers.archive("index.html" to html)
        val manifest = helpers.manifest(archive, html.toByteArray().size)
        MockWebServer().use { server ->
            server.dispatcher = object : Dispatcher() {
                override fun dispatch(request: RecordedRequest): MockResponse = when {
                    request.path == "/api/mobile-ui/manifest" -> MockResponse().setBody(Buffer().write(manifest))
                    request.path?.startsWith("/api/mobile-ui/packages/") == true -> MockResponse().setBody(Buffer().write(archive))
                    request.path == "/api/provider-manage/test/" -> MockResponse().addHeader("Content-Type", "text/html").setBody(panel)
                    request.path == "/api/profiles" -> MockResponse().setBody("[]")
                    else -> MockResponse().setResponseCode(404)
                }
            }
            server.start()
            val context = InstrumentationRegistry.getInstrumentation().targetContext
            val intent = Intent(context, MainActivity::class.java).putExtra("localBackendPort", server.port)
            ActivityScenario.launch<MainActivity>(intent).use { scenario ->
                eventually { evaluate(scenario, "typeof window.native") == "\"function\"" }
                work(scenario)
            }
        }
    }

    private fun views(view: View): List<WebView> = when (view) {
        is WebView -> listOf(view)
        is ViewGroup -> (0 until view.childCount).flatMap { views(view.getChildAt(it)) }
        else -> emptyList()
    }
    private fun evaluate(scenario: ActivityScenario<MainActivity>, script: String): String {
        val results = LinkedBlockingQueue<String>()
        scenario.onActivity { activity ->
            views(activity.window.decorView).first { it.visibility == View.VISIBLE }.evaluateJavascript(script) { results.offer(it) }
        }
        return results.poll(5, TimeUnit.SECONDS) ?: error("No script result")
    }
    private fun eventually(ready: () -> Boolean) {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(20)
        while (!ready()) { check(System.nanoTime() < deadline) { "Timed out waiting for phone state" }; Thread.sleep(100) }
    }
    private fun command(scenario: ActivityScenario<MainActivity>, method: String, args: String = "{}") {
        val id = evaluate(scenario, "native('$method',$args)")
        eventually { evaluate(scenario, "Boolean(replies[$id])") == "true" }
        assertEquals("null", evaluate(scenario, "replies[$id].error"))
    }

    @Test fun rotationSleepBackAndProviderFramesKeepTheMountedPage() = fixture { scenario ->
        var original: MainActivity? = null
        scenario.onActivity { original = it; assertEquals(android.media.AudioManager.STREAM_MUSIC, it.volumeControlStream); assertEquals(ActivityInfo.SCREEN_ORIENTATION_PORTRAIT, it.requestedOrientation) }
        evaluate(scenario, "history.pushState({},'', '/board/test');window.draft='kept';window.drawer=true;window.addEventListener('keydown',e=>{if(e.key==='Escape'&&drawer){e.preventDefault();drawer=false}})")
        command(scenario, "setSlideshowActive", "{active:true}")
        command(scenario, "setKeepAwake", "{active:true}")
        scenario.onActivity {
            assertEquals(ActivityInfo.SCREEN_ORIENTATION_SENSOR, it.requestedOrientation)
            assertTrue(it.window.attributes.flags and WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON != 0)
            it.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
        }
        eventually {
            var landscape = false
            scenario.onActivity { landscape = it.resources.configuration.orientation == Configuration.ORIENTATION_LANDSCAPE }
            landscape
        }
        scenario.onActivity { assertSame(original, it) }
        assertEquals("\"kept\"", evaluate(scenario, "draft"))
        assertEquals("\"/board/test\"", evaluate(scenario, "location.pathname"))
        assertEquals("true", evaluate(scenario, "drawer"))
        eventually { evaluate(scenario, "Boolean(document.querySelector('iframe').contentDocument?.querySelector('button'))") == "true" }
        evaluate(scenario, "window.pauses=0;document.querySelector('audio').pause=()=>pauses++")
        scenario.moveToState(Lifecycle.State.CREATED)
        scenario.onActivity { assertEquals(0, it.window.attributes.flags and WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
        scenario.moveToState(Lifecycle.State.RESUMED)
        eventually { evaluate(scenario, "pauses>0 && events.some(e=>e[0]==='app-active'&&e[1]===false) && events.some(e=>e[0]==='app-active'&&e[1]===true)") == "true" }
        assertEquals("\"kept\"", evaluate(scenario, "draft"))
        scenario.onActivity { it.onBackPressedDispatcher.onBackPressed() }
        eventually { evaluate(scenario, "drawer") == "false" }
        assertEquals("\"/board/test\"", evaluate(scenario, "location.pathname"))
        command(scenario, "setKeepAwake", "{active:false}")
        scenario.onActivity { assertEquals(0, it.window.attributes.flags and WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
        command(scenario, "setSlideshowActive", "{active:false}")
        scenario.onActivity { assertEquals(ActivityInfo.SCREEN_ORIENTATION_PORTRAIT, it.requestedOrientation) }
        assertEquals("\"kept\"", evaluate(scenario, "draft"))
    }

    @Test fun cancellingShareDoesNotReportAnExportAndHeadphoneRemovalPausesMedia() = fixture { scenario ->
        evaluate(scenario, "window.pauses=0;document.querySelector('audio').pause=()=>pauses++")
        scenario.onActivity {
            // Android reserves this broadcast to the OS; exercise its registered
            // receiver directly without impersonating a hardware event.
            val field = MainActivity::class.java.getDeclaredField("events").apply { isAccessible = true }
            (field.get(it) as android.content.BroadcastReceiver).onReceive(it, Intent(android.media.AudioManager.ACTION_AUDIO_BECOMING_NOISY))
        }
        eventually { evaluate(scenario, "pauses>0 && events.some(e=>e[0]==='media-interruption')") == "true" }
        val id = evaluate(scenario, "native('share',{filename:'test.txt',bytes:[104,105]})")
        eventually { scenario.state != Lifecycle.State.RESUMED }
        InstrumentationRegistry.getInstrumentation().sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_BACK)
        eventually { scenario.state == Lifecycle.State.RESUMED }
        eventually { evaluate(scenario, "Boolean(replies[$id])") == "true" }
        assertEquals("false", evaluate(scenario, "replies[$id].result"))
        assertEquals("null", evaluate(scenario, "replies[$id].error"))
    }

    @Test fun preferencesRestoreBeforePageScriptsAcrossNewPortsAndStayIsolated() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        LocalPreferences(context, "emulator", "emulator").save(org.json.JSONObject())
        fixture { scenario ->
            evaluate(scenario, "localStorage.setItem('readiness-test','saved')")
            eventually { LocalPreferences(context, "emulator", "emulator").load().optString("readiness-test") == "saved" }
            evaluate(scenario, "location.reload()")
            eventually { evaluate(scenario, "window.initialPreference") == "\"saved\"" }
        }
        fixture { scenario -> assertEquals("\"saved\"", evaluate(scenario, "window.initialPreference")) }
        assertFalse(LocalPreferences(context, "another-account", "emulator").load().has("readiness-test"))
        assertFalse(LocalPreferences(context, "emulator", "another-server").load().has("readiness-test"))
        LocalPreferences(context, "emulator", "emulator").save(org.json.JSONObject())
    }
}
