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
    /// Per answer item: the mesh entities that carry its highlight material, and that colour.
    private var litGroups: [String: (entities: [Entity], color: UIColor)] = [:]
    private var originalMaterials: [ObjectIdentifier: [any Material]] = [:]
    /// Tags held back while the choreography has not reached their item yet.
    private var suppressedLabelIDs: Set<String> = []

    init(root: Entity) {
        self.root = root
        index = SceneIndex(root: root)
        unit = Self.labelUnit(for: root)
        func capture(_ entity: Entity) {
            if let model = entity.components[ModelComponent.self] {
                originals.append(Original(entity: entity, materials: model.materials))
                originalMaterials[ObjectIdentifier(entity)] = model.materials
            }
            for child in entity.children { capture(child) }
        }
        capture(root)
    }

    private var roomPlates: [String: Entity] = [:]

    /// Rooms highlight through their floor tint plate (room volumes are hidden). Call after the blueprint is built
    /// and before the first highlight; the plate's own material is restored on clear.
    func attachRoomPlates(_ plates: [String: ModelEntity]) {
        for (id, plate) in plates {
            roomPlates[id] = plate
            if let model = plate.components[ModelComponent.self] {
                originals.append(Original(entity: plate, materials: model.materials))
                originalMaterials[ObjectIdentifier(plate)] = model.materials
            }
        }
    }

    /// Tag and callout size follows the model so a 1:100 table model still reads clearly.
    static func labelUnit(for root: Entity) -> Float {
        let extent = root.visualBounds(relativeTo: root).extents.max()
        return max(0.15, extent.isFinite ? extent * 0.021 : 0)
    }

    /// Tags stay parallel to the screen (upright, never rolled) by copying the camera rotation. A full billboard
    /// rolls arbitrarily when the phone looks straight down at the table.
    func faceCamera(_ orientation: simd_quatf) {
        for label in labelsByItemID.values where label.isEnabled {
            label.setOrientation(orientation, relativeTo: nil)
        }
    }

    /// Walk mode is 1:1, where table-sized tags would be huge.
    func setLabelScale(_ scale: Float) {
        labelScale = scale
        for (id, label) in labelsByItemID {
            label.scale = SIMD3(repeating: scale)
            if let anchor = labelAnchors[id] { label.position = anchor.base + [0, anchor.offset * scale, 0] }
        }
    }

    /// More than this many highlighted items and the per-item tags are dropped (same number as the web, W-53).
    static let tagLimit = 12

    static func isDense(count: Int) -> Bool { count > tagLimit }

    /// Labels are keyed by item ID so a filtered selection can retain its 2D numbers.
    /// Without explicit labels, numbers follow the original request order, including missing IDs.
    /// Captions are short item names shown under each number.
    /// `kinds` maps item IDs to their kind; items with a kind get that kind's colour on the item, badge and dot,
    /// the rest keep the accent colour.
    func highlight(itemIDs: [String], labels: [String: String] = [:], captions: [String: String] = [:],
                   kinds: [String: String] = [:], details: [String: String] = [:]) {
        clear()
        guard !itemIDs.isEmpty else { return }

        var selected: Set<ObjectIdentifier> = []
        var colorFor: [ObjectIdentifier: UIColor] = [:]
        var groups: [String: (entities: [Entity], color: UIColor)] = [:]
        var resolved: [(id: String, entity: Entity, label: String)] = []
        var seen: Set<String> = []
        func select(_ entity: Entity, color: UIColor) {
            selected.insert(ObjectIdentifier(entity))
            colorFor[ObjectIdentifier(entity)] = color
            for child in entity.children { select(child, color: color) }
        }
        for (offset, id) in itemIDs.enumerated() where seen.insert(id).inserted {
            guard let entity = roomPlates[id] ?? index.entity(for: id) else { continue }
            select(entity, color: kinds[id].flatMap { $0.isEmpty ? nil : KindColors.style(for: $0).color }
                   ?? Self.accentColor)
            resolved.append((id, entity, labels[id] ?? String(offset + 1)))
            let color = colorFor[ObjectIdentifier(entity)] ?? Self.accentColor
            var meshes: [Entity] = []
            func collect(_ node: Entity) {
                if node.components[ModelComponent.self] != nil { meshes.append(node) }
                for child in node.children { collect(child) }
            }
            collect(entity)
            groups[id] = (meshes, color)
        }
        // Unknown evidence should leave the drawing readable rather than dim everything.
        guard !resolved.isEmpty else { return }
        
        for original in originals {
            guard var model = original.entity.components[ModelComponent.self],
                  selected.contains(ObjectIdentifier(original.entity)) else { continue }
            let highlight = UnlitMaterial(color: colorFor[ObjectIdentifier(original.entity)] ?? Self.accentColor)
            model.materials = Array(repeating: highlight, count: max(original.materials.count, 1))
            original.entity.components.set(model)
        }
        litGroups = groups
        // Dense answers (web W-53 rule): keep the per-kind glow and the legend chip, drop the per-item tags.
        // The tapped item still gets its callout through ARSceneController.selectedItem.
        guard !Self.isDense(count: resolved.count) else { return }
        for item in resolved {
            let style = kinds[item.id].flatMap { $0.isEmpty ? nil : KindColors.style(for: $0) }
            let base = style.flatMap { $0.key == "other" ? nil : $0.label } ?? captions[item.id]
            // "Door \u{00B7} 0.90 m": the detail keeps its own case (capitalising would turn "m" into "M").
            // With a detail the numbered badge already names the item ("D3"), so the caption is "D3 \u{00B7} 1.00 m".
            let caption = details[item.id] ?? base.map { $0.capitalized(with: nil) }
            addLabel(item.label, caption: caption,
                     for: item.id, above: item.entity, style: style)
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
            guard !suppressedLabelIDs.contains(id), visibleItemIDs.contains(id), let anchor = labelAnchors[id],
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
        litGroups.removeAll()
        suppressedLabelIDs.removeAll()
        restoreOriginals()
    }

    /// Turns one answer item's highlight on or off without touching its tag (used to light items up in sequence).
    func setLit(_ itemID: String, _ lit: Bool) {
        guard let group = litGroups[itemID] else { return }
        let highlight = UnlitMaterial(color: group.color)
        for entity in group.entities {
            guard var model = entity.components[ModelComponent.self] else { continue }
            let original = originalMaterials[ObjectIdentifier(entity)] ?? model.materials
            model.materials = lit ? Array(repeating: highlight, count: max(original.count, 1)) : original
            entity.components.set(model)
        }
    }

    /// Hides tags until `revealLabel` is called, e.g. while the choreography waits for their item.
    func suppressLabels(_ ids: Set<String>) {
        suppressedLabelIDs.formUnion(ids)
        for id in ids { labelsByItemID[id]?.isEnabled = false }
    }

    func revealLabel(_ itemID: String) {
        suppressedLabelIDs.remove(itemID)
        labelsByItemID[itemID]?.isEnabled = true
    }

    var litItemIDs: [String] { Array(litGroups.keys) }

    private func restoreOriginals() {
        for original in originals {
            guard var model = original.entity.components[ModelComponent.self] else { continue }
            model.materials = original.materials
            original.entity.components.set(model)
        }
    }

    /// Floating billboard tag: a dark capsule with a bold number and a small kind label,
    /// joined to the item by a thin grey leader. Placement is resolved in screen space.
    private func addLabel(_ text: String, caption: String?, for itemID: String, above entity: Entity,
                          style: KindStyle?) {
        let bounds = entity.visualBounds(relativeTo: root)
        let offset = unit * 1.6
        let white = UnlitMaterial(color: .white)
        let ink = UnlitMaterial(color: HologramStyle.ink)
        let red = UnlitMaterial(color: style?.color ?? HologramStyle.brandRed)
        let onBadge = UnlitMaterial(color: style?.on ?? .white)

        // White card, brand-red numbered badge, dark kind label: the same look as the web's citation chips.
        let mesh = MeshResource.generateText(text, extrusionDepth: unit * 0.02,
                                             font: .systemFont(ofSize: CGFloat(unit * 0.7), weight: .semibold))
        let number = ModelEntity(mesh: mesh, materials: [onBadge])
        number.name = text
        let nb = number.visualBounds(relativeTo: number)

        var captionEntity: ModelEntity?
        var cb = BoundingBox(min: .zero, max: .zero)
        if let caption, !caption.isEmpty {
            let short = caption.count > 26 ? String(caption.prefix(25)) + "…" : caption
            let captionMesh = MeshResource.generateText(short, extrusionDepth: unit * 0.01,
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
