import XCTest
@testable import Hologram

final class AppConfigurationTests: XCTestCase {
    func testLaunchArgumentsOverrideEnvironmentAndPlist() {
        XCTAssertEqual(AppConfiguration.value(for: "WEB_URL", arguments: ["app", "-WEB_URL", "http://localhost:4173"],
                                               environment: ["WEB_URL": "http://localhost:5173"],
                                               configured: "https://example.test"), "http://localhost:4173")
    }

    func testEnvironmentOverridesPlistAndMissingArgumentValueIsIgnored() {
        for arguments in [["app"], ["app", "-WEB_URL"], ["app", "-WEB_URL", "-OtherFlag"]] {
            XCTAssertEqual(AppConfiguration.value(for: "WEB_URL", arguments: arguments,
                                                   environment: ["WEB_URL": "http://localhost:4173"],
                                                   configured: "https://example.test"), "http://localhost:4173")
        }
        XCTAssertEqual(AppConfiguration.value(for: "WEB_URL", arguments: [], environment: ["WEB_URL": " "],
                                               configured: "https://example.test"), "https://example.test")
    }

    func testStableWebBuildUsesLocalAPI() {
        XCTAssertEqual(AppConfiguration.apiURL(webURL: URL(string: "http://localhost:4173")!, configured: nil),
                       URL(string: "http://localhost:8000")!)
    }
}
