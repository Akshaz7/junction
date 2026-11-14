import UIKit

/// One fixed colour per item kind, copied from web/public/kind-colors.json (Okabe-Ito, colour-blind safe)
/// so 2D boxes, 3D highlights and AR use the same colour for the same kind. KindColorsTests keeps them equal.
struct KindStyle: Equatable {
    let key: String
    let color: UIColor
    let on: UIColor
    let label: String
    let plural: String
}

enum KindColors {
    static let keys = ["door", "window", "wall", "room", "toilet", "sink", "shower", "bathtub", "stairs", "pipe", "drain", "fitting", "other"]

    private static let table: [String: (color: UInt32, on: UInt32, label: String, plural: String)] = [
        "door": (0xD55E00, 0xFFFFFF, "Door", "Doors"),
        "window": (0x0072B2, 0xFFFFFF, "Window", "Windows"),
        "wall": (0xE69F00, 0x1A1A1A, "Wall", "Walls"),
        "room": (0x009E73, 0xFFFFFF, "Room", "Rooms"),
        "toilet": (0xCC79A7, 0x1A1A1A, "Toilet", "Toilets"),
        "sink": (0x56B4E9, 0x1A1A1A, "Sink", "Sinks"),
        "shower": (0xF0E442, 0x1A1A1A, "Shower", "Showers"),
        "bathtub": (0x882255, 0xFFFFFF, "Bathtub", "Bathtubs"),
        "stairs": (0x999933, 0xFFFFFF, "Stairs", "Stairs"),
        "pipe": (0x332288, 0xFFFFFF, "Pipe", "Pipes"),
        "drain": (0x8C510A, 0xFFFFFF, "Drain", "Drains"),
        "fitting": (0xB2182B, 0xFFFFFF, "Fitting", "Fittings"),
        "other": (0x7F7F7F, 0xFFFFFF, "Other", "Other"),
    ]
    private static let aliases = ["curtain_wall": "wall", "stair": "stairs", "stairflight": "stairs",
                                  "stair_flight": "stairs", "sanitary": "toilet", "wc": "toilet",
                                  "pipe_segment": "pipe", "pipesegment": "pipe", "pipe_fitting": "fitting",
                                  "pipefitting": "fitting", "valve": "fitting", "valve_damper": "fitting"]

    /// Same mapping as the web `kindKey`: anything unknown is "other".
    static func key(for kind: String?) -> String {
        let k = (kind ?? "").lowercased()
        if keys.contains(k) { return k }
        return aliases[k] ?? "other"
    }

    static func style(for kind: String?) -> KindStyle {
        let key = key(for: kind)
        let row = table[key]!
        return KindStyle(key: key, color: UIColor(hex: row.color), on: UIColor(hex: row.on),
                         label: row.label, plural: row.plural)
    }

    /// "Doors 11 · Windows 11" legend rows in first-seen order.
    static func counts(of kinds: [String?]) -> [(style: KindStyle, count: Int)] {
        var order: [String] = []
        var counts: [String: Int] = [:]
        for kind in kinds {
            let key = key(for: kind)
            if counts[key] == nil { order.append(key) }
            counts[key, default: 0] += 1
        }
        return order.map { (style(for: $0), counts[$0]!) }
    }
}
