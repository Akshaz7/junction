import XCTest
@testable import Hologram

private final class AdviseStub: URLProtocol {
    nonisolated(unsafe) static var handler: ((URLRequest) -> (Int, Data))?
    nonisolated(unsafe) static var lastBody: [String: Any]?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        if let stream = request.httpBodyStream {
            stream.open()
            var data = Data()
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable {
                let n = stream.read(&buffer, maxLength: buffer.count)
                if n <= 0 { break }
                data.append(buffer, count: n)
            }
            Self.lastBody = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        } else if let body = request.httpBody {
            Self.lastBody = (try? JSONSerialization.jsonObject(with: body)) as? [String: Any]
        }
        let (status, data) = Self.handler?(request) ?? (500, Data())
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

/// I-29: hiding an item in AR (tap or voice) runs the same /api/advise rule check as the web edit panel.
@MainActor
final class AdvisorHideCheckTests: XCTestCase {
    private func controller() -> AdvisorCardsController {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [AdviseStub.self]
        let client = AdvisorClient(baseURL: URL(string: "http://example.test")!, session: URLSession(configuration: config))
        return AdvisorCardsController(client: client)
    }

    private let violation = """
    {"cards":[{"card_id":"adv:exits:Erdgeschoss:1","kind":"warning","title":"Fewer than two exits left on Erdgeschoss",
     "body":"Violation of 848/2017 §33.","item_ids":["door-34"],
     "source":{"type":"rule","ref":"fi-fire-exits-per-storey","title":"848/2017, 33 §","quote":"q"},
     "severity":"violation","checked":["fi-fire-exits-per-storey"]}]}
    """

    override func tearDown() { AdviseStub.handler = nil; AdviseStub.lastBody = nil }

    func testHidePostsTheSameEditBodyAsTheWebPanel() async throws {
        AdviseStub.handler = { [violation] _ in (200, Data(violation.utf8)) }
        let advisor = controller()
        await advisor.checkHide(itemIDs: ["door-34"], docID: "ifc_bench__ac20-arc", chatID: "chat-1")
        let body = try XCTUnwrap(AdviseStub.lastBody)
        XCTAssertEqual(body["doc_id"] as? String, "ifc_bench__ac20-arc")
        XCTAssertEqual(body["chat_id"] as? String, "chat-1")
        let edit = try XCTUnwrap(body["edit"] as? [String: Any])
        XCTAssertEqual(edit["op"] as? String, "hide")
        XCTAssertEqual(edit["item_ids"] as? [String], ["door-34"])
    }

    func testViolationCardIsSpotlightedAfterAHide() async {
        AdviseStub.handler = { [violation] _ in (200, Data(violation.utf8)) }
        let advisor = controller()
        await advisor.checkHide(itemIDs: ["door-34"], docID: "d", chatID: nil)
        XCTAssertEqual(advisor.spotlight?.level, .violation)
        XCTAssertEqual(advisor.status, .cards)
        XCTAssertNil(advisor.status.message)
        XCTAssertNil(AdviseStub.lastBody?["chat_id"])
    }

    func testEmptyResponseSaysCheckedNoIssues() async {
        AdviseStub.handler = { _ in (200, Data(#"{"cards":[]}"#.utf8)) }
        let advisor = controller()
        await advisor.checkHide(itemIDs: ["w1"], docID: "d", chatID: nil)
        XCTAssertEqual(advisor.status, .clear)
        XCTAssertTrue(advisor.status.message?.hasPrefix("Checked: no issues") ?? false)
        XCTAssertNil(advisor.spotlight)
    }

    func testServerErrorIsReportedNotSilent() async {
        AdviseStub.handler = { _ in (503, Data()) }
        let advisor = controller()
        await advisor.checkHide(itemIDs: ["w1"], docID: "d", chatID: nil)
        XCTAssertEqual(advisor.status, .unavailable)
        XCTAssertEqual(advisor.status.message, "Rule check unavailable. This edit was not checked.")
        XCTAssertTrue(advisor.cards.isEmpty)
    }

    func testUndoClearsTheStatusAndCards() async {
        AdviseStub.handler = { [violation] _ in (200, Data(violation.utf8)) }
        let advisor = controller()
        await advisor.checkHide(itemIDs: ["door-34"], docID: "d", chatID: nil)
        advisor.clearEditCards()
        XCTAssertEqual(advisor.status, .idle)
        XCTAssertNil(advisor.spotlight)
    }

    func testSecondHideSupersedesAnInFlightResult() async {
        AdviseStub.handler = { [violation] _ in (200, Data(violation.utf8)) }
        let advisor = controller()
        async let first: Void = advisor.checkHide(itemIDs: ["a"], docID: "d", chatID: nil)
        async let second: Void = advisor.checkHide(itemIDs: ["b"], docID: "d", chatID: nil)
        _ = await (first, second)
        XCTAssertEqual(advisor.status, .cards)
    }

    func testEmptyItemListDoesNothing() async {
        let advisor = controller()
        await advisor.checkHide(itemIDs: [], docID: "d", chatID: nil)
        XCTAssertEqual(advisor.status, .idle)
    }
}
