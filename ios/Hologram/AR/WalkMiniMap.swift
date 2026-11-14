import SwiftUI
import simd

struct WalkMiniMap: View {
    let manifest: SceneManifest
    let cameraTransform: simd_float4x4?
    let highlightedItemIDs: [String]
    let guide: WalkGuide?
    let targetItemID: String?
    let onSelectItem: (String) -> Void

    private let accent = Color(uiColor: HighlightController.accentColor)

    private var cameraPosition: SIMD3<Float>? {
        cameraTransform.map { SIMD3($0.columns.3.x, $0.columns.3.y, $0.columns.3.z) }
    }

    private var mapBounds: SceneBounds? {
        guard let bounds = manifest.bounds else { return nil }
        guard let cameraPosition else { return bounds }
        // Keep the real camera dot visible when the user is outside the footprint.
        return bounds.union(SceneBounds(minimum: cameraPosition, maximum: cameraPosition))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("You are here", systemImage: "location.fill").font(.caption.bold())
            if let bounds = mapBounds {
                Canvas { context, size in
                    let rect = CGRect(origin: .zero, size: size).insetBy(dx: 12, dy: 12)
                    for id in manifest.items.keys.sorted() {
                        guard let item = manifest.items[id]?.bbox_m else { continue }
                        let first = WalkGuide.project(item.minimum, bounds: bounds, into: rect)
                        let last = WalkGuide.project(item.maximum, bounds: bounds, into: rect)
                        let box = CGRect(x: first.x, y: first.y,
                                         width: max(last.x - first.x, 1), height: max(last.y - first.y, 1))
                        let selected = highlightedItemIDs.contains(id) || targetItemID == id
                        let path = Path(box)
                        context.fill(path, with: .color(selected ? accent.opacity(0.65) : .secondary.opacity(0.15)))
                        context.stroke(path, with: .color(selected ? accent : .secondary.opacity(0.4)), lineWidth: 1)
                    }
                    if let cameraPosition {
                        let dot = WalkGuide.project(cameraPosition, bounds: bounds, into: rect)
                        let circle = Path(ellipseIn: CGRect(x: dot.x - 5, y: dot.y - 5, width: 10, height: 10))
                        context.fill(circle, with: .color(.blue))
                        context.stroke(circle, with: .color(.white), lineWidth: 2)
                    }
                }
                .frame(width: 164, height: 140)
                .background(.background.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
                .contentShape(Rectangle())
                .gesture(SpatialTapGesture().onEnded { event in
                    selectItem(at: event.location, bounds: bounds)
                })
                .accessibilityLabel("Scene map. Blue dot is your position. Highlighted items are red.")
            } else {
                Text("Scene map unavailable.").font(.caption)
            }
            if let guide {
                HStack(spacing: 10) {
                    Image(systemName: guide.arrived ? "checkmark.circle.fill" : "arrow.up")
                        .font(.title2.bold())
                        .rotationEffect(.degrees(guide.arrived ? 0 : Double(guide.bearingDegrees)))
                        .foregroundStyle(accent)
                        .frame(width: 32, height: 32)
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(guide.arrived ? "Arrived" : "\(guide.horizontalDistance, specifier: "%.1f") m")
                            .font(.callout.bold()).monospacedDigit()
                        if let targetItemID {
                            Text(targetItemID).font(.caption2).lineLimit(1).truncationMode(.middle)
                        }
                    }
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("\(guide.arrived ? "Arrived. " : "")\(guide.horizontalDistance, specifier: "%.1f") metres, \(guide.bearingDegrees, specifier: "%.0f") degrees relative to your heading")
            } else {
                Text(cameraPosition == nil ? "Place on the floor to locate yourself." : "Tap an item to guide you.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .frame(width: 164, alignment: .leading)
        .padding(12)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
        .accessibilityIdentifier("walk-mini-map")
    }

    private func selectItem(at point: CGPoint, bounds: SceneBounds) {
        let rect = CGRect(x: 12, y: 12, width: 140, height: 116)
        // Prefer the smallest overlapping bbox so windows/doors win over room boxes.
        let hits = manifest.items.compactMap { id, item -> (String, CGFloat)? in
            guard let box = item.bbox_m else { return nil }
            let first = WalkGuide.project(box.minimum, bounds: bounds, into: rect)
            let last = WalkGuide.project(box.maximum, bounds: bounds, into: rect)
            let projected = CGRect(x: first.x, y: first.y, width: max(last.x - first.x, 1),
                                   height: max(last.y - first.y, 1))
            return projected.insetBy(dx: -5, dy: -5).contains(point)
                ? (id, projected.width * projected.height) : nil
        }
        if let hit = hits.sorted(by: { $0.1 == $1.1 ? $0.0 < $1.0 : $0.1 < $1.1 }).first {
            onSelectItem(hit.0)
        }
    }
}
