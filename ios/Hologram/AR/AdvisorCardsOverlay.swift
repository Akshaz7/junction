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

/// The edit's most severe advisor card, anchored above the item it is about, styled like the web card:
/// severity chip, title, body, "Checked" line, source. Sits near the removed door and follows the model.
struct AdvisorCallout: View {
    let card: AdvisorCard?
    let anchor: CGPoint?
    let onDismiss: () -> Void
    let onShow: (AdvisorCard) -> Void

    static func color(_ level: AdvisorCard.Level) -> Color {
        switch level {
        case .violation: return Color(red: 0.70, green: 0.15, blue: 0.12)
        case .suggestion: return Color(red: 0.70, green: 0.42, blue: 0)
        case .info: return Color(red: 0.42, green: 0.42, blue: 0.42)
        }
    }

    static func chipLabel(_ level: AdvisorCard.Level) -> String {
        switch level {
        case .violation: return "Violation"
        case .suggestion: return "Suggestion"
        case .info: return "Info"
        }
    }

    /// "Checked: fi-fire-exits-per-storey, ..." capped so it stays a short line.
    static func checkedLine(_ card: AdvisorCard) -> String? {
        guard let checked = card.checked, !checked.isEmpty else { return nil }
        let shown = checked.prefix(3).joined(separator: ", ")
        return "Checked: " + shown + (checked.count > 3 ? " +\(checked.count - 3) more" : "")
    }

    var body: some View {
        GeometryReader { proxy in
            if let card {
                let tint = Self.color(card.level)
                let width = min(proxy.size.width - 32, 300)
                let x = min(max(anchor?.x ?? proxy.size.width / 2, width / 2 + 16), proxy.size.width - width / 2 - 16)
                // Above the anchor with a short leader; a fixed spot under the top bar when the item is off screen.
                let y = anchor.map { max($0.y - 96, 150) } ?? 190
                VStack(spacing: 0) {
                    VStack(alignment: .leading, spacing: 5) {
                        HStack(spacing: 6) {
                            Text(Self.chipLabel(card.level).uppercased())
                                .font(.system(size: 10, weight: .bold)).tracking(0.4)
                                .padding(.horizontal, 6).padding(.vertical, 2)
                                .background(tint, in: Capsule()).foregroundStyle(.white)
                            Spacer()
                            Button(action: onDismiss) { Image(systemName: "xmark").font(.system(size: 11, weight: .bold)) }
                                .accessibilityIdentifier("advisor-callout-dismiss")
                        }
                        Text(card.title).font(.system(size: 14, weight: .semibold)).fixedSize(horizontal: false, vertical: true)
                        Text(card.body).font(.system(size: 12)).lineLimit(4).fixedSize(horizontal: false, vertical: true)
                        if let line = Self.checkedLine(card) {
                            Text(line).font(.system(size: 10)).foregroundStyle(.secondary).lineLimit(2)
                                .accessibilityIdentifier("advisor-callout-checked")
                        }
                        Text(card.source.title).font(.system(size: 10)).foregroundStyle(.secondary).lineLimit(1)
                    }
                    .padding(10)
                    .frame(width: width, alignment: .leading)
                    .background(
                        RoundedRectangle(cornerRadius: 12).fill(Color(.systemBackground).opacity(0.96))
                            .overlay(alignment: .leading) { Rectangle().fill(tint).frame(width: 4) }
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                    )
                    .shadow(color: .black.opacity(0.18), radius: 8, y: 2)
                    .onTapGesture { onShow(card) }
                    if anchor != nil {
                        Rectangle().fill(tint).frame(width: 2, height: 36)
                        Circle().fill(tint).frame(width: 8, height: 8)
                    }
                }
                .position(x: x, y: y + (anchor != nil ? 70 : 40))
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("advisor-callout")
                .transition(.opacity)
            }
        }
        .allowsHitTesting(card != nil)
        .animation(.easeOut(duration: 0.25), value: card)
    }
}
