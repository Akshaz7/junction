import XCTest
@testable import Hologram

final class BuildSequenceTests: XCTestCase {
    private func item(_ name: String, _ kind: String, _ storey: String?, _ x: Float = 0, _ z: Float = 0,
                       id: String? = nil) -> BuildItem {
        BuildItem(id: id ?? "GUID\(name)", usdName: name, kind: kind, storey: storey, center: [x, z])
    }

    private let storeys = [SceneManifest.Storey(name: "Ground", elevation_m: 0),
                           SceneManifest.Storey(name: "First", elevation_m: 3)]

    func testIFCOrderIsFoundationThenStoreysThenRoofWithWebLabels() {
        let items = [
            item("roof", "roof", "First"), item("w1", "wall", "First"), item("d0", "door", "Ground"),
            item("w0", "wall", "Ground"), item("s0", "slab", "Ground"), item("f", "footing", nil),
            item("c0", "column", "Ground"), item("st0", "stairs", "Ground"), item("s1", "slab", "First"),
        ]
        let seq = BuildSequence.make(items: items, storeys: storeys)
        XCTAssertFalse(seq.isRaster)
        XCTAssertEqual(seq.steps.map(\.label), [
            "Foundations", "Ground slab", "Ground columns and beams", "Ground walls", "Ground stairs",
            "Ground doors and windows", "First slab", "First walls", "Roof",
        ])
        XCTAssertEqual(seq.total, 9)
    }

    func testStoreysAreOrderedByElevationNotListOrder() {
        let seq = BuildSequence.make(items: [item("a", "wall", "First"), item("b", "wall", "Ground")],
                                     storeys: storeys.reversed())
        XCTAssertEqual(seq.steps.map(\.label), ["Ground walls", "First walls"])
    }

    func testItemsWithoutAStoreyJoinTheLowestOneAndSiteStaysOut() {
        let seq = BuildSequence.make(items: [item("w", "wall", nil), item("ground", "site", nil)], storeys: storeys)
        XCTAssertEqual(seq.steps.map(\.label), ["Ground walls"])
        XCTAssertFalse(seq.steps.flatMap(\.usdNames).contains("ground"))
    }

    func testRoomsAreSlabsAndUnknownKindsAreOpeningsLikeTheWeb() {
        let seq = BuildSequence.make(items: [item("r", "room", "Ground"), item("lamp", "light", "Ground")],
                                     storeys: storeys)
        XCTAssertEqual(seq.steps.map(\.label), ["Ground slab", "Ground doors and windows"])
    }

    func testRasterPlanIsFloorWallsDoorsAndWindows() {
        let items = [item("d", "door", "Floor 1", id: "door-1"), item("w", "wall", "Floor 1", id: "wall-1"),
                     item("r", "room", "Floor 1", id: "room-1"), item("win", "window", "Floor 1", id: "window-2")]
        let seq = BuildSequence.make(items: items, storeys: [SceneManifest.Storey(name: "Floor 1", elevation_m: 0)])
        XCTAssertTrue(seq.isRaster)
        XCTAssertEqual(seq.steps.map(\.label), ["Floor", "Walls", "Doors and windows"])
        XCTAssertEqual(seq.steps[0].usdNames, ["r"])
        XCTAssertEqual(Set(seq.steps[2].usdNames), ["d", "win"])
    }

    func testRasterAlwaysHasAFloorStepEvenWithoutRooms() {
        let seq = BuildSequence.make(items: [item("w", "wall", "F", id: "wall-1")], storeys: [])
        XCTAssertEqual(seq.steps.map(\.label), ["Floor", "Walls"])
    }

    func testPlanMapIDPatternMatchesTheWeb() {
        for id in ["wall-3", "door_leaf-12", "room-0"] { XCTAssertTrue(BuildSequence.isPlanMapID(id), id) }
        for id in ["2O2Fr$t4X7Zf8NOew3FLOH", "Wall-3", "wall-", "-3", "wall-3a", "wall3"] {
            XCTAssertFalse(BuildSequence.isPlanMapID(id), id)
        }
    }

    func testStepDurationIsSharedAndWithinLimits() {
        let few = BuildSequence.make(items: [item("w", "wall", "G", id: "wall-1")], storeys: [])
        XCTAssertEqual(few.stepSeconds, BuildSequence.maxStepSeconds)
        var big: [BuildItem] = []
        for i in 0..<5 {
            for kind in ["slab", "wall", "stairs", "door", "column"] { big.append(item("\(kind)\(i)", kind, "S\(i)")) }
        }
        let storeys = (0..<5).map { SceneManifest.Storey(name: "S\($0)", elevation_m: Float($0) * 3) }
        let seq = BuildSequence.make(items: big, storeys: storeys)
        XCTAssertEqual(seq.total, 25)
        XCTAssertEqual(seq.stepSeconds, BuildSequence.minStepSeconds)
        XCTAssertLessThanOrEqual(seq.totalDuration, BuildSequence.totalBudget * 1.3)
    }

