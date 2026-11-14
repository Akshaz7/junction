import Foundation
import simd

/// Pure ordering and timing for the build-up reveal. Same step order as the web (FIX-5):
/// foundations, then per storey (slab, columns/beams, walls, stairs, doors/windows, fixtures), then the roof.
/// Single-storey raster or DXF plans have no foundations or structure, so they come out as floor, walls, openings.
enum BuildPhase: Int, CaseIterable, Comparable {
    case foundation, slab, structure, walls, stairs, openings, fixtures, roof

    static func < (lhs: BuildPhase, rhs: BuildPhase) -> Bool { lhs.rawValue < rhs.rawValue }

    /// Seconds before the whole sequence is scaled to fit its budget. Walls 1.2 s, openings 0.6 s.
    var baseDuration: TimeInterval {
        switch self {
        case .walls: return 1.2
        case .openings, .roof: return 0.6
        default: return 0.5
        }
    }

    var label: String {
        switch self {
        case .foundation: return "Foundations"
        case .slab: return "Floor"
        case .structure: return "Columns and beams"
        case .walls: return "Walls"
        case .stairs: return "Stairs"
        case .openings: return "Doors and windows"
        case .fixtures: return "Fixtures"
        case .roof: return "Roof"
        }
    }

    /// nil means the item is not part of the build (site and room volumes are not physical elements).
    static func classify(kind: String?) -> BuildPhase? {
        guard let kind = kind?.lowercased() else { return .fixtures }
        switch kind {
        case "site", "room", "space", "zone": return nil
        case "footing", "pile", "foundation": return .foundation
        case "slab", "floor", "covering": return .slab
        case "column", "beam", "member": return .structure
        case "wall", "curtain_wall", "curtainwall": return .walls
        case "stairs", "stair", "railing", "ramp": return .stairs
        case "door", "window": return .openings
        case "roof": return .roof
        default: return .fixtures
        }
    }
}

struct BuildItem: Equatable {
    let usdName: String
    let kind: String?
    let storey: String?
    /// Centre of the item on the floor plane (x, z), used to stagger items from the middle outwards.
    let center: SIMD2<Float>
}

struct BuildStep: Equatable {
    let phase: BuildPhase
    let storey: String?
    let start: TimeInterval
    let duration: TimeInterval
    /// Items in animation order (nearest the model centre first).
    let usdNames: [String]

    var title: String { storey.map { "\($0) \(phase.label.lowercased())" } ?? phase.label }
}

struct BuildSlot: Equatable {
    let usdName: String
    let phase: BuildPhase
    let start: TimeInterval
    let duration: TimeInterval
    var end: TimeInterval { start + duration }
}

struct BuildSequence: Equatable {
    static let totalBudget: TimeInterval = 5.0
    /// Fraction of a step used to stagger item starts; each item then rises over the rest.
    static let staggerFraction = 0.6

    let steps: [BuildStep]
    /// Every scheduled item, sorted by start time.
    let slots: [BuildSlot]
    var totalDuration: TimeInterval { steps.last.map { $0.start + $0.duration } ?? 0 }
    var isEmpty: Bool { slots.isEmpty }

    static func make(items: [BuildItem], storeys: [SceneManifest.Storey]) -> BuildSequence {
        var elevation: [String: Float] = [:]
        for storey in storeys {
            if let name = storey.name { elevation[name] = storey.elevation_m ?? 0 }
        }
        let centre = items.isEmpty ? SIMD2<Float>.zero
            : items.reduce(SIMD2<Float>.zero) { $0 + $1.center } / Float(items.count)

        // Group by (storey rank, phase). Roof is global and last; foundations are global and first.
        struct Key: Hashable { let rank: Int; let storey: String?; let phase: BuildPhase }
        var groups: [Key: [BuildItem]] = [:]
        for item in items {
            guard let phase = BuildPhase.classify(kind: item.kind) else { continue }
            let key: Key
            switch phase {
            case .foundation: key = Key(rank: -1, storey: nil, phase: phase)
            case .roof: key = Key(rank: Int.max, storey: nil, phase: phase)
            default:
                let rank = item.storey.flatMap { elevation[$0] }.map { Int(($0 * 100).rounded()) } ?? -1
                key = Key(rank: rank, storey: item.storey, phase: phase)
            }
            groups[key, default: []].append(item)
        }
        let orderedKeys = groups.keys.sorted {
            if $0.rank != $1.rank { return $0.rank < $1.rank }
            if $0.phase != $1.phase { return $0.phase < $1.phase }
            return ($0.storey ?? "") < ($1.storey ?? "")
        }
        let raw = orderedKeys.reduce(0) { $0 + $1.phase.baseDuration }
        let factor = raw > totalBudget ? totalBudget / raw : 1

        var steps: [BuildStep] = []
        var slots: [BuildSlot] = []
        var cursor: TimeInterval = 0
        for key in orderedKeys {
            let duration = key.phase.baseDuration * factor
            let members = groups[key, default: []].sorted {
                let a = simd_distance_squared($0.center, centre), b = simd_distance_squared($1.center, centre)
                return a != b ? a < b : $0.usdName < $1.usdName
            }
            let names = members.map(\.usdName)
            steps.append(BuildStep(phase: key.phase, storey: key.storey, start: cursor, duration: duration,
                                   usdNames: names))
            let spread = duration * staggerFraction
            let each = max(duration - spread, 0.05)
            for (index, name) in names.enumerated() {
                let offset = names.count > 1 ? spread * Double(index) / Double(names.count - 1) : 0
                slots.append(BuildSlot(usdName: name, phase: key.phase, start: cursor + offset, duration: each))
            }
            cursor += duration
        }
        return BuildSequence(steps: steps, slots: slots.sorted { $0.start < $1.start })
    }

    static func make(manifest: SceneManifest, include: Set<String>? = nil) -> BuildSequence {
        let items = manifest.items.compactMap { id, item -> BuildItem? in
            if let include, !include.contains(id) { return nil }
            let center = item.bbox_m.map { SIMD2($0.center.x, $0.center.z) } ?? .zero
            return BuildItem(usdName: item.usd_name, kind: item.kind, storey: item.storey, center: center)
        }
        return make(items: items, storeys: manifest.storeys ?? [])
    }

    /// Ease-out cubic, 0...1.
    static func easeOut(_ t: Double) -> Double {
        let x = min(max(t, 0), 1)
        return 1 - pow(1 - x, 3)
    }
}
