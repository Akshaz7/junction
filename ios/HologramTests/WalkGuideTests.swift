import XCTest
import simd
@testable import Hologram

final class WalkGuideTests: XCTestCase {
    func testTargetStraightAheadHasZeroBearing() {
        let guide = WalkGuide(cameraTransform: matrix_identity_float4x4, target: [0, 0, -5])
        XCTAssertEqual(guide.bearingDegrees, 0, accuracy: 0.0001)
        XCTAssertEqual(guide.horizontalDistance, 5, accuracy: 0.0001)
        XCTAssertFalse(guide.arrived)
    }

    func testTargetRightHasPositiveNinetyBearing() {
        let guide = WalkGuide(cameraTransform: matrix_identity_float4x4, target: [5, 0, 0])
        XCTAssertEqual(guide.bearingDegrees, 90, accuracy: 0.0001)
    }

    func testTargetBehindHasOneEightyBearing() {
        let guide = WalkGuide(cameraTransform: matrix_identity_float4x4, target: [0, 0, 5])
        XCTAssertEqual(guide.bearingDegrees, 180, accuracy: 0.0001)
    }

    func testArrivalIsStrictlyUnderOneMetreAndIgnoresHeight() {
        XCTAssertTrue(WalkGuide(cameraTransform: matrix_identity_float4x4, target: [0.6, 8, -0.7]).arrived)
        XCTAssertFalse(WalkGuide(cameraTransform: matrix_identity_float4x4, target: [0, 0, -1]).arrived)
        let coincident = WalkGuide(cameraTransform: matrix_identity_float4x4, target: [0, 3, 0])
        XCTAssertTrue(coincident.arrived)
        XCTAssertEqual(coincident.horizontalDistance, 0)
        XCTAssertEqual(coincident.bearingDegrees, 0)
    }

    func testBearingUsesCameraHeadingAndPositionInModelSpace() {
        // Camera at (10, 1.6, 20), looking toward +X instead of the default -Z.
        var camera = simd_float4x4(simd_quatf(angle: -.pi / 2, axis: [0, 1, 0]))
        camera.columns.3 = [10, 1.6, 20, 1]
        let ahead = WalkGuide(cameraTransform: camera, target: [15, 0, 20])
        XCTAssertEqual(ahead.bearingDegrees, 0, accuracy: 0.0001)
        XCTAssertEqual(ahead.horizontalDistance, 5, accuracy: 0.0001)
        let right = WalkGuide(cameraTransform: camera, target: [10, 0, 25])
        XCTAssertEqual(right.bearingDegrees, 90, accuracy: 0.0001)
        let left = WalkGuide(cameraTransform: camera, target: [10, 0, 15])
        XCTAssertEqual(left.bearingDegrees, -90, accuracy: 0.0001)
    }

    func testBearingWrapsAcrossHeadingBoundary() {
        let camera = simd_float4x4(simd_quatf(angle: -170 * .pi / 180, axis: [0, 1, 0]))
        let target = SIMD3<Float>(sin(-170 * .pi / 180), 0, -cos(-170 * .pi / 180)) * 10
        let guide = WalkGuide(cameraTransform: camera, target: target)
        XCTAssertEqual(guide.bearingDegrees, 20, accuracy: 0.0001)
    }

    func testMiniMapProjectsSceneBoundsIntoOffsetRectWithEqualAxisScale() {
        let bounds = SceneBounds(minimum: [-4, 0, -2], maximum: [4, 3, 2])
        let rect = CGRect(x: 10, y: 20, width: 200, height: 200)
        // 8 x 4 metres fits a 200 x 100 rectangle, centred inside the map.
        XCTAssertEqual(WalkGuide.project(bounds.minimum, bounds: bounds, into: rect), CGPoint(x: 10, y: 70))
        XCTAssertEqual(WalkGuide.project(bounds.maximum, bounds: bounds, into: rect), CGPoint(x: 210, y: 170))
        XCTAssertEqual(WalkGuide.project(bounds.center, bounds: bounds, into: rect), CGPoint(x: 110, y: 120))
        let outside = WalkGuide.project([8, 0, 0], bounds: bounds, into: rect)
        XCTAssertGreaterThan(outside.x, rect.maxX, "Do not clamp an outside camera into the building")
    }

    func testMiniMapHandlesPointBoundsWithoutDivisionByZero() {
        let bounds = SceneBounds(minimum: [7, 2, 8], maximum: [7, 2, 8])
        let point = WalkGuide.project(bounds.center, bounds: bounds, into: CGRect(x: 0, y: 0, width: 100, height: 100))
        XCTAssertEqual(point, CGPoint(x: 50, y: 50))
    }

    func testFixtureManifestBoundsAndFloorElevation() throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "fixture.scene", withExtension: "json"))
        let manifest = try JSONDecoder().decode(SceneManifest.self, from: Data(contentsOf: url))
        let bounds = try XCTUnwrap(manifest.bounds)
        XCTAssertEqual(bounds.minimum, SIMD3<Float>(-3.125, 0, -2.125))
        XCTAssertEqual(bounds.maximum, SIMD3<Float>(3, 2.7, 2))
        XCTAssertEqual(manifest.floorElevation, 0, "No storeys uses scene y=0")
        let target = try XCTUnwrap(manifest.items["window-001"]?.bbox_m).center
        let guide = WalkGuide(cameraTransform: matrix_identity_float4x4, target: target)
        XCTAssertEqual(guide.horizontalDistance, 2.5, accuracy: 0.0001)
    }

    func testLowestStoreyDefinesFloorAndEmptySceneHasNoMap() throws {
        let data = Data(#"{"storeys":[{"elevation_m":3.0},{"elevation_m":-2.5},{"elevation_m":0}],"items":{}}"#.utf8)
        let manifest = try JSONDecoder().decode(SceneManifest.self, from: data)
        XCTAssertEqual(manifest.floorElevation, -2.5)
        XCTAssertNil(manifest.bounds)
        // Floor translated to an AR plane at world y=-1: scene floor -2.5 lands at -1.
        var modelToWorld = matrix_identity_float4x4
        modelToWorld.columns.3 = [4, -1 - manifest.floorElevation, 6, 1]
        let floor = modelToWorld * SIMD4<Float>(0, manifest.floorElevation, 0, 1)
        XCTAssertEqual(floor.y, -1)
        var worldCamera = matrix_identity_float4x4
        worldCamera.columns.3 = [4, 0.6, 6, 1]
        let cameraInModel = simd_inverse(modelToWorld) * worldCamera
        let guide = WalkGuide(cameraTransform: cameraInModel, target: [0, manifest.floorElevation, -3])
        XCTAssertEqual(guide.horizontalDistance, 3, accuracy: 0.0001)
        XCTAssertEqual(guide.bearingDegrees, 0, accuracy: 0.0001)
    }

    func testInvalidBoundsAreRejected() {
        for json in ["[[0,0],[1,1]]", "[[1,0,0],[0,1,1]]"] {
            XCTAssertThrowsError(try JSONDecoder().decode(SceneBounds.self, from: Data(json.utf8)))
        }
    }
}