    func testItemsAreStaggeredFromTheCentreOutwardsWithinAStep() {
        let items = [item("far", "wall", "G", 10, 0), item("near", "wall", "G", 0.1, 0), item("mid", "wall", "G", 3, 0),
                     item("origin", "wall", "G", -10, 0)]
        let seq = BuildSequence.make(items: items, storeys: [])
        XCTAssertEqual(seq.steps[0].usdNames.first, "near")
        let count = seq.steps[0].usdNames.count
        // Halfway into the step the nearest item is ahead of the farthest one; at the end all are complete.
        XCTAssertGreaterThan(BuildSequence.growth(position: 0.5, step: 0, index: 0, count: count),
                             BuildSequence.growth(position: 0.5, step: 0, index: count - 1, count: count))
        for index in 0..<count { XCTAssertEqual(BuildSequence.growth(position: 1, step: 0, index: index, count: count), 1) }
    }

    func testGrowthIsZeroBeforeAndOneAfterItsStep() {
        XCTAssertEqual(BuildSequence.growth(position: 1, step: 1, index: 0, count: 3), 0)
        XCTAssertEqual(BuildSequence.growth(position: 2, step: 1, index: 2, count: 3), 1)
        XCTAssertEqual(BuildSequence.growth(position: 5, step: 1, index: 0, count: 1), 1)
    }

    func testManifestOverloadHonoursIncludeSet() throws {
        let json = """
        {"items":{"a":{"usd_name":"i_a","kind":"wall","storey":"G","bbox_m":[[0,0,0],[1,2,1]]},
                  "b":{"usd_name":"i_b","kind":"door","storey":"G","bbox_m":[[0,0,0],[1,2,1]]}},
         "storeys":[{"name":"G","elevation_m":0}]}
        """
        let manifest = try JSONDecoder().decode(SceneManifest.self, from: Data(json.utf8))
        XCTAssertEqual(Set(BuildSequence.make(manifest: manifest).steps.flatMap(\.usdNames)), ["i_a", "i_b"])
        XCTAssertEqual(BuildSequence.make(manifest: manifest, include: ["a"]).steps.flatMap(\.usdNames), ["i_a"])
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
        XCTAssertGreaterThan(seq.steps.flatMap(\.usdNames).count, 500)
        XCTAssertFalse(seq.isRaster)
        // Golden list from the web `buildSteps` on the same scene.json (label | item count).
        let web = ["Keller slab|18", "Keller walls|24", "Keller stairs|1", "Keller doors and windows|136",
                   "Erdgeschoss slab|19", "Erdgeschoss columns and beams|2", "Erdgeschoss walls|29",
                   "Erdgeschoss stairs|4", "Erdgeschoss doors and windows|148", "1. Obergeschoss slab|23",
                   "1. Obergeschoss walls|29", "1. Obergeschoss stairs|4", "1. Obergeschoss doors and windows|126",
                   "2. Obergeschoss slab|23", "2. Obergeschoss walls|29", "2. Obergeschoss stairs|4",
                   "2. Obergeschoss doors and windows|126", "Dachgeschoss slab|25", "Dachgeschoss walls|10",
                   "Dachgeschoss stairs|3"]
        XCTAssertEqual(seq.steps.map { "\($0.label)|\($0.usdNames.count)" }, web)
        XCTAssertTrue(seq.steps.contains { $0.label.hasSuffix(" walls") })
        XCTAssertLessThanOrEqual(seq.totalDuration, BuildSequence.totalBudget * 1.3)
    }

    func testBundledRasterSceneMatchesTheWebSteps() throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "scene", withExtension: "json",
                                                           subdirectory: "DemoScenes/cubicasa5k__colorful-11397")
            ?? Bundle.main.url(forResource: "scene", withExtension: "json",
                               subdirectory: "DemoScenes/cubicasa5k__colorful-11397"))
        let manifest = try JSONDecoder().decode(SceneManifest.self, from: Data(contentsOf: url))
        let seq = BuildSequence.make(manifest: manifest)
        XCTAssertTrue(seq.isRaster)
        XCTAssertEqual(seq.steps.map { "\($0.label)|\($0.usdNames.count)" },
                       ["Floor|10", "Walls|40", "Doors and windows|27"])
    }
}
