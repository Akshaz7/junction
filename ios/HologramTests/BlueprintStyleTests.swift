import XCTest
@testable import Hologram

final class BlueprintStyleTests: XCTestCase {
    private func item(name: String? = nil, props: [String: SceneProperty]? = nil) -> SceneManifest.Item {
        return SceneManifest.Item(usd_name: "i_x", bbox_m: nil, name: name, kind: "room", storey: nil, tag: nil, props: props)
    }

    func testSurfacesMatchTheWebBlueprintLayer() throws {
        func rgb(_ kind: String) throws -> [Int] {
            var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
            try XCTUnwrap(BlueprintStyle.surface(for: kind)).color.getRed(&r, green: &g, blue: &b, alpha: &a)
            return [r, g, b].map { Int(($0 * 255).rounded()) }
        }
        XCTAssertEqual(try rgb("wall"), [0xD9, 0xD4, 0xC9])
        XCTAssertEqual(try rgb("window"), [0x9F, 0xD3, 0xEA])
        XCTAssertEqual(try rgb("door"), [0x9C, 0x6B, 0x3C])
        XCTAssertEqual(try rgb("slab"), [0xE6, 0xE2, 0xD9])
        XCTAssertEqual(try rgb("roof"), [0x9A, 0x8F, 0x86])
        XCTAssertEqual(try rgb("stairs"), [0x5F, 0x5A, 0x54])
        XCTAssertEqual(try rgb("toilet"), [0xF4, 0xF7, 0xF9])
        XCTAssertEqual(try XCTUnwrap(BlueprintStyle.surface(for: "window")).alpha, 0.38, accuracy: 0.001)
        XCTAssertNil(BlueprintStyle.surface(for: nil))
    }

    func testRoomTypeAndName() {
        XCTAssertEqual(BlueprintStyle.roomType(name: "Bathroom 2"), .wet)
        XCTAssertEqual(BlueprintStyle.roomType(name: "Dusche"), .wet)
        XCTAssertEqual(BlueprintStyle.roomType(name: "K\u{00FC}che"), .kitchen)
        XCTAssertEqual(BlueprintStyle.roomType(name: "Corridor"), .other)
        XCTAssertEqual(BlueprintStyle.roomType(name: nil), .other)
        XCTAssertEqual(BlueprintStyle.roomType(item(props: ["room_type": .string("kitchen")])), .kitchen)
        XCTAssertEqual(BlueprintStyle.roomName(item(name: "Kitchen")), "Kitchen")
        XCTAssertEqual(BlueprintStyle.roomName(item(props: ["LongName": .string("Sauna")])), "Sauna")
        XCTAssertNil(BlueprintStyle.roomName(item()))
    }

    func testAreaIsNeverInvented() {
        XCTAssertEqual(BlueprintStyle.roomArea(item(props: ["area_m2": .number(12.5)])), 12.5)
        XCTAssertNil(BlueprintStyle.roomArea(item()))
        XCTAssertEqual(BlueprintStyle.roomLabel(name: "Kitchen", area: 12.44), "Kitchen\n12.4 m\u{00B2}")
        XCTAssertEqual(BlueprintStyle.roomLabel(name: nil, area: 8), "8.0 m\u{00B2}")
        XCTAssertEqual(BlueprintStyle.roomLabel(name: "Hall", area: nil), "Hall")
        XCTAssertNil(BlueprintStyle.roomLabel(name: nil, area: nil))
    }

    func testRoomLabelLayoutRules() throws {
        let text: SIMD2<Float> = [4, 1.2]   // text extent for a 1 m font
        XCTAssertNil(BlueprintStyle.roomLabelLayout(footprint: [1.1, 6], textPerMetre: text), "shorter side under 1.2 m")
        let big = try XCTUnwrap(BlueprintStyle.roomLabelLayout(footprint: [5, 5], textPerMetre: text))
        XCTAssertEqual(big.fontSize, 0.9, accuracy: 0.001, "shorter side 5 gives 1.0, clamped to 0.9, text fits")
        let wide = try XCTUnwrap(BlueprintStyle.roomLabelLayout(footprint: [5, 5], textPerMetre: [8, 1.2]))
        XCTAssertEqual(wide.fontSize, 0.9 * 5 / 8, accuracy: 0.001, "width capped at 90% of the room side")
        XCTAssertFalse(big.rotated)
        let tall = try XCTUnwrap(BlueprintStyle.roomLabelLayout(footprint: [2, 5], textPerMetre: [2, 1]))
        XCTAssertTrue(tall.rotated, "z more than 1.6x x")
        XCTAssertFalse(try XCTUnwrap(BlueprintStyle.roomLabelLayout(footprint: [3, 4.7], textPerMetre: [2, 1])).rotated)
        XCTAssertNil(BlueprintStyle.roomLabelLayout(footprint: [1.3, 1.3], textPerMetre: [12, 1]), "fitted text under 0.14 m")
        XCTAssertEqual(BlueprintStyle.roomLabelHeight(minY: 0, maxY: 0.1), 0.05, accuracy: 0.0001)
        XCTAssertEqual(BlueprintStyle.roomLabelHeight(minY: 0, maxY: 2.6), 2.63, accuracy: 0.0001)
    }

    func testDoorDetailShowsWidth() {
        let door = SceneManifest.Item(usd_name: "i_d", bbox_m: nil, name: nil, kind: "door", storey: nil, tag: "D3",
                                      props: ["width_m": .number(0.9)])
        XCTAssertEqual(BlueprintStyle.detail(for: door), "0.90 m")
        XCTAssertNil(BlueprintStyle.detail(for: item(name: "Kitchen")))
    }

    func testDimensionAndStoreyText() {
        XCTAssertEqual(BlueprintStyle.dimensionText(42), "42.0 m")
        XCTAssertEqual(BlueprintStyle.storeyLabel(name: "Erdgeschoss", elevation: 0), "Erdgeschoss \u{00B7} +0.00 m")
        XCTAssertEqual(BlueprintStyle.storeyLabel(name: "Keller", elevation: -3), "Keller \u{00B7} \u{2212}3.00 m")
        XCTAssertEqual(BlueprintStyle.storeyLabel(name: "1. OG", elevation: 3), "1. OG \u{00B7} +3.00 m")
    }

    func testLabelOpacityFadesWithAngularSize() {
        XCTAssertEqual(BlueprintStyle.labelOpacity(width: 1, distance: 100), 0)
        XCTAssertEqual(BlueprintStyle.labelOpacity(width: 0.04, distance: 0.4), 1)
        XCTAssertEqual(BlueprintStyle.labelOpacity(width: 1, distance: 8), 1)
        let mid = BlueprintStyle.labelOpacity(width: 1, distance: 50)
        XCTAssertTrue(mid > 0 && mid < 1)
    }
}
