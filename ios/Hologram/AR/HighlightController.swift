import RealityKit
import UIKit

/// Applies answer evidence without changing the USD prim hierarchy or item names.
/// Answer items turn solid warm amber; everything else keeps its real materials.
@MainActor
final class HighlightController {
    /// Solid warm accent for answer items (amber).
    static let accentColor = UIColor(red: 1.0, green: 0.69, blue: 0.13, alpha: 1)

    private static let tierCount = 5

    private struct Original {
        let entity: Entity
        let materials: [any Material]
    }

    private let root: Entity
    private let index: SceneIndex
    private var originals: [Original] = []
    private(set) var labelsByItemID: [String: Entity] = [:]
    private var labelScale: Float = 1
    private var labelAnchors: [String: (base: SIMD3<Float>, offset: Float)] = [:]

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
        
        let highlight = UnlitMaterial(color: Self.accentColor)
        for original in originals {
            guard var model = original.entity.components[ModelComponent.self],
                  selected.contains(ObjectIdentifier(original.entity)) else { continue }
            model.materials = Array(repeating: highlight, count: max(original.materials.count, 1))
            original.entity.components.set(model)
        }
        // Stagger leader heights along the model so neighbouring tags never overlap.
        let sorted = resolved.sorted {
            let a = $0.entity.visualBounds(relativeTo: root).center
            let b = $1.entity.visualBounds(relativeTo: root).center
            return a.x == b.x ? a.z < b.z : a.x < b.x
        }
        for (rank, item) in sorted.enumerated() {
            addLabel(item.label, caption: captions[item.id], for: item.id, above: item.entity,
                     tier: rank % Self.tierCount)
        }
    }

    func clear() {
        for label in labelsByItemID.values { label.removeFromParent() }
        labelsByItemID.removeAll()
        labelAnchors.removeAll()
        restoreOriginals()
    }

    private func restoreOriginals() {
        for original in originals {
            guard var model = original.entity.components[ModelComponent.self] else { continue }
            model.materials = original.materials
            original.entity.components.set(model)
        }
    }

    /// Floating billboard tag: a dark capsule with a bold number and a small kind label,
    /// joined to the item by a thin grey leader. `tier` raises the tag to avoid overlaps.
    private func addLabel(_ text: String, caption: String?, for itemID: String, above entity: Entity,
                          tier: Int) {
        let unit = Self.labelUnit(for: root)
        let bounds = entity.visualBounds(relativeTo: root)
        let offset = unit * (1.6 + Float(tier) * 2.0)
        let white = UnlitMaterial(color: .white)
        let grey = UnlitMaterial(color: UIColor(white: 0.78, alpha: 1))

        let mesh = MeshResource.generateText(text, extrusionDepth: unit * 0.02,
                                             font: .boldSystemFont(ofSize: CGFloat(unit * 0.9)))
        let number = ModelEntity(mesh: mesh, materials: [white])
        number.name = text
        let nb = number.visualBounds(relativeTo: number)

        var captionEntity: ModelEntity?
        var cb = BoundingBox(min: .zero, max: .zero)
        if let caption, !caption.isEmpty {
            let short = caption.count > 22 ? String(caption.prefix(21)) + "…" : caption
            let captionMesh = MeshResource.generateText(short.capitalized(with: nil), extrusionDepth: unit * 0.01,
                                                        font: .systemFont(ofSize: CGFloat(unit * 0.4), weight: .medium))
            let entity = ModelEntity(mesh: captionMesh, materials: [grey])
            entity.name = "caption"
            cb = entity.visualBounds(relativeTo: entity)
            captionEntity = entity
        }

        let pad = unit * 0.28
        let gap = captionEntity == nil ? 0 : unit * 0.12
        let contentWidth = max(nb.extents.x, cb.extents.x)
        let contentHeight = nb.extents.y + gap + (captionEntity == nil ? 0 : cb.extents.y)
        let width = max(contentWidth + pad * 2, unit * 1.2)
        let height = contentHeight + pad * 2

        var fill = UnlitMaterial(color: UIColor(white: 0.04, alpha: 1))
        fill.blending = .transparent(opacity: .init(floatLiteral: 0.82))
        var edge = UnlitMaterial(color: .white)
        edge.blending = .transparent(opacity: .init(floatLiteral: 0.35))
        let border = unit * 0.03
        let edgePlane = ModelEntity(mesh: .generatePlane(width: width + border * 2, height: height + border * 2,
                                                         cornerRadius: height / 2 + border), materials: [edge])
        let fillPlane = ModelEntity(mesh: .generatePlane(width: width, height: height, cornerRadius: height / 2),
                                    materials: [fill])
        // Capsule bottom sits at the card origin; the leader hangs from there.
        let cy = height / 2
        edgePlane.position = [0, cy, -unit * 0.004]
        fillPlane.position = [0, cy, 0]
        let textZ = unit * 0.01
        var cursor = height - pad
        number.position = [-nb.center.x, cursor - nb.max.y, textZ]
        cursor -= nb.extents.y + gap
        if let captionEntity {
            captionEntity.position = [-cb.center.x, cursor - cb.max.y, textZ]
        }

        let card = Entity()
        card.addChild(edgePlane)
        card.addChild(fillPlane)
        card.addChild(number)
        if let captionEntity { card.addChild(captionEntity) }

        let label = Entity()
        label.name = "answer-label-" + itemID
        label.components.set(BillboardComponent())
        let base = SIMD3<Float>(bounds.center.x, bounds.max.y, bounds.center.z)
        label.position = base + [0, offset * labelScale, 0]
        label.scale = SIMD3(repeating: labelScale)
        labelAnchors[itemID] = (base, offset)
        label.addChild(card)

        // Thin grey leader and a small white dot where it meets the item.
        let width2 = max(unit * 0.02, 0.0015)
        let leader = ModelEntity(mesh: .generateBox(size: [width2, offset, width2]), materials: [grey])
        leader.position = [0, -offset / 2, 0]
        label.addChild(leader)
        let dot = ModelEntity(mesh: .generateSphere(radius: unit * 0.07), materials: [white])
        dot.position = [0, -offset, 0]
        label.addChild(dot)

        root.addChild(label)
        labelsByItemID[itemID] = label
    }
}
