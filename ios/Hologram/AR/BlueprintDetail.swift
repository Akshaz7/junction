import RealityKit
import UIKit

/// Blueprint-level detail drawn inside the model: element materials, wall cut tops, floor tints with room
/// names and areas, overall dimension lines and the storey label. Everything is flat on the floor so it
/// reads from above, and sits in one group per storey that follows the cutaway.
@MainActor
final class BlueprintDetail {
    private struct FloorLabel {
        let entity: Entity
        let width: Float
    }

    private let group = Entity()
    private var storeyGroups: [String: Entity] = [:]
    private var floorLabels: [(storey: String, label: FloorLabel)] = []
    private var lastLOD: TimeInterval = 0

    var root: Entity { group }

    /// Thin floor tint per room item ID. An answer that highlights a room lights this plate, never a solid volume.
    private(set) var roomPlates: [String: ModelEntity] = [:]

    // MARK: Materials and wall cut tops (before highlight capture)

    static func applyMaterials(manifest: SceneManifest, index: SceneIndex, content: Entity) {
        let capMesh = MeshResource.generateBox(size: 1)
        let capMaterial = SimpleMaterial(color: BlueprintStyle.wallCapColor, roughness: 0.9, isMetallic: false)
        var cache: [String: any Material] = [:]
        for item in manifest.items.values {
            guard let surface = BlueprintStyle.surface(for: item.kind),
                  let entity = index.entitiesByUSDName[item.usd_name] else { continue }
            let key = "\(item.kind ?? "")"
            let material: any Material
            if let cached = cache[key] { material = cached } else {
                var pbr = PhysicallyBasedMaterial()
                pbr.baseColor = .init(tint: surface.color.withAlphaComponent(surface.alpha))
                pbr.roughness = .init(floatLiteral: surface.roughness)
                pbr.metallic = .init(floatLiteral: 0)
                if surface.alpha < 1 { pbr.blending = .transparent(opacity: .init(floatLiteral: Float(surface.alpha))) }
                cache[key] = pbr
                material = pbr
            }
            recolour(entity, material)
            if item.kind?.lowercased() == "wall" { addCap(to: entity, content: content, mesh: capMesh, material: capMaterial) }
        }
    }

    private static func recolour(_ entity: Entity, _ material: any Material) {
        if var model = entity.components[ModelComponent.self] {
            model.materials = Array(repeating: material, count: max(model.materials.count, 1))
            entity.components.set(model)
        }
        for child in entity.children { recolour(child, material) }
    }

    /// A thin dark slab on top of an axis-aligned wall: the blueprint "poche" cut. Diagonal and very thick
    /// boxes are skipped because their bounding box would overstate the wall.
    private static func addCap(to wall: Entity, content: Entity, mesh: MeshResource, material: SimpleMaterial) {
        let box = wall.visualBounds(relativeTo: content)
        let size = box.extents
        guard size.x.isFinite, size.z.isFinite, min(size.x, size.z) > 0.03, min(size.x, size.z) <= 0.6,
              max(size.x, size.z) >= 2 * min(size.x, size.z) else { return }
        let cap = ModelEntity(mesh: mesh, materials: [material])
        cap.name = "blueprint-cap"
        wall.addChild(cap)
        cap.setScale([size.x, 0.03, size.z], relativeTo: content)
        cap.setPosition([box.center.x, box.max.y + 0.012, box.center.z], relativeTo: content)
    }

    // MARK: Floor labels, dimensions, storey label (after placement geometry is final)

