import CoreGraphics

enum ProjectedLabelLayout {
    struct Candidate {
        let id: String
        let distance: Float
        let rectangles: [CGRect?]
    }

    /// Reserve screen space nearest first. If every tier collides, omit the farther tag.
    static func tiers(for candidates: [Candidate], viewport: CGRect) -> [String: Int] {
        var occupied: [CGRect] = []
        var result: [String: Int] = [:]
        for candidate in candidates.sorted(by: {
            $0.distance == $1.distance ? $0.id < $1.id : $0.distance < $1.distance
        }) {
            for (tier, rectangle) in candidate.rectangles.enumerated() {
                guard let rectangle, !rectangle.isNull, !rectangle.isEmpty,
                      rectangle.minX.isFinite, rectangle.minY.isFinite,
                      rectangle.maxX.isFinite, rectangle.maxY.isFinite,
                      viewport.contains(rectangle) else { continue }
                let padded = rectangle.insetBy(dx: -4, dy: -4)
                guard !occupied.contains(where: { $0.intersects(padded) }) else { continue }
                result[candidate.id] = tier
                occupied.append(padded)
                break
            }
        }
        return result
    }
}
