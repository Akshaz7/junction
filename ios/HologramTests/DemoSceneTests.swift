import RealityKit
import XCTest
@testable import Hologram

final class DemoSceneTests: XCTestCase {
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
