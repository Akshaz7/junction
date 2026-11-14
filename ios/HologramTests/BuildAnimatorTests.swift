import RealityKit
import XCTest
@testable import Hologram

@MainActor
final class BuildAnimatorTests: XCTestCase {
    private var root: Entity!
    private var entities: [String: Entity] = [:]

    override func setUp() async throws {
        root = Entity()
        entities = [:]
        for name in ["w1", "w2", "d1"] {
            let entity = ModelEntity(mesh: .generateBox(size: [1, 2, 1]))
            entity.position = [0, 1, 0]
            root.addChild(entity)
            entities[name] = entity
        }
    }

    private func sequence() -> BuildSequence {
        BuildSequence.make(items: [
            BuildItem(id: "wall-1", usdName: "w1", kind: "wall", storey: "G", center: [0, 0]),
            BuildItem(id: "wall-2", usdName: "w2", kind: "wall", storey: "G", center: [1, 0]),
            BuildItem(id: "door-1", usdName: "d1", kind: "door", storey: "G", center: [2, 0]),
        ], storeys: [])
    }

    private func animator(pinned: Set<String> = []) -> BuildAnimator {
        BuildAnimator(sequence: sequence(), entities: entities, plan: nil, pinned: { pinned })
    }

    func testStepLabelsFollowTheSequence() {
        let animator = animator()
        animator.begin(reduceMotion: true)
        XCTAssertEqual(animator.state.total, 3)
        animator.setStep(2)
        XCTAssertEqual(animator.state.text, "Step 2 of 3 · Walls")
        animator.setStep(99)
        XCTAssertEqual(animator.state.index, 3)
        animator.setStep(0)
        XCTAssertEqual(animator.state.index, 1)
    }

    func testReduceMotionShowsTheFinishedModelAndTheScrubberStillWorks() {
        let animator = animator()
        animator.begin(reduceMotion: true)
        XCTAssertTrue(animator.isComplete)
        XCTAssertTrue(animator.state.finished)
        XCTAssertFalse(animator.state.playing)
        for entity in entities.values { XCTAssertEqual(entity.scale.y, 1, accuracy: 1e-4) }
        animator.setStep(2)
        XCTAssertFalse(animator.isComplete)
        XCTAssertLessThan(entities["d1"]!.scale.y, 0.01, "the doors step has not happened yet")
        XCTAssertEqual(entities["w1"]!.scale.y, 1, accuracy: 1e-4)
        animator.next()
        animator.next()
        XCTAssertTrue(animator.state.finished)
        XCTAssertEqual(entities["d1"]!.scale.y, 1, accuracy: 1e-4)
    }

    func testScrubbingBackShrinksLaterStepsAndKeepsTheBaseFixed() {
        let animator = animator()
        animator.begin(reduceMotion: true)
        animator.setStep(2)
        let door = entities["d1"]!
        XCTAssertLessThan(door.scale.y, 0.01)
        // Box is 2 high centred at y=1, so its base is 0 and stays there as it shrinks.
        XCTAssertEqual(door.position.y, 0, accuracy: 0.01)
        animator.setStep(3)
        XCTAssertEqual(door.position.y, 1, accuracy: 1e-4)
    }

    func testPinnedItemsStayFullyGrownWhileScrubbing() {
        let animator = animator(pinned: ["d1"])
        animator.begin(reduceMotion: true)
        animator.setStep(1)
        XCTAssertEqual(entities["d1"]!.scale.y, 1, accuracy: 1e-4, "pinned: visible before its step")
        XCTAssertLessThan(entities["w1"]!.scale.y, 0.01, "not pinned: still waiting for the walls step")
    }

    func testPlayAdvancesWithTimeAndStopsAtTheEnd() {
        let animator = animator()
        animator.begin()
        XCTAssertTrue(animator.state.playing)
        XCTAssertEqual(animator.position, 0)
        animator.tick(now: 100)
        animator.tick(now: 100.09)
        XCTAssertEqual(animator.position, 0.09 / animator.sequence.stepSeconds, accuracy: 1e-6)
        for i in 1...200 { animator.tick(now: 100.09 + Double(i) * 0.05) }
        XCTAssertTrue(animator.isComplete)
        XCTAssertFalse(animator.state.playing)
    }

    func testPausingSnapsToTheStepBeingBuilt() {
        let animator = animator()
        animator.begin()
        animator.setStep(1)
        animator.play()
        animator.tick(now: 10)
        animator.tick(now: 10.1)
        XCTAssertGreaterThan(animator.position, 1)
        animator.pause()
        XCTAssertEqual(animator.position, 2)
        XCTAssertFalse(animator.state.playing)
    }

    func testPlayAtTheEndRestartsAndFinishingStops() {
        let animator = animator()
        animator.begin(reduceMotion: true)
        animator.play()
        XCTAssertEqual(animator.position, 0)
        XCTAssertTrue(animator.state.playing)
        animator.finish()
        XCTAssertTrue(animator.isComplete)
        XCTAssertFalse(animator.state.playing)
    }

    func testDisposeRestoresFullGeometry() {
        let animator = animator()
        animator.begin(reduceMotion: true)
        animator.setStep(1)
        animator.dispose()
        for entity in entities.values {
            XCTAssertEqual(entity.scale.y, 1, accuracy: 1e-4)
            XCTAssertEqual(entity.position.y, 1, accuracy: 1e-4)
        }
    }
}
