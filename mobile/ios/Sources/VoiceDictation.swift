import AVFoundation
import OSLog
import Speech

/// Hands microphone buffers to whichever recognition request is current. Set on the main actor, read on the audio thread.
final class DictationAudioFeed: @unchecked Sendable {
    private let lock = NSLock()
    private var request: SFSpeechAudioBufferRecognitionRequest?

    func use(_ request: SFSpeechAudioBufferRecognitionRequest?) {
        lock.lock(); self.request = request; lock.unlock()
    }

    func append(_ buffer: AVAudioPCMBuffer) {
        lock.lock(); let request = self.request; lock.unlock()
        request?.append(buffer)
    }
}

/// Built outside the main actor: the tap runs on the audio thread.
private func dictationTap(_ feed: DictationAudioFeed) -> AVAudioNodeTapBlock {
    { buffer, _ in feed.append(buffer) }
}

/// One recognizer callback, reduced to plain values before it crosses to the main actor.
private struct RecognitionUpdate: Sendable {
    let text: String?
    let isFinal: Bool
    let errorDomain: String?
    let errorCode: Int
}

/**
 * Push-to-talk dictation with the phone's speech recognizer, on device when
 * offered. Pauses and recognizer time limits don't end a dictation; only stop
 * or cancel does. Events reach the page as `stimma:voice` with the session
 * number that `start` returned, matching the Android shell.
 */
@MainActor
final class VoiceDictation {
    private static let maxQuietRestarts = 12
    private static let logger = Logger(subsystem: "ai.stimma.mobile", category: "voice")

    private let emit: ([String: Any]) -> Void
    private let engine = AVAudioEngine()
    private let feed = DictationAudioFeed()
    private var recognizer: SFSpeechRecognizer?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var transcript = DictationTranscript()
    private var listening = false
    private var tapInstalled = false
    private var onDevice = false
    private var quietRestarts = 0
    private var stopping: CheckedContinuation<Void, Never>?
    private var savedAudio: (category: AVAudioSession.Category, mode: AVAudioSession.Mode, options: AVAudioSession.CategoryOptions)?
    private(set) var session = 0

    init(emit: @escaping ([String: Any]) -> Void) { self.emit = emit }

    /// A recognizer exists for the phone's language.
    var available: Bool { SFSpeechRecognizer() != nil }

    var permissionGranted: Bool {
        SFSpeechRecognizer.authorizationStatus() == .authorized && AVAudioApplication.shared.recordPermission == .granted
    }

