import QuartzCore
import RealityKit
import UIKit

/// Plays the voice "wow" moment on the placed model: one turntable spin on its base, non-answer geometry dims,
/// answer items light up in reading order with a pulse ring on the floor and a tag pop. One per-frame update.
@MainActor
final class AnswerChoreographer {
    struct Entry {
        let item: AnswerChoreography.Item
        let entity: Entity
        let color: UIColor
    }

    private struct Ring {
        let entity: ModelEntity
        let start: TimeInterval
        let radius: Float
    }

    private let container: Entity
    private let content: Entity
    private let pivot: SIMD3<Float>
    private let highlights: HighlightController
    private let entries: [String: Entry]
    private let slots: [AnswerChoreography.Slot]
    private let dimmed: [(entity: Entity, original: Float)]
    private let dimTarget: Float
    private let labelPop: [String: Entity]
    private let baseOrientation: simd_quatf
    private let basePosition: SIMD3<Float>
    private let unit: Float
    private let spin: Bool
    private let onCount: (Int) -> Void
    private let onFinish: () -> Void
    private var startedAt: TimeInterval = 0
    private var nextSlot = 0
    private var rings: [Ring] = []
    private var lastDimStep = -1
    private let ringMesh: MeshResource?
    private(set) var isFinished = false
    private let total: TimeInterval

    static let dimDuration: TimeInterval = 0.4

    init(container: Entity, content: Entity, pivot: SIMD3<Float>, highlights: HighlightController,
         entries: [Entry], dimmed: [(Entity, Float)], dimTarget: Float = 0.3, spin: Bool, unit: Float,
         onCount: @escaping (Int) -> Void, onFinish: @escaping () -> Void) {
        self.container = container
        self.content = content
        self.pivot = pivot
        self.highlights = highlights
        self.entries = Dictionary(uniqueKeysWithValues: entries.map { ($0.item.id, $0) })
        slots = AnswerChoreography.schedule(entries.map(\.item))
        self.dimmed = dimmed.map { ($0.0, $0.1) }
        self.dimTarget = dimTarget
        self.spin = spin
        self.unit = unit
        self.onCount = onCount
        self.onFinish = onFinish
        baseOrientation = container.orientation
        basePosition = container.position
        labelPop = Dictionary(uniqueKeysWithValues: entries.compactMap { entry in
            highlights.labelsByItemID[entry.item.id].map { (entry.item.id, $0) }
        })
        ringMesh = Self.makeRingMesh()
        total = max(AnswerChoreography.totalDuration(for: slots), Self.dimDuration)
    }

    func begin(now: TimeInterval = CACurrentMediaTime()) {
        startedAt = now
        // Start dark: everything is revealed by the sequence.
        for slot in slots { highlights.setLit(slot.id, false) }
        highlights.suppressLabels(Set(slots.map(\.id)))
        onCount(0)
    }

    func tick(now: TimeInterval = CACurrentMediaTime()) {
        guard !isFinished else { return }
        let t = now - startedAt
        applyDim(at: t)
        if spin { applyTurntable(at: t) }

        while nextSlot < slots.count, slots[nextSlot].start <= t {
            light(slots[nextSlot])
            nextSlot += 1
        }
        for (id, label) in labelPop {
            guard let start = slotStart[id], t >= start, let base = finalLabelScale[id] else { continue }
            let p = (t - start) / BuildAnimator.popDuration
            if p < 1 { label.scale = base * Self.popFactor(p) }
        }
        rings.removeAll { ring in
            let p = (t - ring.start) / AnswerChoreography.ringDuration
            if p >= 1 { ring.entity.removeFromParent(); return true }
            let eased = Float(BuildSequence.easeOut(p))
            let s = ring.radius * (0.35 + 1.4 * eased)
            ring.entity.scale = [s, 1, s]
            ring.entity.components.set(OpacityComponent(opacity: 0.9 * (1 - Float(p))))
            return false
        }
        if t >= total { finish() }
    }

    /// Jump to the end state: upright at the user's rotation, everything lit, tags shown, dim kept.
    func finish() {
        guard !isFinished else { return }
        isFinished = true
        container.orientation = baseOrientation
        container.position = basePosition
        while nextSlot < slots.count { light(slots[nextSlot], animate: false); nextSlot += 1 }
        for (id, label) in labelPop { label.scale = finalLabelScale[id] ?? label.scale }
        for ring in rings { ring.entity.removeFromParent() }
        rings.removeAll()
        for item in dimmed { item.entity.components.set(OpacityComponent(opacity: item.original * dimTarget)) }
        onFinish()
    }

