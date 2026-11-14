import CoreGraphics
import simd

/// Scene coordinates are metres, Y up; the camera looks along its local -Z axis.
struct WalkGuide: Equatable {
    let bearingDegrees: Float
    let horizontalDistance: Float
    let arrived: Bool

    init(cameraTransform: simd_float4x4, target: SIMD3<Float>) {
        let position = cameraTransform.columns.3
        let dx = target.x - position.x
        let dz = target.z - position.z
        horizontalDistance = hypot(dx, dz)
        arrived = horizontalDistance < 1
        let forward = -cameraTransform.columns.2
        let heading = hypot(forward.x, forward.z) > 0.0001 ? atan2(forward.x, -forward.z) : 0
        var bearing = (atan2(dx, -dz) - heading) * 180 / .pi
        while bearing > 180 { bearing -= 360 }
        while bearing <= -180 { bearing += 360 }
        bearingDegrees = horizontalDistance < 0.0001 ? 0 : bearing
    }

    /// Aspect-preserving X/Z projection. Negative Z is toward the top of the map.
    /// Positions outside the scene remain outside, so we never claim the user is inside.
    static func project(_ position: SIMD3<Float>, bounds: SceneBounds, into rect: CGRect) -> CGPoint {
        let width = CGFloat(max(bounds.maximum.x - bounds.minimum.x, 0.001))
        let depth = CGFloat(max(bounds.maximum.z - bounds.minimum.z, 0.001))
        let scale = min(rect.width / width, rect.height / depth)
        return CGPoint(x: rect.midX + CGFloat(position.x - bounds.center.x) * scale,
                       y: rect.midY + CGFloat(position.z - bounds.center.z) * scale)
    }
}
