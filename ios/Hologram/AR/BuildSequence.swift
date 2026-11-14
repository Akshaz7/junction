import Foundation
import simd

/// Pure ordering for the build-up. Same steps and labels as the web (`buildSteps` in web/src/viewer3d/rise.ts),
/// so "Step 4 of 12 · Erdgeschoss walls" means the same thing on the laptop and on the table.
/// IFC: foundations, then per storey (lowest first) slab, columns and beams, walls, stairs, doors and windows,
/// then the roof. Plan-map and DXF scenes (ids like `wall-3`): floor, walls, doors and windows.
enum BuildPhase: Int, CaseIterable, Comparable {
    case foundation, slab, structure, walls, stairs, openings, roof

    static func < (lhs: BuildPhase, rhs: BuildPhase) -> Bool { lhs.rawValue < rhs.rawValue }

    /// Web `BUCKET_LABEL`; the storey name is put in front for per-storey steps.
    var label: String {
        switch self {
        case .foundation: return "Foundations"
        case .slab: return "slab"
        case .structure: return "columns and beams"
        case .walls: return "walls"
        case .stairs: return "stairs"
        case .openings: return "doors and windows"
        case .roof: return "Roof"
        }
    }

    static let perStorey: [BuildPhase] = [.slab, .structure, .walls, .stairs, .openings]

    /// Web `ifcBucket`. nil means the item is not part of the build (the site ground stays as it is).
    static func classify(kind: String?) -> BuildPhase? {
        switch kind {
        case "footing", "pile": return .foundation
        case "slab", "covering", "room": return .slab
        case "column", "beam", "member", "plate": return .structure
        case "wall", "curtain_wall": return .walls
        case "stairs", "ramp", "railing": return .stairs
        case "roof": return .roof
        case "site": return nil
        default: return .openings
        }
    }
}

struct BuildItem: Equatable {
    let id: String
    let usdName: String
    let kind: String?
    let storey: String?
    /// Centre of the item on the floor plane (x, z), used to stagger items from the middle outwards.
    let center: SIMD2<Float>

    init(id: String? = nil, usdName: String, kind: String?, storey: String?, center: SIMD2<Float>) {
        self.id = id ?? usdName
        self.usdName = usdName
        self.kind = kind
        self.storey = storey
        self.center = center
    }
}

struct BuildStep: Equatable {
    let label: String
    let phase: BuildPhase
    let storey: String?
    /// Items in animation order (nearest the model centre first).
    let usdNames: [String]
    let itemIDs: [String]
    var title: String { label }
}

struct BuildSequence: Equatable {
    /// Seconds a whole build-up takes at most; each step gets an equal share within these limits.
    static let totalBudget: TimeInterval = 5.0
    static let minStepSeconds: TimeInterval = 0.25
    static let maxStepSeconds: TimeInterval = 1.2
    /// Fraction of a step used to stagger item starts; each item then rises over the rest.
    static let staggerFraction = 0.6

    let steps: [BuildStep]
    let isRaster: Bool
    var total: Int { steps.count }
    var isEmpty: Bool { steps.allSatisfy { $0.usdNames.isEmpty } }
    var stepSeconds: TimeInterval {
        min(Self.maxStepSeconds, max(Self.minStepSeconds, Self.totalBudget / Double(max(1, steps.count))))
    }
    var totalDuration: TimeInterval { stepSeconds * Double(total) }

    /// Web `PLAN_MAP_ID`: plan-map and DXF scenes use `<kind>-<n>` ids; IFC scenes use GlobalIds.
    static func isPlanMapID(_ id: String) -> Bool {
        guard let dash = id.lastIndex(of: "-"), dash != id.startIndex else { return false }
        let head = id[..<dash], tail = id[id.index(after: dash)...]
        return !tail.isEmpty && tail.allSatisfy { $0 >= "0" && $0 <= "9" }
            && head.allSatisfy { ($0 >= "a" && $0 <= "z") || $0 == "_" }
    }

