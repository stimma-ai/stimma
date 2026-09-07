package ai.stimma.mobile

import org.json.JSONObject
import java.io.File
import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.charset.CodingErrorAction
import java.nio.file.Files
import java.nio.file.LinkOption.NOFOLLOW_LINKS
import java.nio.file.StandardCopyOption.ATOMIC_MOVE
import java.security.MessageDigest
import java.text.Normalizer
import java.util.Locale
import java.util.UUID
import java.util.zip.CRC32
import java.util.zip.Inflater

fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
class UIPackageError(message: String) : Exception(message)
fun requirePackage(valid: Boolean) {
    if (!valid) throw UIPackageError("The server interface package failed validation. Update your Stimma Server and try again.")
}

data class PackageManifest(val hash: String, val bytes: Int, val unpackedBytes: Int) {
    companion object {
        fun parse(bytes: ByteArray): PackageManifest {
            requirePackage(bytes.size <= 16384)
            val json = JSONObject(bytes.toString(Charsets.UTF_8))
            for (key in listOf("formatVersion", "bridgeVersion", "apiVersion")) {
                if (json.get(key) != 1) throw UIPackageError("This server interface requires a newer Stimma app.")
            }
            requirePackage(json.getString("entrypoint") == "index.html")
            val result = PackageManifest(json.getString("hash"), json.getInt("bytes"), json.getInt("unpackedBytes"))
            requirePackage(result.hash.matches(Regex("[0-9a-f]{64}")))
            requirePackage(result.bytes in 1..64 * 1024 * 1024 && result.unpackedBytes in 1..128 * 1024 * 1024)
            requirePackage(json.get("bytes") == result.bytes && json.get("unpackedBytes") == result.unpackedBytes)
            return result
        }
    }
}

class UIPackageCache(private val root: File, private val budget: Long = 256L * 1024 * 1024) {
    @Synchronized
    fun cached(manifestBytes: ByteArray, protected: Set<String>, cancelled: () -> Unit): File? {
        val manifest = PackageManifest.parse(manifestBytes)
        val directory = File(root, manifest.hash)
        if (!verify(directory, manifest, cancelled)) return null
        directory.setLastModified(System.currentTimeMillis())
        evict(0, protected + manifest.hash)
        return File(directory, "files")
    }

    @Synchronized
    fun resolve(manifestBytes: ByteArray, protected: Set<String> = emptySet(), cancelled: () -> Unit = {}, download: () -> ByteArray): File {
        val manifest = PackageManifest.parse(manifestBytes)
        root.mkdirs()
        root.listFiles().orEmpty().filter { it.name.startsWith(".stage-") }.forEach { it.deleteRecursively() }
        val destination = File(root, manifest.hash)
        if (verify(destination, manifest, cancelled)) {
            destination.setLastModified(System.currentTimeMillis())
            evict(0, protected + manifest.hash)
            return File(destination, "files")
        }
        cancelled()
        val archive = download()
        val entries = unpack(archive, manifest, cancelled)
        val stage = File(root, ".stage-${UUID.randomUUID()}")
        try {
            val content = File(stage, "files").apply { mkdirs() }
            for ((name, data) in entries) {
                cancelled()
                File(content, name).apply { parentFile!!.mkdirs(); writeBytes(data) }
            }
            File(stage, "archive.tar.gz").writeBytes(archive)
            File(stage, "manifest.json").writeBytes(manifestBytes)
            cancelled()
            requirePackage(!destination.exists() || manifest.hash !in protected)
            evict(archive.size.toLong() + manifest.unpackedBytes + manifestBytes.size, protected)
            destination.deleteRecursively()
            Files.move(stage.toPath(), destination.toPath(), ATOMIC_MOVE)
            destination.setLastModified(System.currentTimeMillis())
            return File(destination, "files")
        } finally { stage.deleteRecursively() }
    }

