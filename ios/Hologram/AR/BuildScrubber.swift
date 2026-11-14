import SwiftUI

/// Compact step scrubber for the AR build-up, styled like the web BuildSlider: previous, play/pause/replay, next,
/// a slider with one stop per step and "Step 4 of 12 · Erdgeschoss walls". Never moves the camera or the model.
struct BuildScrubber: View {
    let state: BuildState
    var onPrevious: () -> Void
    var onToggle: () -> Void
    var onNext: () -> Void
    var onSelect: (Int) -> Void

    private var toggleTitle: String { state.playing ? "Pause" : state.finished ? "Replay" : "Play" }
    private var toggleIcon: String { state.playing ? "pause.fill" : state.finished ? "arrow.counterclockwise" : "play.fill" }

    var body: some View {
        HologramCardPill {
            VStack(spacing: 2) {
                Text(state.text)
                    .font(HologramStyle.caption)
                    .lineLimit(1).minimumScaleFactor(0.8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityIdentifier("build-step-label")
                HStack(spacing: 2) {
                    control("chevron.left", "Previous step", id: "build-prev", disabled: state.index <= 1,
                            action: onPrevious)
                    control(toggleIcon, "\(toggleTitle) build-up", id: "build-play", disabled: false, action: onToggle)
                    control("chevron.right", "Next step", id: "build-next", disabled: state.index >= state.total,
                            action: onNext)
                    if state.total > 1 {
                        Slider(value: Binding(get: { Double(state.index) },
                                              set: { onSelect(Int($0.rounded())) }),
                               in: 1...Double(state.total), step: 1)
                            .tint(HologramStyle.barkColor)
                            .accessibilityLabel("Build step")
                            .accessibilityValue(state.text)
                            .accessibilityIdentifier("build-slider")
                    } else {
                        Spacer()
                    }
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("build-scrubber")
    }

    private func control(_ icon: String, _ label: String, id: String, disabled: Bool,
                         action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: icon).font(.system(size: 14, weight: .semibold))
                .frame(width: 44, height: 36)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .foregroundStyle(HologramStyle.inkColor.opacity(disabled ? 0.3 : 1))
        .disabled(disabled)
        .accessibilityLabel(label)
        .accessibilityIdentifier(id)
    }
}
