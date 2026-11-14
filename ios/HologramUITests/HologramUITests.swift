import XCTest

final class HologramUITests: XCTestCase {
    private let docID = "ifc_bench__ac20-arc"
    // First two doors sorted by item_id in the bundled AC20 scene.json.
    private let doorIDs = ["00RjztLorCQgcGEHv7fY3g", "08uaDJHLH3FAZ6Hg9FwzkG"]

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testAdvisorFixtureShowsOnlySourcedCardsAndTapHighlightsItems() throws {
        let app = configuredApp()
        app.launchArguments += ["-ADVISOR_FIXTURE", "advisor_cards"]
        app.launch()
        defer { app.terminate() }

        #if targetEnvironment(simulator)
        XCTAssertTrue(app.staticTexts["simulator-ar-fallback"].waitForExistence(timeout: 10),
                      "The fixture launch must open the native scene without a toolbar tap")
        #endif
        let door = app.buttons["advisor-card-demo-door"]
        let windows = app.buttons["advisor-card-demo-windows"]
        XCTAssertTrue(door.waitForExistence(timeout: 10))
        XCTAssertTrue(windows.waitForExistence(timeout: 5))
        let cards = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "advisor-card-"))
        XCTAssertEqual(cards.count, 2)
        XCTAssertFalse(app.buttons["advisor-card-demo-unsupported"].exists)
        XCTAssertFalse(app.staticTexts["Unsupported claim · generated for demo"].exists)

        windows.tap()
        #if targetEnvironment(simulator)
        let first = app.staticTexts["highlighted-item-1"]
        XCTAssertTrue(first.waitForExistence(timeout: 5))
        XCTAssertEqual(first.label, "1 · window-001")
        XCTAssertEqual(app.staticTexts["highlighted-item-2"].label, "2 · window-002")
        #endif
        let source = app.buttons["advisor-source-demo-windows"]
        let quote = app.staticTexts["advisor-source-quote-demo-windows"]
        XCTAssertEqual(source.value as? String, "Collapsed")
        XCTAssertFalse(quote.exists)
        source.tap()
        XCTAssertTrue(quote.waitForExistence(timeout: 5))
        XCTAssertEqual(quote.label, "Compare windows W1 and W2 in this generated demonstration scene.")
        source.tap()
        XCTAssertFalse(quote.exists)
    }

    @MainActor
    func testBridgeOpensFloorPlanAndKeepsAnswerAfterEmptyChatRestore() throws {
        let app = configuredApp()
        let floorPlanID = "cubicasa5k__colorful-11397"
        let payload = try JSONSerialization.data(withJSONObject: [
            "doc_id": floorPlanID, "item_ids": ["window-001", "window-002"],
            "chat_id": UUID().uuidString
        ])
        app.launchArguments += ["-AR_BRIDGE_MESSAGE", String(decoding: payload, as: UTF8.self)]
        app.launch()
        defer { app.terminate() }
        let document = app.staticTexts["ar-document-id"]
        XCTAssertTrue(document.waitForExistence(timeout: 30))
        XCTAssertEqual(document.label, floorPlanID)
        XCTAssertTrue(app.staticTexts["scene-credit"].waitForExistence(timeout: 20))
        XCTAssertTrue(app.staticTexts["scene-credit"].label.contains("CubiCasa5K"))
        XCTAssertFalse(app.staticTexts["scene-name"].label.contains("AC20"))
        XCTAssertEqual(app.staticTexts["ar-status"].label, "Scene metadata loaded from the API.")
        XCTAssertEqual(app.staticTexts["highlighted-item-1"].label, "1 · window-001")
        XCTAssertEqual(app.staticTexts["highlighted-item-2"].label, "2 · window-002")
        attachScreenshot("06 - Requested floor plan and answer highlights", app: app)
    }

    @MainActor
    func testLocalWebShellAndNativeDemoScene() throws {
        let app = configuredApp()
        app.launch()
        defer { app.terminate() }
        let web = app.webViews["web-shell"]
        XCTAssertTrue(web.waitForExistence(timeout: 15), "The app must create its WKWebView")
        XCTAssertTrue(web.staticTexts["Where shall we start?"].waitForExistence(timeout: 30),
                      "Start the local web app on port 4173 (or set WEB_URL for the test runner)")
        attachScreenshot("01 - Local web chat starter", app: app)

        app.buttons["Show on table"].tap()
        let picker = app.buttons["demo-scenes-picker"]
        XCTAssertTrue(picker.waitForExistence(timeout: 10))
        picker.tap()
        let ac20 = app.buttons["AC20 · IFC building"]
        XCTAssertTrue(ac20.waitForExistence(timeout: 5))
        attachScreenshot("02 - Native demo scenes picker", app: app)
        ac20.tap()

        assertAC20Metadata(app)
        attachScreenshot("03 - AC20 simulator fallback and credit", app: app)
    }

    @MainActor
    func testJavaScriptBridgeOpensRequestedSceneWithTwoDoors() throws {
        let app = configuredApp()
        let payload = try JSONSerialization.data(withJSONObject: ["doc_id": docID, "item_ids": doorIDs])
        app.launchArguments += ["-AR_BRIDGE_MESSAGE", String(decoding: payload, as: UTF8.self)]
        app.launch()
        defer { app.terminate() }

        // didFinish evaluates JavaScript that posts to the real WKScriptMessage handler.
        let document = app.staticTexts["ar-document-id"]
        XCTAssertTrue(document.waitForExistence(timeout: 30), "The WebKit AR bridge must present the native route")
        XCTAssertEqual(document.label, docID)
        attachScreenshot("04 - Bridge opened AC20 route", app: app)
        assertAC20Metadata(app)
        for (index, itemID) in doorIDs.enumerated() {
            let item = app.staticTexts["highlighted-item-\(index + 1)"]
            XCTAssertTrue(item.waitForExistence(timeout: 5))
            XCTAssertEqual(item.label, "\(index + 1) · \(itemID)")
        }
        XCTAssertFalse(app.staticTexts["highlighted-item-3"].exists)
        attachScreenshot("05 - Bridge selection and scene credit", app: app)

        app.buttons["Done"].tap()
        waitForWebReturn(app)
        // Open and close the same native route while retaining the mounted WKWebView.
        app.navigationBars.buttons["Show on table"].tap()
        XCTAssertTrue(document.waitForExistence(timeout: 10))
        XCTAssertEqual(document.label, docID)
        for (index, itemID) in doorIDs.enumerated() {
            let item = app.staticTexts["highlighted-item-\(index + 1)"]
            XCTAssertTrue(item.waitForExistence(timeout: 10))
            XCTAssertEqual(item.label, "\(index + 1) · \(itemID)")
        }
        app.buttons["Done"].tap()
        waitForWebReturn(app)
        XCTAssertTrue(app.webViews["web-shell"].staticTexts["Where shall we start?"].waitForExistence(timeout: 10))
    }

    @MainActor
    func testUnsentWebDraftSurvivesNativeARRoundTrip() throws {
        let app = configuredApp()
        app.launchArguments += ["-UITEST"]
        app.launch()
        defer { app.terminate() }
        try enterUnsentDraft("Keep this unsent draft", app: app)
        let before = try inspectWebState(app)
        attachWebState(before, name: "Before native AR", app: app)
        XCTAssertEqual(before["draft"] as? String, "Keep this unsent draft")
        XCTAssertEqual(before["composerVisible"] as? Bool, true)
        XCTAssertEqual(before["composerEnabled"] as? Bool, true)
        let route = try XCTUnwrap(before["href"] as? String)
        let timeOrigin = try XCTUnwrap(before["timeOrigin"] as? Double)

        app.navigationBars.buttons["Show on table"].tap()
        XCTAssertTrue(app.staticTexts["ar-document-id"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.staticTexts["ar-document-id"].label, docID)
        app.buttons["Done"].tap()
        waitForWebReturn(app)

        // Read the actual DOM through the retained session. WebKit may rebuild
        // its AX tree across AR, so no composer AX element crosses that boundary.
        let after = try inspectWebState(app)
        attachWebState(after, name: "After native AR", app: app)
        XCTAssertEqual(after["draft"] as? String, "Keep this unsent draft")
        XCTAssertEqual(after["composerVisible"] as? Bool, true, "Viewport facts: \(after)")
        XCTAssertEqual(after["composerEnabled"] as? Bool, true)
        XCTAssertEqual(after["href"] as? String, route, "AR must preserve the web route/chat")
        XCTAssertEqual(after["timeOrigin"] as? Double, timeOrigin, "AR must never reload the page")
        let beforeViewport = try XCTUnwrap(before["visualViewport"] as? [String: Any])
        let afterViewport = try XCTUnwrap(after["visualViewport"] as? [String: Any])
        for (name, state) in [("Before AR", before), ("After AR", after)] {
            let viewport = try XCTUnwrap(state["visualViewport"] as? [String: Any])
            let native = try XCTUnwrap(state["native"] as? [String: Any])
            XCTAssertEqual(try XCTUnwrap(viewport["scale"] as? Double), 1, accuracy: 0.05,
                           "\(name): the page must use the device-width scale. \(state)")
            XCTAssertEqual(try XCTUnwrap(native["zoomScale"] as? Double), 1, accuracy: 0.05,
                           "\(name): native WebKit zoom must remain pinned. \(state)")
        }
        XCTAssertEqual(try XCTUnwrap(afterViewport["scale"] as? Double),
                       try XCTUnwrap(beforeViewport["scale"] as? Double), accuracy: 0.05,
                       "The native cover must not enlarge the retained web page")

        // A visible, enabled input must also accept focus after returning.
        let web = app.webViews["web-shell"]
        let composer = try XCTUnwrap(editableComposer(in: web), composerFrames(in: web))
        composer.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5))
    }

    @MainActor
    private func enterUnsentDraft(_ draft: String, app: XCUIApplication) throws {
        let web = app.webViews["web-shell"]
        XCTAssertTrue(web.waitForExistence(timeout: 15))
        XCTAssertTrue(web.staticTexts["Where shall we start?"].waitForExistence(timeout: 30))
        let composer = try XCTUnwrap(editableComposer(in: web), composerFrames(in: web))
        // WebKit's ARIA combobox may have no suggested accessibility hit point.
        // Its visible input frame still supplies a concrete place to focus it.
        composer.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5),
                      "The visible composer must focus. \(composerFrames(in: web))")
        app.typeText(draft)
    }

    @MainActor
    private func inspectWebState(_ app: XCUIApplication) throws -> [String: Any] {
        let probe = app.navigationBars.buttons["inspect-web-state"]
        XCTAssertTrue(probe.waitForExistence(timeout: 10))
        let previous = probe.value as? String ?? "idle"
        probe.tap()
        let read = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "value BEGINSWITH %@ AND value != %@", "{", previous),
            object: probe)
        XCTAssertEqual(XCTWaiter.wait(for: [read], timeout: 10), .completed,
                       "The native probe must read the live DOM: \(probe.value ?? "no state")")
        let json = try XCTUnwrap(probe.value as? String)
        return try XCTUnwrap(JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: Any])
    }

    @MainActor
    private func composerCandidates(in web: XCUIElement) -> [XCUIElement] {
        let placeholder = "Ask anything. Type @ to include a document"
        let matches = web.descendants(matching: .any).matching(NSPredicate(
            format: "label == %@ OR placeholderValue == %@",
            "Ask about your drawings", placeholder))
        return matches.allElementsBoundByIndex
    }

    @MainActor
    private func editableComposer(in web: XCUIElement) -> XCUIElement? {
        let candidates = composerCandidates(in: web)
        // Prefer native editable types. ARIA role=combobox can expose the actual
        // textarea as comboBox/other, but the 2x2 sr-only label must never qualify.
        for type: XCUIElement.ElementType in [.textView, .textField, .comboBox, .other] {
            if let input = candidates.first(where: {
                let frame = $0.frame
                let visibleFrame = frame.intersection(web.frame)
                return $0.elementType == type && frame.width > 100 && frame.height > 20
                    && visibleFrame.width > 100 && visibleFrame.height > 20
            }) {
                return input
            }
        }
        return nil
    }

    @MainActor
    private func composerFrames(in web: XCUIElement) -> String {
        "Web frame: \(web.frame); composer frames: \(composerCandidates(in: web).map { String(describing: $0.frame) }.joined(separator: ", "))"
    }

    @MainActor
    private func waitForWebReturn(_ app: XCUIApplication) {
        XCTAssertTrue(app.staticTexts["ar-document-id"].waitForNonExistence(timeout: 10),
                      "AR must finish dismissing")
        XCTAssertTrue(app.navigationBars.buttons["Show on table"].waitForExistence(timeout: 10))
        // Always create a new query after dismissal; never poll stale WebKit AX
        // elements inside an NSPredicate closure.
        XCTAssertTrue(app.webViews["web-shell"].waitForExistence(timeout: 10))
    }

    @MainActor
    private func configuredApp() -> XCUIApplication {
        let app = XCUIApplication()
        let environment = ProcessInfo.processInfo.environment
        // Start on Chat regardless of the phone's default tab; avoid navigating through Data.
        var webURL = URLComponents(string: environment["WEB_URL"] ?? "http://localhost:4173")!
        webURL.fragment = "/chat"
        app.launchArguments = ["-NATIVE_TOOLBAR", "-WEB_URL", webURL.url!.absoluteString,
                               "-API_URL", environment["API_URL"] ?? "http://localhost:8000"]
        return app
    }

    @MainActor
    private func assertAC20Metadata(_ app: XCUIApplication) {
        #if targetEnvironment(simulator)
        XCTAssertTrue(app.staticTexts["simulator-ar-fallback"].waitForExistence(timeout: 10))
        #endif
        let credit = app.staticTexts["scene-credit"]
        XCTAssertTrue(credit.waitForExistence(timeout: 20), "AC20 must load its actual scene attribution")
        XCTAssertTrue(credit.label.contains("Karlsruhe Institute of Technology (KIT)"))
        XCTAssertTrue(credit.label.contains("LicenseRef-KIT-unrestricted"))
        XCTAssertEqual(app.staticTexts["ar-document-id"].label, docID)
        XCTAssertEqual(app.staticTexts["scene-name"].label, "AC20 Institute / Phantasy Office Building - arc")
        XCTAssertEqual(app.staticTexts["ar-status"].label, "Scene metadata loaded from the API.",
                       "This live smoke test requires the local API on port 8000")
        // Count is read from the AC20 manifest, never from a UI fixture.
        let count = app.staticTexts["scene-item-count"].label.split(separator: " ").first.flatMap { Int($0) }
        XCTAssertGreaterThan(count ?? 0, 0)
    }

    @MainActor
    private func attachScreenshot(_ name: String, app: XCUIApplication) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    @MainActor
    private func attachWebState(_ state: [String: Any], name: String, app: XCUIApplication) {
        let data = try? JSONSerialization.data(withJSONObject: state, options: [.prettyPrinted, .sortedKeys])
        let attachment = XCTAttachment(string: data.map { String(decoding: $0, as: UTF8.self) } ?? "\(state)")
        attachment.name = "\(name) - DOM and native viewport"
        attachment.lifetime = .keepAlways
        add(attachment)
        attachScreenshot(name, app: app)
    }
}
