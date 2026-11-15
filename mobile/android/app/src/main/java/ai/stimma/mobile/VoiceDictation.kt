package ai.stimma.mobile

import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject

/**
 * Words heard so far in one dictation. The platform recognizer ends an
 * utterance on each pause, so a dictation is several utterances: finished
 * ones are kept and the current one is shown on top of them.
 */
class DictationTranscript {
    private val finished = mutableListOf<String>()
    private var current = ""

    fun partial(text: String) { current = text.trim() }
    fun finish(text: String?) {
        val words = text?.trim().orEmpty().ifEmpty { current }
        if (words.isNotEmpty()) finished += words
        current = ""
    }
    val text: String get() = (finished + current).filter { it.isNotEmpty() }.joinToString(" ")
}

/** What the person is told when the recognizer gives up. Null means keep listening. */
fun dictationErrorMessage(error: Int): String? = when (error) {
    SpeechRecognizer.ERROR_NO_MATCH, SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> null
    SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> VoiceDictation.PERMISSION_MESSAGE
    SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT, SpeechRecognizer.ERROR_SERVER,
    11 /* ERROR_SERVER_DISCONNECTED */ -> "Voice input needs a connection right now. Try again."
    SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "Voice input is busy. Try again in a moment."
    12 /* ERROR_LANGUAGE_NOT_SUPPORTED */, 13 /* ERROR_LANGUAGE_UNAVAILABLE */ -> "Voice input doesn't support this phone's language yet."
    else -> "Voice input stopped. Try again."
}

/**
 * Push-to-talk dictation with the phone's own speech recognizer, preferring
 * on-device recognition. Pauses don't end the dictation; only stop or cancel
 * does. All calls happen on the main thread.
 */
class VoiceDictation(private val context: Context, private val emit: (JSONObject) -> Unit) {
    private var recognizer: SpeechRecognizer? = null
    private var onDevice = false
    private var transcript = DictationTranscript()
    private var listening = false
    private var stopping: CompletableDeferred<Unit>? = null
    private var quietRestarts = 0
    var session = 0L
        private set

    val available: Boolean get() = SpeechRecognizer.isRecognitionAvailable(context) || onDeviceAvailable()

    private fun onDeviceAvailable() = Build.VERSION.SDK_INT >= Build.VERSION_CODES.S &&
        runCatching { SpeechRecognizer.isOnDeviceRecognitionAvailable(context) }.getOrDefault(false)

    /** Begins a new dictation; any earlier one is abandoned. */
    fun start(): Long {
        cancel()
        session += 1
        transcript = DictationTranscript()
        quietRestarts = 0
        listening = true
        onDevice = onDeviceAvailable()
        listen(fresh = true)
        return session
    }

    /** Ends the dictation and resolves everything heard. */
    suspend fun stop(): String {
        if (!listening) return transcript.text
        val done = CompletableDeferred<Unit>()
        stopping = done
        recognizer?.stopListening()
        withTimeoutOrNull(4000) { done.await() }
        val text = transcript.text
        end()
        return text
    }

    fun cancel() {
        if (!listening && recognizer == null) return
        recognizer?.cancel()
        end()
    }

    /** A cancel that also stops a start still waiting on the microphone prompt. */
    fun invalidate() { session += 1; cancel() }

    private fun end() {
        listening = false
        stopping?.complete(Unit); stopping = null
        recognizer?.destroy(); recognizer = null
    }

    private val main = Handler(Looper.getMainLooper())

    /** Listens for the next utterance, reusing this dictation's recognizer unless [fresh]. */
    private fun listen(fresh: Boolean = false) {
        val existing = recognizer
        if (existing != null && !fresh) {
            val owner = session
            // Restart outside the recognizer's own callback so it is idle again.
            main.post { if (owner == session && recognizer === existing && listening) existing.startListening(intent()) }
            return
        }
        existing?.destroy()
        val created = if (onDevice && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S)
            SpeechRecognizer.createOnDeviceSpeechRecognizer(context)
        else SpeechRecognizer.createSpeechRecognizer(context)
        recognizer = created
        val owner = session
        created.setRecognitionListener(object : RecognitionListener {
            fun current() = owner == session && recognizer === created
            override fun onReadyForSpeech(params: Bundle?) {}
            override fun onBeginningOfSpeech() { if (current()) quietRestarts = 0 }
            override fun onRmsChanged(rmsdB: Float) {}
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() {}
            override fun onEvent(eventType: Int, params: Bundle?) {}
            override fun onPartialResults(partialResults: Bundle?) {
                if (!current()) return
                val text = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull() ?: return
                transcript.partial(text)
                send("partial", transcript.text)
            }
            override fun onResults(results: Bundle?) {
                if (!current()) return
                transcript.finish(results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull())
                send("partial", transcript.text)
                stopping?.let { it.complete(Unit); return }
                // A pause ended this utterance; keep listening until the person stops.
                listen()
            }
            override fun onError(error: Int) {
                if (!current()) return
                stopping?.let { transcript.finish(null); it.complete(Unit); return }
                if (onDevice && (error == 12 || error == 13)) { onDevice = false; listen(fresh = true); return }
                val message = dictationErrorMessage(error)
                if (message == null && ++quietRestarts <= MAX_QUIET_RESTARTS) { transcript.finish(null); listen(); return }
                send("error", message ?: QUIET_MESSAGE)
                end()
            }
        })
        created.startListening(intent())
    }

    private fun intent() = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
        .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
        .putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
        .putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, context.packageName)

    private fun send(type: String, text: String) {
        val detail = JSONObject().put("session", session).put("type", type)
        if (type == "error") detail.put("message", text) else detail.put("text", text)
        emit(detail)
    }

    companion object {
        const val PERMISSION_MESSAGE = "Allow microphone access for Stimma in Settings to use voice input."
        /** Silence after which a forgotten dictation stops listening (each try lasts several seconds). */
        private const val MAX_QUIET_RESTARTS = 12
        private const val QUIET_MESSAGE = "Stopped listening. Tap the microphone to talk again."
    }
}
