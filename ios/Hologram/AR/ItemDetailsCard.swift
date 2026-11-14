import SwiftUI

struct ItemCardModel: Identifiable {
    struct Property: Identifiable {
        let name: String
        let value: String
        var id: String { name }
    }

    let id: String
    let name: String
    let kind: String?
    let storey: String?
    let properties: [Property]

    init(itemID: String, item: SceneManifest.Item) {
        id = itemID
        name = item.name.flatMap { $0.isEmpty ? nil : $0 } ?? itemID
        kind = item.kind
        storey = item.storey
        properties = (item.props ?? [:]).sorted { $0.key < $1.key }
            .map { Property(name: $0.key, value: $0.value.displayText) }
    }
}

struct ItemDetailsCard: View {
    let item: ItemCardModel
    let onDismiss: () -> Void
    var onHighlight: (() -> Void)? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(item.name).font(.headline)
                    if item.name != item.id {
                        Text(item.id).font(.caption).foregroundStyle(.secondary)
                    }
                }
                Spacer()
                Button("Dismiss item", systemImage: "xmark", action: onDismiss)
                    .labelStyle(.iconOnly)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    if let kind = item.kind { LabeledContent("Kind", value: kind) }
                    if let storey = item.storey { LabeledContent("Storey", value: storey) }
                    ForEach(item.properties) { property in
                        LabeledContent(property.name, value: property.value)
                    }
                    if item.properties.isEmpty {
                        Text("No additional properties in this scene.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            .frame(maxHeight: 160)
            .fixedSize(horizontal: false, vertical: true)
            if let onHighlight {
                Button("Highlight this", systemImage: "highlighter", action: onHighlight)
                    .accessibilityIdentifier("ar-highlight-item")
            }
        }
        .padding()
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
        .accessibilityIdentifier("ar-item-card")
    }
}
