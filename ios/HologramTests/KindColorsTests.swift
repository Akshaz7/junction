import XCTest
import RealityKit
@testable import Hologram

final class KindColorsTests: XCTestCase {
    private func hex(_ color: UIColor) -> String {
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        color.getRed(&r, green: &g, blue: &b, alpha: &a)
        return String(format: "#%02X%02X%02X", Int((r * 255).rounded()), Int((g * 255).rounded()), Int((b * 255).rounded()))
    }

    func testKeyMappingMatchesTheWeb() {
        XCTAssertEqual(KindColors.key(for: "Door"), "door")
        XCTAssertEqual(KindColors.key(for: "curtain_wall"), "wall")
        XCTAssertEqual(KindColors.key(for: "stair"), "stairs")
        XCTAssertEqual(KindColors.key(for: "furniture"), "other")
        XCTAssertEqual(KindColors.key(for: nil), "other")
        XCTAssertEqual(KindColors.key(for: "pipe_segment"), "pipe")
        XCTAssertEqual(KindColors.key(for: "PipeSegment"), "pipe")
        XCTAssertEqual(KindColors.key(for: "valve"), "fitting")
        XCTAssertEqual(KindColors.key(for: "pipe_fitting"), "fitting")
        XCTAssertEqual(KindColors.key(for: "drain"), "drain")
    }

    func testEveryKindHasADistinctColour() {
        let colours = KindColors.keys.map { hex(KindColors.style(for: $0).color) }
        XCTAssertEqual(Set(colours).count, KindColors.keys.count)
    }

    /// The Swift table must equal web/public/kind-colors.json (skipped when the repo checkout isn't present).
    func testMatchesSharedJSON() throws {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("web/public/kind-colors.json")
        guard let data = try? Data(contentsOf: url) else { throw XCTSkip("kind-colors.json not available") }
        struct File: Decodable { struct Row: Decodable { let color, on, label, plural: String }; let kinds: [String: Row] }
        let file = try JSONDecoder().decode(File.self, from: data)
        XCTAssertEqual(Set(file.kinds.keys), Set(KindColors.keys))
        for (key, row) in file.kinds {
            let style = KindColors.style(for: key)
            XCTAssertEqual(hex(style.color), row.color.uppercased(), key)
            XCTAssertEqual(hex(style.on), row.on.uppercased(), key)
            XCTAssertEqual(style.label, row.label, key)
            XCTAssertEqual(style.plural, row.plural, key)
        }
    }

    func testLegendCountsInFirstSeenOrder() {
        let rows = KindColors.counts(of: ["window", "door", "window", nil, "wall"])
        XCTAssertEqual(rows.map(\.style.key), ["window", "door", "other", "wall"])
        XCTAssertEqual(rows.map(\.count), [2, 1, 1, 1])
    }

    @MainActor
    func testHighlightsUseKindColoursAndBadges() throws {
        let root = Entity()
        for id in ["door-001", "window-001"] {
            let entity = ModelEntity(mesh: .generateBox(size: 1), materials: [SimpleMaterial()])
            entity.name = SceneIndex.usdName(for: id)
            root.addChild(entity)
        }
        let controller = HighlightController(root: root)
        controller.highlight(itemIDs: ["door-001", "window-001"], labels: ["door-001": "1", "window-001": "2"],
                             captions: [:], kinds: ["door-001": "door", "window-001": "window"])
        func color(_ id: String) throws -> String {
            let model = try XCTUnwrap(root.findEntity(named: SceneIndex.usdName(for: id))?.components[ModelComponent.self])
            let material = try XCTUnwrap(model.materials.first as? UnlitMaterial)
            return hex(material.color.tint)
        }
        XCTAssertEqual(try color("door-001"), "#D55E00")
        XCTAssertEqual(try color("window-001"), "#0072B2")
        let doorLabel = try XCTUnwrap(controller.labelsByItemID["door-001"])
        XCTAssertNotNil(doorLabel.findEntity(named: "caption"), "tags carry the kind label")
    }
}
