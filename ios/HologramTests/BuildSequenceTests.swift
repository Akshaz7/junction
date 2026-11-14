import XCTest
@testable import Hologram

final class BuildSequenceTests: XCTestCase {
    private func item(_ name: String, _ kind: String, _ storey: String?, _ x: Float = 0, _ z: Float = 0) -> BuildItem {
        BuildItem(usdName: name, kind: kind, storey: storey, center: [x, z])
    }

    private let storeys = [SceneManifest.Storey(name: "Ground", elevation_m: 0),
                           SceneManifest.Storey(name: "First", elevation_m: 3)]

    func testIFCOrderIsFoundationThenStoreysThenRoof() {
        let items = [
            item("roof", "roof", "First"), item("w1", "wall", "First"), item("d0", "door", "Ground"),
            item("w0", "wall", "Ground"), item("s0", "slab", "Ground"), item("f", "footing", nil),
            item("c0", "column", "Ground"), item("st0", "stairs", "Ground"), item("s1", "slab", "First"),
        ]
        let seq = BuildSequence.make(items: items, storeys: storeys)
        XCTAssertEqual(seq.steps.map(\.phase),
                       [.foundation, .slab, .structure, .walls, .stairs, .openings, .slab, .walls, .roof])
        XCTAssertEqual(seq.steps.map(\.storey), [nil, "Ground", "Ground", "Ground", "Ground", "Ground", "First", "First", nil])
        // Steps never overlap and run back to back.
        for (a, b) in zip(seq.steps, seq.steps.dropFirst()) { XCTAssertEqual(a.start + a.duration, b.start, accuracy: 1e-9) }
    }

    func testRasterPlanIsFloorWallsOpenings() {
        let items = [item("d", "door", "Floor 1"), item("w", "wall", "Floor 1"), item("r", "room", "Floor 1"),
                     item("win", "window", "Floor 1")]
        let seq = BuildSequence.make(items: items, storeys: [SceneManifest.Storey(name: "Floor 1", elevation_m: 0)])
        XCTAssertEqual(seq.steps.map(\.phase), [.walls, .openings])
        XCTAssertFalse(seq.slots.contains { $0.usdName == "r" }, "room volumes are not built")
    }

    func testUpperStoreysBuildAfterLowerOnes() {
        let items = [item("a", "wall", "First"), item("b", "wall", "Ground")]
        let seq = BuildSequence.make(items: items, storeys: storeys)
        let start = Dictionary(uniqueKeysWithValues: seq.slots.map { ($0.usdName, $0.start) })
        XCTAssertLessThan(start["b"]!, start["a"]!)
    }

    func testTotalFitsBudgetAndSmallPlansKeepNaturalTiming() {
        let small = BuildSequence.make(items: [item("w", "wall", "G"), item("d", "door", "G")], storeys: [])
        XCTAssertEqual(small.steps.first { $0.phase == .walls }?.duration ?? 0, 1.2, accuracy: 1e-9)
        XCTAssertEqual(small.steps.first { $0.phase == .openings }?.duration ?? 0, 0.6, accuracy: 1e-9)

        var big: [BuildItem] = []
        for i in 0..<5 {
            for kind in ["slab", "wall", "stairs", "door", "column"] { big.append(item("\(kind)\(i)", kind, "S\(i)")) }
        }
        let storeys = (0..<5).map { SceneManifest.Storey(name: "S\($0)", elevation_m: Float($0) * 3) }
        let seq = BuildSequence.make(items: big, storeys: storeys)
        XCTAssertEqual(seq.totalDuration, BuildSequence.totalBudget, accuracy: 1e-6)
    }

    func testItemsAreStaggeredFromTheCentreOutwardsWithinAStep() {
        let items = [item("far", "wall", "G", 10, 0), item("near", "wall", "G", 0.1, 0), item("mid", "wall", "G", 3, 0),
                     item("origin", "wall", "G", -10, 0)]
        let seq = BuildSequence.make(items: items, storeys: [])
        let order = seq.slots.map(\.usdName)
        XCTAssertEqual(order.first, "near")
        let step = seq.steps[0]
        XCTAssertEqual(seq.slots.first!.start, step.start, accuracy: 1e-9)
        for slot in seq.slots { XCTAssertLessThanOrEqual(slot.end, step.start + step.duration + 1e-9) }
    }

    func testDoorsAndWindowsOpenLastInsideAStoreyAfterStairs() {
        let seq = BuildSequence.make(items: [item("win", "window", "G"), item("st", "stairs", "G"), item("w", "wall", "G")],
                                     storeys: [])
        XCTAssertEqual(seq.steps.map(\.phase), [.walls, .stairs, .openings])
    }

    func testManifestOverloadHonoursIncludeSet() throws {
        let json = """
        {"items":{"a":{"usd_name":"i_a","kind":"wall","storey":"G","bbox_m":[[0,0,0],[1,2,1]]},
                  "b":{"usd_name":"i_b","kind":"door","storey":"G","bbox_m":[[0,0,0],[1,2,1]]}},
         "storeys":[{"name":"G","elevation_m":0}]}
        """
        let manifest = try JSONDecoder().decode(SceneManifest.self, from: Data(json.utf8))
        XCTAssertEqual(Set(BuildSequence.make(manifest: manifest).slots.map(\.usdName)), ["i_a", "i_b"])
        XCTAssertEqual(BuildSequence.make(manifest: manifest, include: ["a"]).slots.map(\.usdName), ["i_a"])
    }

    func testEaseOutIsMonotonicAndClamped() {
        XCTAssertEqual(BuildSequence.easeOut(-1), 0)
        XCTAssertEqual(BuildSequence.easeOut(2), 1)
        var last = 0.0
        for i in 0...20 { let v = BuildSequence.easeOut(Double(i) / 20); XCTAssertGreaterThanOrEqual(v, last); last = v }
    }

    func testBundledAC20SequenceCoversVisibleElementsWithinBudget() throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "scene", withExtension: "json",
                                                           subdirectory: "DemoScenes/ifc_bench__ac20-arc")
            ?? Bundle.main.url(forResource: "scene", withExtension: "json", subdirectory: "DemoScenes/ifc_bench__ac20-arc"))
        let manifest = try JSONDecoder().decode(SceneManifest.self, from: Data(contentsOf: url))
        let seq = BuildSequence.make(manifest: manifest)
        XCTAssertGreaterThan(seq.slots.count, 500)
        XCTAssertLessThanOrEqual(seq.totalDuration, BuildSequence.totalBudget + 1e-6)
    }
}