    /// Asks for the microphone, then speech recognition. Nil when both are allowed; otherwise what to tell the person.
    func requestPermission() async -> String? {
        let microphone: Bool
        switch AVAudioApplication.shared.recordPermission {
        case .granted: microphone = true
        case .denied: microphone = false
        default: microphone = await AVAudioApplication.requestRecordPermission()
        }
        guard microphone else { return DictationMessage.microphone }
        var speech = SFSpeechRecognizer.authorizationStatus()
        if speech == .notDetermined {
            speech = await withCheckedContinuation { continuation in
                SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0) }
            }
        }
        return speech == .authorized ? nil : DictationMessage.speech
    }

    /// Begins a new dictation; any earlier one is abandoned. Returns its session number.
    func start() throws -> Int {
        cancel()
        session += 1
        transcript = DictationTranscript()
        quietRestarts = 0
        guard let recognizer = SFSpeechRecognizer() else { throw ExportError(DictationMessage.unavailable) }
        self.recognizer = recognizer
        onDevice = recognizer.supportsOnDeviceRecognition
        let audio = AVAudioSession.sharedInstance()
        savedAudio = (audio.category, audio.mode, audio.categoryOptions)
        do {
            try audio.setCategory(.record, mode: .measurement, options: .duckOthers)
            try audio.setActive(true, options: .notifyOthersOnDeactivation)
            let input = engine.inputNode
            let format = input.outputFormat(forBus: 0)
            guard format.sampleRate > 0, format.channelCount > 0 else { throw ExportError(DictationMessage.unavailable) }
            input.installTap(onBus: 0, bufferSize: 1024, format: format, block: dictationTap(feed))
            tapInstalled = true
            engine.prepare()
            try engine.start()
        } catch {
            end()
            throw ExportError(DictationMessage.stopped)
        }
        listening = true
        listen()
        return session
    }

    /// Ends the dictation and resolves everything heard.
    func stop() async -> String {
        guard listening else { return transcript.text }
        stopMicrophone()
        request?.endAudio()
        let owner = session
        await withCheckedContinuation { continuation in
            stopping = continuation
            // The last words usually arrive within a moment; never wait forever.
            Task { @MainActor [weak self] in
                try? await Task.sleep(for: .seconds(4))
                if self?.session == owner { self?.resumeStopping() }
            }
        }
        let text = transcript.text
        end()
        return text
    }

    func cancel() {
        guard listening || task != nil || tapInstalled else { return }
        end()
    }

    /// A cancel that also stops a start still waiting on a permission prompt.
    func invalidate() { session += 1; cancel() }

    private func listen() {
        guard let recognizer else { return }
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.addsPunctuation = true
        request.taskHint = .dictation
        if onDevice { request.requiresOnDeviceRecognition = true }
        self.request = request
        feed.use(request)
        let owner = session
        let id = ObjectIdentifier(request)
        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            let failure = error as NSError?
            let update = RecognitionUpdate(text: result?.bestTranscription.formattedString, isFinal: result?.isFinal ?? false,
                                           errorDomain: failure?.domain, errorCode: failure?.code ?? 0)
            Task { @MainActor in self?.handle(update, owner: owner, request: id) }
        }
    }

    private func handle(_ update: RecognitionUpdate, owner: Int, request id: ObjectIdentifier) {
        guard owner == session, listening, let request, ObjectIdentifier(request) == id else { return }
        if let text = update.text {
            if update.isFinal { transcript.finish(text) } else { transcript.partial(text) }
            if !text.isEmpty { quietRestarts = 0 }
            send(["type": "partial", "text": transcript.text])
        }
        if update.isFinal {
            if stopping != nil { resumeStopping(); return }
            // The recognizer ended this stretch on its own; keep listening until the person stops.
            listen()
            return
        }
        guard let domain = update.errorDomain else { return }
        // Only the error's kind is logged, never what was said.
        Self.logger.notice("recognition_error domain=\(domain, privacy: .public) code=\(update.errorCode) on_device=\(self.onDevice)")
        transcript.finish(nil)
        if stopping != nil { resumeStopping(); return }
        let message = dictationErrorMessage(domain: domain, code: update.errorCode)
        if message == nil, quietRestarts < Self.maxQuietRestarts { quietRestarts += 1; listen(); return }
        // On-device recognition can be missing its language files; the phone's server recognizer may still work.
        if message != nil, onDevice { onDevice = false; listen(); return }
        send(["type": "error", "message": message ?? DictationMessage.quiet])
        end()
    }

    private func send(_ detail: [String: Any]) {
        var detail = detail
        detail["session"] = session
        emit(detail)
    }

    private func resumeStopping() {
        stopping?.resume(); stopping = nil
    }

    private func stopMicrophone() {
        if engine.isRunning { engine.stop() }
        if tapInstalled { engine.inputNode.removeTap(onBus: 0); tapInstalled = false }
    }

    private func end() {
        listening = false
        resumeStopping()
        task?.cancel(); task = nil
        feed.use(nil); request = nil
        stopMicrophone()
        if let saved = savedAudio {
            let audio = AVAudioSession.sharedInstance()
            try? audio.setActive(false, options: .notifyOthersOnDeactivation)
            try? audio.setCategory(saved.category, mode: saved.mode, options: saved.options)
            savedAudio = nil
        }
    }
}
