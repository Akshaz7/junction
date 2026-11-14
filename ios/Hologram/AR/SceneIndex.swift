import CryptoKit
import Foundation
import RealityKit

/// Maps the USD prim names shared by scene.json and the USDZ to loaded entities.
@MainActor
struct SceneIndex {
    let entitiesByUSDName: [String: Entity]

    init(root: Entity) {
        var entities: [String: Entity] = [:]
        func visit(_ entity: Entity) {
            if !entity.name.isEmpty {
                entities[entity.name] = entity
            }
            for child in entity.children {
                visit(child)
            }
        }
        visit(root)
        entitiesByUSDName = entities
    }

    static func usdName(for itemId: String) -> String {
        let digest = Insecure.SHA1.hash(data: Data(itemId.utf8))
        let prefix = digest.prefix(8).map { String(format: "%02x", $0) }.joined()
        return "i_" + prefix
    }

    func entity(for itemId: String) -> Entity? {
        entitiesByUSDName[Self.usdName(for: itemId)]
    }
}
