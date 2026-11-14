import Combine
import SwiftUI

struct AdvisorCardsOverlay: View {
    let cards: [AdvisorCard]
    let onSelect: (AdvisorCard) -> Void

    var body: some View {
        VStack(spacing: 8) {
            ForEach(cards.prefix(3)) { card in
                VStack(alignment: .leading, spacing: 4) {
                    Button { onSelect(card) } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Label(card.title, systemImage: icon(for: card.kind))
                                .font(.subheadline.bold())
                            Text((try? AttributedString(markdown: card.body)) ?? AttributedString(card.body))
                                .font(.caption)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("advisor-card-\(card.id)")
                    .accessibilityHint("Highlights the referenced items and shows their tags")
                    AdvisorSourceDisclosure(card: card)
                }
                .padding(12)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14))
            }
        }
    }

    private func icon(for kind: AdvisorCard.Kind) -> String {
        switch kind {
        case .warning: return "exclamationmark.triangle"
        case .option: return "lightbulb"
        case .info: return "info.circle"
        }
    }
}

private struct AdvisorSourceDisclosure: View {
    let card: AdvisorCard
    @StateObject private var disclosure = AdvisorSourceDisclosureState()

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Button { disclosure.isExpanded.toggle() } label: {
                HStack {
                    Text(card.source.title)
                    Spacer()
                    Image(systemName: disclosure.isExpanded ? "chevron.down" : "chevron.right")
                        .accessibilityHidden(true)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("advisor-source-\(card.id)")
            .accessibilityValue(disclosure.isExpanded ? "Expanded" : "Collapsed")
            if disclosure.isExpanded {
                Text(card.source.quote)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("advisor-source-quote-\(card.id)")
            }
        }
        .font(.caption2)
    }
}

private final class AdvisorSourceDisclosureState: ObservableObject {
    @Published var isExpanded = false
}
