import QuartzCore
import RealityKit
import UIKit

/// Drives the build-up reveal: a flat plan appears at the footprint, holds, then every group of items rises
/// from its base (scale-Y 0 to 1, ease-out), step by step. One per-frame update moves all active entities, so
/// 784 items cost a loop rather than 784 animation tasks. Prim names and transforms are restored at the end.
@MainActor
final class BuildAnimator {
    static let planHold: TimeInterval = 0.8
    static let planFadeIn: TimeInterval = 0.25
    static let popDuration: TimeInterval = 0.3
    private static let minScale: Float = 0.001

    private struct Target {
        let entity: Entity
        let baseY: Float
        let position: SIMD3<Float>
        let scale: SIMD3<Float>
        let slot: BuildSlot
    }

    private let sequence: BuildSequence
    private var targets: [Target] = []
    private var nextTarget = 0
    private var active: [Int] = []
    private let plan: Entity?
    private let labels: [(entity: Entity, scale: SIMD3<Float>)]
    private var startedAt: TimeInterval = 0
    private(set) var isFinished = false
    private let onFinish: () -> Void

    var buildStart: TimeInterval { plan == nil ? 0 : Self.planHold }
    var totalDuration: TimeInterval { buildStart + sequence.totalDuration + (labels.isEmpty ? 0 : Self.popDuration) }

    init(sequence: BuildSequence, entities: [String: Entity], plan: Entity?, labels: [Entity],
         onFinish: @escaping () -> Void) {
        self.sequence = sequence
        self.plan = plan
        self.labels = labels.map { ($0, $0.scale) }
        self.onFinish = onFinish
        for slot in sequence.slots {
            guard let entity = entities[slot.usdName], entity.isEnabled, let parent = entity.parent else { continue }
            let baseY = entity.visualBounds(relativeTo: parent).min.y
            guard baseY.isFinite else { continue }
            targets.append(Target(entity: entity, baseY: baseY, position: entity.position,
                                  scale: entity.scale, slot: slot))
        }
    }

    func begin(now: TimeInterval = CACurrentMediaTime()) {
        startedAt = now
        for target in targets { apply(target, progress: 0) }
        for label in labels { label.entity.isEnabled = false }
        plan?.components.set(OpacityComponent(opacity: 0))
    }

    func tick(now: TimeInterval = CACurrentMediaTime()) {
        guard !isFinished else { return }
        let t = now - startedAt
        if let plan { plan.components.set(OpacityComponent(opacity: Float(planOpacity(at: t)))) }

        let buildT = t - buildStart
        while nextTarget < targets.count, targets[nextTarget].slot.start <= buildT {
            active.append(nextTarget)
            nextTarget += 1
        }
        active.removeAll { index in
            let target = targets[index]
            let progress = (buildT - target.slot.start) / target.slot.duration
            if progress >= 1 { restore(target); return true }
            apply(target, progress: BuildSequence.easeOut(progress))
            return false
        }

        let popT = buildT - sequence.totalDuration
        if popT >= 0 { popLabels(at: popT) }
        if t >= totalDuration { finish() }
    }

    /// Jump to the finished model.
    func finish() {
        guard !isFinished else { return }
        isFinished = true
        for target in targets { restore(target) }
        active.removeAll()
        for label in labels { label.entity.scale = label.scale; label.entity.isEnabled = true }
        plan?.removeFromParent()
        onFinish()
    }

    /// Plan fades in, holds, then dissolves while the building rises out of it.
    func planOpacity(at t: TimeInterval) -> Double {
        if t < Self.planFadeIn { return t / Self.planFadeIn }
        if t < buildStart { return 1 }
        let fade = max(sequence.totalDuration * 0.85, 0.5)
        return max(0, 1 - (t - buildStart) / fade)
    }

    private func apply(_ target: Target, progress: Double) {
        let s = max(Float(progress), Self.minScale)
        target.entity.scale = SIMD3(target.scale.x, target.scale.y * s, target.scale.z)
        // Keep the base fixed: p'.y = baseY - s * (baseY - p.y).
        target.entity.position = SIMD3(target.position.x, target.baseY - s * (target.baseY - target.position.y),
                                       target.position.z)
    }

    private func restore(_ target: Target) {
        target.entity.scale = target.scale
        target.entity.position = target.position
    }

    private func popLabels(at t: TimeInterval) {
        let p = min(t / Self.popDuration, 1)
        // Overshoot to 1.15 at 60 percent, settle at 1.
        let factor = Float(p < 0.6 ? 1.15 * BuildSequence.easeOut(p / 0.6) : 1.15 - 0.15 * ((p - 0.6) / 0.4))
        for label in labels {
            label.entity.isEnabled = true
            label.entity.scale = label.scale * max(factor, 0.01)
        }
    }
}

/// Draws a plan-view image from item footprints so the reveal has something flat to start from. Generated for demo,
/// not the source drawing.
enum BuildPlanImage {
    struct Rect { let kind: String?; let minX: Float; let maxX: Float; let minZ: Float; let maxZ: Float }

    static func render(rects: [Rect], longSide: CGFloat = 1024) -> CGImage? {
        guard !rects.isEmpty else { return nil }
        let minX = rects.map(\.minX).min()!, maxX = rects.map(\.maxX).max()!
        let minZ = rects.map(\.minZ).min()!, maxZ = rects.map(\.maxZ).max()!
        let w = max(CGFloat(maxX - minX), 0.01), d = max(CGFloat(maxZ - minZ), 0.01)
        let scale = longSide / max(w, d)
        let size = CGSize(width: max(w * scale, 8), height: max(d * scale, 8))
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        let image = UIGraphicsImageRenderer(size: size, format: format).image { context in
            HologramStyle.stage.setFill()
            context.fill(CGRect(origin: .zero, size: size))
            let cg = context.cgContext
            for rect in rects.sorted(by: { order($0.kind) < order($1.kind) }) {
                let frame = CGRect(x: CGFloat(rect.minX - minX) * scale, y: CGFloat(rect.minZ - minZ) * scale,
                                   width: max(CGFloat(rect.maxX - rect.minX) * scale, 2),
                                   height: max(CGFloat(rect.maxZ - rect.minZ) * scale, 2))
                switch rect.kind {
                case "door": HologramStyle.brandRed.setFill()
                case "window": HologramStyle.forest.withAlphaComponent(0.55).setFill()
                case "slab", "floor": UIColor(white: 0.9, alpha: 1).setFill()
                default: HologramStyle.bark.setFill()
                }
                cg.fill(frame)
            }
        }
        return image.cgImage
    }

    private static func order(_ kind: String?) -> Int {
        switch kind { case "slab", "floor": return 0; case "wall": return 1; default: return 2 }
    }

    /// Flat quad on the XZ plane facing up. Image top maps to -z, so the plan reads like a map seen from above.
    static func mesh(width: Float, depth: Float) -> MeshResource? {
        var descriptor = MeshDescriptor(name: "build-plan")
        descriptor.positions = MeshBuffer([[-width / 2, 0, -depth / 2], [width / 2, 0, -depth / 2],
                                           [width / 2, 0, depth / 2], [-width / 2, 0, depth / 2]])
        descriptor.normals = MeshBuffer([[0, 1, 0], [0, 1, 0], [0, 1, 0], [0, 1, 0]])
        descriptor.textureCoordinates = MeshBuffer([[0, 0], [1, 0], [1, 1], [0, 1]])
        descriptor.primitives = .triangles([0, 2, 1, 0, 3, 2])
        return try? MeshResource.generate(from: [descriptor])
    }
}
