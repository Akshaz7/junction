import Foundation
import simd

struct SceneBounds: Decodable, Equatable {
    let minimum: SIMD3<Float>
    let maximum: SIMD3<Float>
    var center: SIMD3<Float> { (minimum + maximum) / 2 }

    init(minimum: SIMD3<Float>, maximum: SIMD3<Float>) {
        self.minimum = minimum
        self.maximum = maximum
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        let points = try container.decode([[Float]].self)
        guard points.count == 2, points.allSatisfy({ $0.count == 3 && $0.allSatisfy(\.isFinite) }),
              zip(points[0], points[1]).allSatisfy({ $0 <= $1 }) else {
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Invalid scene bbox_m")
        }
        minimum = SIMD3(points[0][0], points[0][1], points[0][2])
        maximum = SIMD3(points[1][0], points[1][1], points[1][2])
    }

    func union(_ other: SceneBounds) -> SceneBounds {
        SceneBounds(minimum: simd_min(minimum, other.minimum), maximum: simd_max(maximum, other.maximum))
    }
}

struct SceneManifest: Decodable {
    struct Item: Decodable {
        let usd_name: String
        /// glTF node name in scene.glb, used to rebuild the scene on the device when there is no USDZ.
        var node: String? = nil
        let bbox_m: SceneBounds?
        let name: String?
        let kind: String?
        let storey: String?
        let tag: String?
        let props: [String: SceneProperty]?
    }

    struct Storey: Decodable {
        let name: String?
        let elevation_m: Float?
    }

    let doc_id: String?
    let title: String?
    let items: [String: Item]
    let storeys: [Storey]?
    let credit: String?
    let licence: String?
    let note: String?

    var floorElevation: Float { storeys?.compactMap(\.elevation_m).filter(\.isFinite).min() ?? 0 }

    var bounds: SceneBounds? {
        items.values.compactMap(\.bbox_m).reduce(nil) { result, bounds in
            result.map { $0.union(bounds) } ?? bounds
        }
    }
}

/// Preserve optional metadata without assuming that every property is a string.
enum SceneProperty: Decodable {
    case string(String), number(Double), bool(Bool)
    case array([SceneProperty]), object([String: SceneProperty]), null

    init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer()
        if value.decodeNil() { self = .null }
        else if let bool = try? value.decode(Bool.self) { self = .bool(bool) }
        else if let number = try? value.decode(Double.self) { self = .number(number) }
        else if let string = try? value.decode(String.self) { self = .string(string) }
        else if let array = try? value.decode([SceneProperty].self) { self = .array(array) }
        else { self = .object(try value.decode([String: SceneProperty].self)) }
    }

    var displayText: String {
        switch self {
        case .string(let value): return value
        case .number(let value): return String(value)
        case .bool(let value): return value ? "Yes" : "No"
        case .array(let values): return values.map(\.displayText).joined(separator: ", ")
        case .object(let values):
            return values.keys.sorted().map { "\($0): \(values[$0]!.displayText)" }.joined(separator: ", ")
        case .null: return "Not available"
        }
    }
}
