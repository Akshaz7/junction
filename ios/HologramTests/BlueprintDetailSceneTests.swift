import RealityKit
import UIKit
import XCTest
@testable import Hologram

@MainActor
final class BlueprintDetailSceneTests: XCTestCase {
    private func loadAC20() async throws -> (SceneManifest, Entity, SceneIndex) {
        let files = try XCTUnwrap(DemoScenes.files(for: "ifc_bench__ac20-arc"))
        let manifest = try JSONDecoder().decode(SceneManifest.self, from: Data(contentsOf: files.manifestURL))
        let root = try await Entity(contentsOf: files.modelURL)
        return (manifest, root, SceneIndex(root: root))
    }

    func testBuildsRoomLabelsTintsDimensionsAndStoreyLabelAtSlabTop() async throws {
        let (manifest, root, index) = try await loadAC20()
        let detail = BlueprintDetail()
        detail.build(manifest: manifest, index: index, content: root)
        root.addChild(detail.root)
        func all(named name: String) -> [Entity] {
            var found: [Entity] = []
            func walk(_ e: Entity) { if e.name == name { found.append(e) }; e.children.forEach(walk) }
            walk(detail.root)
            return found
        }
        let rooms = manifest.items.values.filter { $0.kind == "room" }
        XCTAssertGreaterThan(all(named: "blueprint-floor").count, rooms.count / 2)
        XCTAssertGreaterThan(all(named: "blueprint-room-label").count, 10)
        XCTAssertGreaterThanOrEqual(all(named: "blueprint-storey-label").count, 4)
        XCTAssertGreaterThanOrEqual(all(named: "blueprint-dimension-label").count, 8)
        // Every floor tint sits just above its storey's slab top, not inside it.
        let elevations = Dictionary(uniqueKeysWithValues: (manifest.storeys ?? []).compactMap { s in
            s.name.map { ($0, s.elevation_m ?? 0) } })
        let tops = BlueprintDetail.floorTops(manifest: manifest, elevations: elevations)
        XCTAssertFalse(tops.isEmpty)
        for plate in all(named: "blueprint-floor") {
            let y = plate.position.y
            XCTAssertTrue(tops.values.contains { abs($0 - y) < 0.02 }, "plate y \(y) not near any slab top")
        }
    }

    func testRoomNamesAndAreasComeFromTheManifest() async throws {
        let (manifest, _, _) = try await loadAC20()
        let named = manifest.items.values.filter { $0.kind == "room" }.compactMap(BlueprintStyle.roomName)
        XCTAssertTrue(named.contains("Besprechungsraum I"), "rooms: \(named.prefix(5))")
        let room = try XCTUnwrap(manifest.items.values.first { BlueprintStyle.roomName($0) == "Besprechungsraum I" })
        XCTAssertEqual(BlueprintStyle.roomArea(room, footprint: [1, 1]), 23.9, accuracy: 0.01)
    }

    /// Renders the Keller storey from above with an offscreen ARView and writes a PNG for review.
    func testRenderKellerPlanFromAbove() async throws {
        let (manifest, root, index) = try await loadAC20()
        BlueprintDetail.applyMaterials(manifest: manifest, index: index, content: root)
        let detail = BlueprintDetail()
        detail.build(manifest: manifest, index: index, content: root)
        root.addChild(detail.root)
        let hidden = CutawayPolicy(manifest: manifest).hiddenUSDNames(activeStorey: "Keller", showRoof: false)
        for item in manifest.items.values { index.entitiesByUSDName[item.usd_name]?.isEnabled = !hidden.contains(item.usd_name) }
        detail.update(activeStorey: "Keller", hidden: false, cameraPosition: [0, 40, 0], time: 100)
        let view = ARView(frame: CGRect(x: 0, y: 0, width: 900, height: 1400), cameraMode: .nonAR, automaticallyConfigureSession: false)
        view.environment.background = .color(.white)
        let anchor = AnchorEntity(world: .zero)
        anchor.addChild(root)
        view.scene.addAnchor(anchor)
        let bounds = root.visualBounds(relativeTo: nil)
        let camera = PerspectiveCamera()
        let height = max(bounds.extents.x, bounds.extents.z) * 1.1
        camera.look(at: bounds.center, from: bounds.center + [0, height, 0.01], relativeTo: nil)
        let cameraAnchor = AnchorEntity(world: .zero)
        cameraAnchor.addChild(camera)
        view.scene.addAnchor(cameraAnchor)
        let light = DirectionalLight()
        light.look(at: bounds.center, from: bounds.center + [5, 20, 5], relativeTo: nil)
        cameraAnchor.addChild(light)
        let window = UIWindow(frame: view.frame)
        window.addSubview(view)
        window.makeKeyAndVisible()
        try await Task.sleep(for: .seconds(3))
        let expectation = expectation(description: "snapshot")
        var image: UIImage?
        view.snapshot(saveToHDR: false) { image = $0; expectation.fulfill() }
        await fulfillment(of: [expectation], timeout: 20)
        if let data = image?.pngData() {
            try data.write(to: URL(fileURLWithPath: "/tmp/hologram-keller-plan.png"))
        }
        XCTAssertNotNil(image)
    }
}