    /// Un-dims everything. Called by the controller when the next answer or command replaces this one.
    func restoreDim() {
        for item in dimmed { item.entity.components.set(OpacityComponent(opacity: item.original)) }
    }

    // MARK: - Steps

    private lazy var slotStart: [String: TimeInterval] = Dictionary(uniqueKeysWithValues: slots.map { ($0.id, $0.start) })
    private var finalLabelScale: [String: SIMD3<Float>] = [:]

    private func light(_ slot: AnswerChoreography.Slot, animate: Bool = true) {
        highlights.setLit(slot.id, true)
        if let label = labelPop[slot.id] {
            if finalLabelScale[slot.id] == nil { finalLabelScale[slot.id] = label.scale }
            highlights.revealLabel(slot.id)
            if animate { label.scale = finalLabelScale[slot.id]! * 0.01 } else { label.scale = finalLabelScale[slot.id]! }
        }
        onCount(slot.index + 1)
        if animate, let entry = entries[slot.id] { spawnRing(for: entry, at: slot.start) }
    }

    private func spawnRing(for entry: Entry, at start: TimeInterval) {
        guard let mesh = ringMesh else { return }
        let bounds = entry.entity.visualBounds(relativeTo: content)
        guard bounds.center.x.isFinite else { return }
        var material = UnlitMaterial(color: entry.color)
        material.blending = .transparent(opacity: .init(floatLiteral: 1))
        let ring = ModelEntity(mesh: mesh, materials: [material])
        ring.name = "answer-pulse-ring"
        ring.position = [bounds.center.x, bounds.min.y + unit * 0.02, bounds.center.z]
        let radius = max(max(bounds.extents.x, bounds.extents.z) * 0.8, unit * 0.9)
        ring.scale = [radius * 0.35, 1, radius * 0.35]
        ring.components.set(OpacityComponent(opacity: 0.9))
        content.addChild(ring)
        rings.append(Ring(entity: ring, start: start, radius: radius))
    }

    private func applyDim(at t: TimeInterval) {
        // Ramp in six quantised steps; per-frame opacity writes on hundreds of entities are not needed.
        let step = Int(min(t / Self.dimDuration, 1) * 6)
        guard step != lastDimStep else { return }
        lastDimStep = step
        let f = 1 - (1 - dimTarget) * Float(step) / 6
        for item in dimmed { item.entity.components.set(OpacityComponent(opacity: item.original * f)) }
    }

    /// Spin about the footprint centre, composed with the user's own rotation so it ends exactly where it began.
    private func applyTurntable(at t: TimeInterval) {
        let angle = AnswerChoreography.turntableAngle(at: t)
        let spinRotation = simd_quatf(angle: angle, axis: [0, 1, 0])
        let q = spinRotation * baseOrientation
        let s = container.scale
        let c = SIMD3<Float>(pivot.x * s.x, 0, pivot.z * s.z)
        let fixed = basePosition + baseOrientation.act(c)
        container.orientation = q
        container.position = fixed - q.act(c)
    }

    /// Scale overshoot: 0 to 1.15 by 60 percent of the pop, settling at 1.
    static func popFactor(_ p: Double) -> Float {
        let x = min(max(p, 0), 1)
        let f = x < 0.6 ? 1.15 * BuildSequence.easeOut(x / 0.6) : 1.15 - 0.15 * ((x - 0.6) / 0.4)
        return Float(max(f, 0.01))
    }

    /// Flat ring (annulus) in the XZ plane, unit outer radius.
    private static func makeRingMesh() -> MeshResource? {
        let segments = 48
        let inner: Float = 0.86
        var positions: [SIMD3<Float>] = [], normals: [SIMD3<Float>] = [], indices: [UInt32] = []
        for i in 0..<segments {
            let a = Float(i) / Float(segments) * 2 * .pi
            positions.append([cos(a), 0, sin(a)])
            positions.append([cos(a) * inner, 0, sin(a) * inner])
            normals.append([0, 1, 0]); normals.append([0, 1, 0])
        }
        for i in 0..<segments {
            let o0 = UInt32(i * 2), i0 = o0 + 1
            let o1 = UInt32(((i + 1) % segments) * 2), i1 = o1 + 1
            indices += [o0, i0, o1, o1, i0, i1]
            indices += [o0, o1, i0, o1, i1, i0]   // visible from below as well
        }
        var descriptor = MeshDescriptor(name: "pulse-ring")
        descriptor.positions = MeshBuffer(positions)
        descriptor.normals = MeshBuffer(normals)
        descriptor.primitives = .triangles(indices)
        return try? MeshResource.generate(from: [descriptor])
    }
}
