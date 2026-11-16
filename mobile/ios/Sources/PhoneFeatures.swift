import Foundation

/// Native commands added after the first shell release; the UI checks this list before using them.
let nativeFeatures = ["print", "saveFile", "shareBase64", "voice"]

/// Runs at document start so the page knows these commands before its first script.
func nativeFeaturesScript() -> String {
    let list = (try? JSONSerialization.data(withJSONObject: nativeFeatures)).map { String(decoding: $0, as: UTF8.self) } ?? "[]"
    return "window.stimmaNativeFeatures=Object.freeze(\(list))"
}

/// Where a saved file lands on the phone. The raw value is what the page is told.
enum SaveTarget: String {
    case photo = "photos", video = "videos", files
    /// The location the page reads to word its confirmation.
    var location: String { self == .files ? "files" : "photos" }
}

/// Formats Photos shows; everything else goes to Files.
private let photoFormats: Set<String> = ["jpg", "jpeg", "png", "gif", "webp", "bmp", "heic", "heif", "avif", "tif", "tiff"]
private let videoFormats: Set<String> = ["mp4", "m4v", "mov"]

func saveTarget(_ filename: String) -> SaveTarget {
    let ext = (filename as NSString).pathExtension.lowercased()
    if photoFormats.contains(ext) { return .photo }
    if videoFormats.contains(ext) { return .video }
    return .files
}

/// A name that is a single, ordinary file name.
func validExportName(_ name: String) -> Bool {
    !name.trimmingCharacters(in: .whitespaces).isEmpty && name.count <= 255 && name != "." && name != ".."
        && !name.unicodeScalars.contains { $0 == "/" || $0 == "\\" || $0.value < 32 }
}

/// Exports pass through the bridge in memory and are capped like Android's.
let exportLimit = 64 * 1024 * 1024

/// Base64 length for `bytes` raw bytes, so oversized input is refused before decoding.
func base64Length(_ bytes: Int) -> Int { (bytes + 2) / 3 * 4 }

struct ExportError: LocalizedError {
    let errorDescription: String?
    init(_ message: String) { errorDescription = message }
}

/// The file's bytes, sent as base64 by current pages and as a byte array by older ones.
func exportData(_ args: [String: Any], tooLarge: String) throws -> Data {
    if let encoded = args["base64"] as? String {
        guard encoded.utf8.count <= base64Length(exportLimit) else { throw ExportError(tooLarge) }
        guard let data = Data(base64Encoded: encoded) else { throw ExportError("This file could not be read.") }
        return data
    }
    guard let values = args["bytes"] as? [UInt8], values.count <= exportLimit else { throw ExportError(tooLarge) }
    return Data(values)
}

/**
 * Words heard so far in one dictation. A recognition task can end on its own
 * (a long pause or a time limit), so a dictation is several utterances:
 * finished ones are kept and the current one is shown on top of them.
 */
struct DictationTranscript {
    private var finished: [String] = []
    private var current = ""

    mutating func partial(_ text: String) { current = text.trimmingCharacters(in: .whitespacesAndNewlines) }
    mutating func finish(_ text: String?) {
        let trimmed = text?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let words = trimmed.isEmpty ? current : trimmed
        if !words.isEmpty { finished.append(words) }
        current = ""
    }
    var text: String { (finished + [current]).filter { !$0.isEmpty }.joined(separator: " ") }
}

enum DictationMessage {
    static let microphone = "Allow microphone access in Settings"
    static let speech = "Allow speech recognition in Settings"
    static let unavailable = "Voice input isn't available on this phone"
    static let stopped = "Voice input stopped. Try again."
    static let connection = "Voice input needs a connection right now. Try again."
    static let quiet = "Stopped listening. Tap the microphone to talk again."
}

/// What the person is told when recognition fails. Nil means silence: keep listening.
func dictationErrorMessage(domain: String, code: Int) -> String? {
    switch (domain, code) {
    case ("kAFAssistantErrorDomain", 1110), ("kAFAssistantErrorDomain", 203): return nil
    case (NSURLErrorDomain, _): return DictationMessage.connection
    default: return DictationMessage.stopped
    }
}
