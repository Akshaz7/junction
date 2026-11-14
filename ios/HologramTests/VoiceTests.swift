import XCTest
@testable import Hologram

final class VoiceTests: XCTestCase {
    private static let answerJSON = #"{"answer":{"text_md":"There are **two windows**. [1]"},"evidence":{"boxes":[{"item_id":"window-002","label":"8"},{"item_id":"window-001","label":"3"},{"item_id":"door-001","label":"9"}],"scene":{"doc_id":"fixture__ios","highlight_item_ids":["window-001","window-002"],"camera_target_item_id":"window-002"}}}"#

    private static var stream: String {
        ": heartbeat\r\nevent: status\r\ndata: {\"text\":\"Thinking…\"}\r\n\r\n"
        + "event: trace\ndata: {\"step\":\"route\",\"detail\":\"count / window -> plan map\"}\n\n"
        + "event: answer\ndata: \(answerJSON)\n\n"
    }

    func testMultipartPreservesAudioAndNamesFileWithAcceptedMIMEType() throws {
        let audio = Data([0, 255, 13, 10, 42])
        let request = VoiceRequests.speechIntent(baseURL: URL(string: "https://api.example")!,
                                                 audio: audio, boundary: "test-boundary")
        XCTAssertEqual(request.url?.absoluteString, "https://api.example/api/speech-intent")
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Content-Type"), "multipart/form-data; boundary=test-boundary")
        var expected = Data("--test-boundary\r\nContent-Disposition: form-data; name=\"file\"; filename=\"question.m4a\"\r\nContent-Type: audio/mp4\r\n\r\n".utf8)
        expected.append(audio)
        expected.append(Data("\r\n--test-boundary--\r\n".utf8))
        XCTAssertEqual(request.httpBody, expected)
    }

    func testSSEParsesStatusTraceAndAnswerWithCRLFAndComments() throws {
        var parser = VoiceSSEParser()
        let events = try Self.stream.components(separatedBy: "\n").compactMap { try parser.consume($0) }
        XCTAssertEqual(events.count, 3)
        XCTAssertEqual(events[0], .status("Thinking…"))
        XCTAssertEqual(events[1], .trace("count / window -> plan map"))
        guard case .answer(let answer) = events[2] else { return XCTFail("Missing answer") }
        XCTAssertEqual(answer.answer.text_md, "There are **two windows**. [1]")
        XCTAssertEqual(answer.highlightLabels, ["window-001": "3", "window-002": "8"])
        XCTAssertNil(try parser.finish())
    }

