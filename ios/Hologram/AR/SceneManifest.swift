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
        let bbox_m: SceneBounds?
    }

    struct Storey: Decodable {
        let elevation_m: Float?
    }

    let items: [String: Item]
    let storeys: [Storey]?

    var floorElevation: Float { storeys?.compactMap(\.elevation_m).filter(\.isFinite).min() ?? 0 }

    var bounds: SceneBounds? {
        items.values.compactMap(\.bbox_m).reduce(nil) { result, bounds in
            result.map { $0.union(bounds) } ?? bounds
        }
    }
}
