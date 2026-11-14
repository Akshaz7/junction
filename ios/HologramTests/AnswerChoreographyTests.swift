import XCTest
@testable import Hologram

final class AnswerChoreographyTests: XCTestCase {
    private func item(_ id: String, x: Float, z: Float, elevation: Float = 0, kind: String? = "door") -> AnswerChoreography.Item {
        .init(id: id, kind: kind, center: [x, z], elevation: elevation)
    }

    func testReadingOrderIsStoreyThenRowThenLeftToRight() {
        let items = [
            item("c", x: 1, z: 3), item("b", x: 5, z: 0.2), item("a", x: 1, z: 0.4),
            item("up", x: 0, z: 0, elevation: 3)
        ]
        XCTAssertEqual(AnswerChoreography.readingOrder(items).map(\.id), ["a", "b", "c", "up"])
    }

    func testScheduleCapsStepAndTotalSpan() {
        let few = (0..<4).map { item("f\($0)", x: Float($0), z: 0) }
        let slots = AnswerChoreography.schedule(few)
        XCTAssertEqual(slots.map(\.index), [0, 1, 2, 3])
        XCTAssertEqual(slots[1].start - slots[0].start, AnswerChoreography.maxStep, accuracy: 1e-9)

        let many = (0..<60).map { item("m\($0)", x: Float($0), z: 0) }
        let last = AnswerChoreography.schedule(many).last!
        XCTAssertLessThanOrEqual(last.start, AnswerChoreography.lightDelay + AnswerChoreography.maxLightSpan)
        XCTAssertTrue(AnswerChoreography.schedule([]).isEmpty)
    }

    func testTotalDurationCoversSpinAndLastPop() {
        let slots = AnswerChoreography.schedule((0..<3).map { item("s\($0)", x: Float($0), z: 0) })
        XCTAssertGreaterThanOrEqual(AnswerChoreography.totalDuration(for: slots), AnswerChoreography.spinDuration)
        let long = AnswerChoreography.schedule((0..<60).map { item("l\($0)", x: Float($0), z: 0) })
        XCTAssertGreaterThan(AnswerChoreography.totalDuration(for: long), AnswerChoreography.spinDuration)
    }

    func testTurntableAngleIsSmoothFullTurn() {
        XCTAssertEqual(AnswerChoreography.turntableAngle(at: 0), 0, accuracy: 1e-6)
        XCTAssertEqual(AnswerChoreography.turntableAngle(at: AnswerChoreography.spinDuration), 2 * .pi, accuracy: 1e-5)
        XCTAssertEqual(AnswerChoreography.turntableAngle(at: 99), 2 * .pi, accuracy: 1e-5)
        var previous: Float = -1
        for step in 0...30 {
            let angle = AnswerChoreography.turntableAngle(at: Double(step) * 0.1)
            XCTAssertGreaterThanOrEqual(angle, previous)
            previous = angle
        }
    }

    func testCaptionPluralisesAndFallsBackForMixedKinds() {
        XCTAssertEqual(AnswerChoreography.caption(count: 1, kinds: ["door"]), "1 door")
        XCTAssertEqual(AnswerChoreography.caption(count: 12, kinds: ["door", "door"]), "12 doors")
        XCTAssertEqual(AnswerChoreography.caption(count: 5, kinds: ["door", "window"]), "5 items")
        XCTAssertEqual(AnswerChoreography.caption(count: 1, kinds: [nil]), "1 item")
    }

    func testSilenceDetectorEndsAfterQuietFollowingSpeech() {
        var detector = SilenceDetector()
        var verdict = SilenceDetector.Verdict.listening
        for tick in 0..<10 { verdict = detector.feed(powerDB: -20, at: Double(tick) * 0.1) }
        XCTAssertEqual(verdict, .listening)
        XCTAssertEqual(detector.feed(powerDB: -60, at: 1.5), .listening)
        XCTAssertEqual(detector.feed(powerDB: -60, at: 2.0), .listening)
        XCTAssertEqual(detector.feed(powerDB: -60, at: 2.2), .endOfSpeech)
    }

    func testSilenceDetectorTimesOutWithoutSpeechAndIgnoresClicks() {
        var detector = SilenceDetector()
        XCTAssertEqual(detector.feed(powerDB: -10, at: 0.1), .listening)   // one loud sample is a click
        XCTAssertEqual(detector.feed(powerDB: -70, at: 0.2), .listening)
        XCTAssertFalse(detector.heardSpeech)
        XCTAssertEqual(detector.feed(powerDB: -70, at: 3), .listening)
        XCTAssertEqual(detector.feed(powerDB: -70, at: 8.1), .noSpeech)
    }
}
