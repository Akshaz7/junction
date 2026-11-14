import RealityKit
import UIKit

/// A floating 3D billboard callout for a tapped item: name, kind/storey and a few properties,
/// joined to the item by a thin leader line. Replaces the flat SwiftUI details card in AR.
@MainActor
enum HologramCallout {
    static let grey = UIColor(white: 0.78, alpha: 1)

    static func lines(for item: ItemCardModel) -> (title: String, details: String) {
        func clip(_ text: String, _ limit: Int = 30) -> String {
            text.count > limit ? String(text.prefix(limit - 1)) + "…" : text
        }
        var rows: [String] = []
        let meta = [item.kind, item.storey].compactMap { $0 }.filter { !$0.isEmpty }
        if !meta.isEmpty { rows.append(clip(meta.joined(separator: " · "))) }
        for property in item.properties.prefix(3) { rows.append(clip("\(property.name): \(property.value)")) }
        if rows.isEmpty { rows.append("No extra properties") }
        return (clip(item.name, 26), rows.joined(separator: "\n"))
    }

    /// `anchor` is the top centre of the item in `root` coordinates.
    static func make(item: ItemCardModel, anchor: SIMD3<Float>, unit: Float, scale: Float) -> Entity {
        let content = lines(for: item)
        let titleMesh = MeshResource.generateText(content.title, extrusionDepth: unit * 0.01,
                                                  font: .boldSystemFont(ofSize: CGFloat(unit * 0.6)))
        let detailMesh = MeshResource.generateText(content.details, extrusionDepth: unit * 0.01,
                                                   font: .systemFont(ofSize: CGFloat(unit * 0.42)),
                                                   containerFrame: .zero, alignment: .left,
                                                   lineBreakMode: .byClipping)
        let title = ModelEntity(mesh: titleMesh, materials: [UnlitMaterial(color: .white)])
        let details = ModelEntity(mesh: detailMesh, materials: [UnlitMaterial(color: grey)])
        let tb = title.visualBounds(relativeTo: title)
        let db = details.visualBounds(relativeTo: details)

        let pad = unit * 0.35
        let gap = unit * 0.25
        let width = max(tb.extents.x, db.extents.x) + pad * 2
        let height = tb.extents.y + gap + db.extents.y + pad * 2

        var fill = UnlitMaterial(color: UIColor(white: 0.04, alpha: 1))
        fill.blending = .transparent(opacity: .init(floatLiteral: 0.72))
        var edge = UnlitMaterial(color: grey)
        edge.blending = .transparent(opacity: .init(floatLiteral: 0.35))
        let border = unit * 0.04
        let edgePlane = ModelEntity(mesh: .generatePlane(width: width + border * 2, height: height + border * 2,
                                                         cornerRadius: pad * 0.6), materials: [edge])
        let fillPlane = ModelEntity(mesh: .generatePlane(width: width, height: height, cornerRadius: pad * 0.5),
                                    materials: [fill])
        edgePlane.position.z = -unit * 0.004
        title.position = [-width / 2 + pad - tb.min.x, height / 2 - pad - tb.max.y, unit * 0.01]
        details.position = [-width / 2 + pad - db.min.x,
                            height / 2 - pad - tb.extents.y - gap - db.max.y, unit * 0.01]

        let card = Entity()
        card.name = "item-callout-card"
        card.components.set(BillboardComponent())
        for part in [edgePlane, fillPlane, title, details] { card.addChild(part) }

        let rise = unit * 3
        let side = width / 2 + unit * 0.6
        card.position = [side, rise + height / 2, 0]
        card.scale = SIMD3(repeating: scale)
        card.position = [side * scale, (rise + height / 2) * scale, 0]

        // Leader from the item to the card's lower edge.
        let end = SIMD3<Float>(side * scale, rise * scale, 0)
        let length = max(simd_length(end), 0.001)
        let thickness = max(unit * 0.03, 0.002)
        let leader = ModelEntity(mesh: .generateBox(size: [thickness, length, thickness]),
                                 materials: [UnlitMaterial(color: grey)])
        leader.position = end / 2
        leader.orientation = simd_quatf(from: [0, 1, 0], to: end / length)
        let dot = ModelEntity(mesh: .generateSphere(radius: unit * 0.1),
                              materials: [UnlitMaterial(color: .white)])

        let container = Entity()
        container.name = "item-callout"
        container.position = anchor
        for part in [card, leader, dot] { container.addChild(part) }
        return container
    }
}
