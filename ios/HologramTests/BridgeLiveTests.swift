import RealityKit
import WebKit
import XCTest
@testable import Hologram

final class BridgeLiveTests: XCTestCase {
    @MainActor
    func testInitialChatStateKeepsBridgeAnswerThenLaterLiveSelectionWins() async throws {
        let connection = FakeLiveConnection()
        connection.messages = [
            .string(#"{"type":"scene.state","doc_id":"fixture__ios","chat_id":"chat-a","hidden":["wall-001"],"highlighted":[],"labels":{}}"#),
            .string(#"{"type":"scene.highlight","doc_id":"fixture__ios","chat_id":"chat-a","item_ids":["window-002"]}"#),
            .string(#"{"type":"scene.state","doc_id":"fixture__ios","chat_id":"chat-a","hidden":[],"highlighted":["door-001"],"labels":{}}"#)
        ]
        let received = expectation(description: "Initial restore and later updates")
        received.expectedFulfillmentCount = 3
        var selections: [[String]] = []
        let socket = LiveSocket(makeConnection: { _ in connection })
        defer { socket.stop() }
        socket.onState = { state in
            if selections.isEmpty { XCTAssertEqual(state.hidden, ["wall-001"]) }
            selections.append(state.highlighted); received.fulfill()
        }
        socket.onHighlight = { request in selections.append(request.itemIDs); received.fulfill() }
        socket.start(docID: "fixture__ios", chatID: "chat-a", entryItemIDs: ["window-001", "door-001"])
        await fulfillment(of: [received], timeout: 2)
        XCTAssertEqual(selections, [["window-001", "door-001"], ["window-002"], ["door-001"]])
    }

    @MainActor
    func testBridgeHandlerPresentsRequestedDocumentAndPreservesItemOrder() throws {
        let router = ShellPresentation()
        let handler = WebShell.Coordinator(onARRequest: router.showAR)
        let body: [String: Any] = ["doc_id": "fixture__ios",
                                   "item_ids": ["window-001", "door-001"]]
        handler.handleMessage(name: "ar", body: body)
        let request = try XCTUnwrap(router.arRequest)
        XCTAssertEqual(request.docID, "fixture__ios")
        XCTAssertEqual(request.itemIDs, ["window-001", "door-001"])

        handler.handleMessage(name: "other", body: body)
        handler.handleMessage(name: "ar", body: ["doc_id": "", "item_ids": []])
        handler.handleMessage(name: "ar", body: ["doc_id": "other", "item_ids": [1]])
        handler.handleMessage(name: "ar", body: "invalid")
        XCTAssertEqual(router.arRequest, request, "Invalid messages must not change the presented scene")
        handler.handleMessage(name: "ar", body: ["doc_id": "second__doc", "item_ids": []])
        XCTAssertEqual(router.arRequest?.docID, "second__doc")
        XCTAssertEqual(router.arRequest?.itemIDs, [])
    }

    @MainActor
    func testToolbarUsesDemoUntilBridgeSelectionThenRemembersItAfterDismissal() throws {
        let router = ShellPresentation()
        router.showFromToolbar()
        XCTAssertEqual(router.arRequest?.docID, DemoScenes.all[0].id)
        XCTAssertNil(router.lastBridgeRequest)
        let handler = WebShell.Coordinator(onARRequest: router.showAR)
        handler.handleMessage(name: "ar", body: ["doc_id": "ifc_bench__ac20-arc", "item_ids": ["door-001", "door-002"]],
                              pageURL: URL(string: "http://localhost:4173/#/chat?chat=saved%2Fchat%26more"))
        let selection = try XCTUnwrap(router.arRequest)
        XCTAssertEqual(selection.chatID, "saved/chat&more")
        router.arRequest = nil
        router.showFromToolbar()
        XCTAssertEqual(router.arRequest, selection)
        XCTAssertEqual(router.lastBridgeRequest, selection)
    }

    @MainActor
    func testBridgeRejectsMalformedIDsAndUsesExplicitChatBeforePageContext() {
        let handler = WebShell.Coordinator { _ in XCTFail("Invalid payload routed") }
        let invalid: [Any] = [
            [:], ["doc_id": 1, "item_ids": []], ["doc_id": " \n", "item_ids": []],
            ["doc_id": "doc", "item_ids": ["valid", 1]], ["doc_id": "doc", "item_ids": [" "]],
            ["doc_id": "doc", "item_ids": [] as [String], "chat_id": 1],
            ["doc_id": "doc", "item_ids": NSNull()]
        ]
        for body in invalid { handler.handleMessage(name: "ar", body: body) }
        let request = ARRequest(body: ["doc_id": "doc", "item_ids": [], "chat_id": "explicit"],
                                pageURL: URL(string: "https://example.test/#/chat?chat=page"))
        XCTAssertEqual(request?.chatID, "explicit")
        XCTAssertNil(ARRequest(body: ["doc_id": "doc", "item_ids": []])?.chatID)
    }

    @MainActor
    func testScopedSocketJoinsDocumentAndChatAndRejectsOtherChatEvents() async throws {
        let connection = FakeLiveConnection()
        connection.messages = [
            .string(#"{"type":"scene.highlight","doc_id":"other","chat_id":"chat-a","item_ids":["wrong-doc"]}"#),
            .string(#"{"type":"scene.edit","doc_id":"fixture__ios","chat_id":"chat-b","op":"hide","item_ids":["door-001"]}"#),
            .string(#"{"type":"scene.state","doc_id":"fixture__ios","chat_id":"chat-a","hidden":["door-001"],"highlighted":["window-001"],"labels":{"window-001":"W1"}}"#),
            .string(#"{"type":"scene.edit","doc_id":"fixture__ios","chat_id":"chat-a","op":"restore","item_ids":["door-001"]}"#),
            .string(#"{"type":"scene.highlight","doc_id":"fixture__ios","item_ids":["window-002"]}"#)
        ]
        let received = expectation(description: "Scoped state, edit, highlight received")
        received.expectedFulfillmentCount = 3
        var order: [String] = []
        let socket = LiveSocket(apiURL: URL(string: "https://example.test")!, makeConnection: { url in
            let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
            XCTAssertEqual(components?.path, "/ws")
            XCTAssertEqual(components?.queryItems?.first { $0.name == "doc_id" }?.value, "fixture__ios")
            XCTAssertEqual(components?.queryItems?.first { $0.name == "chat_id" }?.value, "chat-a")
            return connection
        })
        defer { socket.stop() }
        socket.onState = { state in
            XCTAssertEqual(state.labels["window-001"], "W1")
            order.append("state"); received.fulfill()
        }
        socket.onEdit = { edit in
            XCTAssertEqual(edit.command.op, .restore)
            order.append("restore"); received.fulfill()
        }
        socket.onHighlight = { request in
            XCTAssertEqual(request.itemIDs, ["window-002"])
            order.append("highlight"); received.fulfill()
        }
        socket.start(docID: "fixture__ios", chatID: "chat-a")
        await fulfillment(of: [received], timeout: 2)
        XCTAssertEqual(order, ["state", "restore", "highlight"])
        await socket.sendHighlight(docID: "fixture__ios", itemIDs: ["door-001"])
        guard case .string(let text) = try XCTUnwrap(connection.sent.last) else {
            return XCTFail("Expected a JSON highlight")
        }
        let payload = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any])
        XCTAssertEqual(payload["chat_id"] as? String, "chat-a")
    }

    #if targetEnvironment(simulator)
    @MainActor
    func testSimulatorAppliesStateEditsAndHighlightForBridgeDocument() throws {
        let preview = SimulatorSceneMetadata()
        func apply(_ json: String) throws {
            preview.apply(try LiveSocket.decode(Data(json.utf8)), docID: "fixture__ios")
        }
        try apply(#"{"type":"scene.state","doc_id":"fixture__ios","hidden":["door-001"],"highlighted":["window-001"],"labels":{"window-001":"W1"}}"#)
        XCTAssertEqual(preview.hiddenItemIDs, ["door-001"])
        XCTAssertEqual(preview.itemIDs, ["window-001"])
        XCTAssertEqual(preview.labels, ["window-001": "W1"])
        try apply(#"{"type":"scene.edit","doc_id":"other","op":"reset","item_ids":[]}"#)
        XCTAssertEqual(preview.hiddenItemIDs, ["door-001"])
        try apply(#"{"type":"scene.edit","doc_id":"fixture__ios","op":"restore","item_ids":["door-001"]}"#)
        XCTAssertTrue(preview.hiddenItemIDs.isEmpty)
        try apply(#"{"type":"scene.highlight","doc_id":"fixture__ios","item_ids":["window-002"]}"#)
        XCTAssertEqual(preview.itemIDs, ["window-002"])
        XCTAssertTrue(preview.labels.isEmpty)
    }
    #endif

    func testLiveDecoderReadsHighlightsPingAndIgnoresOtherEvents() throws {
        let data = Data(#"{"type":"scene.highlight","doc_id":"fixture__ios","item_ids":["window-001","door-001"]}"#.utf8)
        XCTAssertEqual(try LiveSocket.decode(data), .highlight(ARRequest(
            docID: "fixture__ios", itemIDs: ["window-001", "door-001"])))
        XCTAssertEqual(try LiveSocket.decode(Data(#"{"type":"ping"}"#.utf8)), .ping)
        XCTAssertEqual(try LiveSocket.decode(Data(#"{"type":"chat.message","chat_id":"chat-1"}"#.utf8)), .ignored)
        XCTAssertEqual(try LiveSocket.decode(Data(#"{"type":"scene.highlight","doc_id":"fixture__ios"}"#.utf8)), .ignored)
        XCTAssertThrowsError(try LiveSocket.decode(Data("broken JSON".utf8)))
    }

    @MainActor
    func testMatchingLiveHighlightUpdatesSceneAndOtherDocumentIsIgnored() async throws {
        let controller = ARSceneController()
        await controller.load(url: nil, itemIDs: ["wall-001"])
        XCTAssertTrue(controller.isFixture)
        XCTAssertEqual(controller.activeDocID, "fixture__ios")
        let request = ARRequest(docID: "fixture__ios", itemIDs: ["window-001", "door-001"])
        XCTAssertTrue(controller.applyLiveHighlight(request))
        XCTAssertEqual(controller.highlightedItemIDs, request.itemIDs)
        let labels = try XCTUnwrap(controller.highlightController).labelsByItemID
        XCTAssertNotNil(labels["window-001"]?.findEntity(named: "1"))
        XCTAssertNotNil(labels["door-001"]?.findEntity(named: "2"))
        XCTAssertFalse(controller.applyLiveHighlight(ARRequest(docID: "another__doc", itemIDs: ["wall-002"])))
        XCTAssertEqual(controller.highlightedItemIDs, request.itemIDs)
        XCTAssertTrue(controller.applyLiveHighlight(ARRequest(docID: "fixture__ios", itemIDs: [])))
        XCTAssertTrue(controller.highlightedItemIDs.isEmpty)
        XCTAssertTrue(try XCTUnwrap(controller.highlightController).labelsByItemID.isEmpty)
    }

    @MainActor
    func testSocketDispatchesEditsAndJoinStateInReceiveOrder() async throws {
        let connection = FakeLiveConnection()
        connection.messages = [
            .string(#"{"type":"scene.state","doc_id":"fixture__ios","hidden":["door-001"],"highlighted":[],"labels":{}}"#),
            .string(#"{"type":"scene.edit","doc_id":"fixture__ios","op":"hide","item_ids":["window-001"],"edit_id":"1"}"#),
            .string(#"{"type":"scene.edit","doc_id":"fixture__ios","op":"restore","item_ids":["window-001"],"edit_id":"2"}"#)
        ]
        let received = expectation(description: "State, hide, restore received")
        received.expectedFulfillmentCount = 3
        var order: [String] = []
        let socket = LiveSocket(makeConnection: { _ in connection })
        defer { socket.stop() }
        socket.onState = { state in
            XCTAssertEqual(state.hidden, ["door-001"])
            order.append("state")
            received.fulfill()
        }
        socket.onEdit = { edit in
            XCTAssertEqual(edit.command.item_ids, ["window-001"])
            order.append(edit.command.op.rawValue)
            received.fulfill()
        }
        socket.start()
        await fulfillment(of: [received], timeout: 2)
        XCTAssertEqual(order, ["state", "hide", "restore"])
    }

    @MainActor
    func testSocketReceivesHighlightsRepliesToPingAndSendsSelection() async throws {
        let connection = FakeLiveConnection()
        let received = expectation(description: "Live highlight received")
        let sent = expectation(description: "Pong and selection sent")
        sent.expectedFulfillmentCount = 2
        connection.onSend = { _ in sent.fulfill() }
        let socket = LiveSocket(apiURL: URL(string: "https://example.test")!, makeConnection: { url in
            XCTAssertEqual(url.absoluteString, "wss://example.test/ws")
            return connection
        })
        defer { socket.stop() }
        socket.onHighlight = { request in
            XCTAssertEqual(request.docID, "fixture__ios")
            XCTAssertEqual(request.itemIDs, ["window-001"])
            received.fulfill()
        }
        socket.start()
        connection.messages = [
            .string(#"{"type":"ping"}"#),
            .data(Data(#"{"type":"scene.highlight","doc_id":"fixture__ios","item_ids":["window-001"]}"#.utf8))
        ]
        await fulfillment(of: [received], timeout: 2)
        await socket.sendHighlight(docID: "fixture__ios", itemIDs: ["door-001"])
        await fulfillment(of: [sent], timeout: 2)
        let payloads = try connection.sent.map { message -> [String: Any] in
            guard case .string(let text) = message else { throw TestError.unexpectedMessage }
            return try XCTUnwrap(JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any])
        }
        XCTAssertEqual(payloads[0]["type"] as? String, "pong")
        XCTAssertEqual(payloads[1]["type"] as? String, "scene.highlight")
        XCTAssertEqual(payloads[1]["doc_id"] as? String, "fixture__ios")
        XCTAssertEqual(payloads[1]["item_ids"] as? [String], ["door-001"])
        socket.stop()
        XCTAssertTrue(connection.closed)
    }

    func testConfigurationDerivesLocalAPIAndAcceptsExplicitDeploymentURL() {
        for host in ["localhost", "127.0.0.1", "192.168.1.5", "10.0.0.5", "172.20.0.2", "mac.local", "[::1]"] {
            let web = URL(string: "http://\(host):5173/chat?id=1")!
            let api = AppConfiguration.apiURL(webURL: web, configured: nil)
            XCTAssertEqual(api.port, 8000)
            XCTAssertEqual(api.host, web.host)
            XCTAssertEqual(api.path, "")
            XCTAssertNil(api.query)
        }
        let web = URL(string: "https://hologram.example/chat")!
        XCTAssertEqual(AppConfiguration.apiURL(webURL: web, configured: ""), URL(string: "https://hologram.example"))
        let explicit = "https://api.example"
        let api = AppConfiguration.apiURL(webURL: web, configured: explicit)
        XCTAssertEqual(api.absoluteString, explicit)
        XCTAssertEqual(AppConfiguration.socketURL(apiURL: api).absoluteString, "wss://api.example/ws")
        XCTAssertEqual(LiveSocket.reconnectDelay(failures: 0), 1)
        XCTAssertEqual(LiveSocket.reconnectDelay(failures: 1), 2)
        XCTAssertEqual(LiveSocket.reconnectDelay(failures: 100), 30)
    }

    private enum TestError: Error { case unexpectedMessage }
}

@MainActor
private final class FakeLiveConnection: LiveSocketConnection {
    var messages: [URLSessionWebSocketTask.Message] = []
    var sent: [URLSessionWebSocketTask.Message] = []
    var onSend: ((URLSessionWebSocketTask.Message) -> Void)?
    var closed = false
    private var pendingReceive: CheckedContinuation<URLSessionWebSocketTask.Message, Error>?

    func receive() async throws -> URLSessionWebSocketTask.Message {
        if !messages.isEmpty { return messages.removeFirst() }
        return try await withCheckedThrowingContinuation { pendingReceive = $0 }
    }

    func send(_ message: URLSessionWebSocketTask.Message) async throws {
        sent.append(message)
        onSend?(message)
    }

    func close() {
        closed = true
        pendingReceive?.resume(throwing: CancellationError())
        pendingReceive = nil
    }
}
