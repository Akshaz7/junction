import XCTest
@testable import Hologram

final class HologramTests: XCTestCase {
    func testARBridgeAcceptsContractPayload() throws {
        let request = try XCTUnwrap(ARRequest(body: [
            "doc_id": "cubicasa5k__colorful-11397",
            "item_ids": ["window-007"]
        ]))
        XCTAssertEqual(request.docID, "cubicasa5k__colorful-11397")
        XCTAssertEqual(request.itemIDs, ["window-007"])
    }
}
