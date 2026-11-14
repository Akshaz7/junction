import Foundation
import simd

/// Pure plan for the voice "wow" moment: a 360 degree turntable spin while the answer items light up one by
/// one in reading order, each with a pulse ring and a tag pop. No RealityKit here so it can be unit tested.
enum AnswerChoreography {
    static let spinDuration: TimeInterval = 3.0
    static let lightDelay: TimeInterval = 0.4
    static let maxLightSpan: TimeInterval = 3.0
    static let maxStep: TimeInterval = 0.25
    static let ringDuration: TimeInterval = 0.8
    /// Items closer in depth than this share a row when ordering left to right.
    static let rowHeight: Float = 1.5

    struct Item: Equatable {
        let id: String
        let kind: String?
        let center: SIMD2<Float>   // x, z on the floor plane
        let elevation: Float       // storey elevation, lower storeys first
    }

    struct Slot: Equatable {
        let id: String
        let index: Int
        let start: TimeInterval
    }

    /// Reading order: lowest storey first, then rows from north to south, then left to right.
    static func readingOrder(_ items: [Item]) -> [Item] {
        items.sorted { a, b in
            if a.elevation != b.elevation { return a.elevation < b.elevation }
            let rowA = Int((a.center.y / rowHeight).rounded(.down)), rowB = Int((b.center.y / rowHeight).rounded(.down))
            if rowA != rowB { return rowA < rowB }
            if a.center.x != b.center.x { return a.center.x < b.center.x }
            return a.id < b.id
        }
    }

    static func schedule(_ items: [Item]) -> [Slot] {
        let ordered = readingOrder(items)
        guard !ordered.isEmpty else { return [] }
        let step = min(maxStep, maxLightSpan / Double(ordered.count))
        return ordered.enumerated().map { Slot(id: $1.id, index: $0, start: lightDelay + Double($0) * step) }
    }

    static func totalDuration(for slots: [Slot], popDuration: TimeInterval = BuildAnimator.popDuration) -> TimeInterval {
        let lights = (slots.last?.start ?? 0) + max(popDuration, ringDuration)
        return max(spinDuration, lights)
    }

    /// Smooth start and stop: 0 at t=0 and a full 2 pi turn at `spinDuration`.
    static func turntableAngle(at t: TimeInterval) -> Float {
        let x = min(max(t / spinDuration, 0), 1)
        let eased = x < 0.5 ? 4 * x * x * x : 1 - pow(-2 * x + 2, 3) / 2
        return Float(eased) * 2 * .pi
    }

    /// "7 doors" / "1 door" while counting up; "items" when kinds are mixed.
    static func caption(count: Int, kinds: [String?]) -> String {
        let keys = Set(kinds.map { KindColors.key(for: $0) })
        guard keys.count == 1, let key = keys.first, key != "other" else { return "\(count) \(count == 1 ? "item" : "items")" }
        let style = KindColors.style(for: key)
        return "\(count) \(count == 1 ? style.label.lowercased() : style.plural.lowercased())"
    }
}

/// Energy-based end-of-speech detection for hands-free voice: ends the question after `silenceToEnd` seconds of
/// quiet once speech has been heard.
struct SilenceDetector {
    enum Verdict: Equatable { case listening, endOfSpeech, noSpeech }

    var speechThresholdDB: Float = -38
    var silenceToEnd: TimeInterval = 1.2
    var minDuration: TimeInterval = 0.8
    var noSpeechTimeout: TimeInterval = 8
    /// Consecutive loud samples needed to count as speech, so a click or a tap on the screen does not.
    var loudSamplesForSpeech = 2

    private(set) var heardSpeech = false
    private var loudRun = 0
    private var lastLoud: TimeInterval = 0

    /// `time` is seconds since recording started.
    mutating func feed(powerDB: Float, at time: TimeInterval) -> Verdict {
        if powerDB > speechThresholdDB {
            loudRun += 1
            lastLoud = time
            if loudRun >= loudSamplesForSpeech { heardSpeech = true }
        } else {
            loudRun = 0
        }
        if !heardSpeech { return time >= noSpeechTimeout ? .noSpeech : .listening }
        if time >= minDuration, time - lastLoud >= silenceToEnd { return .endOfSpeech }
        return .listening
    }
}
