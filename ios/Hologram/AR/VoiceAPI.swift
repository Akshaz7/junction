import Foundation

enum VoiceError: LocalizedError {
    case message(String)
    var errorDescription: String? {
        if case .message(let text) = self { return text }
        return nil
    }
}

struct VoiceAnswer: Decodable, Equatable {
    struct Answer: Decodable, Equatable { let text_md: String }
    struct Evidence: Decodable, Equatable {
        struct Box: Decodable, Equatable { let item_id: String; let label: String }
        struct Scene: Decodable, Equatable {
            let doc_id: String
            let highlight_item_ids: [String]
            let camera_target_item_id: String?
            let commands: [SceneCommand]?
        }
        let boxes: [Box]
        let scene: Scene
    }
    let answer: Answer
    let evidence: Evidence

    var highlightLabels: [String: String] {
        var labels: [String: String] = [:]
        let selected = Set(evidence.scene.highlight_item_ids)
        for box in evidence.boxes where selected.contains(box.item_id) && labels[box.item_id] == nil {
            labels[box.item_id] = box.label
        }
        return labels
    }
}

enum VoiceEvent: Equatable {
    case status(String), trace(String), answer(VoiceAnswer)
}

/// A line parser shared by the streaming client and hardware-free tests.
struct VoiceSSEParser {
    private var event = ""
    private var data: [String] = []

    mutating func consume(_ rawLine: String) throws -> VoiceEvent? {
        let line = rawLine.hasSuffix("\r") ? String(rawLine.dropLast()) : rawLine
        if line.isEmpty { return try finish() }
        if line.hasPrefix(":") { return nil }
        let parts = line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false)
        let value = parts.count > 1 ? String(parts[1]).replacingOccurrences(of: "^ ", with: "", options: .regularExpression) : ""
        if parts[0] == "event" { event = value }
        if parts[0] == "data" { data.append(value) }
        return nil
    }

    mutating func finish() throws -> VoiceEvent? {
        defer { event = ""; data = [] }
        guard !data.isEmpty else { return nil }
        let bytes = Data(data.joined(separator: "\n").utf8)
        if event == "answer" { return .answer(try JSONDecoder().decode(VoiceAnswer.self, from: bytes)) }
        let json = try JSONSerialization.jsonObject(with: bytes) as? [String: Any]
        switch event {
        case "status": return .status(json?["text"] as? String ?? "Thinking…")
        case "trace": return .trace(json?["detail"] as? String ?? "Exploring document…")
        case "error": throw VoiceError.message(json?["detail"] as? String ?? "The question could not be answered.")
        default: return nil
        }
    }
}

enum VoiceRequests {
    static func speechIntent(baseURL: URL, audio: Data, boundary: String = UUID().uuidString) -> URLRequest {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/speech-intent"))
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        var body = Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"question.m4a\"\r\nContent-Type: audio/mp4\r\n\r\n".utf8)
        body.append(audio)
        body.append(Data("\r\n--\(boundary)--\r\n".utf8))
        request.httpBody = body
        return request
    }

    static func json(baseURL: URL, path: String, body: [String: Any]) throws -> URLRequest {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        return request
    }

    static func usesDevice(_ data: Data) -> Bool {
        (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["fallback"] as? String == "device"
    }
}

@MainActor
protocol VoiceTransport {
    func data(for request: URLRequest) async throws -> (Data, URLResponse)
    func answer(for request: URLRequest, onEvent: (VoiceEvent) -> Void) async throws -> VoiceAnswer
}

