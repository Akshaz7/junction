import XCTest
@testable import Hologram

final class SceneIdentityTests: XCTestCase {
    func testFallbackUsesLoadedDocumentAndVisibleFallbackNotice() throws {
        let manifest = try JSONDecoder().decode(SceneManifest.self, from: Data(
            #"{"doc_id":"fixture__ios","items":{}}"#.utf8))
        let identity = SceneIdentity(requestedDocID: "ifc_bench__ac20-arc", manifest: manifest)
        XCTAssertEqual(identity.docID, "fixture__ios")
        XCTAssertEqual(identity.title, "Sample model · generated")
        XCTAssertTrue(try XCTUnwrap(identity.notice).contains("Requested scene unavailable"))
        XCTAssertTrue(try XCTUnwrap(identity.notice).contains("Showing Sample model"))
    }

    func testActualTitleAndOfflineCopyIdentifyTheLoadedDocument() throws {
        let manifest = try JSONDecoder().decode(SceneManifest.self, from: Data(
            #"{"doc_id":"house__one","title":"House One","items":{}}"#.utf8))
        let identity = SceneIdentity(requestedDocID: "house__one", manifest: manifest,
                                     documentTitle: "House One, ground floor", isBundled: true)
        XCTAssertEqual(identity.title, "House One, ground floor")
        XCTAssertEqual(identity.notice, "Offline copy · House One, ground floor")
        XCTAssertEqual(SceneIdentity(requestedDocID: "other", manifest: manifest).title, "House One")
    }
}
