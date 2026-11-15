import RealityKit
import XCTest
@testable import Hologram

final class AdvisorCardTests: XCTestCase {
    private func fixtureURL() throws -> URL {
        try XCTUnwrap(Bundle(for: Self.self).url(forResource: "advisor_cards", withExtension: "json"))
    }

    private func fixture() throws -> Data { try Data(contentsOf: fixtureURL()) }

    private func eventData(docID: String = "fixture__ios") throws -> Data {
        var json = try XCTUnwrap(JSONSerialization.jsonObject(with: fixture()) as? [String: Any])
        json["type"] = "advisor.cards"
        json["doc_id"] = docID
        json["chat_id"] = "chat-demo"
        return try JSONSerialization.data(withJSONObject: json)
    }

    func testFixtureDropsMissingSourceAndPreservesContractFieldsAndCodableRoundTrip() throws {
        let response = try JSONDecoder().decode(AdvisorCardsResponse.self, from: fixture())
        XCTAssertEqual(response.cards.map(\.id), ["demo-door", "demo-windows"])
        let card = try XCTUnwrap(response.cards.first)
        XCTAssertEqual(card.kind, .warning)
        XCTAssertEqual(card.item_ids, ["door-001"])
        XCTAssertEqual(card.source.type, .document)
        XCTAssertEqual(card.source.ref, "fixture__ios+page1")
        XCTAssertEqual(card.source.title, "Sample door note · generated for demo")
        XCTAssertEqual(card.source.quote, "Review door D1 in this generated demonstration scene.")
        XCTAssertEqual(try JSONDecoder().decode(AdvisorCard.self, from: JSONEncoder().encode(card)), card)
        var json = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(card)) as? [String: Any])
        json.removeValue(forKey: "source")
        XCTAssertThrowsError(try JSONDecoder().decode(AdvisorCard.self, from: JSONSerialization.data(withJSONObject: json)))
    }

    func testNullSourcesAreDroppedAndOnlyThreeUniqueSupportedCardsSurvive() throws {
        let supported = try JSONDecoder().decode(AdvisorCardsResponse.self, from: fixture()).cards[0]
        let original = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(supported)) as? [String: Any])
        var missing = original
        missing["source"] = NSNull()
        var cards: [[String: Any]] = [missing, original]
        for index in 1...4 {
            var card = original
            card["card_id"] = "demo-\(index)"
            cards.append(card)
        }
        cards.insert(original, at: 2)
        let response = try JSONDecoder().decode(AdvisorCardsResponse.self,
            from: JSONSerialization.data(withJSONObject: ["cards": cards]))
        XCTAssertEqual(response.cards.map(\.id), ["demo-door", "demo-1", "demo-2"])
    }

    func testAllKindsAndSourceTypesDecode() throws {
        let source = try JSONDecoder().decode(AdvisorCardsResponse.self, from: fixture()).cards[0]
        for (kind, sourceType) in [("warning", "rule"), ("option", "material_table"), ("info", "document")] {
            var json = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(source)) as? [String: Any])
            json["kind"] = kind
            json["source"] = ["type": sourceType, "ref": "generated-demo", "title": "Generated for demo", "quote": "Generated for demo"]
            let card = try JSONDecoder().decode(AdvisorCard.self, from: JSONSerialization.data(withJSONObject: json))
            XCTAssertEqual(card.kind.rawValue, kind)
            XCTAssertEqual(card.source.type.rawValue, sourceType)
        }
    }

    func testSourceURLAndSectionAreOptionalAndOnlyHTTPLinksAreShown() throws {
        let base = try JSONDecoder().decode(AdvisorCardsResponse.self, from: fixture()).cards[0]
        var json = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(base)) as? [String: Any])
        let fullQuote = String(repeating: "Each evacuation area shall have exits. ", count: 20)

        // Without url/section (older servers): decodes, no link.
        json["source"] = ["type": "rule", "ref": "fi-fire-exits-per-storey", "title": "848/2017, 33 §", "quote": "q"]
        let plain = try JSONDecoder().decode(AdvisorCard.self, from: JSONSerialization.data(withJSONObject: json))
        XCTAssertNil(plain.source.url)
        XCTAssertNil(plain.source.section)
        XCTAssertNil(plain.source.linkURL)

        // With url/section and a full (uncut) quote.
        let link = "https://technical-regulation-information-system.ec.europa.eu/en/notification/18529/text/F/EN"
        json["source"] = ["type": "rule", "ref": "fi-fire-exits-per-storey", "title": "848/2017, 33 §",
                          "quote": fullQuote, "url": link, "section": "33 §"]
        let linked = try JSONDecoder().decode(AdvisorCard.self, from: JSONSerialization.data(withJSONObject: json))
        XCTAssertEqual(linked.source.url, link)
        XCTAssertEqual(linked.source.section, "33 §")
        XCTAssertEqual(linked.source.quote, fullQuote)
        XCTAssertEqual(linked.source.linkURL, URL(string: link))
        XCTAssertEqual(try JSONDecoder().decode(AdvisorCard.self, from: JSONEncoder().encode(linked)), linked)

        // Explicit null and non-http(s) URLs decode but never become links.
        let badURLs: [Any] = [NSNull(), "javascript:alert(1)", "ftp://example.com/x", "not a url", ""]
        for bad in badURLs {
            json["source"] = ["type": "rule", "ref": "r", "title": "t", "quote": "q", "url": bad]
            let card = try JSONDecoder().decode(AdvisorCard.self, from: JSONSerialization.data(withJSONObject: json))
            XCTAssertNil(card.source.linkURL, "\(bad)")
        }
    }

    @MainActor
    func testLiveSocketDecodesDispatchesAndFiltersAdvisorCardsByDocument() async throws {
        let data = try eventData()
        guard case .advisorCards(let event) = try LiveSocket.decode(data) else {
            return XCTFail("Expected advisor.cards command")
        }
        XCTAssertEqual(event.chat_id, "chat-demo")
        XCTAssertEqual(event.cards.count, 2)
        XCTAssertEqual(try LiveSocket.decode(eventData(docID: "")), .ignored)

        let advisor = AdvisorCardsController()
        await advisor.load(docID: "fixture__ios", fixtureURL: try fixtureURL())
        let other = try JSONDecoder().decode(AdvisorCardsEvent.self,
            from: Data(#"{"doc_id":"other","cards":[]}"#.utf8))
        advisor.receive(other)
        XCTAssertEqual(advisor.docID, "fixture__ios")
        XCTAssertEqual(advisor.cards.map(\.id), ["demo-door", "demo-windows"])

        let received = expectation(description: "Advisor event reaches its callback")
        let connection = AdvisorLiveConnection(data: data)
        let socket = LiveSocket(makeConnection: { _ in connection })
        defer { socket.stop() }
        socket.onAdvisorCards = { update in
            XCTAssertEqual(update, event)
            advisor.receive(update)
            received.fulfill()
        }
        socket.start()
        await fulfillment(of: [received], timeout: 2)
        XCTAssertEqual(advisor.cards, event.cards)
    }

    @MainActor
    func testCardTapUsesExistingHighlightPathAndShowsManifestTags() async throws {
        let bundle = Bundle(for: Self.self)
        let manifestURL = try XCTUnwrap(bundle.url(forResource: "fixture.scene", withExtension: "json"))
        var json = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: manifestURL)) as? [String: Any])
        var items = try XCTUnwrap(json["items"] as? [String: [String: Any]])
        items["window-001"]?["tag"] = "W1"
        items["window-002"]?["tag"] = "W2"
        json["items"] = items
        let taggedManifest = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        try JSONSerialization.data(withJSONObject: json).write(to: taggedManifest)
        defer { try? FileManager.default.removeItem(at: taggedManifest) }
        let model = try XCTUnwrap(bundle.url(forResource: "fixture", withExtension: "usdz"))
        let scene = ARSceneController()
        await scene.load(url: model, manifestURL: taggedManifest)
        let advisor = AdvisorCardsController()
        await advisor.load(docID: "fixture__ios", fixtureURL: try fixtureURL())
        let card = try XCTUnwrap(advisor.cards.last)
        XCTAssertTrue(advisor.select(card) { request in
            XCTAssertTrue(scene.applyLiveHighlight(request))
        })
        XCTAssertEqual(scene.highlightedItemIDs, ["window-001", "window-002"])
        let labels = try XCTUnwrap(scene.highlightController).labelsByItemID
        XCTAssertNotNil(labels["window-001"]?.findEntity(named: "W1"))
        XCTAssertNotNil(labels["window-002"]?.findEntity(named: "W2"))
        XCTAssertNil(labels["door-001"])

        // A card from a prior scene must no longer be selectable after replacement.
        let empty = Data(#"{"doc_id":"fixture__ios","cards":[]}"#.utf8)
        advisor.receive(try JSONDecoder().decode(AdvisorCardsEvent.self, from: empty))
        XCTAssertFalse(advisor.select(card) { _ in XCTFail("Stale card must not highlight") })
    }

    @MainActor
    func testAdvisePOSTDecodesSupportedCardsAndRejectsHTTPFailure() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [AdvisorURLProtocol.self]
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        AdvisorURLProtocol.responseData = try fixture()
        AdvisorURLProtocol.statusCode = 200
        let client = AdvisorClient(baseURL: URL(string: "https://advisor.test")!, session: session)
        let response = try await client.advise(docID: "fixture__ios")
        XCTAssertEqual(response.cards.count, 2)
        let request = try XCTUnwrap(AdvisorURLProtocol.lastRequest)
        XCTAssertEqual(request.url?.path, "/api/advise")
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Content-Type"), "application/json")
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: AdvisorURLProtocol.requestBody) as? [String: String])
        XCTAssertEqual(body, ["doc_id": "fixture__ios"])
        AdvisorURLProtocol.statusCode = 503
        do {
            _ = try await client.advise(docID: "fixture__ios")
            XCTFail("HTTP failure must not produce cards")
        } catch { XCTAssertEqual((error as? URLError)?.code, .badServerResponse) }
    }
}

