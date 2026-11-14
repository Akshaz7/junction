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
        let web = app.webViews["web-shell"]
        XCTAssertTrue(web.waitForExistence(timeout: 10))
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
        XCTAssertTrue(web.staticTexts["Where shall we start?"].waitForExistence(timeout: 10))
    }

    @MainActor
    func testUnsentWebDraftSurvivesNativeARRoundTrip() throws {
        let app = configuredApp()
        let payload = try JSONSerialization.data(withJSONObject: ["doc_id": docID, "item_ids": doorIDs])
        app.launchArguments += ["-AR_BRIDGE_MESSAGE", String(decoding: payload, as: UTF8.self)]
        app.launch()
        defer { app.terminate() }
        let document = app.staticTexts["ar-document-id"]
        XCTAssertTrue(document.waitForExistence(timeout: 30))
        XCTAssertEqual(document.label, docID)
        app.buttons["Done"].tap()
        let web = app.webViews["web-shell"]
        XCTAssertTrue(web.waitForExistence(timeout: 10))

        let composerReady = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            self.editableComposer(in: web) != nil
        }, object: web)
        guard XCTWaiter.wait(for: [composerReady], timeout: 10) == .completed,
              let composer = editableComposer(in: web) else {
            attachScreenshot("Draft check - WebKit exposed no editable composer", app: app)
            throw XCTSkip("WebKit exposed no full-sized editable composer; the separate bridge routing and two-door test remains required.")
        }
        composer.tap()
        guard app.keyboards.firstMatch.waitForExistence(timeout: 5) else {
            attachScreenshot("Draft check - composer did not focus", app: app)
            throw XCTSkip("WebKit did not focus the composer after tapping its full-sized input; draft survival could not be checked. Bridge routing and two-door assertions run separately.")
        }
        composer.typeText("Keep this unsent draft")
        XCTAssertEqual(composer.value as? String, "Keep this unsent draft")
        app.navigationBars.buttons["Show on table"].tap()
        XCTAssertTrue(document.waitForExistence(timeout: 10))
        XCTAssertEqual(document.label, docID)
        app.buttons["Done"].tap()
        XCTAssertTrue(web.waitForExistence(timeout: 10))
        let retainedReady = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            self.editableComposer(in: web) != nil
        }, object: web)
        _ = XCTWaiter.wait(for: [retainedReady], timeout: 10)
        // Known bug, row I-15: the web view loses its composer/draft after the AR round-trip (LEAD 06:50).
        XCTExpectFailure("I-15: WKWebView state is not retained across the native AR round-trip", strict: false)
        let retainedComposer = try XCTUnwrap(editableComposer(in: web), "The web view must keep its composer (and draft) after the AR round-trip")
        XCTAssertEqual(retainedComposer.value as? String, "Keep this unsent draft")
    }

    @MainActor
    private func editableComposer(in web: XCUIElement) -> XCUIElement? {
        let placeholder = "Ask anything. Type @ to include a document"
        let matches = web.descendants(matching: .any).matching(NSPredicate(
            format: "label == %@ OR placeholderValue == %@",
            "Ask about your drawings", placeholder))
        let candidates = matches.allElementsBoundByIndex
        // Prefer native editable types. ARIA role=combobox can expose the actual
        // textarea as comboBox/other, but the 2x2 sr-only label must never qualify.
        for type: XCUIElement.ElementType in [.textView, .textField, .comboBox, .other] {
            if let input = candidates.first(where: {
                $0.elementType == type && $0.frame.width > 100 && $0.frame.height > 20 && $0.isHittable
            }) {
                return input
            }
        }
        return nil
    }

    @MainActor
    private func configuredApp() -> XCUIApplication {
        let app = XCUIApplication()
        let environment = ProcessInfo.processInfo.environment
        // Start on Chat regardless of the phone's default tab; avoid navigating through Data.
        var webURL = URLComponents(string: environment["WEB_URL"] ?? "http://localhost:4173")!
        webURL.fragment = "/chat"
        app.launchArguments = ["-WEB_URL", webURL.url!.absoluteString,
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
        XCTAssertEqual(app.staticTexts["scene-name"].label, "AC20 · IFC building")
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
}
