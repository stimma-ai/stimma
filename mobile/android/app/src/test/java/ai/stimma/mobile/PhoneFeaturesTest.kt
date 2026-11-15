package ai.stimma.mobile

import android.speech.SpeechRecognizer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PhoneFeaturesTest {
    @Test fun galleryFormatsLandInPhotosAndTheRestInDownloads() {
        assertEquals(SaveTarget.PHOTO, saveTarget("sunset.PNG"))
        assertEquals(SaveTarget.PHOTO, saveTarget("a.b.jpeg"))
        assertEquals(SaveTarget.VIDEO, saveTarget("clip.mp4"))
        assertEquals(SaveTarget.DOWNLOAD, saveTarget("drawing.svg"))
        assertEquals(SaveTarget.DOWNLOAD, saveTarget("bundle.zip"))
        assertEquals(SaveTarget.DOWNLOAD, saveTarget("README"))
        assertEquals("Pictures/Stimma", SaveTarget.PHOTO.folder)
        assertEquals("Movies/Stimma", SaveTarget.VIDEO.folder)
        assertEquals("Download", SaveTarget.DOWNLOAD.folder)
        assertEquals("photos", SaveTarget.VIDEO.location)
    }

    @Test fun exportNamesAreSingleOrdinaryFileNames() {
        assertTrue(validExportName("art (1).png"))
        for (bad in listOf("", " ", ".", "..", "a/b.png", "a\\b.png", "a\nb", "x".repeat(256))) assertFalse(bad, validExportName(bad))
    }

    @Test fun base64LimitMatchesTheEncodedSize() {
        assertEquals(0, base64Length(0))
        assertEquals(4, base64Length(1))
        assertEquals(4, base64Length(3))
        assertEquals(8, base64Length(4))
        assertEquals(89478488L, base64Length(64L * 1024 * 1024))
    }

    @Test fun pausesKeepEarlierUtterancesUnderTheCurrentOne() {
        val transcript = DictationTranscript()
        transcript.partial("a red")
        assertEquals("a red", transcript.text)
        transcript.finish("a red fox")
        transcript.partial(" running ")
        assertEquals("a red fox running", transcript.text)
        // An utterance cut short keeps what was already heard.
        transcript.finish(null)
        transcript.finish("")
        assertEquals("a red fox running", transcript.text)
    }

    @Test fun silenceKeepsListeningWhileRealFailuresStop() {
        assertNull(dictationErrorMessage(SpeechRecognizer.ERROR_NO_MATCH))
        assertNull(dictationErrorMessage(SpeechRecognizer.ERROR_SPEECH_TIMEOUT))
        assertEquals(VoiceDictation.PERMISSION_MESSAGE, dictationErrorMessage(SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS))
        assertTrue(dictationErrorMessage(SpeechRecognizer.ERROR_NETWORK)!!.contains("connection"))
    }

    @Test fun featureListNamesEveryNewCommand() {
        assertEquals(listOf("print", "saveFile", "shareBase64", "voice"), NATIVE_FEATURES)
    }
}