    /// Everything here reads manifest boxes (they share the USD content frame; see DemoSceneTests), never the
    /// visible entities: room volumes are hidden by the cutaway and report no bounds.
    func build(manifest: SceneManifest, index: SceneIndex, content: Entity) {
        group.name = "blueprint-detail"
        let policy = CutawayPolicy(manifest: manifest)
        let elevations = Dictionary(policy.storeys.compactMap { s in s.name.map { ($0, s.elevation_m ?? 0) } },
                                    uniquingKeysWith: { first, _ in first })
        let floorTops = Self.floorTops(manifest: manifest, elevations: elevations)
        var wallRects: [String: (minX: Float, maxX: Float, minZ: Float, maxZ: Float)] = [:]
        var slabRects: [String: (minX: Float, maxX: Float, minZ: Float, maxZ: Float)] = [:]
        func grow(_ rects: inout [String: (minX: Float, maxX: Float, minZ: Float, maxZ: Float)],
                  _ storey: String, _ box: SceneBounds) {
            var r = rects[storey] ?? (box.minimum.x, box.maximum.x, box.minimum.z, box.maximum.z)
            r.minX = min(r.minX, box.minimum.x); r.maxX = max(r.maxX, box.maximum.x)
            r.minZ = min(r.minZ, box.minimum.z); r.maxZ = max(r.maxZ, box.maximum.z)
            rects[storey] = r
        }
        for (id, item) in manifest.items {
            guard let storey = item.storey, elevations[storey] != nil, let box = item.bbox_m else { continue }
            switch item.kind?.lowercased() {
            case "wall": grow(&wallRects, storey, box)
            case "slab", "floor": grow(&slabRects, storey, box)
            case "room", "space":
                let floorY = floorTops[storey] ?? (elevations[storey] ?? 0) + 0.02
                addRoom(id, item, box: box, storey: storey, floorY: floorY)
            default: break
            }
        }
        // Overall footprint of the walls, else the slabs (web rule); nothing is measured from rooms.
        for (storey, rect) in slabRects where wallRects[storey] == nil { wallRects[storey] = rect }
        for (storey, rect) in wallRects {
            let label = BlueprintStyle.storeyLabel(name: storey, elevation: elevations[storey] ?? 0)
            addDimensions(rect: (rect.minX, rect.maxX, rect.minZ, rect.maxZ,
                                 floorTops[storey] ?? (elevations[storey] ?? 0) + 0.02),
                          storey: storey, storeyLabel: label)
        }
        for (name, entity) in storeyGroups { entity.isEnabled = name == policy.activeStorey() }
    }

    /// Top of each storey's floor slab, +2 cm: the highest slab surface that starts at the storey elevation.
    static func floorTops(manifest: SceneManifest, elevations: [String: Float]) -> [String: Float] {
        var tops: [String: Float] = [:]
        for item in manifest.items.values {
            guard item.kind?.lowercased() == "slab" || item.kind?.lowercased() == "floor",
                  let storey = item.storey, let elevation = elevations[storey], let box = item.bbox_m,
                  box.minimum.y <= elevation + 0.1, box.maximum.y <= elevation + 0.6,
                  box.maximum.y >= elevation - 0.6 else { continue }
            tops[storey] = max(tops[storey] ?? -.greatestFiniteMagnitude, box.maximum.y)
        }
        return tops.mapValues { $0 + 0.02 }
    }

    private func storeyGroup(_ name: String) -> Entity {
        if let existing = storeyGroups[name] { return existing }
        let entity = Entity()
        entity.name = "blueprint-storey"
        group.addChild(entity)
        storeyGroups[name] = entity
        return entity
    }

