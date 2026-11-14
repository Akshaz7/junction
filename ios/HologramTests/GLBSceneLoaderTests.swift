import XCTest
import RealityKit
@testable import Hologram

/// Uploaded drawings have scene.glb and often no (or a stale) scene.usdz; AR must build from the GLB on the device.
final class GLBSceneLoaderTests: XCTestCase {
    private let docID = "cubicasa5k__colorful-11397"

    private var artifactDirectory: URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("artifacts/\(docID)")
    }

    func testRejectsNonGLBData() {
        XCTAssertThrowsError(try GLBSceneLoader.parse(Data("not a glb file at all".utf8)))
    }

    /// A one-triangle GLB, built by hand, becomes a named entity with a mesh.
    @MainActor
    func testTinyGLBBecomesNamedEntity() throws {
        var bin = Data()
        for v: Float in [0, 0, 0, 1, 0, 0, 0, 0, 1] { withUnsafeBytes(of: v.bitPattern.littleEndian) { bin.append(contentsOf: $0) } }
        for i: UInt16 in [0, 1, 2, 0] { withUnsafeBytes(of: i.littleEndian) { bin.append(contentsOf: $0) } }
        let json: [String: Any] = [
            "asset": ["version": "2.0"], "scene": 0, "scenes": [["nodes": [0]]],
            "nodes": [["name": "wall-1", "mesh": 0]],
            "meshes": [["primitives": [["attributes": ["POSITION": 0], "indices": 1, "mode": 4, "material": 0]]]],
            "materials": [["pbrMetallicRoughness": ["baseColorFactor": [0.5, 0.5, 0.5, 0.5]], "doubleSided": true]],
            "accessors": [["bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"],
                          ["bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"]],
            "bufferViews": [["buffer": 0, "byteOffset": 0, "byteLength": 36], ["buffer": 0, "byteOffset": 36, "byteLength": 6]],
            "buffers": [["byteLength": bin.count]],
        ]
        let glb = try Self.container(json: json, bin: bin)
        let root = try GLBSceneLoader.entity(from: glb, nodeNames: ["wall-1": "i_abc"])
        let index = SceneIndex(root: root)
        let wall = try XCTUnwrap(index.entitiesByUSDName["i_abc"])
        XCTAssertEqual(wall.children.count, 1)
        XCTAssertNotNil(wall.children.first?.components[ModelComponent.self])
    }

    @MainActor
    func testTruncatedGLBFailsSoftly() throws {
        let glb = try Self.container(json: ["asset": ["version": "2.0"], "nodes": [["name": "x", "mesh": 0]],
                                            "meshes": [["primitives": [["attributes": ["POSITION": 0]]]]],
                                            "accessors": [["bufferView": 0, "componentType": 5126, "count": 99, "type": "VEC3"]],
                                            "bufferViews": [["buffer": 0, "byteLength": 12]]], bin: Data(count: 12))
        XCTAssertThrowsError(try GLBSceneLoader.entity(from: glb, nodeNames: [:]))
    }

    /// The real uploaded raster scene (skipped without the local artifacts folder): GLB only, no USDZ.
    @MainActor
    func testUploadedRasterSceneLoadsFromGLBWithoutUSDZ() async throws {
        let glb = artifactDirectory.appendingPathComponent("scene.glb")
        let manifest = artifactDirectory.appendingPathComponent("scene.json")
        guard FileManager.default.fileExists(atPath: glb.path), FileManager.default.fileExists(atPath: manifest.path) else {
            throw XCTSkip("artifacts/\(docID) not available")
        }
        let files = SceneRepository.Files(modelURL: artifactDirectory.appendingPathComponent("no-such.usdz"),
                                          manifestURL: manifest, glbURL: glb)
        let scene = try await ARSceneLoader.load(docID: docID, url: nil, fetcher: { _ in files })
        XCTAssertFalse(scene.isFixture)
        XCTAssertEqual(scene.manifest?.doc_id, docID)
        let index = SceneIndex(root: scene.entity)
        let items = try XCTUnwrap(scene.manifest?.items)
        XCTAssertFalse(items.isEmpty)
        for item in items.values { XCTAssertNotNil(index.entitiesByUSDName[item.usd_name], item.usd_name) }
        XCTAssertGreaterThan(scene.entity.visualBounds(relativeTo: nil).extents.x, 1)
        // The embedded plan image is decoded onto the plan_floor plane.
        let floor = try XCTUnwrap(index.entitiesByUSDName["plan_floor"])
        let model = try XCTUnwrap(floor.children.first?.components[ModelComponent.self])
        let material = try XCTUnwrap(model.materials.first as? PhysicallyBasedMaterial)
        XCTAssertNotNil(material.baseColor.texture)
    }

    /// A stale USDZ (belongs to another scene) is skipped in favour of the GLB.
    @MainActor
    func testStaleUSDZFallsBackToGLB() async throws {
        let glb = artifactDirectory.appendingPathComponent("scene.glb")
        let manifest = artifactDirectory.appendingPathComponent("scene.json")
        guard FileManager.default.fileExists(atPath: glb.path),
              let stale = Bundle(for: Self.self).url(forResource: "fixture", withExtension: "usdz") else {
            throw XCTSkip("artifacts/\(docID) not available")
        }
        let files = SceneRepository.Files(modelURL: stale, manifestURL: manifest, glbURL: glb)
        let scene = try await ARSceneLoader.load(docID: docID, url: nil, fetcher: { _ in files })
        XCTAssertFalse(scene.isFixture)
        XCTAssertEqual(scene.manifest?.doc_id, docID)
    }

    /// No usable model at all: the loader falls back to the bundled copy, else the labelled sample, instead of crashing.
    @MainActor
    func testNoModelFilesFallBackToLabelledSample() async throws {
        let manifest = artifactDirectory.appendingPathComponent("scene.json")
        guard FileManager.default.fileExists(atPath: manifest.path) else { throw XCTSkip("artifacts not available") }
        let files = SceneRepository.Files(modelURL: artifactDirectory.appendingPathComponent("none.usdz"), manifestURL: manifest)
        let scene = try await ARSceneLoader.load(docID: docID, url: nil, fetcher: { _ in files })
        XCTAssertTrue(scene.isFixture || scene.isBundledDemo)
        // A document with no bundled copy ends on the labelled sample, never an error or a crash.
        let other = try await ARSceneLoader.load(docID: "uploaded__no-bundle", url: nil, fetcher: { _ in files })
        XCTAssertTrue(other.isFixture)
    }

    private static func container(json: [String: Any], bin: Data) throws -> Data {
        var jsonData = try JSONSerialization.data(withJSONObject: json)
        while jsonData.count % 4 != 0 { jsonData.append(0x20) }
        var bin = bin
        while bin.count % 4 != 0 { bin.append(0) }
        func le(_ v: Int) -> Data { var x = UInt32(v).littleEndian; return Data(bytes: &x, count: 4) }
        var out = le(0x4654_6C67) + le(2) + le(12 + 8 + jsonData.count + 8 + bin.count)
        out += le(jsonData.count) + le(0x4E4F_534A) + jsonData + le(bin.count) + le(0x004E_4942) + bin
        return out
    }
}
