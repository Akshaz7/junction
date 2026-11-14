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
    private let unit: Float
    private var originals: [Original] = []
    private(set) var labelsByItemID: [String: Entity] = [:]
    private var labelScale: Float = 1
    private var labelAnchors: [String: (base: SIMD3<Float>, offset: Float)] = [:]
    private var labelSizes: [String: SIMD2<Float>] = [:]

    init(root: Entity) {
        self.root = root
        index = SceneIndex(root: root)
        unit = Self.labelUnit(for: root)
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
        for item in resolved {
            addLabel(item.label, caption: captions[item.id], for: item.id, above: item.entity)
        }
    }

    /// Reproject every few frames so rotating the phone also restaggers collinear items.
    func layoutLabels(cameraTransform: simd_float4x4, viewport: CGRect, visibleItemIDs: Set<String>,
                      project: (SIMD3<Float>) -> CGPoint?) {
        let camera = SIMD3<Float>(cameraTransform.columns.3.x, cameraTransform.columns.3.y,
                                 cameraTransform.columns.3.z)
        let right = SIMD3<Float>(cameraTransform.columns.0.x, cameraTransform.columns.0.y,
                                cameraTransform.columns.0.z)
        let up = SIMD3<Float>(cameraTransform.columns.1.x, cameraTransform.columns.1.y,
                             cameraTransform.columns.1.z)
        let back = SIMD3<Float>(cameraTransform.columns.2.x, cameraTransform.columns.2.y,
                               cameraTransform.columns.2.z)
        let transform = root.transformMatrix(relativeTo: nil)
        let worldScale = simd_length(SIMD3<Float>(transform.columns.0.x, transform.columns.0.y,
                                                transform.columns.0.z)) * labelScale
        var positions: [String: [SIMD3<Float>]] = [:]
        var candidates: [ProjectedLabelLayout.Candidate] = []
        for (id, label) in labelsByItemID {
            label.isEnabled = false
            guard visibleItemIDs.contains(id), let anchor = labelAnchors[id],
                  let size = labelSizes[id] else { continue }
            let base = root.convert(position: anchor.base + [0, anchor.offset * labelScale, 0], to: nil)
            guard simd_dot(base - camera, back) < 0 else { continue }
            let width = size.x * worldScale
            let height = size.y * worldScale
            let tiers = (0..<Self.tierCount).map { base + up * (Float($0) * height * 1.3) }
            positions[id] = tiers
            let rectangles: [CGRect?] = tiers.map { position in
                let corners = [-right * width / 2, right * width / 2].flatMap { x in
                    [position + x, position + x + up * height]
                }
                let points = corners.compactMap(project)
                guard points.count == 4 else { return nil }
                let xs = points.map(\.x), ys = points.map(\.y)
                return CGRect(x: xs.min()!, y: ys.min()!, width: xs.max()! - xs.min()!,
                              height: ys.max()! - ys.min()!)
            }
            candidates.append(.init(id: id, distance: simd_length(base - camera), rectangles: rectangles))
        }
        for (id, tier) in ProjectedLabelLayout.tiers(for: candidates, viewport: viewport) {
            guard let label = labelsByItemID[id], let position = positions[id]?[tier],
                  let anchor = labelAnchors[id] else { continue }
            label.setPosition(position, relativeTo: nil)
            label.isEnabled = true
            // Keep the leader attached to its item when the card moves in screen space.
            let tip = label.convert(position: anchor.base, from: root)
            if let leader = label.findEntity(named: "answer-leader") {
                leader.position = tip / 2
                leader.scale.y = simd_length(tip) / anchor.offset
                leader.orientation = simd_quatf(from: [0, -1, 0], to: simd_normalize(tip))
            }
            label.findEntity(named: "answer-dot")?.position = tip
        }
    }

    func clear() {
        for label in labelsByItemID.values { label.removeFromParent() }
        labelsByItemID.removeAll()
        labelAnchors.removeAll()
        labelSizes.removeAll()
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
    /// joined to the item by a thin grey leader. Placement is resolved in screen space.
    private func addLabel(_ text: String, caption: String?, for itemID: String, above entity: Entity) {
        let bounds = entity.visualBounds(relativeTo: root)
        let offset = unit * 1.6
        let white = UnlitMaterial(color: .white)
        let ink = UnlitMaterial(color: HologramStyle.ink)
        let red = UnlitMaterial(color: HologramStyle.brandRed)

        // White card, brand-red numbered badge, dark kind label: the same look as the web's citation chips.
        let mesh = MeshResource.generateText(text, extrusionDepth: unit * 0.02,
                                             font: .systemFont(ofSize: CGFloat(unit * 0.7), weight: .semibold))
        let number = ModelEntity(mesh: mesh, materials: [white])
        number.name = text
        let nb = number.visualBounds(relativeTo: number)

        var captionEntity: ModelEntity?
        var cb = BoundingBox(min: .zero, max: .zero)
        if let caption, !caption.isEmpty {
            let short = caption.count > 22 ? String(caption.prefix(21)) + "…" : caption
            let captionMesh = MeshResource.generateText(short.capitalized(with: nil), extrusionDepth: unit * 0.01,
                                                        font: .systemFont(ofSize: CGFloat(unit * 0.55), weight: .medium))
            let entity = ModelEntity(mesh: captionMesh, materials: [ink])
            entity.name = "caption"
            cb = entity.visualBounds(relativeTo: entity)
            captionEntity = entity
        }

        let pad = unit * 0.2
        let gap = captionEntity == nil ? 0 : unit * 0.3
        let badgeH = unit * 1.0
        let badgeW = max(badgeH, nb.extents.x + unit * 0.5)
        let contentWidth = badgeW + gap + (captionEntity == nil ? 0 : cb.extents.x)
        let width = contentWidth + pad * 2
        let height = badgeH + pad * 2

        let border = unit * 0.035
        let radius = height * 0.32
        var edge = UnlitMaterial(color: .black)
        edge.blending = .transparent(opacity: .init(floatLiteral: 0.28))
        let edgePlane = ModelEntity(mesh: .generatePlane(width: width + border * 2, height: height + border * 2,
                                                         cornerRadius: radius + border), materials: [edge])
        let fillPlane = ModelEntity(mesh: .generatePlane(width: width, height: height, cornerRadius: radius),
                                    materials: [white])
        let badge = ModelEntity(mesh: .generatePlane(width: badgeW, height: badgeH, cornerRadius: badgeH * 0.3),
                                materials: [red])
        // Card bottom sits at the origin; the leader hangs from there.
        let cy = height / 2
        let left = -width / 2 + pad
        edgePlane.position = [0, cy, -unit * 0.004]
        fillPlane.position = [0, cy, 0]
        badge.position = [left + badgeW / 2, cy, unit * 0.005]
        number.position = [left + badgeW / 2 - nb.center.x, cy - nb.center.y, unit * 0.01]
        if let captionEntity {
            captionEntity.position = [left + badgeW + gap - cb.min.x, cy - cb.center.y, unit * 0.01]
        }

        let card = Entity()
        card.addChild(edgePlane)
        card.addChild(fillPlane)
        card.addChild(badge)
        card.addChild(number)
        if let captionEntity { card.addChild(captionEntity) }

        let label = Entity()
        label.name = "answer-label-" + itemID
        label.components.set(BillboardComponent())
        let base = SIMD3<Float>(bounds.center.x, bounds.max.y, bounds.center.z)
        label.position = base + [0, offset * labelScale, 0]
        label.scale = SIMD3(repeating: labelScale)
        labelAnchors[itemID] = (base, offset)
        labelSizes[itemID] = [width + border * 2, height + border * 2]
        label.addChild(card)

        // Thin grey leader and a small white dot where it meets the item.
        let width2 = max(unit * 0.02, 0.0015)
        let leader = ModelEntity(mesh: .generateBox(size: [width2, offset, width2]), materials: [ink])
        leader.name = "answer-leader"
        leader.position = [0, -offset / 2, 0]
        label.addChild(leader)
        let dot = ModelEntity(mesh: .generateSphere(radius: unit * 0.07), materials: [red])
        dot.name = "answer-dot"
        dot.position = [0, -offset, 0]
        label.addChild(dot)

        root.addChild(label)
        labelsByItemID[itemID] = label
    }
}