    private func addRoom(_ id: String, _ item: SceneManifest.Item, box: SceneBounds, storey: String, floorY: Float) {
        let extents = box.maximum - box.minimum
        let footprint = SIMD2(extents.x, extents.z)
        guard footprint.x > 0.5, footprint.y > 0.5 else { return }
        let parent = storeyGroup(storey)
        // Floor tint, inset so the walls stay crisp.
        let plate = ModelEntity(
            mesh: .generateBox(size: [max(footprint.x - 0.2, 0.1), 0.01, max(footprint.y - 0.2, 0.1)]),
            materials: [Self.flatMaterial(BlueprintStyle.roomTint(BlueprintStyle.roomType(item)), alpha: 0.7)])
        plate.name = "blueprint-floor"
        plate.position = [box.center.x, floorY + 0.005, box.center.z]
        parent.addChild(plate)
        roomPlates[id] = plate
        guard let text = BlueprintStyle.roomLabel(name: BlueprintStyle.roomName(item),
                                                  area: BlueprintStyle.roomArea(item)),
              let metrics = Self.measure(text),
              let layout = BlueprintStyle.roomLabelLayout(footprint: footprint, textPerMetre: metrics.perMetre),
              let label = Self.flatText(text, scale: layout.fontSize / Self.baseFont, color: BlueprintStyle.roomLabelColor)
        else { return }
        if layout.rotated { label.entity.orientation = simd_quatf(angle: .pi / 2, axis: [0, 1, 0]) * label.entity.orientation }
        // Room volumes are never drawn on the table, so every label lies on its floor tint.
        let y = floorY + 0.03
        label.entity.position = [box.center.x, y, box.center.z]
        label.entity.name = "blueprint-room-label"
        parent.addChild(label.entity)
        floorLabels.append((storey, label))
    }

    private func addDimensions(rect: (minX: Float, maxX: Float, minZ: Float, maxZ: Float, y: Float),
                               storey: String, storeyLabel: String) {
        let parent = storeyGroup(storey)
        let width = rect.maxX - rect.minX, depth = rect.maxZ - rect.minZ
        guard width > 1, depth > 1 else { return }
        let y = rect.y + 0.01
        let line = Self.flatMaterial(UIColor(white: 0.12, alpha: 1), alpha: 1)
        let offset: Float = 1.2
        func bar(_ size: SIMD3<Float>, _ at: SIMD3<Float>) {
            let e = ModelEntity(mesh: .generateBox(size: size), materials: [line])
            e.position = at
            e.name = "blueprint-dimension"
            parent.addChild(e)
        }
        let zLine = rect.maxZ + offset, xLine = rect.minX - offset
        bar([width, 0.012, 0.05], [(rect.minX + rect.maxX) / 2, y, zLine])
        bar([0.05, 0.012, 0.25], [rect.minX, y, zLine])
        bar([0.05, 0.012, 0.25], [rect.maxX, y, zLine])
        bar([0.05, 0.012, depth], [xLine, y, (rect.minZ + rect.maxZ) / 2])
        bar([0.25, 0.012, 0.05], [xLine, y, rect.minZ])
        bar([0.25, 0.012, 0.05], [xLine, y, rect.maxZ])
        let ink = BlueprintStyle.inkColor
        if let t = Self.flatText(BlueprintStyle.dimensionText(width), fitWidth: width * 0.5, fitDepth: 0.9, color: ink, plate: true) {
            t.entity.position = [(rect.minX + rect.maxX) / 2, y + 0.02, zLine]
            t.entity.name = "blueprint-dimension-label"
            parent.addChild(t.entity)
            floorLabels.append((storey, t))
        }
        if let t = Self.flatText(BlueprintStyle.dimensionText(depth), fitWidth: depth * 0.5, fitDepth: 0.9, color: ink, plate: true) {
            // Reads bottom to top along the left edge.
            t.entity.orientation = simd_quatf(angle: .pi / 2, axis: [0, 1, 0]) * t.entity.orientation
            t.entity.position = [xLine, y + 0.02, (rect.minZ + rect.maxZ) / 2]
            t.entity.name = "blueprint-dimension-label"
            parent.addChild(t.entity)
            floorLabels.append((storey, t))
        }
        if let t = Self.flatText(storeyLabel, fitWidth: max(width * 0.6, 2), fitDepth: 0.9, color: ink) {
            t.entity.position = [rect.minX + t.width / 2, y + 0.01, rect.minZ - 0.6]
            t.entity.name = "blueprint-storey-label"
            parent.addChild(t.entity)
            floorLabels.append((storey, t))
        }
    }

    // MARK: Per frame

