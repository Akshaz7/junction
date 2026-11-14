import RealityKit
import XCTest
@testable import Hologram

final class SceneCommandTests: XCTestCase {
    private func event(_ body: String) throws -> LiveSocket.Command {
        try LiveSocket.decode(Data(body.utf8))
    }

    @MainActor
    private func loadScene(withStoreys: Bool = false) async throws -> ARSceneController {
        // Synthetic fixture metadata, generated for demo; use the real fixture prims.
        let bundle = Bundle(for: Self.self)
        let source = try XCTUnwrap(bundle.url(forResource: "fixture.scene", withExtension: "json"))
        var json = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: source)) as? [String: Any])
        var items = try XCTUnwrap(json["items"] as? [String: [String: Any]])
        items["window-001"]?["tag"] = "W1"
        items["window-002"]?["tag"] = "W2"
        if withStoreys {
            json["storeys"] = [["name": "Ground", "elevation_m": 0], ["name": "Upper", "elevation_m": 3]]
            items["window-001"]?["storey"] = "Ground"
            items["window-002"]?["storey"] = "Upper"
            items["door-001"]?["kind"] = "roof"
        }
        json["items"] = items
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        try JSONSerialization.data(withJSONObject: json).write(to: url)
        defer { try? FileManager.default.removeItem(at: url) }
        let model = try XCTUnwrap(bundle.url(forResource: "fixture", withExtension: "usdz"))
        let controller = ARSceneController()
        await controller.load(url: model, manifestURL: url)
        XCTAssertTrue(controller.isLoaded)
        return controller
    }

    @MainActor
    func testHideAndRestoreFadeWithoutRemovingPrimAndRapidRestoreWins() async throws {
        let controller = try await loadScene()
        let window = try XCTUnwrap(controller.sceneIndex?.entity(for: "window-001"))
        let hide = try event(#"{"type":"scene.edit","doc_id":"fixture__ios","op":"hide","item_ids":["window-001"],"edit_id":"hide-1"}"#)
        let restore = try event(#"{"type":"scene.edit","doc_id":"fixture__ios","op":"restore","item_ids":["window-001"]}"#)
        XCTAssertTrue(controller.applyLiveCommand(hide))
        XCTAssertFalse(controller.visibleItemIDs.contains("window-001"))
        XCTAssertTrue(window.isEnabled, "Keep the entity enabled while it fades out")
        try await Task.sleep(for: .milliseconds(400))
        XCTAssertFalse(window.isEnabled)
        XCTAssertNotNil(window.parent, "Hidden prims stay in the index and remain restorable")
        XCTAssertTrue(controller.applyLiveCommand(restore))
        XCTAssertTrue(controller.visibleItemIDs.contains("window-001"))
        XCTAssertTrue(window.isEnabled)
        try await Task.sleep(for: .milliseconds(400))
        XCTAssertEqual(window.components[OpacityComponent.self]?.opacity, 1)

        // A duplicate edit must not re-hide a window after its later restore.
        controller.applyLiveCommand(hide)
        XCTAssertTrue(controller.visibleItemIDs.contains("window-001"))
        controller.applyLiveCommand(try event(#"{"type":"scene.edit","doc_id":"fixture__ios","op":"hide","item_ids":["window-001"]}"#))
        controller.applyLiveCommand(restore)
        try await Task.sleep(for: .milliseconds(400))
        XCTAssertTrue(window.isEnabled, "A cancelled hide cannot disable a later restore")
        XCTAssertEqual(window.components[OpacityComponent.self]?.opacity, 1)
    }

    @MainActor
    func testIsolateResetAndUnknownIDs() async throws {
        let controller = try await loadScene()
        let all = controller.visibleItemIDs
        controller.applyLiveCommand(try event(#"{"type":"scene.edit","doc_id":"fixture__ios","op":"highlight","item_ids":["window-001"],"labels":{"window-001":"W7"}}"#))
        controller.applyLiveCommand(try event(#"{"type":"scene.edit","doc_id":"fixture__ios","op":"isolate","item_ids":["window-001","missing"]}"#))
        XCTAssertEqual(controller.visibleItemIDs, ["window-001"])
        try await Task.sleep(for: .milliseconds(400))
        for id in all.subtracting(["window-001"]) {
            XCTAssertEqual(controller.sceneIndex?.entity(for: id)?.isEnabled, false)
        }
        controller.applyLiveCommand(try event(#"{"type":"scene.edit","doc_id":"fixture__ios","op":"reset","item_ids":[]}"#))
        XCTAssertEqual(controller.visibleItemIDs, all)
        XCTAssertTrue(controller.hiddenItemIDs.isEmpty)
        XCTAssertTrue(controller.highlightedItemIDs.isEmpty)
        XCTAssertTrue(try XCTUnwrap(controller.highlightController).labelsByItemID.isEmpty)
        controller.applyLiveCommand(try event(#"{"type":"scene.edit","doc_id":"fixture__ios","op":"hide","item_ids":["missing"]}"#))
        XCTAssertEqual(controller.visibleItemIDs, all)
    }

    @MainActor
    func testStateSnapshotReplacesEditsAndRendersExplicitAndManifestTags() async throws {
        let controller = try await loadScene()
        controller.applyLiveCommand(try event(#"{"type":"scene.edit","doc_id":"fixture__ios","op":"hide","item_ids":["wall-001"]}"#))
        controller.applyLiveCommand(try event(#"{"type":"scene.state","doc_id":"fixture__ios","hidden":["door-001"],"highlighted":["window-001","window-002"],"labels":{"window-001":"W7"}}"#))
        XCTAssertEqual(controller.hiddenItemIDs, ["door-001"])
        XCTAssertFalse(controller.visibleItemIDs.contains("door-001"))
        XCTAssertTrue(controller.visibleItemIDs.contains("wall-001"))
        XCTAssertEqual(controller.highlightedItemIDs, ["window-001", "window-002"])
        let labels = try XCTUnwrap(controller.highlightController).labelsByItemID
        XCTAssertNotNil(labels["window-001"]?.findEntity(named: "W7"))
        XCTAssertNotNil(labels["window-002"]?.findEntity(named: "W2"))
        controller.applyLiveCommand(try event(#"{"type":"scene.state","doc_id":"fixture__ios","hidden":[],"highlighted":[],"labels":{}}"#))
        XCTAssertTrue(controller.hiddenItemIDs.isEmpty)
        XCTAssertTrue(controller.highlightedItemIDs.isEmpty)
    }

    @MainActor
    func testOtherDocumentEventsDoNotChangeVisibilityOrHighlights() async throws {
        let controller = try await loadScene()
        let all = controller.visibleItemIDs
        XCTAssertFalse(controller.applyLiveCommand(try event(#"{"type":"scene.edit","doc_id":"other","op":"isolate","item_ids":["window-001"]}"#)))
        XCTAssertFalse(controller.applyLiveCommand(try event(#"{"type":"scene.state","doc_id":"other","hidden":["window-001"],"highlighted":["window-002"],"labels":{}}"#)))
        XCTAssertEqual(controller.visibleItemIDs, all)
        XCTAssertTrue(controller.highlightedItemIDs.isEmpty)
    }

    @MainActor
    func testCutawayWinsOverRestoreAndHighlightSwitchesStoreyWithoutClearingEdits() async throws {
        let controller = try await loadScene(withStoreys: true)
        XCTAssertFalse(controller.visibleItemIDs.contains("window-002"))
        controller.applyLiveCommand(try event(#"{"type":"scene.edit","doc_id":"fixture__ios","op":"restore","item_ids":["window-002","door-001"]}"#))
        XCTAssertFalse(controller.visibleItemIDs.contains("window-002"))
        XCTAssertFalse(controller.visibleItemIDs.contains("door-001"), "Roof policy wins over edits")
        controller.applyLiveCommand(try event(#"{"type":"scene.edit","doc_id":"fixture__ios","op":"hide","item_ids":["window-001"]}"#))
        controller.applyLiveCommand(try event(#"{"type":"scene.edit","doc_id":"fixture__ios","op":"highlight","item_ids":["window-002"]}"#))
        XCTAssertEqual(controller.activeStorey, "Upper")
        XCTAssertTrue(controller.visibleItemIDs.contains("window-002"))
        XCTAssertFalse(controller.visibleItemIDs.contains("window-001"))
        controller.stepStorey(-1)
        XCTAssertFalse(controller.visibleItemIDs.contains("window-002"))
        XCTAssertEqual(controller.highlightController?.labelsByItemID["window-002"]?.isEnabled, false)
        controller.applyLiveCommand(try event(#"{"type":"scene.edit","doc_id":"fixture__ios","op":"reset","item_ids":[]}"#))
        XCTAssertTrue(controller.visibleItemIDs.contains("window-001"))
        XCTAssertFalse(controller.visibleItemIDs.contains("door-001"), "Reset keeps the cutaway policy")
    }

    @MainActor
    func testVoiceCommandsRunInOrderAndKeepPriorHighlightOnHideAnswer() async throws {
        let controller = try await loadScene()
        let json = #"""
        {"answer":{"text_md":"Windows tagged."},"evidence":{"boxes":[],"scene":{
          "doc_id":"fixture__ios","highlight_item_ids":[],"commands":[
            {"op":"hide","item_ids":["window-001"]},
            {"op":"restore","item_ids":["window-001"]},
            {"op":"highlight","item_ids":["window-001","window-002"],"labels":{"window-001":"W7"}},
            {"op":"hide","item_ids":["window-002"]}
          ]}}}
        """#
        let answer = try JSONDecoder().decode(VoiceAnswer.self, from: Data(json.utf8))
        XCTAssertTrue(controller.applyVoiceAnswer(answer))
        XCTAssertTrue(controller.visibleItemIDs.contains("window-001"))
        XCTAssertFalse(controller.visibleItemIDs.contains("window-002"))
        XCTAssertEqual(controller.highlightedItemIDs, ["window-001", "window-002"])
        XCTAssertNotNil(controller.highlightController?.labelsByItemID["window-001"]?.findEntity(named: "W7"))
        XCTAssertEqual(controller.highlightController?.labelsByItemID["window-002"]?.isEnabled, false)
        let other = try JSONDecoder().decode(VoiceAnswer.self, from: Data(json.replacingOccurrences(of: "fixture__ios", with: "other").utf8))
        XCTAssertFalse(controller.applyVoiceAnswer(other))
    }

    func testDecoderRejectsMalformedCommandsAndIgnoresEmptyDocID() throws {
        XCTAssertThrowsError(try event(#"{"type":"scene.edit","doc_id":"fixture__ios","op":"delete","item_ids":[]}"#))
        XCTAssertThrowsError(try event(#"{"type":"scene.state","doc_id":"fixture__ios","hidden":[]}"#))
        XCTAssertEqual(try event(#"{"type":"scene.edit","doc_id":"","op":"reset","item_ids":[]}"#), .ignored)
    }
}
