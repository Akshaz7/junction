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

    func build(manifest: SceneManifest, index: SceneIndex, content: Entity) {
        group.name = "blueprint-detail"
        let policy = CutawayPolicy(manifest: manifest)
        let elevations = Dictionary(policy.storeys.compactMap { s in s.name.map { ($0, s.elevation_m ?? 0) } },
                                    uniquingKeysWith: { first, _ in first })
        var wallRects: [String: (minX: Float, maxX: Float, minZ: Float, maxZ: Float, y: Float)] = [:]
        for item in manifest.items.values {
            guard let storey = item.storey, elevations[storey] != nil,
                  let entity = index.entitiesByUSDName[item.usd_name] else { continue }
            let box = entity.visualBounds(relativeTo: content)
            guard box.extents.x.isFinite, box.extents.z.isFinite, box.extents.x > 0 || box.extents.z > 0 else { continue }
            switch item.kind?.lowercased() {
            case "wall":
                var r = wallRects[storey] ?? (box.min.x, box.max.x, box.min.z, box.max.z, box.min.y)
                r.minX = min(r.minX, box.min.x); r.maxX = max(r.maxX, box.max.x)
                r.minZ = min(r.minZ, box.min.z); r.maxZ = max(r.maxZ, box.max.z)
                r.y = min(r.y, box.min.y)
                wallRects[storey] = r
            case "room", "space":
                addRoom(item, box: box, storey: storey, content: content)
            default: break
            }
        }
        for (storey, rect) in wallRects {
            let label = BlueprintStyle.storeyLabel(name: storey, elevation: elevations[storey] ?? 0)
            addDimensions(rect: rect, storey: storey, storeyLabel: label)
        }
        for (name, entity) in storeyGroups { entity.isEnabled = name == policy.activeStorey() }
    }

    private func storeyGroup(_ name: String) -> Entity {
        if let existing = storeyGroups[name] { return existing }
        let entity = Entity()
        entity.name = "blueprint-storey"
        group.addChild(entity)
        storeyGroups[name] = entity
        return entity
    }

    private func addRoom(_ item: SceneManifest.Item, box: BoundingBox, storey: String, content: Entity) {
        let footprint = SIMD2(box.extents.x, box.extents.z)
        guard footprint.x > 0.5, footprint.y > 0.5 else { return }
        let name = BlueprintStyle.roomName(item)
        let area = BlueprintStyle.roomArea(item, footprint: footprint)
        let parent = storeyGroup(storey)
        let floorY = box.min.y
        // Floor tint, inset so the walls stay crisp.
        let plate = ModelEntity(
            mesh: .generateBox(size: [max(footprint.x - 0.2, 0.1), 0.01, max(footprint.y - 0.2, 0.1)]),
            materials: [Self.flatMaterial(BlueprintStyle.roomTint(BlueprintStyle.roomType(name: name)), alpha: 0.7)])
        plate.name = "blueprint-floor"
        plate.position = [box.center.x, floorY + 0.045, box.center.z]
        parent.addChild(plate)
        guard area >= BlueprintStyle.minLabelledArea else { return }
        let text = BlueprintStyle.roomLabel(name: name, area: area)
        guard let label = Self.flatText(text, fitWidth: footprint.x * 0.8, fitDepth: footprint.y * 0.7,
                                        color: UIColor(white: 0.15, alpha: 1)) else { return }
        label.entity.position = [box.center.x, floorY + 0.07, box.center.z]
        label.entity.name = "blueprint-room-label"
        parent.addChild(label.entity)
        floorLabels.append((storey, label))
    }

    private func addDimensions(rect: (minX: Float, maxX: Float, minZ: Float, maxZ: Float, y: Float),
                               storey: String, storeyLabel: String) {
        let parent = storeyGroup(storey)
        let width = rect.maxX - rect.minX, depth = rect.maxZ - rect.minZ
        guard width > 1, depth > 1 else { return }
        let y = rect.y + 0.07
        let line = Self.flatMaterial(UIColor(white: 0.12, alpha: 1), alpha: 1)
        let offset: Float = 0.7
        func bar(_ size: SIMD3<Float>, _ at: SIMD3<Float>) {
            let e = ModelEntity(mesh: .generateBox(size: size), materials: [line])
            e.position = at
            e.name = "blueprint-dimension"
            parent.addChild(e)
        }
        let zLine = rect.maxZ + offset, xLine = rect.minX - offset
        bar([width, 0.012, 0.05], [(rect.minX + rect.maxX) / 2, y, zLine])
        bar([0.05, 0.012, 0.4], [rect.minX, y, zLine])
        bar([0.05, 0.012, 0.4], [rect.maxX, y, zLine])
        bar([0.05, 0.012, depth], [xLine, y, (rect.minZ + rect.maxZ) / 2])
        bar([0.4, 0.012, 0.05], [xLine, y, rect.minZ])
        bar([0.4, 0.012, 0.05], [xLine, y, rect.maxZ])
        let ink = UIColor(white: 0.1, alpha: 1)
        if let t = Self.flatText(BlueprintStyle.dimensionText(width), fitWidth: width * 0.5, fitDepth: 0.9, color: ink) {
            t.entity.position = [(rect.minX + rect.maxX) / 2, y + 0.01, zLine + 0.5]
            t.entity.name = "blueprint-dimension-label"
            parent.addChild(t.entity)
            floorLabels.append((storey, t))
        }
        if let t = Self.flatText(BlueprintStyle.dimensionText(depth), fitWidth: depth * 0.5, fitDepth: 0.9, color: ink) {
            // Reads bottom to top along the left edge.
            t.entity.orientation = simd_quatf(angle: .pi / 2, axis: [0, 1, 0]) * t.entity.orientation
            t.entity.position = [xLine - 0.5, y + 0.01, (rect.minZ + rect.maxZ) / 2]
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

    /// Text lying flat on the floor (no billboard), centred, scaled down to fit the given box.
    private static func flatText(_ text: String, fitWidth: Float, fitDepth: Float, color: UIColor) -> FloorLabel? {
        let font = UIFont.systemFont(ofSize: 0.3, weight: .semibold)
        let mesh = MeshResource.generateText(text, extrusionDepth: 0.002, font: font, containerFrame: .zero,
                                             alignment: .center, lineBreakMode: .byWordWrapping)
        let extents = mesh.bounds.extents
        guard extents.x > 0, extents.y > 0 else { return nil }
        let fit = min(1, fitWidth / extents.x, fitDepth / extents.y)
        guard fit >= 0.3 else { return nil }
        let model = ModelEntity(mesh: mesh, materials: [UnlitMaterial(color: color)])
        // Centre the text on its own origin, then lay it flat so the top of the text points to -z.
        model.position = [-mesh.bounds.center.x, -mesh.bounds.center.y, 0]
        let holder = Entity()
        holder.addChild(model)
        holder.orientation = simd_quatf(angle: -.pi / 2, axis: [1, 0, 0])
        holder.scale = SIMD3(repeating: fit)
        return FloorLabel(entity: holder, width: extents.x * fit)
    }
}
