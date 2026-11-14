import RealityKit
import UIKit

/// Applies answer evidence without changing the USD prim hierarchy or item names.
///
/// Two looks share one restore path. By default the scene keeps its original materials
/// and unselected items are dimmed grey. With `hologramEnabled` the whole model is a
/// translucent cyan hologram, and answer items turn solid amber so they stand out.
@MainActor
final class HighlightController {
    /// Solid warm accent for answer items (amber) and their 3D tags.
    static let accentColor = UIColor(red: 1.0, green: 0.69, blue: 0.13, alpha: 1)
    static let dimColor = UIColor(white: 0xd4 / 255.0, alpha: 1)
    /// Hologram base colour, #3FC8FF.
    static let hologramColor = UIColor(red: 0x3F / 255.0, green: 0xC8 / 255.0, blue: 0xFF / 255.0, alpha: 1)
    static let hologramOpacity: Float = 0.42
    static let hologramDimOpacity: Float = 0.14

    private struct Original {
        let entity: Entity
        let materials: [any Material]
    }

    private let root: Entity
    private let index: SceneIndex
    private var originals: [Original] = []
    private(set) var labelsByItemID: [String: Entity] = [:]
    private var active: (itemIDs: [String], labels: [String: String], captions: [String: String])?
    private var labelScale: Float = 1
    private var labelAnchors: [String: (base: SIMD3<Float>, offset: Float)] = [:]

    /// Turns the whole model into a blue hologram. Highlights are re-applied on top.
    var hologramEnabled = false {
        didSet {
            guard hologramEnabled != oldValue else { return }
            if let active {
                highlight(itemIDs: active.itemIDs, labels: active.labels, captions: active.captions)
            } else {
                applyBaseline()
            }
        }
    }

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

    /// Tag and callout size follows the model so a 1:100 table model still reads clearly.
    static func labelUnit(for root: Entity) -> Float {
        let extent = root.visualBounds(relativeTo: root).extents.max()
        return max(0.25, extent.isFinite ? extent * 0.035 : 0)
    }

    /// Walk mode is 1:1, where table-sized tags would be huge.
    func setLabelScale(_ scale: Float) {
        labelScale = scale
        for (id, label) in labelsByItemID {
            label.scale = SIMD3(repeating: scale)
            if let anchor = labelAnchors[id] { label.position = anchor.base + [0, anchor.offset * scale, 0] }
        }
    }

    private static func hologramMaterial(color: UIColor = hologramColor, opacity: Float) -> UnlitMaterial {
        var material = UnlitMaterial(color: color)
        material.blending = .transparent(opacity: .init(floatLiteral: opacity))
        return material
    }

    /// Labels are keyed by item ID so a filtered selection can retain its 2D numbers.
    /// Without explicit labels, numbers follow the original request order, including missing IDs.
    /// Captions are short item names shown under each number.
    func highlight(itemIDs: [String], labels: [String: String] = [:], captions: [String: String] = [:]) {
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
        active = (itemIDs, labels, captions)

        let highlight = UnlitMaterial(color: Self.accentColor)
        let dim: any Material = hologramEnabled
            ? Self.hologramMaterial(opacity: Self.hologramDimOpacity)
            : SimpleMaterial(color: Self.dimColor, roughness: 1, isMetallic: false)
        for original in originals {
            guard var model = original.entity.components[ModelComponent.self] else { continue }
            let material: any Material = selected.contains(ObjectIdentifier(original.entity)) ? highlight : dim
            model.materials = Array(repeating: material, count: max(original.materials.count, 1))
            original.entity.components.set(model)
        }
        for item in resolved {
            addLabel(item.label, caption: captions[item.id], for: item.id, above: item.entity)
        }
    }

    func clear() {
        for label in labelsByItemID.values { label.removeFromParent() }
        labelsByItemID.removeAll()
        labelAnchors.removeAll()
        active = nil
        applyBaseline()
    }

    private func applyBaseline() {
        let holo = Self.hologramMaterial(opacity: Self.hologramOpacity)
        for original in originals {
            guard var model = original.entity.components[ModelComponent.self] else { continue }
            model.materials = hologramEnabled
                ? Array(repeating: holo, count: max(original.materials.count, 1))
                : original.materials
            original.entity.components.set(model)
        }
    }

    /// Floating billboard tag: number, short name, and a thin leader down to the item.
    private func addLabel(_ text: String, caption: String?, for itemID: String, above entity: Entity) {
        let unit = Self.labelUnit(for: root)
        let bounds = entity.visualBounds(relativeTo: root)
        let glow = UnlitMaterial(color: Self.accentColor)
        let offset = unit * 2.2

        let mesh = MeshResource.generateText(text, extrusionDepth: unit * 0.02,
                                             font: .boldSystemFont(ofSize: CGFloat(unit)))
        let number = ModelEntity(mesh: mesh, materials: [glow])
        number.name = text
        let textBounds = number.visualBounds(relativeTo: number)

        let label = Entity()
        label.name = "answer-label-" + itemID
        label.components.set(BillboardComponent())
        let base = SIMD3<Float>(bounds.center.x, bounds.max.y, bounds.center.z)
        label.position = base + [0, offset * labelScale, 0]
        label.scale = SIMD3(repeating: labelScale)
        labelAnchors[itemID] = (base, offset)

        var numberBase: Float = unit * 0.15
        if let caption, !caption.isEmpty {
            let short = caption.count > 24 ? String(caption.prefix(23)) + "…" : caption
            let captionMesh = MeshResource.generateText(short, extrusionDepth: unit * 0.01,
                                                        font: .systemFont(ofSize: CGFloat(unit * 0.5), weight: .medium))
            let captionEntity = ModelEntity(mesh: captionMesh,
                                            materials: [UnlitMaterial(color: UIColor(white: 1, alpha: 1))])
            captionEntity.name = "caption"
            let cb = captionEntity.visualBounds(relativeTo: captionEntity)
            captionEntity.position = [-cb.center.x, unit * 0.1 - cb.min.y, 0]
            label.addChild(captionEntity)
            numberBase = unit * 0.1 + cb.extents.y + unit * 0.2
        }
        number.position = [-textBounds.center.x, numberBase - textBounds.min.y, 0]
        label.addChild(number)

        // Leader line and a bright dot where it meets the item.
        let width = max(unit * 0.03, 0.002)
        let leader = ModelEntity(mesh: .generateBox(size: [width, offset, width]), materials: [glow])
        leader.position = [0, -offset / 2, 0]
        label.addChild(leader)
        let dot = ModelEntity(mesh: .generateSphere(radius: unit * 0.1), materials: [glow])
        dot.position = [0, -offset, 0]
        label.addChild(dot)

        root.addChild(label)
        labelsByItemID[itemID] = label
    }
}