@MainActor
final class URLVoiceTransport: VoiceTransport {
    private let session: URLSession
    init(session: URLSession = .shared) { self.session = session }

    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        try await session.data(for: request)
    }

    func answer(for request: URLRequest, onEvent: (VoiceEvent) -> Void) async throws -> VoiceAnswer {
        let (bytes, response) = try await session.bytes(for: request)
        try VoiceClient.validate(response)
        guard (response as? HTTPURLResponse)?.mimeType == "text/event-stream" else {
            throw VoiceError.message("The server did not return an answer stream.")
        }
        var parser = VoiceSSEParser()
        var line = Data()
        var previousWasCR = false
        func acceptLine() throws -> VoiceAnswer? {
            defer { line.removeAll(keepingCapacity: true) }
            if let event = try parser.consume(String(decoding: line, as: UTF8.self)) {
                onEvent(event)
                if case .answer(let answer) = event { return answer }
            }
            return nil
        }
        // AsyncBytes.lines skips empty lines; SSE requires them as event boundaries.
        for try await byte in bytes {
            try Task.checkCancellation()
            if byte == 10 && previousWasCR {
                previousWasCR = false
                continue
            }
            if byte == 10 || byte == 13 {
                previousWasCR = byte == 13
                if let answer = try acceptLine() { return answer }
            } else {
                previousWasCR = false
                line.append(byte)
            }
        }
        if !line.isEmpty, let answer = try acceptLine() { return answer }
        if let event = try parser.finish() {
            onEvent(event)
            if case .answer(let answer) = event { return answer }
        }
        throw VoiceError.message("The answer stream ended before an answer arrived.")
    }
}

@MainActor
final class VoiceClient {
    private let baseURL: URL
    private let transport: any VoiceTransport
    private var chatIDs: [String: String] = [:]

    init(baseURL: URL = AppConfiguration.apiURL, transport: (any VoiceTransport)? = nil) {
        self.baseURL = baseURL
        self.transport = transport ?? URLVoiceTransport()
    }

    static func validate(_ response: URLResponse) throws {
        guard let response = response as? HTTPURLResponse, (200..<300).contains(response.statusCode) else {
            throw VoiceError.message("Voice request failed (HTTP \((response as? HTTPURLResponse)?.statusCode ?? 0)). Try again.")
        }
    }

    /// nil requests transcription of the same recording by the device.
    func transcribe(audio: Data) async throws -> String? {
        let (data, response) = try await transport.data(for: VoiceRequests.speechIntent(baseURL: baseURL, audio: audio))
        try Self.validate(response)
        if VoiceRequests.usesDevice(data) { return nil }
        struct Transcript: Decodable { let text: String }
        return try JSONDecoder().decode(Transcript.self, from: data).text
    }

    /// `chatID`: the web chat AR was opened from. Voice questions and answers are posted there, so the
    /// whole AR conversation shows up in that chat afterwards. Without one, a "Voice in AR" chat is created
    /// (listed in History) and reused for the rest of the session.
    func ask(_ text: String, docID: String, chatID existingChat: String? = nil,
             onEvent: (VoiceEvent) -> Void) async throws -> VoiceAnswer {
        let chatID: String
        if let existingChat, !existingChat.isEmpty {
            chatID = existingChat
        } else if let existing = chatIDs[docID] {
            chatID = existing
        } else {
            let request = try VoiceRequests.json(baseURL: baseURL, path: "api/chats",
                                                 body: ["doc_ids": [docID], "title": "Voice in AR"])
            let (data, response) = try await transport.data(for: request)
            try Self.validate(response)
            struct Chat: Decodable { let id: String }
            chatID = try JSONDecoder().decode(Chat.self, from: data).id
            chatIDs[docID] = chatID
        }
        var request = try VoiceRequests.json(baseURL: baseURL, path: "api/chats/\(chatID)/messages",
                                            body: ["content": text, "doc_ids": [docID]])
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        return try await transport.answer(for: request, onEvent: onEvent)
    }

    /// nil requests AVSpeechSynthesizer playback.
    func speech(text: String) async throws -> Data? {
        let request = try VoiceRequests.json(baseURL: baseURL, path: "api/tts",
                                            body: ["text": String(text.prefix(1500))])
        let (data, response) = try await transport.data(for: request)
        try Self.validate(response)
        if VoiceRequests.usesDevice(data) { return nil }
        guard (response as? HTTPURLResponse)?.mimeType?.hasPrefix("audio/") == true else {
            throw VoiceError.message("The server returned no speech audio.")
        }
        return data
    }
}
