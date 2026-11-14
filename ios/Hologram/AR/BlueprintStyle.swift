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

    private static func hex(_ value: UInt32) -> UIColor {
        UIColor(red: CGFloat((value >> 16) & 0xFF) / 255, green: CGFloat((value >> 8) & 0xFF) / 255,
                blue: CGFloat(value & 0xFF) / 255, alpha: 1)
    }

    /// Same colours as the web blueprint layer (web/src/viewer3d/README.md, "Blueprint layer"). Window glass is
    /// 38% opaque; a highlighted window goes through the highlight material, which is opaque. Unknown kinds keep
    /// their own materials (nil).
    static func surface(for kind: String?) -> Surface? {
        switch kind?.lowercased() {
        case "wall": return .init(color: hex(0xD9D4C9), alpha: 1, roughness: 0.92)
        case "slab", "floor": return .init(color: hex(0xE6E2D9), alpha: 1, roughness: 0.95)
        case "roof": return .init(color: hex(0x9A8F86), alpha: 1, roughness: 0.9)
        case "window": return .init(color: hex(0x9FD3EA), alpha: windowGlassOpacity, roughness: 0.1)
        case "door": return .init(color: hex(0x9C6B3C), alpha: 1, roughness: 0.7)
        case "stairs", "stair": return .init(color: hex(0x5F5A54), alpha: 1, roughness: 0.85)
        case "column": return .init(color: hex(0xBDB7AD), alpha: 1, roughness: 0.9)
        case "railing": return .init(color: hex(0x8D99A6), alpha: 1, roughness: 0.85)
        case "furniture": return .init(color: hex(0xB9AD9D), alpha: 1, roughness: 0.8)
        case "toilet", "sink", "shower", "bathtub": return .init(color: hex(0xF4F7F9), alpha: 1, roughness: 0.3)
        default: return nil
        }
    }

    static let windowGlassOpacity: CGFloat = 0.38

    /// Web app text token (HologramStyle.ink) and the light paper colour used for halos and dimension patches.
    static let inkColor = HologramStyle.ink
    static let paperColor = UIColor(red: 0.98, green: 0.97, blue: 0.95, alpha: 1)

    /// Wall colour x 0.42: the cut top reads darker than the wall faces, as on the web.
    static let wallCapColor = UIColor(red: 0.851 * 0.42, green: 0.831 * 0.42, blue: 0.788 * 0.42, alpha: 1)
    static let roomLabelColor = hex(0x1F2937)

    enum RoomType { case wet, kitchen, other }

    /// Floor tint class from props.room_type (raster) or the room name, like the web.
    static func roomType(name: String?) -> RoomType {
        let text = (name ?? "").lowercased()
        let has = { (words: [String]) in words.contains { text.contains($0) } }
        if has(["wc", "toilet", "bath", "shower", "sauna", "laundry", "bad", "dusch", "pesu", "kylpy", "suihku"]) { return .wet }
        if has(["kitchen", "k\u{00FC}che", "kuche", "keitti\u{00F6}", "keittio", "k\u{00F6}k", "pantry"]) { return .kitchen }
        return .other
    }

    static func roomType(_ item: SceneManifest.Item) -> RoomType {
        if let type = item.props?["room_type"].flatMap(propertyText), !type.isEmpty {
            let fromType = roomType(name: type)
            if fromType != .other { return fromType }
        }
        return roomType(name: roomName(item))
    }

    static func roomTint(_ type: RoomType) -> UIColor {
        switch type {
        case .wet: return hex(0xCDE3F3)
        case .kitchen: return hex(0xF4E4C9)
        case .other: return hex(0xF1EEE6)
        }
    }

    /// Room name from the manifest: item name, then props LongName / name. Nil when none.
    static func roomName(_ item: SceneManifest.Item) -> String? {
        var candidates: [String?] = [item.name]
        for key in ["LongName", "long_name", "name", "Name"] {
            candidates.append(item.props?[key].flatMap(propertyText))
        }
        return candidates.compactMap { $0?.trimmingCharacters(in: .whitespacesAndNewlines) }.first { !$0.isEmpty }
    }

    /// Area in m2 from the manifest (props.area_m2). Nil when the data has none: nothing is invented.
    static func roomArea(_ item: SceneManifest.Item) -> Float? {
        for key in ["area_m2", "area", "Area", "NetFloorArea", "GrossFloorArea"] {
            if let text = item.props?[key].flatMap(propertyText), let value = Float(text), value.isFinite, value > 0 {
                return value
            }
        }
        return nil
    }

    static func areaText(_ area: Float) -> String {
        String(format: "%.1f m\u{00B2}", area)
    }

    /// "Kitchen\n12.4 m2". A missing name or area drops that line; neither drops the label (nil).
    static func roomLabel(name: String?, area: Float?) -> String? {
        let lines = [name.flatMap { $0.isEmpty ? nil : $0 }, area.map(areaText)].compactMap { $0 }
        return lines.isEmpty ? nil : lines.joined(separator: "\n")
    }

    /// Rooms whose shorter side is under this get no label.
    static let minLabelSide: Float = 1.2
    static let minFontSize: Float = 0.14

    struct RoomLabelLayout: Equatable {
        let fontSize: Float
        let rotated: Bool
    }

    /// Web rules: hide under 1.2 m; font = clamp(shorter * 0.2, 0.14, 0.9); shrink so width <= 90% of the room side
    /// and height <= 60% of the other side; rotate 90 degrees when the room is more than 1.6x longer in z than in x;
    /// hide when the fitted font is under 0.14. `textPerMetre` is the text extent for a 1 m font.
    static func roomLabelLayout(footprint: SIMD2<Float>, textPerMetre: SIMD2<Float>) -> RoomLabelLayout? {
        let shorter = min(footprint.x, footprint.y)
        guard shorter >= minLabelSide, textPerMetre.x > 0, textPerMetre.y > 0 else { return nil }
        let rotated = footprint.y > 1.6 * footprint.x
        let along = rotated ? footprint.y : footprint.x
        let across = rotated ? footprint.x : footprint.y
        var font = min(max(shorter * 0.2, minFontSize), 0.9)
        let shrink = min(1, 0.9 * along / (textPerMetre.x * font), 0.6 * across / (textPerMetre.y * font))
        font *= shrink
        return font >= minFontSize ? RoomLabelLayout(fontSize: font, rotated: rotated) : nil
    }

    /// Flat rooms (raster plans, bbox height <= 0.3 m) get their label just above the floor; volume rooms
    /// (IFC spaces are opaque boxes) on the top face.
    static func roomLabelHeight(minY: Float, maxY: Float) -> Float {
        maxY - minY <= 0.3 ? minY + 0.05 : maxY + 0.03
    }

    /// Door width for callouts ("0.90 m") from props.width_m; nil for anything else or when absent.
    static func detail(for item: SceneManifest.Item) -> String? {
        guard item.kind?.lowercased() == "door", let text = item.props?["width_m"].flatMap(propertyText),
              let width = Float(text), width.isFinite, width > 0 else { return nil }
        return widthText(width)
    }

    static func dimensionText(_ metres: Float) -> String { String(format: "%.1f m", metres) }

    /// Door callout width keeps two decimals ("0.90 m").
    static func widthText(_ metres: Float) -> String { String(format: "%.2f m", metres) }

    /// "Erdgeschoss \u{00B7} +0.00 m", "Keller \u{00B7} \u{2212}3.00 m" (a real minus sign).
    static func storeyLabel(name: String, elevation: Float) -> String {
        let magnitude = String(format: "%.2f", abs(elevation))
        let sign = elevation < -0.005 ? "\u{2212}" : "+"
        return "\(name) \u{00B7} \(sign)\(magnitude) m"
    }

    /// 0 to 1 label opacity from the angular size of the label as seen from the camera.
    static func labelOpacity(width: Float, distance: Float) -> Float {
        guard distance > 0.01, width > 0 else { return 0 }
        let angular = width / distance
        return min(max((angular - 0.012) / 0.02, 0), 1)
    }

    private static func propertyText(_ property: SceneProperty) -> String? {
        switch property {
        case .string(let text): return text
        case .number(let value): return String(value)
        default: return nil
        }
    }
}
