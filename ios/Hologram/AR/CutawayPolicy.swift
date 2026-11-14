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

    /// Site terrain and room volumes (IfcSite / IfcSpace) are hidden on the table: they bury the model
    /// under a slab and coloured boxes. Rooms are never drawn as volumes, not even when highlighted: the floor tint
    /// plate (BlueprintDetail.roomPlates) carries the highlight instead. `keep` is accepted for other kinds.
    func hiddenUSDNames(activeStorey: String?, showRoof: Bool, keep: Set<String> = []) -> Set<String> {
        let sortedStoreys = storeys
        let activeElevation = sortedStoreys.first { $0.name == activeStorey }?.elevation_m
        var elevations: [String: Float] = [:]
        for storey in sortedStoreys { if let name = storey.name, let e = storey.elevation_m, elevations[name] == nil { elevations[name] = e } }
        var hidden: Set<String> = []
        for (id, item) in manifest.items {
            let kind = item.kind?.lowercased() ?? ""
            if kind == "site" || kind == "ifcsite" || kind == "room" || kind == "space" || kind == "ifcspace" {
                hidden.insert(item.usd_name)
                continue
            }
            // The explicit roof toggle also reveals roofs assigned to a higher storey.
            if isRoof(item) {
                if !showRoof { hidden.insert(item.usd_name) }
            } else if let activeElevation,
                      let elevation = item.storey.flatMap({ elevations[$0] }),
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