    /// Follows the cutaway storey, hides during the build-up, and fades floor text that is too small on screen.
    func update(activeStorey: String?, hidden: Bool, cameraPosition: SIMD3<Float>, time: TimeInterval) {
        group.isEnabled = !hidden
        guard !hidden, time - lastLOD >= 0.25 else { return }
        lastLOD = time
        for (name, entity) in storeyGroups { entity.isEnabled = name == activeStorey }
        for (storey, label) in floorLabels where storey == activeStorey {
            let world = label.entity.position(relativeTo: nil)
            let scale = label.entity.scale(relativeTo: nil).x / max(label.entity.scale.x, 0.0001)
            let opacity = BlueprintStyle.labelOpacity(width: label.width * scale,
                                                      distance: simd_distance(world, cameraPosition))
            label.entity.components.set(OpacityComponent(opacity: opacity))
            label.entity.isEnabled = opacity > 0.01
        }
    }

    // MARK: Helpers

    private static func flatMaterial(_ color: UIColor, alpha: CGFloat) -> UnlitMaterial {
        var material = UnlitMaterial(color: color.withAlphaComponent(alpha))
        if alpha < 1 { material.blending = .transparent(opacity: .init(floatLiteral: Float(alpha))) }
        return material
    }

    static let baseFont: Float = 0.3

    /// Text extent for a 1 m font, used to lay a label out before it is built.
    private static func measure(_ text: String) -> (perMetre: SIMD2<Float>, mesh: MeshResource)? {
        let font = UIFont.systemFont(ofSize: CGFloat(baseFont), weight: .semibold)
        let mesh = MeshResource.generateText(text, extrusionDepth: 0.002, font: font, containerFrame: .zero,
                                             alignment: .center, lineBreakMode: .byWordWrapping)
        let extents = mesh.bounds.extents
        guard extents.x > 0, extents.y > 0 else { return nil }
        return (SIMD2(extents.x, extents.y) / baseFont, mesh)
    }

    private static func flatText(_ text: String, fitWidth: Float, fitDepth: Float, color: UIColor, plate: Bool = false) -> FloorLabel? {
        guard let (perMetre, _) = measure(text) else { return nil }
        let fit = min(1, fitWidth / (perMetre.x * baseFont), fitDepth / (perMetre.y * baseFont))
        guard fit >= 0.2 else { return nil }
        return flatText(text, scale: fit, color: color, plate: plate)
    }

    /// Text lying flat on the floor (no billboard), centred, at an explicit scale (1 = 0.3 m font).
    private static func flatText(_ text: String, scale fit: Float, color: UIColor, plate: Bool = false) -> FloorLabel? {
        guard let (_, mesh) = measure(text) else { return nil }
        let extents = mesh.bounds.extents
        let model = ModelEntity(mesh: mesh, materials: [UnlitMaterial(color: color)])
        // Centre the text on its own origin, then lay it flat so the top of the text points to -z.
        model.position = [-mesh.bounds.center.x, -mesh.bounds.center.y, 0]
        let holder = Entity()
        // Subtle light halo: four offset copies in paper white behind the ink.
        let halo = UnlitMaterial(color: BlueprintStyle.paperColor.withAlphaComponent(0.9))
        for (dx, dy) in [(0.012, 0.0), (-0.012, 0.0), (0.0, 0.012), (0.0, -0.012)] as [(Float, Float)] {
            let h = ModelEntity(mesh: mesh, materials: [halo])
            h.position = [-mesh.bounds.center.x + dx, -mesh.bounds.center.y + dy, -0.004]
            holder.addChild(h)
        }
        if plate {
            // Paper patch behind a dimension value so the number sits centred on its line.
            let patch = ModelEntity(mesh: .generateBox(size: [extents.x + 0.4, extents.y + 0.3, 0.004]),
                                    materials: [UnlitMaterial(color: BlueprintStyle.paperColor)])
            patch.position = [0, 0, -0.01]
            holder.addChild(patch)
        }
        holder.addChild(model)
        holder.orientation = simd_quatf(angle: -.pi / 2, axis: [1, 0, 0])
        holder.scale = SIMD3(repeating: fit)
        return FloorLabel(entity: holder, width: extents.x * fit)
    }
}
