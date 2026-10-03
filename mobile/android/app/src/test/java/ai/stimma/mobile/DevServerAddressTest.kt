package ai.stimma.mobile

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class DevServerAddressTest {
    @Test fun acceptsAndNormalizesExplicitIPOrigins() {
        mapOf(" 192.168.1.20:9407 " to "http://192.168.1.20:9407",
            "http://100.64.0.20:9192/" to "http://100.64.0.20:9192",
            "https://192.168.1.20:443" to "https://192.168.1.20",
            "[fd00::20]:9407" to "http://[fd00::20]:9407").forEach { (input, expected) ->
            assertEquals(expected, DevServerAddress.parse(input))
        }
    }
    @Test fun rejectsAmbiguousOrCredentialBearingAddresses() {
        listOf("", "localhost:9407", "example.com:9407", "192.168.1.20", "192.168.1.20:0",
            "192.168.1.20:65536", "192.168.1.20:abc", "192.168.1.20:9407/api",
            "http://user:pass@192.168.1.20:9407", "file://192.168.1.20:9407",
            "192.168.1.20:9407?token=secret", "192.168.1.20:9407#fragment",
            "192.168.1.20:9407\n/path", "999.999.999.999:9407").forEach {
            assertThrows(it, IllegalArgumentException::class.java) { DevServerAddress.parse(it) }
        }
    }
}
