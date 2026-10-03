package ai.stimma.mobile

import java.net.URI
import java.net.InetAddress

/** Explicit IP and frontend port, matching the iOS debug connection flow. */
object DevServerAddress {
    const val HELP = "Enter an IP address and frontend port, such as 192.168.1.20:9407 (IPv6: [fd00::20]:9407)."
    fun parse(address: String): String {
        try {
            val value = address.trim()
            require(value.isNotEmpty() && value.none { it.isWhitespace() })
            val uri = URI(if (value.contains("://")) value else "http://$value")
            require(uri.scheme in setOf("http", "https") && uri.port in 1..65535)
            require(uri.rawUserInfo == null && uri.rawQuery == null && uri.rawFragment == null && uri.rawPath in setOf("", "/"))
            val host = requireNotNull(uri.host).removeSurrounding("[", "]")
            if (host.contains(':')) {
                require(host.all { it in "0123456789abcdefABCDEF:." })
                InetAddress.getByName(host)
            } else {
                val octets = host.split('.')
                require(octets.size == 4 && octets.all { it.isNotEmpty() && it.all { c -> c in '0'..'9' } && it.toInt() in 0..255 && (it.length == 1 || !it.startsWith('0')) })
            }
            val port = if (uri.port == if (uri.scheme == "https") 443 else 80) -1 else uri.port
            return URI(uri.scheme, null, host, port, null, null, null).toASCIIString()
        } catch (_: Exception) { throw IllegalArgumentException(HELP) }
    }
}