@MainActor
private final class AdvisorLiveConnection: LiveSocketConnection {
    private var data: Data?
    private var pending: CheckedContinuation<URLSessionWebSocketTask.Message, Error>?
    init(data: Data) { self.data = data }
    func receive() async throws -> URLSessionWebSocketTask.Message {
        if let data {
            self.data = nil
            return .data(data)
        }
        return try await withCheckedThrowingContinuation { pending = $0 }
    }
    func send(_ message: URLSessionWebSocketTask.Message) async throws {}
    func close() {
        pending?.resume(throwing: CancellationError())
        pending = nil
    }
}

private final class AdvisorURLProtocol: URLProtocol {
    static var responseData = Data()
    static var statusCode = 200
    static var lastRequest: URLRequest?
    static var requestBody = Data()
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.lastRequest = request
        Self.requestBody = request.httpBody ?? Data()
        if let stream = request.httpBodyStream {
            stream.open()
            defer { stream.close() }
            var buffer = [UInt8](repeating: 0, count: 1024)
            while stream.hasBytesAvailable {
                let count = stream.read(&buffer, maxLength: buffer.count)
                if count <= 0 { break }
                Self.requestBody.append(contentsOf: buffer.prefix(count))
            }
        }
        let response = HTTPURLResponse(url: request.url!, statusCode: Self.statusCode,
            httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Self.responseData)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
