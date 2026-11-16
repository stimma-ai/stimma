import Foundation

@main
struct PhoneFeatureChecks {
    static func main() throws {
        precondition(nativeFeatures == ["print", "saveFile", "shareBase64", "voice"])
        precondition(nativeFeaturesScript() == #"window.stimmaNativeFeatures=Object.freeze(["print","saveFile","shareBase64","voice"])"#)

        precondition(saveTarget("sunset.PNG") == .photo && saveTarget("a.b.jpeg") == .photo)
        precondition(saveTarget("clip.mov") == .video && saveTarget("clip.mp4") == .video)
        for name in ["drawing.svg", "bundle.zip", "notes.txt", "README", "clip.webm"] { precondition(saveTarget(name) == .files, name) }
        precondition(SaveTarget.video.location == "photos" && SaveTarget.files.location == "files")

        precondition(validExportName("art (1).png"))
        for bad in ["", " ", ".", "..", "a/b.png", "a\\b.png", "a\nb", String(repeating: "x", count: 256)] {
            precondition(!validExportName(bad), bad)
        }

        precondition(base64Length(0) == 0 && base64Length(1) == 4 && base64Length(3) == 4 && base64Length(4) == 8)
        precondition(base64Length(exportLimit) == 89_478_488)
        let decoded = try exportData(["base64": "AQL6"], tooLarge: "big")
        precondition(decoded == Data([1, 2, 250]))
        let legacy = try exportData(["bytes": [UInt8]([1, 2])], tooLarge: "big")
        precondition(legacy == Data([1, 2]))
        for args: [String: Any] in [["base64": "not base64!"], ["base64": String(repeating: "A", count: base64Length(exportLimit) + 4)], [:]] {
            do { _ = try exportData(args, tooLarge: "big"); fatalError("Accepted an invalid export") } catch is ExportError {}
        }

        var transcript = DictationTranscript()
        transcript.partial("a red")
        precondition(transcript.text == "a red")
        transcript.finish("a red fox")
        transcript.partial(" running ")
        precondition(transcript.text == "a red fox running")
        // A stretch cut short keeps what was already heard.
        transcript.finish(nil)
        transcript.finish("")
        precondition(transcript.text == "a red fox running")

        precondition(dictationErrorMessage(domain: "kAFAssistantErrorDomain", code: 1110) == nil)
        precondition(dictationErrorMessage(domain: NSURLErrorDomain, code: -1009) == DictationMessage.connection)
        precondition(dictationErrorMessage(domain: "kAFAssistantErrorDomain", code: 1101) == DictationMessage.stopped)
        print("Phone feature checks passed")
    }
}
