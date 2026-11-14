import RealityKit
import XCTest
@testable import Hologram

final class SceneIndexTests: XCTestCase {
    @MainActor
    func testFixtureContainsWindowByContractUSDName() async throws {
        let bundle = Bundle(for: Self.self)
        let fixtureURL = try XCTUnwrap(bundle.url(forResource: "fixture", withExtension: "usdz"))
        let root = try await Entity(contentsOf: fixtureURL)
        let index = SceneIndex(root: root)
        let usdName = SceneIndex.usdName(for: "window-001")
        let window = try XCTUnwrap(index.entitiesByUSDName[usdName])
        XCTAssertEqual(window.name, usdName)
        XCTAssertTrue(index.entity(for: "window-001") === window)
    }

    @MainActor
    func testUSDNameMatchesFixtureManifest() throws {
        struct Manifest: Decodable {
            struct Item: Decodable { let usd_name: String }
            let items: [String: Item]
        }
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "fixture.scene", withExtension: "json"))
        let manifest = try JSONDecoder().decode(Manifest.self, from: Data(contentsOf: url))
        let window = try XCTUnwrap(manifest.items["window-001"])
        XCTAssertEqual(SceneIndex.usdName(for: "window-001"), window.usd_name)
        for (itemID, item) in manifest.items {
            XCTAssertEqual(SceneIndex.usdName(for: itemID), item.usd_name)
        }
    }
}