    private fun verify(directory: File, manifest: PackageManifest, cancelled: () -> Unit): Boolean {
        return try {
            requirePackage(Files.isDirectory(directory.toPath(), NOFOLLOW_LINKS))
            val archive = File(directory, "archive.tar.gz")
            requirePackage(Files.isRegularFile(archive.toPath(), NOFOLLOW_LINKS) && archive.length() == manifest.bytes.toLong())
            val stored = File(directory, "manifest.json")
            requirePackage(Files.isRegularFile(stored.toPath(), NOFOLLOW_LINKS) && stored.length() <= 16384)
            requirePackage(PackageManifest.parse(stored.readBytes()) == manifest)
            val entries = unpack(archive.readBytes(), manifest, cancelled)
            val content = File(directory, "files")
            requirePackage(Files.isDirectory(content.toPath(), NOFOLLOW_LINKS))
            val found = mutableSetOf<String>()
            content.walkTopDown().forEach { file ->
                cancelled()
                requirePackage(!Files.isSymbolicLink(file.toPath()))
                if (!file.isDirectory) {
                    val name = file.relativeTo(content).invariantSeparatorsPath
                    val expected = entries[name]
                    requirePackage(expected != null && Files.isRegularFile(file.toPath(), NOFOLLOW_LINKS) && file.length() == expected.size.toLong())
                    val digest = MessageDigest.getInstance("SHA-256")
                    file.inputStream().use { input ->
                        val buffer = ByteArray(65536)
                        while (true) { cancelled(); val count = input.read(buffer); if (count < 0) break; digest.update(buffer, 0, count) }
                    }
                    requirePackage(digest.digest().contentEquals(MessageDigest.getInstance("SHA-256").digest(expected!!)))
                    found.add(name)
                }
            }
            requirePackage(found == entries.keys)
            true
        } catch (error: Exception) {
            cancelled()
            false
        }
    }

    private fun evict(reserving: Long, protected: Set<String>) {
        val packages = root.listFiles().orEmpty().filter { it.name.matches(Regex("[0-9a-f]{64}")) }
        val sizes = packages.associateWith { directory -> directory.walkTopDown().filter { it.isFile }.sumOf { it.length() } }
        var total = reserving + sizes.values.sum()
        val candidates = packages.filter { it.name !in protected }.sortedBy { it.lastModified() }
        if (total - candidates.sumOf { sizes.getValue(it) } > budget) throw UIPackageError("There is not enough space for the server interface.")
        for (candidate in candidates) if (total > budget) {
            requirePackage(candidate.deleteRecursively())
            total -= sizes.getValue(candidate)
        }
    }

