import AVFoundation
import Speech
import SwiftUI

@MainActor
final class ARVoiceController: NSObject, ObservableObject, AVSpeechSynthesizerDelegate {
    @Published private(set) var isRecording = false
    @Published private(set) var isBusy = false
    @Published private(set) var level: Float = 0
    @Published private(set) var seconds = 0
    @Published private(set) var status = "Ask about this drawing"
    @Published private(set) var transcript = ""
    @Published private(set) var answerText = ""

    private let client = VoiceClient()
    private var recorder: AVAudioRecorder?
    private var recordingURL: URL?
    private var player: AVAudioPlayer?
    private let synthesizer = AVSpeechSynthesizer()
    private var work: Task<Void, Never>?
    private var metering: Task<Void, Never>?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var recognitionContinuation: CheckedContinuation<String, Error>?
    private var recognitionTimeout: Task<Void, Never>?
    private var recognitionID: UUID?

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    func toggle(docID: String, onAnswer: @escaping (VoiceAnswer) -> Void) {
        if isRecording {
            finishRecording(docID: docID, onAnswer: onAnswer)
            return
        }
        guard !isBusy else { return }
        work?.cancel()
        stopPlayback()
        isBusy = true
        work = Task { [self] in
            do {
                let granted = await AVAudioApplication.requestRecordPermission()
                try Task.checkCancellation()
                guard granted else { throw VoiceError.message("Allow microphone access in Settings to ask by voice.") }
                let session = AVAudioSession.sharedInstance()
                try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker])
                try session.setActive(true)
                let url = FileManager.default.temporaryDirectory.appendingPathComponent("question-\(UUID().uuidString).m4a")
                recordingURL = url
                let recorder = try AVAudioRecorder(url: url, settings: [
                    AVFormatIDKey: kAudioFormatMPEG4AAC,
                    AVSampleRateKey: 44100,
                    AVNumberOfChannelsKey: 1,
                    AVEncoderAudioQualityKey: AVAudioQuality.medium.rawValue
                ])
                recorder.isMeteringEnabled = true
                guard recorder.record(forDuration: 15) else { throw VoiceError.message("Unable to start the microphone.") }
                self.recorder = recorder
                isBusy = false
                isRecording = true
                transcript = ""
                answerText = ""
                seconds = 0
                status = "Listening… Tap to send (15 seconds maximum)."
                metering = Task { [weak self] in
                    while !Task.isCancelled {
                        try? await Task.sleep(for: .milliseconds(100))
                        guard !Task.isCancelled, let self, self.isRecording, let recorder = self.recorder else { return }
                        recorder.updateMeters()
                        self.level = min(1, max(0, pow(10, recorder.averagePower(forChannel: 0) / 20)))
                        self.seconds = min(15, Int(recorder.currentTime))
                        if !recorder.isRecording {
                            self.finishRecording(docID: docID, onAnswer: onAnswer)
                            return
                        }
                    }
                }
            } catch is CancellationError {
                return
            } catch {
                if !Task.isCancelled { fail(error) }
            }
        }
    }

    private func finishRecording(docID: String, onAnswer: @escaping (VoiceAnswer) -> Void) {
        guard isRecording, let url = recordingURL else { return }
        recorder?.stop()
        recorder = nil
        metering?.cancel()
        metering = nil
        isRecording = false
        isBusy = true
        level = 0
        status = "Transcribing…"
        work = Task {
            defer {
                try? FileManager.default.removeItem(at: url)
                if recordingURL == url {
                    recordingURL = nil
                    isBusy = false
                }
            }
            do {
                let audio = try Data(contentsOf: url)
                let remoteText = try await client.transcribe(audio: audio)
                try Task.checkCancellation()
                let text: String
                if let remoteText {
                    text = remoteText
                } else {
                    status = "Transcribing on device…"
                    text = try await transcribeOnDevice(url)
                }
                try Task.checkCancellation()
                transcript = text.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !transcript.isEmpty else { throw VoiceError.message("No speech detected. Try again.") }
                status = "Thinking…"
                let answer = try await client.ask(transcript, docID: docID) { [weak self] event in
                    switch event {
                    case .status(let text), .trace(let text): self?.status = text
                    case .answer: break
                    }
                }
                try Task.checkCancellation()
                answerText = answer.answer.text_md
                onAnswer(answer)
                status = "Speaking answer…"
                let spoken = Self.spokenText(answerText)
                let audioData = try await client.speech(text: spoken)
                try Task.checkCancellation()
                try AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio)
                try AVAudioSession.sharedInstance().setActive(true)
                if let audioData {
                    let player = try AVAudioPlayer(data: audioData)
                    self.player = player
                    guard player.play() else { throw VoiceError.message("Unable to play the spoken answer.") }
                    while player.isPlaying {
                        try await Task.sleep(for: .milliseconds(100))
                    }
                    self.player = nil
                    deactivateAudio()
                    status = "Ask another question"
                } else {
                    let utterance = AVSpeechUtterance(string: spoken)
                    utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
                    synthesizer.speak(utterance)
                }
            } catch is CancellationError {
                return
            } catch {
                if !Task.isCancelled { fail(error) }
            }
        }
    }

    private func transcribeOnDevice(_ url: URL) async throws -> String {
        let authorization = await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0) }
        }
        try Task.checkCancellation()
        guard authorization == .authorized else {
            throw VoiceError.message("Allow speech recognition in Settings to transcribe on device.")
        }
        guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US")),
              recognizer.isAvailable, recognizer.supportsOnDeviceRecognition else {
            throw VoiceError.message("English on-device speech recognition is unavailable on this device.")
        }
        let request = SFSpeechURLRecognitionRequest(url: url)
        request.requiresOnDeviceRecognition = true
        request.shouldReportPartialResults = false
        let id = UUID()
        recognitionID = id
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                recognitionContinuation = continuation
                recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
                    // Extract values before crossing to the main actor.
                    let text = result?.isFinal == true ? result?.bestTranscription.formattedString : nil
                    Task { @MainActor in
                        guard let self, self.recognitionID == id else { return }
                        if let text { self.finishRecognition(.success(text)) }
                        else if let error { self.finishRecognition(.failure(error)) }
                    }
                }
                recognitionTimeout = Task { [weak self] in
                    try? await Task.sleep(for: .seconds(30))
                    guard !Task.isCancelled, self?.recognitionID == id else { return }
                    self?.finishRecognition(.failure(VoiceError.message("Transcription timed out. Try again.")))
                }
            }
        } onCancel: {
            Task { @MainActor [weak self] in
                guard self?.recognitionID == id else { return }
                self?.finishRecognition(.failure(CancellationError()))
            }
        }
    }

    private func finishRecognition(_ result: Result<String, Error>) {
        let continuation = recognitionContinuation
        recognitionContinuation = nil
        recognitionID = nil
        recognitionTask?.cancel()
        recognitionTask = nil
        recognitionTimeout?.cancel()
        recognitionTimeout = nil
        continuation?.resume(with: result)
    }

    func stop() {
        work?.cancel()
        work = nil
        metering?.cancel()
        metering = nil
        recorder?.stop()
        recorder = nil
        finishRecognition(.failure(CancellationError()))
        if let recordingURL { try? FileManager.default.removeItem(at: recordingURL) }
        recordingURL = nil
        isRecording = false
        isBusy = false
        level = 0
        status = "Ask about this drawing"
        stopPlayback()
    }

    private func stopPlayback() {
        player?.stop()
        player = nil
        synthesizer.stopSpeaking(at: .immediate)
        deactivateAudio()
    }

    private func deactivateAudio() {
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    private func fail(_ error: Error) {
        status = error.localizedDescription
        recorder?.stop()
        recorder = nil
        if let recordingURL { try? FileManager.default.removeItem(at: recordingURL) }
        recordingURL = nil
        isBusy = false
        isRecording = false
        stopPlayback()
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            guard let self, !self.isRecording, !self.isBusy else { return }
            self.status = "Ask another question"
            self.deactivateAudio()
        }
    }

    static func spokenText(_ markdown: String) -> String {
        let plain = (try? AttributedString(markdown: markdown)).map { String($0.characters) } ?? markdown
        return plain.replacingOccurrences(of: #"\[\d+\]"#, with: "", options: .regularExpression)
    }
}

