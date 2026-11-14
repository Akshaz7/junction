import XCTest
@testable import Hologram

final class PairLinkTests: XCTestCase {
    func testParsesPairCode() {
        XCTAssertEqual(PairLink(url: URL(string: "hologram://pair?code=AB12cd")!)?.code, "AB12cd")
        XCTAssertEqual(PairLink(url: URL(string: "HOLOGRAM://pair?code=x-1_2&utm=3")!)?.code, "x-1_2")
    }

    func testRejectsOtherLinks() {
        for text in ["hologram://pair", "hologram://pair?code=", "hologram://other?code=1", "https://pair?code=1",
                     "hologram://pair?code=a%20b", "hologram://pair?code=%3Cscript%3E",
                     "hologram://pair?code=" + String(repeating: "a", count: 65)] {
            XCTAssertNil(PairLink(url: URL(string: text)!), text)
        }
    }

    func testWebURLUsesConfiguredOrigin() throws {
        let link = try XCTUnwrap(PairLink(url: URL(string: "hologram://pair?code=ZZ9")!))
        XCTAssertEqual(link.webURL(base: URL(string: "https://hologram-khaki.vercel.app/#/chat")!)?.absoluteString,
                       "https://hologram-khaki.vercel.app/#/pair?code=ZZ9")
        XCTAssertEqual(link.webURL(base: URL(string: "http://10.0.0.2:4173")!)?.absoluteString,
                       "http://10.0.0.2:4173/#/pair?code=ZZ9")
    }
}
