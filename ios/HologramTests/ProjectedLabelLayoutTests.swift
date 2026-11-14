import XCTest
@testable import Hologram

final class ProjectedLabelLayoutTests: XCTestCase {
    func testCollinearTagsUseDifferentTiersAndHideTheFarOneWhenFull() {
        let rectangles = (0..<5).map { tier -> CGRect? in
            CGRect(x: 100, y: 250 - tier * 40, width: 80, height: 30)
        }
        let candidates = (0..<7).reversed().map {
            ProjectedLabelLayout.Candidate(id: "item-\($0)", distance: Float($0 + 1), rectangles: rectangles)
        }
        let result = ProjectedLabelLayout.tiers(for: candidates, viewport: CGRect(x: 0, y: 0, width: 400, height: 400))
        XCTAssertEqual(result.count, 5)
        XCTAssertEqual(result["item-0"], 0, "Reserve the nearest tag first regardless of input order")
        XCTAssertNil(result["item-5"])
        XCTAssertNil(result["item-6"])
        let shown = result.values.map { rectangles[$0]! }
        for (index, rect) in shown.enumerated() {
            XCTAssertFalse(shown.dropFirst(index + 1).contains { $0.intersects(rect) })
        }
    }

    func testCameraRotationRecomputesCollisionsAndOffscreenTagsAreOmitted() {
        let viewport = CGRect(x: 0, y: 0, width: 400, height: 400)
        let rect = CGRect(x: 100, y: 100, width: 80, height: 30)
        let beside = rect.offsetBy(dx: 100, dy: 0)
        let before = ProjectedLabelLayout.tiers(for: [
            .init(id: "a", distance: 1, rectangles: [rect]),
            .init(id: "b", distance: 2, rectangles: [beside])], viewport: viewport)
        XCTAssertEqual(before.count, 2)
        let after = ProjectedLabelLayout.tiers(for: [
            .init(id: "a", distance: 2, rectangles: [rect]),
            .init(id: "b", distance: 1, rectangles: [rect]),
            .init(id: "outside", distance: 0, rectangles: [rect.offsetBy(dx: 400, dy: 0), nil])], viewport: viewport)
        XCTAssertEqual(after, ["b": 0])
    }
}