struct ARVoicePanel: View {
    @ObservedObject var voice: ARVoiceController
    let docID: String?
    let onAnswer: (VoiceAnswer) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if !voice.answerText.isEmpty {
                ScrollView {
                    Text((try? AttributedString(markdown: voice.answerText)) ?? AttributedString(voice.answerText))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                }.frame(maxHeight: 140)
                .accessibilityIdentifier("ar-voice-answer")
            }
            if !voice.transcript.isEmpty {
                Text(voice.transcript).font(.caption).foregroundStyle(.secondary).lineLimit(2)
            }
            HStack(spacing: 12) {
                Button {
                    if let docID { voice.toggle(docID: docID, onAnswer: onAnswer) }
                } label: {
                    Image(systemName: voice.isRecording ? "stop.circle.fill" : "mic.circle.fill")
                        .font(.largeTitle)
                }
                .accessibilityLabel(voice.isRecording ? "Send voice question" : "Ask by voice")
                .accessibilityIdentifier("ar-voice-mic")
                .disabled(voice.isBusy || docID == nil)
                VStack(alignment: .leading, spacing: 4) {
                    Text(voice.status).font(.caption)
                    if voice.isRecording {
                        ProgressView(value: Double(voice.level)).tint(.red)
                            .accessibilityLabel("Microphone level")
                        Text("\(voice.seconds) / 15 s").font(.caption.monospacedDigit())
                    }
                }
                Spacer(minLength: 0)
                if voice.isBusy { ProgressView() }
            }
            Text("AI can make mistakes. Verify important information.")
                .font(.caption2).foregroundStyle(.secondary)
        }
        .padding().background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
    }
}
