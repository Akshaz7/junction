import RealityKit
import UIKit

/// Applies answer evidence without changing the USD prim hierarchy or item names.
@MainActor
final class HighlightController {
    // --brand-red and --grey-300 from the product theme.
    static let accentColor = UIColor(red: 0x66 / 255.0, green: 0x2c / 255.0, blue: 0x23 / 255.0, alpha: 1)
    static let dimColor = UIColor(white: 0xd4 / 255.0, alpha: 1)

    private struct Original {
        let entity: Entity
        let materials: [any Material]
    }

    private let root: Entity
    private let index: SceneIndex
    private var originals: [Original] = []
    private(set) var labelsByItemID: [String: Entity] = [:]

    init(root: Entity) {
        self.root = root
        index = SceneIndex(root: root)
        func capture(_ entity: Entity) {
            if let model = entity.components[ModelComponent.self] {
                originals.append(Original(entity: entity, materials: model.materials))
            }
            for child in entity.children { capture(child) }
        }
        capture(root)
    }

    /// Labels are keyed by item ID so a filtered selection can retain its 2D numbers.
    /// Without explicit labels, numbers follow the original request order, including missing IDs.
    func highlight(itemIDs: [String], labels: [String: String] = [:]) {
        clear()
        guard !itemIDs.isEmpty else { return }

        var selected: Set<ObjectIdentifier> = []
        var resolved: [(id: String, entity: Entity, label: String)] = []
        var seen: Set<String> = []
        func select(_ entity: Entity) {
            selected.insert(ObjectIdentifier(entity))
            for child in entity.children { select(child) }
        }
        for (offset, id) in itemIDs.enumerated() where seen.insert(id).inserted {
            guard let entity = index.entity(for: id) else { continue }
            select(entity)
            resolved.append((id, entity, labels[id] ?? String(offset + 1)))
        }
        // Unknown evidence should leave the drawing readable rather than dim everything.
        guard !resolved.isEmpty else { return }

        let highlight = UnlitMaterial(color: Self.accentColor)
        let dim = SimpleMaterial(color: Self.dimColor, roughness: 1, isMetallic: false)
        for original in originals {
            guard var model = original.entity.components[ModelComponent.self] else { continue }
            let material: any Material = selected.contains(ObjectIdentifier(original.entity)) ? highlight : dim
            model.materials = Array(repeating: material, count: max(original.materials.count, 1))
            original.entity.components.set(model)
        }
        for item in resolved {
            addLabel(item.label, for: item.id, above: item.entity)
        }
    }

    func clear() {
        for label in labelsByItemID.values { label.removeFromParent() }
        labelsByItemID.removeAll()
        for original in originals {
            guard var model = original.entity.components[ModelComponent.self] else { continue }
            model.materials = original.materials
            original.entity.components.set(model)
        }
    }

    private func addLabel(_ text: String, for itemID: String, above entity: Entity) {
        let bounds = entity.visualBounds(relativeTo: root)
        let mesh = MeshResource.generateText(text, extrusionDepth: 0.005,
                                             font: .boldSystemFont(ofSize: 0.25))
        let number = ModelEntity(mesh: mesh, materials: [UnlitMaterial(color: Self.accentColor)])
        number.name = text
        let textBounds = number.visualBounds(relativeTo: number)
        number.position = [-textBounds.center.x, -textBounds.min.y, 0]

        let label = Entity()
        label.name = "answer-label-" + itemID
        label.components.set(BillboardComponent())
        label.position = [bounds.center.x, bounds.max.y + 0.12, bounds.center.z]
        label.addChild(number)
        root.addChild(label)
        labelsByItemID[itemID] = label
    }
}
