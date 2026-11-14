import XCTest
@testable import Hologram

final class BlueprintStyleTests: XCTestCase {
    private func item(name: String? = nil, props: [String: SceneProperty]? = nil) -> SceneManifest.Item {
        return SceneManifest.Item(usd_name: "i_x", bbox_m: nil, name: name, kind: "room", storey: nil, tag: nil, props: props)
    }

    func testSurfacesByKind() {
        XCTAssertNotNil(BlueprintStyle.surface(for: "wall"))
        XCTAssertLessThan(BlueprintStyle.surface(for: "window")!.alpha, 1)
        XCTAssertNil(BlueprintStyle.surface(for: "roof"))
        XCTAssertNil(BlueprintStyle.surface(for: nil))
    }

    func testRoomTypeAndName() {
        XCTAssertEqual(BlueprintStyle.roomType(name: "Bathroom 2"), .wet)
        XCTAssertEqual(BlueprintStyle.roomType(name: "Corridor"), .circulation)
        XCTAssertEqual(BlueprintStyle.roomType(name: "Office"), .work)
        XCTAssertEqual(BlueprintStyle.roomType(name: nil), .other)
        XCTAssertEqual(BlueprintStyle.roomName(item(name: "Kitchen")), "Kitchen")
        XCTAssertEqual(BlueprintStyle.roomName(item(props: ["LongName": .string("Sauna")])), "Sauna")
        XCTAssertNil(BlueprintStyle.roomName(item()))
    }

    func testAreaAndLabels() {
        XCTAssertEqual(BlueprintStyle.roomArea(item(props: ["area_m2": .number(12.5)]), footprint: [2, 2]), 12.5)
        XCTAssertEqual(BlueprintStyle.roomArea(item(), footprint: [3, 4]), 12)
        XCTAssertEqual(BlueprintStyle.roomLabel(name: "Kitchen", area: 12.44), "Kitchen\n12.4 m\u{00B2}")
        XCTAssertEqual(BlueprintStyle.roomLabel(name: nil, area: 8), "8.0 m\u{00B2}")
    }

    func testDimensionAndStoreyText() {
        XCTAssertEqual(BlueprintStyle.dimensionText(12.4), "12.40 m")
        XCTAssertEqual(BlueprintStyle.storeyLabel(name: "Erdgeschoss", elevation: 0), "Erdgeschoss \u{00B7} \u{00B1}0.00")
        XCTAssertEqual(BlueprintStyle.storeyLabel(name: "Keller", elevation: -3), "Keller \u{00B7} -3.00")
        XCTAssertEqual(BlueprintStyle.storeyLabel(name: "1. OG", elevation: 3), "1. OG \u{00B7} +3.00")
    }

    func testLabelOpacityFadesWithAngularSize() {
        XCTAssertEqual(BlueprintStyle.labelOpacity(width: 1, distance: 100), 0)
        XCTAssertEqual(BlueprintStyle.labelOpacity(width: 0.04, distance: 0.4), 1)
        XCTAssertEqual(BlueprintStyle.labelOpacity(width: 1, distance: 8), 1)
        let mid = BlueprintStyle.labelOpacity(width: 1, distance: 25)
        XCTAssertTrue(mid > 0 && mid < 1)
    }
}
