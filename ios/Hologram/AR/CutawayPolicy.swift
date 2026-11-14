import Foundation

/// Cutaway decisions use only manifest metadata, independent of AR placement and scale.
struct CutawayPolicy {
    let manifest: SceneManifest

    var storeys: [SceneManifest.Storey] {
        (manifest.storeys ?? []).filter {
            guard let name = $0.name, !name.isEmpty, let elevation = $0.elevation_m else { return false }
            return elevation.isFinite
        }.sorted {
            if $0.elevation_m == $1.elevation_m { return $0.name! < $1.name! }
            return $0.elevation_m! < $1.elevation_m!
        }
    }

    func activeStorey(cameraTargetItemID: String? = nil, highlightedItemIDs: [String] = []) -> String? {
        let candidates = [cameraTargetItemID].compactMap { $0 } + highlightedItemIDs
        for id in candidates {
            if let name = manifest.items[id]?.storey, storeys.contains(where: { $0.name == name }) {
                return name
            }
        }
        return (storeys.first { $0.elevation_m! >= 0 } ?? storeys.first)?.name
    }

    func hiddenUSDNames(activeStorey: String?, showRoof: Bool) -> Set<String> {
        let activeElevation = storeys.first { $0.name == activeStorey }?.elevation_m
        var hidden: Set<String> = []
        for item in manifest.items.values {
            // The explicit roof toggle also reveals roofs assigned to a higher storey.
            if isRoof(item) {
                if !showRoof { hidden.insert(item.usd_name) }
            } else if let activeElevation,
                      let elevation = storeys.first(where: { $0.name == item.storey })?.elevation_m,
                      elevation > activeElevation {
                hidden.insert(item.usd_name)
            }
        }
        return hidden
    }

    private func isRoof(_ item: SceneManifest.Item) -> Bool {
        let kind = item.kind?.lowercased() ?? ""
        if kind == "roof" || kind == "ifcroof" { return true }
        let metadata = (item.props ?? [:]).values.map(\.displayText).joined(separator: " ").lowercased()
        return (kind.contains("covering") || metadata.contains("ifccovering"))
            && (kind.contains("roof") || metadata.contains("roof"))
    }
}
