import XCTest

final class HologramUITests: XCTestCase {
    private let docID = "ifc_bench__ac20-arc"
    // First two doors sorted by item_id in the bundled AC20 scene.json.
    private let doorIDs = ["00RjztLorCQgcGEHv7fY3g", "08uaDJHLH3FAZ6Hg9FwzkG"]

    override func setUpWithError() throws {
        continueAfterFailure = false
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

        // This route can only open after the debug WKUserScript posts to the real ar handler.
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
        attachScreenshot("05 - Bridge selection and scene credit", app: app)
    }

    @MainActor
    private func configuredApp() -> XCUIApplication {
        let app = XCUIApplication()
        let environment = ProcessInfo.processInfo.environment
        app.launchArguments = ["-WEB_URL", environment["WEB_URL"] ?? "http://localhost:4173",
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
