import RealityKit
import XCTest
@testable import Hologram

final class DemoSceneTests: XCTestCase {
    @MainActor
    func testCorrectManifestWithWrongUSDZCannotLoadAsRequestedDocument() async throws {
        let docID = "ifc_bench__ac20-arc"
        let files = try XCTUnwrap(DemoScenes.files(for: docID))
        let wrong = try XCTUnwrap(DemoScenes.files(for: "cubicasa5k__colorful-11397"))
        let loaded = try await ARSceneLoader.load(docID: docID, url: nil, fetcher: { _ in
            SceneRepository.Files(modelURL: wrong.modelURL, manifestURL: files.manifestURL)
        })
        XCTAssertTrue(loaded.isBundledDemo, "Reject mismatched USDZ and use only the matching offline copy")
        XCTAssertEqual(loaded.manifest?.doc_id, docID)
        let index = SceneIndex(root: loaded.entity)
        XCTAssertNotNil(index.entity(for: "00RjztLorCQgcGEHv7fY3g"))
    }

    @MainActor
    func testBundledAC20DoorCanBeFoundByManifestUSDName() async throws {
        let files = try XCTUnwrap(DemoScenes.files(for: "ifc_bench__ac20-arc"))
        let manifest = try JSONDecoder().decode(SceneManifest.self, from: Data(contentsOf: files.manifestURL))
        let door = try XCTUnwrap(manifest.items.sorted { $0.key < $1.key }.first { $0.value.kind == "door" })
        let root = try await Entity(contentsOf: files.modelURL)
        let index = SceneIndex(root: root)
        let entity = try XCTUnwrap(index.entitiesByUSDName[door.value.usd_name])
        XCTAssertEqual(entity.name, door.value.usd_name)
        XCTAssertTrue(index.entity(for: door.key) === entity)
    }

    @MainActor
    func testFailedFetchLoadsRequestedBundledSceneAndCredit() async throws {
        for demo in DemoScenes.all {
            var requested: [String] = []
            let loaded = try await ARSceneLoader.load(docID: demo.id, url: nil, fetcher: { docID in
                requested.append(docID)
                throw URLError(.notConnectedToInternet)
            })
            XCTAssertEqual(requested, [demo.id], "Try the network before bundled resources")
            XCTAssertFalse(loaded.isFixture)
            XCTAssertTrue(loaded.isBundledDemo)
            XCTAssertEqual(loaded.manifest?.doc_id, demo.id)
            XCTAssertFalse(try XCTUnwrap(loaded.attribution).credit.isEmpty)
            if demo.id == "ifc_bench__ac20-arc" {
                XCTAssertTrue(try XCTUnwrap(loaded.attribution).credit.contains("KIT"))
            } else {
                XCTAssertTrue(try XCTUnwrap(loaded.attribution).credit.contains("CubiCasa5K"))
                XCTAssertEqual(loaded.attribution?.licence, "CC-BY-NC-SA-4.0")
                XCTAssertTrue(try XCTUnwrap(loaded.manifest?.note).contains("generated for demo"))
            }
        }
    }

    @MainActor
    func testSuccessfulFetchTakesPriorityOverBundle() async throws {
        let docID = "cubicasa5k__colorful-11397"
        let files = try XCTUnwrap(DemoScenes.files(for: docID))
        let loaded = try await ARSceneLoader.load(docID: docID, url: nil, fetcher: { _ in files })
        XCTAssertEqual(loaded.manifest?.doc_id, docID)
        XCTAssertFalse(loaded.isBundledDemo)
        XCTAssertFalse(loaded.isFixture)
        XCTAssertNotNil(loaded.attribution)
    }

    @MainActor
    func testUnusableDownloadedModelFallsBackToMatchingBundle() async throws {
        let docID = "cubicasa5k__colorful-11397"
        let files = try XCTUnwrap(DemoScenes.files(for: docID))
        let loaded = try await ARSceneLoader.load(docID: docID, url: nil, fetcher: { _ in
            SceneRepository.Files(modelURL: files.modelURL.deletingLastPathComponent()
                .appendingPathComponent("not-built.usdz"), manifestURL: files.manifestURL)
        })
        XCTAssertEqual(loaded.manifest?.doc_id, docID)
        XCTAssertTrue(loaded.isBundledDemo)
        XCTAssertFalse(loaded.isFixture)
    }
}

final class BundledAC20LoadTests: XCTestCase {
    @MainActor
    func testBundledAC20LoadsThroughLoaderWithoutFixtureFallback() async throws {
        let docID = "ifc_bench__ac20-arc"
        let files = try XCTUnwrap(DemoScenes.files(for: docID))
        let loaded = try await ARSceneLoader.load(docID: docID, url: nil, fetcher: { _ in files })
        XCTAssertFalse(loaded.isFixture)
        XCTAssertEqual(loaded.manifest?.doc_id, docID)
        XCTAssertGreaterThan(loaded.manifest?.items.count ?? 0, 100)
        XCTAssertFalse(SceneIndex(root: loaded.entity).entitiesByUSDName.isEmpty)
    }

    @MainActor
    func testControllerLoadsAC20FromBundleQuickly() async throws {
        let docID = "ifc_bench__ac20-arc"
        let files = try XCTUnwrap(DemoScenes.files(for: docID))
        let controller = ARSceneController()
        let start = Date()
        await controller.load(docID: docID, url: files.modelURL, manifestURL: files.manifestURL)
        print("AC20-LOAD-SECONDS \(Date().timeIntervalSince(start)) status=\(controller.status) loaded=\(controller.isLoaded) active=\(String(describing: controller.activeDocID)) title=\(controller.sceneIdentity.title)")
        XCTAssertTrue(controller.isLoaded)
        // Tags re-read visibility every few frames on device; it must stay far below a frame.
        let tick = Date()
        for _ in 0..<50 { _ = controller.visibleItemIDs }
        let perCall = Date().timeIntervalSince(tick) / 50
        print("AC20-VISIBLE-PER-CALL-MS \(perCall * 1000)")
        XCTAssertLessThan(perCall, 0.008)
    }

    @MainActor
    func testLiveAPILoadsAC20() async throws {
        let docID = "ifc_bench__ac20-arc"
        let url = try XCTUnwrap(URL(string: "https://hologram-khaki.vercel.app"))
        let start = Date()
        let loaded = try await ARSceneLoader.load(docID: docID, apiURL: url, url: nil)
        print("AC20-API-SECONDS \(Date().timeIntervalSince(start)) bundled=\(loaded.isBundledDemo) fixture=\(loaded.isFixture) title=\(loaded.documentTitle ?? "nil")")
        XCTAssertFalse(loaded.isFixture)
    }
}