    func testSSEHandlesMultilineDataAndFinalEventWithoutBlankLine() throws {
        var parser = VoiceSSEParser()
        XCTAssertNil(try parser.consume("event: status"))
        XCTAssertNil(try parser.consume("data: {"))
        XCTAssertNil(try parser.consume("data: \"text\": \"Exploring document\"}"))
        XCTAssertEqual(try parser.finish(), .status("Exploring document"))
        _ = try parser.consume("event: error")
        _ = try parser.consume(#"data: {"detail":"No drawing available"}"#)
        XCTAssertThrowsError(try parser.consume("")) { error in
            XCTAssertEqual(error.localizedDescription, "No drawing available")
        }
    }

    func testFallbackDecisionOnlyUsesExplicitDeviceResponse() {
        XCTAssertTrue(VoiceRequests.usesDevice(Data(#"{"fallback":"device","reason":"No Gemini key"}"#.utf8)))
        XCTAssertFalse(VoiceRequests.usesDevice(Data(#"{"text":"ask a question"}"#.utf8)))
        XCTAssertFalse(VoiceRequests.usesDevice(Data(#"{"fallback":"server"}"#.utf8)))
        XCTAssertFalse(VoiceRequests.usesDevice(Data([0, 255, 7])))
    }

    @MainActor
    func testURLTransportReadsActualAsyncByteLinesWithoutNetwork() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [VoiceStreamURLProtocol.self]
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        VoiceStreamURLProtocol.responseData = Data(Self.stream.utf8)
        let transport = URLVoiceTransport(session: session)
        let request = URLRequest(url: URL(string: "https://voice.test/stream")!)
        var events: [VoiceEvent] = []
        let answer = try await transport.answer(for: request) { events.append($0) }
        XCTAssertEqual(events.count, 3)
        XCTAssertEqual(events.first, .status("Thinking…"))
        XCTAssertEqual(answer.highlightLabels["window-002"], "8")
    }

    @MainActor
    func testDeviceTranscriptReachesChatWithARDocumentAndReusesCreatedChat() async throws {
        let transport = FakeVoiceTransport(stream: Self.stream)
        let client = VoiceClient(baseURL: URL(string: "https://api.example")!, transport: transport)
        let transcript = try await client.transcribe(audio: Data([1, 2, 3]))
        XCTAssertNil(transcript, "Server fallback selects device transcription")
        // The device supplies this text; no speech recognizer or microphone runs in tests.
        let deviceTranscript = "How many windows are there?"
        var events: [VoiceEvent] = []
        let answer = try await client.ask(deviceTranscript, docID: "fixture__ios") { events.append($0) }
        XCTAssertEqual(events.count, 3)
        XCTAssertEqual(answer.highlightLabels["window-002"], "8")
        let speech = try await client.speech(text: "There are two windows.")
        XCTAssertNil(speech, "TTS fallback selects AVSpeechSynthesizer")
        _ = try await client.ask("Where are they?", docID: "fixture__ios") { _ in }

        XCTAssertEqual(transport.requests.map { $0.url!.path }, [
            "/api/speech-intent", "/api/chats", "/api/chats/chat-1/messages", "/api/tts", "/api/chats/chat-1/messages"
        ])
        let create = try XCTUnwrap(JSONSerialization.jsonObject(with: XCTUnwrap(transport.requests[1].httpBody)) as? [String: Any])
        XCTAssertEqual(create["doc_ids"] as? [String], ["fixture__ios"])
        let message = try XCTUnwrap(JSONSerialization.jsonObject(with: XCTUnwrap(transport.requests[2].httpBody)) as? [String: Any])
        XCTAssertEqual(message["content"] as? String, deviceTranscript)
        XCTAssertEqual(message["doc_ids"] as? [String], ["fixture__ios"])
        XCTAssertEqual(transport.requests[2].value(forHTTPHeaderField: "Accept"), "text/event-stream")
    }

    @MainActor
    func testServerTranscriptAndAudioAndHTTPFailure() async throws {
        let transport = FakeVoiceTransport(stream: Self.stream)
        transport.deviceFallback = false
        let client = VoiceClient(baseURL: URL(string: "https://api.example")!, transport: transport)
        let text = try await client.transcribe(audio: Data([1]))
        XCTAssertEqual(text, "Where are the windows?")
        let audio = try await client.speech(text: "Two windows.")
        XCTAssertEqual(audio, Data([1, 2, 3]))
        transport.statusCode = 503
        do {
            _ = try await client.transcribe(audio: Data([1]))
            XCTFail("HTTP failure must not be interpreted as device fallback")
        } catch { XCTAssertTrue(error.localizedDescription.contains("503")) }
    }

    @MainActor
    func testVoiceAnswerPreservesBoxNumbersAndRejectsAnotherDocument() async throws {
        let controller = ARSceneController()
        await controller.load(url: nil)
        let answer = try JSONDecoder().decode(VoiceAnswer.self, from: Data(Self.answerJSON.utf8))
        XCTAssertTrue(controller.applyVoiceAnswer(answer))
        XCTAssertEqual(controller.highlightedItemIDs, ["window-001", "window-002"])
        XCTAssertEqual(controller.targetItemID, "window-002")
        let labels = try XCTUnwrap(controller.highlightController).labelsByItemID
        XCTAssertNotNil(labels["window-001"]?.findEntity(named: "3"))
        XCTAssertNotNil(labels["window-002"]?.findEntity(named: "8"))
        XCTAssertNil(labels["door-001"])
        let other = try JSONDecoder().decode(VoiceAnswer.self, from: Data(Self.answerJSON.replacingOccurrences(of: "fixture__ios", with: "other__doc").utf8))
        XCTAssertFalse(controller.applyVoiceAnswer(other))
        XCTAssertEqual(controller.highlightedItemIDs, ["window-001", "window-002"])
        XCTAssertEqual(ARVoiceController.spokenText(answer.answer.text_md), "There are two windows. ")
    }
}

private final class VoiceStreamURLProtocol: URLProtocol {
    static var responseData = Data()
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil,
                                       headerFields: ["Content-Type": "text/event-stream"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        // Deliberately split inside UTF-8 and SSE field boundaries.
        for byte in Self.responseData { client?.urlProtocol(self, didLoad: Data([byte])) }
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@MainActor
private final class FakeVoiceTransport: VoiceTransport {
    var requests: [URLRequest] = []
    var deviceFallback = true
    var statusCode = 200
    let stream: String
    init(stream: String) { self.stream = stream }

    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        requests.append(request)
        let path = request.url!.path
        let body: Data
        let mime: String
        switch path {
        case "/api/chats":
            body = Data(#"{"id":"chat-1"}"#.utf8)
            mime = "application/json"
        case "/api/speech-intent" where !deviceFallback:
            body = Data(#"{"text":"Where are the windows?","intent":"ask","provider":"gemini"}"#.utf8)
            mime = "application/json"
        case "/api/tts" where !deviceFallback:
            body = Data([1, 2, 3])
            mime = "audio/mpeg"
        default:
            body = Data(#"{"fallback":"device","reason":"No key"}"#.utf8)
            mime = "application/json"
        }
        return (body, HTTPURLResponse(url: request.url!, statusCode: statusCode, httpVersion: nil,
                                      headerFields: ["Content-Type": mime])!)
    }

    func answer(for request: URLRequest, onEvent: (VoiceEvent) -> Void) async throws -> VoiceAnswer {
        requests.append(request)
        var parser = VoiceSSEParser()
        for line in stream.components(separatedBy: "\n") {
            if let event = try parser.consume(line) {
                onEvent(event)
                if case .answer(let answer) = event { return answer }
            }
        }
        throw VoiceError.message("Missing test answer")
    }
}
