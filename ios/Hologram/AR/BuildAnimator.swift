import QuartzCore
import RealityKit
import UIKit

/// Drives the build-up and its scrubber. State is one position 0...N (N steps, same as the web `rise.ts`): steps
/// 1...floor(p) are complete and the next one is growing (scale-Y from its own base, ease-out, staggered from the
/// model centre). Playing advances the position with time; the scrubber sets it directly. Items in `pinned` (the
/// answer's highlights) stay fully grown whatever the step. One per-frame update moves only entities whose growth
/// changed, so 784 items cost a loop rather than 784 animation tasks.
@MainActor
final class BuildAnimator {
    static let planHold: TimeInterval = 0.8
    static let planFadeIn: TimeInterval = 0.25
    /// Used by the answer choreography for its label pop.
    static let popDuration: TimeInterval = 0.3
    private static let minScale: Float = 0.001

    private struct Target {
        let entity: Entity
        let baseY: Float
        let position: SIMD3<Float>
        let scale: SIMD3<Float>
        let usdName: String
        let step: Int
        let index: Int
        let count: Int
        var applied: Double = 1
    }

    let sequence: BuildSequence
    private var targets: [Target] = []
    private let plan: Entity?
    private let pinned: () -> Set<String>
    private var lastPinned: Set<String> = []
    private var lastTick: TimeInterval?
    private var elapsed: TimeInterval = 0
    private var intro: TimeInterval = 0
    private var dirty = true
    private(set) var position: Double = 0
    private(set) var isPlaying = false

    var total: Int { sequence.total }
    var isComplete: Bool { position >= Double(total) && !isPlaying }

    var state: BuildState {
        let index = min(total, max(1, Int(ceil(position - 1e-9))))
        return BuildState(index: index, total: total, label: sequence.steps[safe: index - 1]?.label ?? "",
                          playing: isPlaying, finished: position >= Double(total))
    }

    init(sequence: BuildSequence, entities: [String: Entity], plan: Entity?, pinned: @escaping () -> Set<String>) {
        self.sequence = sequence
        self.plan = plan
        self.pinned = pinned
        for (stepIndex, step) in sequence.steps.enumerated() {
            for (index, name) in step.usdNames.enumerated() {
                guard let entity = entities[name], entity.isEnabled, let parent = entity.parent else { continue }
                let baseY = entity.visualBounds(relativeTo: parent).min.y
                guard baseY.isFinite else { continue }
                targets.append(Target(entity: entity, baseY: baseY, position: entity.position, scale: entity.scale,
                                      usdName: name, step: stepIndex, index: index, count: step.usdNames.count))
            }
        }
    }

    /// Starts at the flat plan and plays, or, with Reduce Motion, shows the finished model with the scrubber ready.
    func begin(reduceMotion: Bool = false) {
        lastTick = nil
        elapsed = 0
        if reduceMotion {
            position = Double(total)
            isPlaying = false
        } else {
            position = 0
            isPlaying = true
            intro = plan == nil ? 0 : Self.planHold
        }
        dirty = true
        refresh(force: true)
    }

    func tick(now: TimeInterval = CACurrentMediaTime()) {
        let dt = lastTick.map { min(max(now - $0, 0), 0.1) } ?? 0
        lastTick = now
        elapsed += dt
        if isPlaying {
            var remaining = dt
            if intro > 0 {
                let used = min(intro, remaining)
                intro -= used
                remaining -= used
            }
            if remaining > 0 {
                position = min(Double(total), position + remaining / sequence.stepSeconds)
                dirty = true
                if position >= Double(total) { isPlaying = false }
            }
        }
        let current = pinned()
        if current != lastPinned { dirty = true }
        if dirty || elapsed < Self.planFadeIn { refresh(force: false) }
    }

    func play() {
        if position >= Double(total) { position = 0; intro = plan == nil ? 0 : Self.planHold / 2 }
        isPlaying = true
        dirty = true
    }

    /// Stops on the step being built (web `pause`: snap to the whole step).
    func pause() {
        guard isPlaying else { return }
        position = min(Double(total), ceil(position - 1e-9))
        isPlaying = false
        dirty = true
        refresh(force: false)
    }

    /// Shows steps 1...index complete. Scrubbing pauses playback.
    func setStep(_ index: Int) {
        position = Double(min(total, max(1, index)))
        isPlaying = false
        dirty = true
        refresh(force: false)
    }

    func next() { setStep(state.index + 1) }
    func previous() { setStep(state.index - 1) }

    /// Jump to the finished model.
    func finish() {
        position = Double(total)
        isPlaying = false
        dirty = true
        refresh(force: false)
    }

    /// Full geometry again and the plan removed; the animator is not used after this.
    func dispose() {
        position = Double(total)
        isPlaying = false
        for index in targets.indices { restore(targets[index]); targets[index].applied = 1 }
        plan?.removeFromParent()
    }

    /// Plan fades in, then dissolves while the building rises out of it. Gone once everything is built.
    func planOpacity() -> Double {
        let fadeIn = min(1, elapsed / Self.planFadeIn)
        let fade = max(0, 1 - position / max(Double(total) * 0.85, 0.5))
        return fadeIn * fade
    }

    private func refresh(force: Bool) {
        dirty = false
        let current = pinned()
        lastPinned = current
        plan?.components.set(OpacityComponent(opacity: Float(planOpacity())))
        for index in targets.indices {
            let target = targets[index]
            let factor = current.contains(target.usdName) ? 1
                : BuildSequence.growth(position: position, step: target.step, index: target.index, count: target.count)
            guard force || factor != target.applied else { continue }
            targets[index].applied = factor
            if factor >= 1 { restore(target) } else { apply(target, progress: factor) }
        }
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
}

private extension Array {
    subscript(safe index: Int) -> Element? { indices.contains(index) ? self[index] : nil }
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
