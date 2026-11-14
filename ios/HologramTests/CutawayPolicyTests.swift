import RealityKit
import XCTest
@testable import Hologram

final class CutawayPolicyTests: XCTestCase {
    // Synthetic manifest, generated for demo. Prim names match the bundled test USDZ.
    private let json = #"""
    {"doc_id":"fixture__ios","note":"generated for demo","storeys":[
      {"name":"Upper","elevation_m":3},
      {"name":"Basement","elevation_m":-3},
      {"name":"Ground","elevation_m":0}
    ],"items":{
      "wall-001":{"usd_name":"i_7b48a86d5f6d4471","kind":"wall","storey":"Basement"},
      "window-001":{"usd_name":"i_52f45ebe784f28cc","kind":"window","storey":"Ground"},
      "window-002":{"usd_name":"i_cb9deec18252f998","kind":"window","storey":"Upper"},
      "door-001":{"usd_name":"i_7eea4caad788ba9b","kind":"roof","storey":"Upper"},
      "wall-002":{"usd_name":"i_df1b6aaadb3c980f","kind":"wall","storey":null}
    }}
    """#

    private func manifest() throws -> SceneManifest {
        try JSONDecoder().decode(SceneManifest.self, from: Data(json.utf8))
    }

    func testRoomVolumesStayHiddenEvenWhenHighlighted() throws {
        let withRoom = json.replacingOccurrences(of: #""wall-002""#, with:
            #""room-001":{"usd_name":"i_room1","kind":"room","storey":"Ground"},"wall-002""#)
        let manifest = try JSONDecoder().decode(SceneManifest.self, from: Data(withRoom.utf8))
        let policy = CutawayPolicy(manifest: manifest)
        XCTAssertTrue(policy.hiddenUSDNames(activeStorey: "Ground", showRoof: false).contains("i_room1"))
        XCTAssertTrue(policy.hiddenUSDNames(activeStorey: "Ground", showRoof: false, keep: ["room-001"]).contains("i_room1"))
    }

    func testDefaultHidesRoofAndHigherStoreysButKeepsGroundBasementAndUnknown() throws {
        let policy = CutawayPolicy(manifest: try manifest())
        XCTAssertEqual(policy.storeys.compactMap(\.name), ["Basement", "Ground", "Upper"])
        let active = policy.activeStorey()
        XCTAssertEqual(active, "Ground", "Start at the lowest nonnegative elevation")
        XCTAssertEqual(policy.hiddenUSDNames(activeStorey: active, showRoof: false),
                       ["i_7eea4caad788ba9b", "i_cb9deec18252f998"])
    }

    func testShowRoofRevealsRoofEvenAboveActiveStorey() throws {
        let policy = CutawayPolicy(manifest: try manifest())
        XCTAssertEqual(policy.hiddenUSDNames(activeStorey: "Ground", showRoof: true),
                       ["i_cb9deec18252f998"])
        XCTAssertEqual(policy.hiddenUSDNames(activeStorey: "Upper", showRoof: false),
                       ["i_7eea4caad788ba9b"])
        XCTAssertTrue(policy.hiddenUSDNames(activeStorey: "Upper", showRoof: true).isEmpty)
    }

    func testAnswerStoreyUsesCameraTargetThenHighlightOrderThenDefault() throws {
        let policy = CutawayPolicy(manifest: try manifest())
        XCTAssertEqual(policy.activeStorey(highlightedItemIDs: ["window-002", "window-001"]), "Upper")
        XCTAssertEqual(policy.activeStorey(cameraTargetItemID: "wall-001",
                                           highlightedItemIDs: ["window-002"]), "Basement")
        XCTAssertEqual(policy.activeStorey(cameraTargetItemID: "missing",
                                           highlightedItemIDs: ["wall-002", "window-002"]), "Upper")
        XCTAssertEqual(policy.activeStorey(highlightedItemIDs: ["missing", "wall-002"]), "Ground")
    }

    func testCoveringRoofMetadataAndMissingStoreys() throws {
        let manifest = try JSONDecoder().decode(SceneManifest.self, from: Data(#"""
        {"note":"generated for demo","items":{
          "roof":{"usd_name":"roof","kind":"IfcRoof"},
          "covering":{"usd_name":"covering","kind":"IfcCovering","props":{"predefined_type":"ROOFING"}},
          "typed":{"usd_name":"typed","kind":"IfcCovering.ROOFING"},
          "metadata":{"usd_name":"metadata","kind":"other",
                      "props":{"ifc_class":"IfcCovering","predefined_type":"ROOFING"}},
          "ceiling":{"usd_name":"ceiling","kind":"IfcCovering","props":{"predefined_type":"CEILING"}},
          "unknown":{"usd_name":"unknown"}
        }}
        """#.utf8))
        let policy = CutawayPolicy(manifest: manifest)
        XCTAssertNil(policy.activeStorey())
        XCTAssertEqual(policy.hiddenUSDNames(activeStorey: nil, showRoof: false),
                       ["roof", "covering", "typed", "metadata"])
        XCTAssertTrue(policy.hiddenUSDNames(activeStorey: nil, showRoof: true).isEmpty)
    }

    func testNoNonnegativeStoreyFallsBackToLowestKnownElevation() throws {
        let manifest = try JSONDecoder().decode(SceneManifest.self, from: Data(#"""
        {"items":{},"storeys":[{"name":"B1","elevation_m":-3},
                               {"name":"Unknown"},{"name":"B2","elevation_m":-6}]}
        """#.utf8))
        XCTAssertEqual(CutawayPolicy(manifest: manifest).activeStorey(), "B2")
    }

    @MainActor
    func testControllerAppliesCutawayRestoresVisibilityAndKeepsItInWalkMode() async throws {
        let manifestURL = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try Data(json.utf8).write(to: manifestURL)
        defer { try? FileManager.default.removeItem(at: manifestURL) }
        let modelURL = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "fixture", withExtension: "usdz"))
        let controller = ARSceneController()
        await controller.load(url: modelURL, manifestURL: manifestURL,
                              itemIDs: ["window-001", "window-002"])
        XCTAssertTrue(controller.isLoaded)
        let index = try XCTUnwrap(controller.sceneIndex)
        let roof = try XCTUnwrap(index.entity(for: "door-001"))
        let upper = try XCTUnwrap(index.entity(for: "window-002"))
        let labels = try XCTUnwrap(controller.highlightController).labelsByItemID
        XCTAssertEqual(controller.activeStorey, "Ground")
        XCTAssertFalse(roof.isEnabled)
        XCTAssertFalse(upper.isEnabled)
        XCTAssertEqual(labels["window-002"]?.isEnabled, false)
        controller.setShowRoof(true)
        XCTAssertTrue(roof.isEnabled)
        XCTAssertFalse(upper.isEnabled)
        controller.setWalking(true)
        XCTAssertTrue(controller.showRoof)
        XCTAssertFalse(upper.isEnabled)
        controller.setShowRoof(false)
        XCTAssertFalse(roof.isEnabled, "The roof toggle also works during walking")
        controller.stepStorey(1)
        XCTAssertEqual(controller.activeStorey, "Upper")
        XCTAssertTrue(upper.isEnabled)
        XCTAssertEqual(labels["window-002"]?.isEnabled, true)
        XCTAssertFalse(controller.canStepStoreyUp)
        controller.stepStorey(1)
        XCTAssertEqual(controller.activeStorey, "Upper")
        controller.setWalking(false)
        XCTAssertEqual(controller.activeStorey, "Upper")
        XCTAssertFalse(roof.isEnabled)
        controller.stepStorey(-1)
        controller.stepStorey(-1)
        XCTAssertEqual(controller.activeStorey, "Basement")
        XCTAssertFalse(controller.canStepStoreyDown)
        XCTAssertFalse(try XCTUnwrap(index.entity(for: "window-001")).isEnabled)
        XCTAssertTrue(controller.applyLiveHighlight(ARRequest(docID: "fixture__ios", itemIDs: ["window-002"])))
        XCTAssertEqual(controller.activeStorey, "Upper", "Live answers select their own storey")
        XCTAssertTrue(upper.isEnabled)
        XCTAssertFalse(roof.isEnabled)
        let label = try XCTUnwrap(controller.highlightController?.labelsByItemID["window-002"])
        let root = try XCTUnwrap(label.parent)
        XCTAssertGreaterThan(label.position.y, upper.visualBounds(relativeTo: root).max.y)
    }
}
