import RealityKit
import UIKit

/// An unlit pale blue box keeps tap selection distinct from red answer evidence.
/// It has no collision shapes and never replaces the scene's materials.
@MainActor
final class ItemSelectionOutline {
    private(set) var outline: Entity?

    func select(_ entity: Entity) {
        clear()
        let bounds = entity.visualBounds(relativeTo: entity)
        guard bounds.extents.x.isFinite, bounds.extents.y.isFinite, bounds.extents.z.isFinite,
              bounds.extents.max() > 0 else { return }
        let thickness = max(bounds.extents.max() * 0.004, 0.005)
        let half = bounds.extents / 2 + SIMD3<Float>(repeating: thickness)
        let outline = Entity()
        outline.name = "tap-selection-outline"
        outline.position = bounds.center
        let material = UnlitMaterial(color: UIColor(red: 0.65, green: 0.9, blue: 1, alpha: 1))
        for axis in 0..<3 {
            let crossA = (axis + 1) % 3
            let crossB = (axis + 2) % 3
            for a in [Float(-1), Float(1)] {
                for b in [Float(-1), Float(1)] {
                    var size = SIMD3<Float>(repeating: thickness)
                    size[axis] = half[axis] * 2
                    let edge = ModelEntity(mesh: .generateBox(size: size), materials: [material])
                    edge.position[crossA] = half[crossA] * a
                    edge.position[crossB] = half[crossB] * b
                    outline.addChild(edge)
                }
            }
        }
        entity.addChild(outline)
        self.outline = outline
    }

    func clear() {
        outline?.removeFromParent()
        outline = nil
    }
}
