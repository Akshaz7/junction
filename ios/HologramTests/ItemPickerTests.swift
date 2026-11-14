import RealityKit
import XCTest
@testable import Hologram

final class ItemPickerTests: XCTestCase {
    @MainActor
    func testChildMeshResolvesToWindowAndCardShowsWindowKind() async throws {
        let bundle = Bundle(for: Self.self)
        let sceneURL = try XCTUnwrap(bundle.url(forResource: "fixture.scene", withExtension: "json"))
        let manifest = try JSONDecoder().decode(SceneManifest.self, from: Data(contentsOf: sceneURL))
        let modelURL = try XCTUnwrap(bundle.url(forResource: "fixture", withExtension: "usdz"))
        let root = try await Entity(contentsOf: modelURL)
        let windowItem = try XCTUnwrap(manifest.items["window-001"])
        let window = try XCTUnwrap(root.findEntity(named: windowItem.usd_name))
        let mesh = ModelEntity(mesh: .generateBox(size: 0.1))
        let intermediate = Entity()
        window.addChild(intermediate)
        intermediate.addChild(mesh)
        let picker = ItemPicker(manifest: manifest)

        XCTAssertEqual(picker.itemID(for: mesh), "window-001")
        XCTAssertEqual(picker.itemID(for: window), "window-001")
        let card = ItemCardModel(itemID: "window-001", item: windowItem)
        XCTAssertEqual(card.kind, "window")
        XCTAssertEqual(card.name, "window-001", "Absent names use the real item ID")
        XCTAssertNil(card.storey)
        XCTAssertTrue(card.properties.isEmpty)
    }

    @MainActor
    func testUnknownEntityReturnsNilAndClosestKnownParentWins() throws {
        let manifest = try JSONDecoder().decode(SceneManifest.self, from: Data(#"""
        {"items":{
            "wall-001":{"usd_name":"custom_wall_prim"},
            "window-001":{"usd_name":"custom_window_prim","kind":"window"}
        }}
        """#.utf8))
        let picker = ItemPicker(manifest: manifest)
        XCTAssertNil(picker.itemID(for: Entity()))
        let wall = Entity()
        wall.name = "custom_wall_prim"
        let window = Entity()
        window.name = "custom_window_prim"
        let mesh = Entity()
        wall.addChild(window)
        window.addChild(mesh)
        XCTAssertEqual(picker.itemID(for: mesh), "window-001", "Use manifest names and nearest known ancestor")
        XCTAssertEqual(picker.itemID(for: wall), "wall-001")
    }

    func testCardPreservesAvailableMetadataAndPropertyTypes() throws {
        let manifest = try JSONDecoder().decode(SceneManifest.self, from: Data(#"""
        {"note":"generated for demo","items":{"window-001":{
            "usd_name":"window_prim","name":"Kitchen window","kind":"window","storey":"Ground floor",
            "props":{"width_m":1.2,"is_external":true,"material":"Timber","fire_rating":null,
                     "tags":["opening","glazed"],"details":{"finish":"Painted"}}
        }}}
        """#.utf8))
        let card = ItemCardModel(itemID: "window-001", item: try XCTUnwrap(manifest.items["window-001"]))
        XCTAssertEqual(card.name, "Kitchen window")
        XCTAssertEqual(card.kind, "window")
        XCTAssertEqual(card.storey, "Ground floor")
        let properties = Dictionary(uniqueKeysWithValues: card.properties.map { ($0.name, $0.value) })
        XCTAssertEqual(properties["is_external"], "Yes")
        XCTAssertEqual(properties["material"], "Timber")
        XCTAssertEqual(properties["fire_rating"], "Not available")
        XCTAssertEqual(properties["tags"], "opening, glazed")
        XCTAssertEqual(properties["details"], "finish: Painted")
        XCTAssertNotNil(properties["width_m"])
        XCTAssertEqual(card.properties.map(\.name), properties.keys.sorted())
    }

    @MainActor
    func testTapOutlineDoesNotReplaceAnswerHighlightAndClearsOnDismissal() throws {
        let root = Entity()
        let window = ModelEntity(mesh: .generateBox(size: 1), materials: [UnlitMaterial(color: .blue)])
        window.name = SceneIndex.usdName(for: "window-001")
        root.addChild(window)
        let answer = HighlightController(root: root)
        answer.highlight(itemIDs: ["window-001"])
        let answerTint = try XCTUnwrap(window.model?.materials.first as? UnlitMaterial).color.tint
        let selection = ItemSelectionOutline()
        selection.select(window)
        let outline = try XCTUnwrap(selection.outline)
        XCTAssertTrue(outline.parent === window)
        XCTAssertEqual(outline.children.count, 12)
        XCTAssertTrue(outline.children.allSatisfy { $0.components[CollisionComponent.self] == nil })
        let outlineMaterial = try XCTUnwrap(outline.children.first?.components[ModelComponent.self]?
            .materials.first as? UnlitMaterial)
        XCTAssertNotEqual(outlineMaterial.color.tint, answerTint)
        XCTAssertEqual(try XCTUnwrap(window.model?.materials.first as? UnlitMaterial).color.tint, answerTint)

        answer.highlight(itemIDs: ["window-001"])
        XCTAssertTrue(selection.outline === outline, "Live evidence updates must preserve tap selection")
        selection.select(window)
        XCTAssertNil(outline.parent, "Replacing tap selection removes the old outline")
        selection.clear()
        selection.clear()
        XCTAssertNil(selection.outline)
        XCTAssertTrue(window.children.isEmpty)
        XCTAssertNotNil(answer.labelsByItemID["window-001"])
        XCTAssertEqual(try XCTUnwrap(window.model?.materials.first as? UnlitMaterial).color.tint, answerTint)
    }
}
