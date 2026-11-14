import RealityKit
import UIKit
import XCTest
@testable import Hologram

final class HighlightControllerTests: XCTestCase {
    @MainActor
    func testFixtureHighlightsTwoItemsDimsThreeAndRestoresMaterials() async throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "fixture", withExtension: "usdz"))
        let root = try await Entity(contentsOf: url)
        let index = SceneIndex(root: root)
        let ids = ["wall-001", "wall-002", "door-001", "window-001", "window-002"]
        let originals = try ids.map { id in
            let entity = try XCTUnwrap(index.entity(for: id))
            return (entity, renderables(in: entity).map { ($0, $0.components[ModelComponent.self]!.materials) })
        }
        XCTAssertEqual(originals.flatMap { $0.1 }.count, 5)
        let childCount = root.children.count
        let controller = HighlightController(root: root)

        controller.highlight(itemIDs: ["window-001", "door-001"],
                             labels: ["window-001": "1", "door-001": "2"])

        for id in ids {
            let entity = try XCTUnwrap(index.entity(for: id))
            let highlighted = id == "window-001" || id == "door-001"
            try assertAppearance(of: entity, highlighted: highlighted)
            XCTAssertTrue(root.findEntity(named: SceneIndex.usdName(for: id)) === entity,
                          "Selection must preserve USD prims")
        }
        XCTAssertEqual(controller.labelsByItemID.count, 2)
        for (id, text) in ["window-001": "1", "door-001": "2"] {
            let label = try XCTUnwrap(controller.labelsByItemID[id])
            let item = try XCTUnwrap(index.entity(for: id))
            XCTAssertTrue(label.parent === root)
            XCTAssertNotNil(label.components[BillboardComponent.self])
            XCTAssertNotNil(label.findEntity(named: text)?.components[ModelComponent.self])
            XCTAssertGreaterThan(label.position.y, item.visualBounds(relativeTo: root).max.y)
        }

        // Replacing evidence must remove old labels and keep explicit 2D numbering.
        let oldLabels = Array(controller.labelsByItemID.values)
        controller.highlight(itemIDs: ["wall-002"], labels: ["wall-002": "19"])
        XCTAssertTrue(oldLabels.allSatisfy { $0.parent == nil })
        XCTAssertEqual(controller.labelsByItemID.count, 1)
        XCTAssertNotNil(controller.labelsByItemID["wall-002"]?.findEntity(named: "19"))
        try assertAppearance(of: XCTUnwrap(index.entity(for: "window-001")), highlighted: false)
        try assertAppearance(of: XCTUnwrap(index.entity(for: "wall-002")), highlighted: true)

        controller.clear()
        controller.clear() // Clearing is safe even when there is no active selection.
        XCTAssertTrue(controller.labelsByItemID.isEmpty)
        XCTAssertEqual(root.children.count, childCount)
        for (_, models) in originals {
            for (entity, materials) in models {
                let restored = try XCTUnwrap(entity.components[ModelComponent.self]).materials
                assertSameMaterials(restored, materials)
            }
        }
    }

    @MainActor
    func testGroupedMeshesMissingIDsDuplicatesAndEmptySelection() throws {
        let root = Entity()
        let group = Entity()
        group.name = SceneIndex.usdName(for: "window-001")
        let mesh = MeshResource.generateBox(size: 1)
        let original = UnlitMaterial(color: .blue)
        let first = ModelEntity(mesh: mesh, materials: [original, original])
        let second = ModelEntity(mesh: mesh, materials: [original])
        group.addChild(first)
        group.addChild(second)
        root.addChild(group)
        let controller = HighlightController(root: root)

        controller.highlight(itemIDs: ["missing", "window-001", "window-001"])
        try assertAppearance(of: group, highlighted: true)
        XCTAssertEqual(first.model?.materials.count, 2, "Preserve material slots")
        XCTAssertEqual(controller.labelsByItemID.count, 1)
        XCTAssertNotNil(controller.labelsByItemID["window-001"]?.findEntity(named: "2"))

        controller.highlight(itemIDs: ["missing"])
        XCTAssertTrue(controller.labelsByItemID.isEmpty)
        assertSameMaterials(try XCTUnwrap(first.model).materials, [original, original])
        assertSameMaterials(try XCTUnwrap(second.model).materials, [original])

        controller.highlight(itemIDs: ["window-001"])
        XCTAssertNotNil(controller.labelsByItemID["window-001"]?.findEntity(named: "1"))
        controller.highlight(itemIDs: [])
        XCTAssertTrue(controller.labelsByItemID.isEmpty)
        assertSameMaterials(try XCTUnwrap(first.model).materials, [original, original])
    }

    @MainActor
    func testUnselectedItemsKeepOriginalMaterialsAndTagsAreStaggered() throws {
        let root = Entity()
        let original = SimpleMaterial(color: .red, isMetallic: false)
        var items: [ModelEntity] = []
        for (n, id) in ["door-001", "door-002", "door-003"].enumerated() {
            let group = Entity()
            group.name = SceneIndex.usdName(for: id)
            let item = ModelEntity(mesh: .generateBox(size: 1), materials: [original])
            group.addChild(item)
            group.position.x = Float(n) * 0.5
            root.addChild(group)
            items.append(item)
        }
        let other = ModelEntity(mesh: .generateBox(size: 1), materials: [original])
        root.addChild(other)
        let controller = HighlightController(root: root)

        controller.highlight(itemIDs: ["door-001", "door-002", "door-003"],
                             captions: ["door-001": "door"])
        assertSameMaterials(try XCTUnwrap(other.model).materials, [original])
        XCTAssertTrue(try XCTUnwrap(items[0].model).materials.first is UnlitMaterial)
        XCTAssertNotNil(controller.labelsByItemID["door-001"]?.findEntity(named: "caption"))
        let heights = ["door-001", "door-002", "door-003"].compactMap { controller.labelsByItemID[$0]?.position.y }
        XCTAssertEqual(Set(heights).count, 3, "Neighbouring tags need different heights")
        controller.clear()
        assertSameMaterials(try XCTUnwrap(items[0].model).materials, [original])
    }

    @MainActor
    private func renderables(in entity: Entity) -> [Entity] {
        (entity.components[ModelComponent.self] == nil ? [] : [entity])
            + entity.children.flatMap { renderables(in: $0) }
    }

    @MainActor
    private func assertAppearance(of entity: Entity, highlighted: Bool,
                                  file: StaticString = #filePath, line: UInt = #line) throws {
        let models = renderables(in: entity)
        XCTAssertFalse(models.isEmpty, file: file, line: line)
        for model in models {
            let materials = try XCTUnwrap(model.components[ModelComponent.self], file: file, line: line).materials
            XCTAssertFalse(materials.isEmpty, file: file, line: line)
            for material in materials {
                if highlighted {
                    let unlit = try XCTUnwrap(material as? UnlitMaterial, file: file, line: line)
                    // RealityKit converts UIKit colours to linear RGB. Read the expected
                    // tint through the same material API before comparing components.
                    let expected = UnlitMaterial(color: HighlightController.accentColor)
                    assertSameColor(unlit.color.tint, expected.color.tint, file: file, line: line)
                } else {
                    // Unselected items keep their real materials, never the accent.
                    if let unlit = material as? UnlitMaterial {
                        let accent = UnlitMaterial(color: HighlightController.accentColor)
                        XCTAssertNotEqual(unlit.color.tint, accent.color.tint, file: file, line: line)
                    }
                }
            }
        }
    }

    @MainActor
    private func assertSameMaterials(_ actual: [any Material], _ expected: [any Material],
                                     file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(actual.count, expected.count, file: file, line: line)
        for (restored, original) in zip(actual, expected) {
            XCTAssertEqual(String(reflecting: type(of: restored)), String(reflecting: type(of: original)),
                           file: file, line: line)
            switch original {
            case let original as PhysicallyBasedMaterial:
                guard let restored = restored as? PhysicallyBasedMaterial else { continue }
                assertSameColor(restored.baseColor.tint, original.baseColor.tint, file: file, line: line)
                XCTAssertEqual(restored.metallic.scale, original.metallic.scale, file: file, line: line)
                XCTAssertEqual(restored.roughness.scale, original.roughness.scale, file: file, line: line)
            case let original as SimpleMaterial:
                guard let restored = restored as? SimpleMaterial else { continue }
                assertSameColor(restored.color.tint, original.color.tint, file: file, line: line)
                XCTAssertEqual(restored.metallic, original.metallic, file: file, line: line)
                XCTAssertEqual(restored.roughness, original.roughness, file: file, line: line)
            case let original as UnlitMaterial:
                guard let restored = restored as? UnlitMaterial else { continue }
                assertSameColor(restored.color.tint, original.color.tint, file: file, line: line)
            default:
                XCTFail("Unexpected fixture material type", file: file, line: line)
            }
        }
    }

    private func assertSameColor(_ actual: UIColor, _ expected: UIColor,
                                 file: StaticString = #filePath, line: UInt = #line) {
        guard let space = CGColorSpace(name: CGColorSpace.extendedLinearSRGB),
              let actualComponents = actual.cgColor.converted(to: space, intent: .defaultIntent,
                                                              options: nil)?.components,
              let expectedComponents = expected.cgColor.converted(to: space, intent: .defaultIntent,
                                                                  options: nil)?.components else {
            XCTFail("Material tints must convert to a common RGB colour space", file: file, line: line)
            return
        }
        XCTAssertEqual(actualComponents.count, expectedComponents.count, file: file, line: line)
        for (actual, expected) in zip(actualComponents, expectedComponents) {
            XCTAssertEqual(actual, expected, accuracy: 0.00001, file: file, line: line)
        }
    }
}