    static func make(items: [BuildItem], storeys: [SceneManifest.Storey]) -> BuildSequence {
        let centre = items.isEmpty ? SIMD2<Float>.zero
            : items.reduce(SIMD2<Float>.zero) { $0 + $1.center } / Float(items.count)
        func ordered(_ members: [BuildItem]) -> [BuildItem] {
            members.sorted {
                let a = simd_distance_squared($0.center, centre), b = simd_distance_squared($1.center, centre)
                return a != b ? a < b : $0.id < $1.id
            }
        }
        func step(_ label: String, _ phase: BuildPhase, _ storey: String?, _ members: [BuildItem]) -> BuildStep {
            let sorted = ordered(members)
            return BuildStep(label: label, phase: phase, storey: storey, usdNames: sorted.map(\.usdName),
                             itemIDs: sorted.map(\.id))
        }

        let isIFC = items.contains { !isPlanMapID($0.id) }
        if !isIFC {
            var floor: [BuildItem] = [], walls: [BuildItem] = [], openings: [BuildItem] = []
            for item in items {
                switch item.kind {
                case "room": floor.append(item)
                case "wall", "column": walls.append(item)
                default: openings.append(item)
                }
            }
            var steps = [step("Floor", .slab, nil, floor)]
            if !walls.isEmpty { steps.append(step("Walls", .walls, nil, walls)) }
            if !openings.isEmpty { steps.append(step("Doors and windows", .openings, nil, openings)) }
            return BuildSequence(steps: steps, isRaster: true)
        }

        // Storeys lowest first; a storey given without elevation sorts by its position in the list.
        let named = storeys.enumerated().compactMap { index, storey -> (name: String, elevation: Float)? in
            storey.name.map { ($0, storey.elevation_m ?? Float(index)) }
        }
        var names = named.enumerated().sorted {
            $0.element.elevation != $1.element.elevation ? $0.element.elevation < $1.element.elevation
                : $0.offset < $1.offset
        }.map(\.element.name)
        let lowest = names.first

        struct Cell: Hashable { let storey: String?; let phase: BuildPhase }
        var cells: [Cell: [BuildItem]] = [:]
        for item in items.sorted(by: { $0.id < $1.id }) {
            guard let phase = BuildPhase.classify(kind: item.kind) else { continue }
            if phase == .foundation || phase == .roof {
                cells[Cell(storey: nil, phase: phase), default: []].append(item)
                continue
            }
            let storey = item.storey ?? lowest
            cells[Cell(storey: storey, phase: phase), default: []].append(item)
            if let storey, !names.contains(storey) { names.append(storey) }
        }

        var steps: [BuildStep] = []
        func add(_ cell: Cell) {
            guard let members = cells[cell], !members.isEmpty else { return }
            let label = cell.storey.map { "\($0) \(cell.phase.label)" } ?? cell.phase.label
            steps.append(step(label, cell.phase, cell.storey, members))
        }
        add(Cell(storey: nil, phase: .foundation))
        for name in names { for phase in BuildPhase.perStorey { add(Cell(storey: name, phase: phase)) } }
        add(Cell(storey: nil, phase: .roof))
        if steps.isEmpty { steps = [step("Model", .openings, nil, items)] }
        return BuildSequence(steps: steps, isRaster: false)
    }

    static func make(manifest: SceneManifest, include: Set<String>? = nil) -> BuildSequence {
        let items = manifest.items.compactMap { id, item -> BuildItem? in
            if let include, !include.contains(id) { return nil }
            let center = item.bbox_m.map { SIMD2($0.center.x, $0.center.z) } ?? .zero
            return BuildItem(id: id, usdName: item.usd_name, kind: item.kind, storey: item.storey, center: center)
        }
        return make(items: items, storeys: manifest.storeys ?? [])
    }

    /// Growth 0...1 of the `index`th of `count` items in a step at slider position `position` (0...total).
    /// Items start staggered from the model centre outwards and ease out.
    static func growth(position: Double, step: Int, index: Int, count: Int) -> Double {
        let local = min(max(position - Double(step), 0), 1)
        if local >= 1 { return 1 }
        let spread = staggerFraction
        let offset = count > 1 ? spread * Double(index) / Double(count - 1) : 0
        return easeOut((local - offset) / (1 - spread))
    }

    /// Ease-out cubic, 0...1.
    static func easeOut(_ t: Double) -> Double {
        let x = min(max(t, 0), 1)
        return 1 - pow(1 - x, 3)
    }
}

/// What the scrubber shows. Same fields as the web `BuildState`.
struct BuildState: Equatable {
    /// 1-based step on the slider (the step being built, or the last completed one).
    let index: Int
    let total: Int
    let label: String
    let playing: Bool
    let finished: Bool

    var text: String { "Step \(index) of \(total) · \(label)" }
}
