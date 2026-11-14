import RealityKit

/// Resolves mesh children using the manifest's actual USD names, not guessed hashes.
@MainActor
struct ItemPicker {
    private let itemIDsByUSDName: [String: String]

    init(manifest: SceneManifest) {
        var names: [String: String] = [:]
        for itemID in manifest.items.keys.sorted() {
            if let name = manifest.items[itemID]?.usd_name, !name.isEmpty {
                names[name] = itemID
            }
        }
        itemIDsByUSDName = names
    }

    func itemID(for entity: Entity) -> String? {
        var candidate: Entity? = entity
        while let current = candidate {
            if let itemID = itemIDsByUSDName[current.name] { return itemID }
            candidate = current.parent
        }
        return nil
    }
}
