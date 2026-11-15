package ai.stimma.mobile

import android.content.ContentResolver
import android.content.ContentValues
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import androidx.annotation.RequiresApi

/** Native commands added after the first shell release; the UI checks this list before using them. */
val NATIVE_FEATURES = listOf("print", "saveFile", "shareBase64", "voice")

/** Where a saved file lands on the phone, and what the person is told. */
enum class SaveTarget(val folder: String, val location: String) {
    PHOTO("${Environment.DIRECTORY_PICTURES}/Stimma", "photos"),
    VIDEO("${Environment.DIRECTORY_MOVIES}/Stimma", "photos"),
    DOWNLOAD(Environment.DIRECTORY_DOWNLOADS, "downloads"),
}

/** Formats the phone's gallery shows; everything else goes to Downloads. */
private val GALLERY_IMAGES = setOf("jpg", "jpeg", "png", "gif", "webp", "bmp", "heic", "heif", "avif")
private val GALLERY_VIDEOS = setOf("mp4", "m4v", "mov", "webm", "3gp", "mkv")

fun saveTarget(filename: String): SaveTarget = when (filename.substringAfterLast('.', "").lowercase()) {
    in GALLERY_IMAGES -> SaveTarget.PHOTO
    in GALLERY_VIDEOS -> SaveTarget.VIDEO
    else -> SaveTarget.DOWNLOAD
}

/** A name that is a single, ordinary file name. */
fun validExportName(name: String) =
    name.isNotBlank() && name.length <= 255 && name !in setOf(".", "..") && name.none { it == '/' || it == '\\' || it.code < 32 }

/** Base64 length for [bytes] raw bytes, so oversized input is refused before decoding. */
fun base64Length(bytes: Long) = (bytes + 2) / 3 * 4

/**
 * Writes into the shared media collections (no permission needed on Android
 * 10+). A gallery format the collection refuses falls back to Downloads.
 * Returns the target actually used.
 */
@RequiresApi(Build.VERSION_CODES.Q)
fun saveToMediaStore(resolver: ContentResolver, filename: String, mimeType: String, data: ByteArray): SaveTarget {
    val preferred = saveTarget(filename)
    val attempts = if (preferred == SaveTarget.DOWNLOAD) listOf(preferred) else listOf(preferred, SaveTarget.DOWNLOAD)
    var failure: Exception? = null
    for (target in attempts) {
        val collection: Uri = when (target) {
            SaveTarget.PHOTO -> MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
            SaveTarget.VIDEO -> MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
            SaveTarget.DOWNLOAD -> MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        }
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, filename)
            put(MediaStore.MediaColumns.MIME_TYPE, mimeType)
            put(MediaStore.MediaColumns.RELATIVE_PATH, target.folder)
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val uri = try { resolver.insert(collection, values) } catch (error: Exception) { failure = error; null } ?: continue
        try {
            resolver.openOutputStream(uri)?.use { it.write(data) } ?: error("No output stream")
            resolver.update(uri, ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }, null, null)
            return target
        } catch (error: Exception) {
            resolver.delete(uri, null, null)
            throw error
        }
    }
    throw failure ?: IllegalStateException("The file could not be saved.")
}
