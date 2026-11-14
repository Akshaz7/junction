import Foundation
import simd
import UIKit

/// Pure rules for the blueprint-style detail: element colours, room tints, labels and dimension text.
/// Generated for demo from the manifest; no values are invented (areas come from the room footprint box
/// unless the manifest carries an area).
enum BlueprintStyle {
    struct Surface: Equatable {
        let color: UIColor
        let alpha: CGFloat
        let roughness: Float
    }

    /// Light warm walls, wood doors, glass windows, dark stairs, neutral furniture. Unknown kinds keep their
    /// own materials (nil).
    static func surface(for kind: String?) -> Surface? {
        switch kind?.lowercased() {
        case "wall": return .init(color: UIColor(red: 0.87, green: 0.84, blue: 0.79, alpha: 1), alpha: 1, roughness: 0.92)
        case "slab", "floor": return .init(color: UIColor(red: 0.78, green: 0.78, blue: 0.76, alpha: 1), alpha: 1, roughness: 0.95)
        case "window": return .init(color: UIColor(red: 0.52, green: 0.74, blue: 0.93, alpha: 1), alpha: 0.42, roughness: 0.1)
        case "door": return .init(color: UIColor(red: 0.62, green: 0.43, blue: 0.26, alpha: 1), alpha: 1, roughness: 0.7)
        case "stairs", "stair", "railing": return .init(color: UIColor(red: 0.32, green: 0.33, blue: 0.36, alpha: 1), alpha: 1, roughness: 0.85)
        case "column": return .init(color: UIColor(red: 0.72, green: 0.70, blue: 0.67, alpha: 1), alpha: 1, roughness: 0.9)
        case "furniture": return .init(color: UIColor(red: 0.91, green: 0.91, blue: 0.89, alpha: 1), alpha: 1, roughness: 0.8)
        default: return nil
        }
    }

    static let wallCapColor = UIColor(red: 0.20, green: 0.19, blue: 0.18, alpha: 1)

    enum RoomType { case wet, circulation, work, other }

    static func roomType(name: String?) -> RoomType {
        let text = (name ?? "").lowercased()
        let has = { (words: [String]) in words.contains { text.contains($0) } }
        if has(["bath", "wc", "toilet", "shower", "sauna", "laundry", "wash", "kylpy", "vessa", "pesu"]) { return .wet }
        if has(["corridor", "hall", "lobby", "entry", "stair", "foyer", "vestibule", "eteinen", "kaytava"]) { return .circulation }
        if has(["office", "work", "meeting", "studio", "toimisto"]) { return .work }
        return .other
    }

    static func roomTint(_ type: RoomType) -> UIColor {
        switch type {
        case .wet: return UIColor(red: 0.62, green: 0.78, blue: 0.92, alpha: 1)
        case .circulation: return UIColor(red: 0.82, green: 0.82, blue: 0.82, alpha: 1)
        case .work: return UIColor(red: 0.95, green: 0.84, blue: 0.66, alpha: 1)
        case .other: return UIColor(red: 0.93, green: 0.90, blue: 0.84, alpha: 1)
        }
    }

    /// Room name from the manifest: name, then props LongName / name / room_type / type. Nil when none.
    static func roomName(_ item: SceneManifest.Item) -> String? {
        var candidates: [String?] = [item.name]
        for key in ["LongName", "long_name", "name", "Name", "room_type", "type"] {
            candidates.append(item.props?[key].flatMap(propertyText))
        }
        return candidates.compactMap { $0?.trimmingCharacters(in: .whitespacesAndNewlines) }.first { !$0.isEmpty }
    }

    /// Area in m2: manifest props (area_m2 / area) if numeric, otherwise the footprint box.
    static func roomArea(_ item: SceneManifest.Item, footprint: SIMD2<Float>) -> Float {
        for key in ["area_m2", "area", "Area", "NetFloorArea", "GrossFloorArea"] {
            if let text = item.props?[key].flatMap(propertyText), let value = Float(text), value.isFinite, value > 0 {
                return value
            }
        }
        return footprint.x * footprint.y
    }

    static func areaText(_ area: Float) -> String {
        String(format: "%.1f m\u{00B2}", area)
    }

    /// "Kitchen\n12.4 m2" or just the area when the room has no name.
    static func roomLabel(name: String?, area: Float) -> String {
        guard let name, !name.isEmpty else { return areaText(area) }
        return "\(name)\n\(areaText(area))"
    }

    /// Rooms smaller than this get no label: it would be unreadable on a table-sized model.
    static let minLabelledArea: Float = 3.0

    static func dimensionText(_ metres: Float) -> String { String(format: "%.2f m", metres) }

    /// "Erdgeschoss · ±0.00", "Keller · -3.00", "1. Obergeschoss · +3.00".
    static func storeyLabel(name: String, elevation: Float) -> String {
        let value = abs(elevation) < 0.005 ? "\u{00B1}0.00" : String(format: "%+.2f", elevation)
        return "\(name) \u{00B7} \(value)"
    }

    /// 0 to 1 label opacity from the angular size of the label as seen from the camera.
    static func labelOpacity(width: Float, distance: Float) -> Float {
        guard distance > 0.01, width > 0 else { return 0 }
        let angular = width / distance
        return min(max((angular - 0.09) / 0.05, 0), 1)
    }

    private static func propertyText(_ property: SceneProperty) -> String? {
        switch property {
        case .string(let text): return text
        case .number(let value): return String(value)
        default: return nil
        }
    }
}
