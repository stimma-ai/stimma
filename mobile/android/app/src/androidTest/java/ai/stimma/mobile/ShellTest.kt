package ai.stimma.mobile

import android.content.Intent
import android.net.Uri
import android.view.View
import android.view.ViewGroup
import android.webkit.WebView
import androidx.browser.customtabs.CustomTabsIntent
import androidx.test.core.app.ActivityScenario
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.lifecycleScope
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import org.junit.Assert.*
import org.junit.Test
import org.junit.Assume.assumeTrue
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.net.InetAddress
import java.net.ServerSocket
import java.net.SocketTimeoutException

class ShellTest {
    @Test fun downloadedInterfaceOpensLibraryAndKeepsPageOnResume() {
        val port = InstrumentationRegistry.getArguments().getString("localBackendPort")?.toIntOrNull()
        assumeTrue("Supply an isolated backend with --local-backend-port", port != null)
        runBlocking { PinnedServer("127.0.0.1", port!!, null, debugLoopback = true).checkConnection() }
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val intent = Intent(context, MainActivity::class.java).putExtra("localBackendPort", port!!)
        ActivityScenario.launch<MainActivity>(intent).use { scenario ->
            val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(30)
            var text = ""
            while (System.nanoTime() < deadline) {
                text = evaluate(scenario, "document.body.innerText")
                if (text.contains("Assets")) break
                Thread.sleep(200)
            }
            assertTrue(text, text.contains("Assets"))
            evaluate(scenario, "document.querySelector('a[href=\"/browse\"]')?.click()")
            Thread.sleep(1000)
            assertEquals("\"/browse\"", evaluate(scenario, "window.location.pathname"))
            val mediaDeadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5)
            var mediaLoaded = "false"
            while (System.nanoTime() < mediaDeadline && mediaLoaded != "true") {
                mediaLoaded = evaluate(scenario, "Array.from(document.images).some(image=>image.src.includes('/api/')&&image.complete&&image.naturalWidth>0)")
                if (mediaLoaded != "true") Thread.sleep(100)
            }
            assertEquals("true", mediaLoaded)
            evaluate(scenario, "window.stimmaResumeCheck='draft-kept'")
            scenario.moveToState(androidx.lifecycle.Lifecycle.State.CREATED)
            scenario.moveToState(androidx.lifecycle.Lifecycle.State.RESUMED)
            assertEquals("\"draft-kept\"", evaluate(scenario, "window.stimmaResumeCheck"))
            assertEquals("\"\"", evaluate(scenario, "document.cookie"))
        }
    }
    private fun webViews(view: View): List<WebView> {
        if (view is WebView) return listOf(view)
        if (view !is ViewGroup) return emptyList()
        return (0 until view.childCount).flatMap { webViews(view.getChildAt(it)) }
    }
    private fun evaluate(scenario: ActivityScenario<MainActivity>, script: String): String {
        val result = LinkedBlockingQueue<String>()
        scenario.onActivity { activity ->
            val view = webViews(activity.window.decorView).first { it.visibility == View.VISIBLE }
            view.evaluateJavascript(script) { result.offer(it) }
        }
        return result.poll(5, TimeUnit.SECONDS) ?: error("No WebView result")
    }

    @Test fun welcomeBridgeAndNativeStorageSurviveActivityRecreation() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val credentials = SecureCredentials(context, "instrumentation-dummy")
        try {
            credentials.write("first-dummy")
            assertEquals("first-dummy", SecureCredentials(context, "instrumentation-dummy").read())
            credentials.write("second-dummy")
            assertEquals("second-dummy", SecureCredentials(context, "instrumentation-dummy").read())
            val stored = java.io.File(context.noBackupFilesDir, "instrumentation-dummy.enc").readBytes()
            assertFalse(stored.toString(Charsets.ISO_8859_1).contains("dummy"))
            ActivityScenario.launch(MainActivity::class.java).use { scenario ->
                val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(20)
                var text = ""
                while (System.nanoTime() < deadline) {
                    text = evaluate(scenario, "document.body.innerText")
                    if (text.contains("Sign in")) break
                    Thread.sleep(200)
                }
                assertTrue(text, text.contains("Sign in"))
                assertEquals("\"\"", evaluate(scenario, "document.cookie"))
                assertEquals("\"object\"", evaluate(scenario, "typeof window.stimmaAndroid"))
                evaluate(scenario, """
                    window.stimmaFrameLoaded=false; window.stimmaFrameReply=false;
                    window.stimmaFrame=document.createElement('iframe');
                    window.stimmaFrame.sandbox='allow-same-origin';
                    window.stimmaFrame.onload=()=>{
                        window.stimmaFrameLoaded=true;
                        const port=window.stimmaFrame.contentWindow.stimmaAndroid;
                        if(port){port.onmessage=()=>{window.stimmaFrameReply=true};
                            port.postMessage(JSON.stringify({id:999999,method:'connectionInfo',args:{}}));}
                    };
                    window.stimmaFrame.src=URL.createObjectURL(new Blob(['<html><body>Generated frame</body></html>'],{type:'text/html'}));
                    document.body.appendChild(window.stimmaFrame);
                """.trimIndent())
                Thread.sleep(500)
                assertEquals("true", evaluate(scenario, "window.stimmaFrameLoaded"))
                assertEquals("false", evaluate(scenario, "window.stimmaFrameReply"))
                ServerSocket(0, 8, InetAddress.getByName("127.0.0.1")).use { otherPort ->
                    otherPort.soTimeout = 1200
                    evaluate(scenario, """
                        fetch('http://127.0.0.1:${otherPort.localPort}/cookie',{credentials:'include'}).catch(()=>{});
                        try {new WebSocket('ws://127.0.0.1:${otherPort.localPort}/socket')} catch {}
                        const image=document.createElement('img');image.src='http://127.0.0.1:${otherPort.localPort}/image';document.body.appendChild(image);
                    """.trimIndent())
                    assertThrows(SocketTimeoutException::class.java) { otherPort.accept().close() }
                }
                scenario.recreate()
                Thread.sleep(1500)
                assertTrue(evaluate(scenario, "document.body.innerText").contains("Sign in"))
            }
        } finally { credentials.clear() }
    }

    @Test fun chromeCustomTabDeliversLocalhostCallback() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        AuthCallback().use { callback ->
            InstrumentationRegistry.getInstrumentation().runOnMainSync {
                val tab = CustomTabsIntent.Builder().build()
                tab.intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                tab.launchUrl(context, Uri.parse("http://localhost:${callback.port}/callback?state=${callback.state}&code=emulator-dummy"))
            }
            assertEquals("emulator-dummy", withTimeout(30000) { callback.code.await() })
        }
    }

    @Test fun browserCallbackReturnsToExistingActivity() {
        val received = LinkedBlockingQueue<String>()
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            var original: MainActivity? = null
            AuthCallback().use { callback ->
                scenario.onActivity { activity ->
                    original = activity
                    val model = ViewModelProvider(activity)[ShellModel::class.java]
                    activity.lifecycleScope.launch { received.offer(model.awaitBrowserCode(callback)) }
                    CustomTabsIntent.Builder().build().launchUrl(activity,
                        Uri.parse("http://localhost:${callback.port}/callback?state=${callback.state}&code=return-dummy"))
                }
                assertEquals("return-dummy", received.poll(30, TimeUnit.SECONDS))
                val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10)
                while (scenario.state != androidx.lifecycle.Lifecycle.State.RESUMED && System.nanoTime() < deadline) {
                    Thread.sleep(100)
                }
                assertEquals(androidx.lifecycle.Lifecycle.State.RESUMED, scenario.state)
                scenario.onActivity { activity -> assertSame(original, activity) }
            }
        }
    }
}
