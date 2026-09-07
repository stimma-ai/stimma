package ai.stimma.mobile

import kotlinx.coroutines.CompletableDeferred
import java.io.Closeable
import java.net.InetAddress
import java.net.ServerSocket
import java.net.URI
import java.net.URLDecoder
import java.util.UUID
import java.util.Collections
import java.net.Socket
import java.util.concurrent.Executors
import java.util.concurrent.Semaphore

class AuthCallback : Closeable {
    val state = UUID.randomUUID().toString() + UUID.randomUUID().toString()
    val code = CompletableDeferred<String>()
    private val executor = Executors.newFixedThreadPool(4)
    private val clients = Collections.synchronizedSet(mutableSetOf<Socket>())
    private val capacity = Semaphore(8)
    private val ipv4 = ServerSocket(0, 8, InetAddress.getByName("127.0.0.1"))
    val port = ipv4.localPort
    private val ipv6 = try { ServerSocket(port, 8, InetAddress.getByName("::1")) }
        catch (error: Exception) { ipv4.close(); executor.shutdownNow(); throw error }
    private var delivered = false

    init {
        for (listener in listOf(ipv4, ipv6)) executor.execute {
            while (!listener.isClosed) {
                val socket = try { listener.accept() } catch (_: Exception) { break }
                if (!capacity.tryAcquire()) { socket.close(); continue }
                clients.add(socket)
                executor.execute {
                    socket.use {
                        try {
                            socket.soTimeout = 5000
                            val request = HttpHead.read(socket.getInputStream())
                            val target = URI(request.target)
                            val parameters = target.rawQuery.orEmpty().split('&').map {
                                val pair = it.split('=', limit = 2)
                                URLDecoder.decode(pair[0], "UTF-8") to URLDecoder.decode(pair.getOrElse(1) { "" }, "UTF-8")
                            }
                            val codes = parameters.filter { it.first == "code" }
                            val states = parameters.filter { it.first == "state" }
                            val value = codes.firstOrNull()?.second.orEmpty()
                            val valid = synchronized(this) {
                                val accepted = !delivered && request.method == "GET" && request.target.startsWith("/callback?") && target.path == "/callback" &&
                                    request.single("host") in setOf("localhost:$port", "127.0.0.1:$port", "[::1]:$port") &&
                                    codes.size == 1 && states.size == 1 && states[0].second == state && value.length in 1..512
                                if (accepted) delivered = true
                                accepted
                            }
                            val body = if (valid) "Returning to Stimma..." else "Invalid sign-in callback."
                            socket.getOutputStream().write(("HTTP/1.1 ${if (valid) "200 OK" else "400 Bad Request"}\r\nContent-Type: text/plain\r\nCache-Control: no-store\r\nConnection: close\r\nContent-Length: ${body.length}\r\n\r\n$body").toByteArray())
                            socket.getOutputStream().flush()
                            if (valid) code.complete(value)
                        } catch (_: Exception) { }
                        finally { clients.remove(socket); capacity.release() }
                    }
                }
            }
        }
    }

    override fun close() {
        ipv4.close(); ipv6.close()
        synchronized(clients) { clients.toList().forEach { runCatching { it.close() } } }
        executor.shutdownNow(); code.cancel()
    }
}
