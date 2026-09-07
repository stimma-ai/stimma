package ai.stimma.mobile

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.FormBody
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.security.KeyStore
import java.util.UUID
import java.util.concurrent.TimeUnit
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlin.coroutines.coroutineContext

fun JSONObject.body(): RequestBody = toString().toRequestBody("application/json".toMediaType())

class NativeAuthError(message: String) : Exception(message)

class SecureCredentials(context: Context, name: String = "refresh") {
    private val alias = "stimma.$name"
    private val file = AtomicFile(File(context.noBackupFilesDir, "$name.enc"))
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    @Synchronized fun read(): String? {
        if (!file.baseFile.exists()) return null
        return try {
            val bytes = file.readFully()
            require(bytes.size in 29..65536)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
            cipher.doFinal(bytes, 12, bytes.size - 12).toString(Charsets.UTF_8)
        } catch (_: Exception) { file.delete(); null }
    }
    @Synchronized fun write(value: String) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val encrypted = cipher.iv + cipher.doFinal(value.toByteArray())
        val output = file.startWrite()
        try { output.write(encrypted); file.finishWrite(output) }
        catch (error: Exception) { file.failWrite(output); throw error }
    }
    @Synchronized fun clear() { file.delete() }
}

class NativeAuth(context: Context) {
    private val credentials = SecureCredentials(context)
    private val mutex = Mutex()
    private val client = OkHttpClient.Builder().followRedirects(false).followSslRedirects(false)
        .callTimeout(20, TimeUnit.SECONDS).build()
    @Volatile private var generation = UUID.randomUUID()
    @Volatile var user: JSONObject? = null
        private set
    private var token: String? = null
    private var expiresAt = 0L
    val hasSession get() = credentials.read() != null

    @Synchronized fun logout() {
        generation = UUID.randomUUID()
        credentials.clear()
        token = null
        user = null
        expiresAt = 0
        client.dispatcher.cancelAll()
    }

    suspend fun exchange(code: String) = mutex.withLock {
        val epoch = generation
        val exchange = request("https://stimma.ai/api/auth/desktop/exchange", JSONObject().put("code", code).body())
        val tokens = request("https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key=$FIREBASE_KEY",
            JSONObject().put("token", exchange.getString("custom_token")).put("returnSecureToken", true).body())
        coroutineContext.ensureActive()
        synchronized(this) {
            check(epoch == generation) { "Sign in cancelled." }
            credentials.write(tokens.getString("refreshToken"))
            token = tokens.getString("idToken")
            expiresAt = System.currentTimeMillis() + tokens.getString("expiresIn").toLong() * 1000
            user = exchange.getJSONObject("user")
        }
    }

    suspend fun validToken(): String = mutex.withLock {
        if (token != null && user != null && expiresAt > System.currentTimeMillis() + 120000) return@withLock token!!
        val epoch = generation
        val refresh = credentials.read() ?: error("Please sign in.")
        val tokens = request("https://securetoken.googleapis.com/v1/token?key=$FIREBASE_KEY",
            FormBody.Builder().add("grant_type", "refresh_token").add("refresh_token", refresh).build())
        coroutineContext.ensureActive()
        synchronized(this) {
            check(epoch == generation) { "Sign in cancelled." }
            credentials.write(tokens.getString("refresh_token"))
        }
        val nextToken = tokens.getString("id_token")
        val account = user ?: request("https://stimma.ai/api/auth/me", bearer = nextToken)
        coroutineContext.ensureActive()
        synchronized(this) {
            check(epoch == generation) { "Sign in cancelled." }
            token = nextToken
            expiresAt = System.currentTimeMillis() + tokens.getString("expires_in").toLong() * 1000
            user = account
        }
        nextToken
    }

    suspend fun devices() = request("https://stimma.ai/api/devices", bearer = validToken()).getJSONArray("devices")

    private suspend fun request(url: String, body: RequestBody? = null, bearer: String? = null): JSONObject = withContext(Dispatchers.IO) {
        val request = Request.Builder().url(url)
        if (body != null) request.post(body)
        if (bearer != null) request.header("Authorization", "Bearer $bearer")
        val stage = when {
            url.startsWith("https://identitytoolkit.googleapis.com/") -> "Account sign-in"
            url.startsWith("https://securetoken.googleapis.com/") -> "Session refresh"
            url.endsWith("/desktop/exchange") -> "Browser sign-in exchange"
            url.endsWith("/devices") -> "Server discovery"
            else -> "Account lookup"
        }
        val (status, bytes) = try { client.newCall(request.build()).awaitBody(1024 * 1024) }
        catch (_: IOException) { throw NativeAuthError("$stage could not reach the service. Check your network and try again.") }
        if (status !in 200..299) {
            if (url.startsWith("https://securetoken.googleapis.com/")) {
                val message = runCatching { JSONObject(bytes.toString(Charsets.UTF_8)).getJSONObject("error").getString("message") }.getOrNull()
                if (message in setOf("INVALID_REFRESH_TOKEN", "TOKEN_EXPIRED", "USER_DISABLED", "USER_NOT_FOUND", "INVALID_GRANT")) logout()
            }
            throw NativeAuthError("$stage failed (HTTP $status). Please try again.")
        }
        JSONObject(bytes.toString(Charsets.UTF_8))
    }

    companion object { private const val FIREBASE_KEY = "AIzaSyB4xzVbmK5OnZGfs9qSwGJdPVbBoddYCvw" }
}