    companion object {
        fun unpack(archive: ByteArray, manifest: PackageManifest, cancelled: () -> Unit = {}): Map<String, ByteArray> {
            requirePackage(archive.size == manifest.bytes && sha256(archive) == manifest.hash)
            val tar = GzipStream(archive, manifest.unpackedBytes + 10000 * 1024 + 10240, cancelled)
            try {
                val entries = linkedMapOf<String, ByteArray>()
                val folded = mutableSetOf<String>()
                var header = ByteArray(512)
                var total = 0
                fun field(start: Int, length: Int): String {
                    val data = header.copyOfRange(start, start + length)
                    val end = data.indexOf(0).let { if (it < 0) data.size else it }
                    requirePackage(data.drop(end).all { it == 0.toByte() })
                    return Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(data, 0, end)).toString()
                }
                fun octal(start: Int, length: Int): Int {
                    val raw = header.copyOfRange(start, start + length).toString(Charsets.US_ASCII).trim('\u0000', ' ')
                    requirePackage(raw.matches(Regex("[0-7]+")))
                    return raw.toInt(8)
                }
                while (true) {
                    cancelled()
                    header = readExact(tar, 512)
                    if (header.all { it == 0.toByte() }) {
                        requirePackage(readExact(tar, 512).all { it == 0.toByte() })
                        val padding = ByteArray(65536)
                        while (true) {
                            val count = tar.read(padding)
                            if (count < 0) break
                            requirePackage((0 until count).all { padding[it] == 0.toByte() })
                        }
                        requirePackage(tar.count % 512 == 0)
                        requirePackage(entries.containsKey("index.html") && total == manifest.unpackedBytes)
                        val directories = mutableSetOf<String>()
                        for (name in folded) {
                            val parts = name.split('/')
                            for (depth in 1 until parts.size) {
                                val parent = parts.take(depth).joinToString("/")
                                requirePackage(parent !in folded)
                                directories.add(parent)
                                requirePackage(directories.size <= 10000)
                            }
                        }
                        return entries
                    }
                    requirePackage(entries.size < 10000 && field(257, 6) == "ustar" && field(263, 2) == "00")
                    requirePackage(header[156] == 0.toByte() || header[156] == 48.toByte())
                    requirePackage(octal(148, 8) == header.indices.sumOf { if (it in 148..155) 32 else header[it].toInt() and 255 })
                    val prefix = field(345, 155)
                    val name = (if (prefix.isEmpty()) "" else "$prefix/") + field(0, 100)
                    val parts = name.split('/')
                    requirePackage(name.toByteArray().size in 1..255 && '\\' !in name && name.none { it.code < 32 || it.code == 127 })
                    requirePackage(parts.size <= 32 && parts.all { it.isNotEmpty() && it != "." && it != ".." })
                    requirePackage(name !in entries && folded.add(Normalizer.normalize(name, Normalizer.Form.NFC).lowercase(Locale.ROOT)))
                    requirePackage(field(157, 100).isEmpty())
                    val size = octal(124, 12)
                    requirePackage(size <= manifest.unpackedBytes - total)
                    val padded = ((size + 511) / 512) * 512
                    entries[name] = readExact(tar, size)
                    requirePackage(readExact(tar, padded - size).all { it == 0.toByte() })
                    total += size
                }
            } finally { tar.close() }
        }

        private fun readExact(input: InputStream, size: Int): ByteArray {
            val result = ByteArray(size)
            var offset = 0
            while (offset < size) {
                val count = input.read(result, offset, minOf(65536, size - offset))
                requirePackage(count > 0)
                offset += count
            }
            return result
        }

        private class GzipStream(private val data: ByteArray, private val maximum: Int, private val cancelled: () -> Unit) : InputStream() {
            private val inflater = Inflater(true)
            private val checksum = CRC32()
            var count = 0
                private set
            init {
                try {
                    requirePackage(data.size >= 18 && data[0] == 31.toByte() && data[1] == 139.toByte() && data[2] == 8.toByte())
                    val flags = data[3].toInt() and 255
                    requirePackage(flags and 0xe2 == 0)
                    var start = 10
                    if (flags and 4 != 0) {
                        requirePackage(start + 2 < data.size - 8)
                        val length = (data[start].toInt() and 255) or ((data[start + 1].toInt() and 255) shl 8)
                        start += 2 + length
                    }
                    for (flag in listOf(8, 16)) if (flags and flag != 0) {
                        while (start < data.size - 8 && data[start++] != 0.toByte()) { }
                    }
                    requirePackage(start < data.size - 8)
                    inflater.setInput(data, start, data.size - start)
                } catch (error: Exception) { inflater.end(); throw error }
            }
            override fun read(): Int {
                val single = ByteArray(1)
                return if (read(single) < 0) -1 else single[0].toInt() and 255
            }
            override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
                cancelled()
                if (length == 0) return 0
                if (inflater.finished()) return -1
                val produced = inflater.inflate(buffer, offset, length)
                requirePackage(produced <= maximum - count && (produced > 0 || inflater.finished()))
                checksum.update(buffer, offset, produced)
                count += produced
                if (inflater.finished()) {
                    requirePackage(inflater.remaining == 8)
                    val trailer = ByteBuffer.wrap(data, data.size - 8, 8).order(ByteOrder.LITTLE_ENDIAN)
                    requirePackage(trailer.int.toLong() and 0xffffffffL == checksum.value && trailer.int == count)
                }
                return if (produced == 0) -1 else produced
            }
            override fun close() { inflater.end() }
        }
    }
}
