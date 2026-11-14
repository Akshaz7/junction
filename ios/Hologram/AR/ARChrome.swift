import SwiftUI
import UIKit

/// Shared AR style constants. Values mirror web/src/styles/tokens.css so the AR chrome, the 2D drawing
/// overlays and the 3D viewer read as one app: dark-green header, white cards, brand-red numbered badges.
enum HologramStyle {
    // Brand colours (hex from tokens.css).
    static let headerGreen = UIColor(hex: 0x011E01)   // app header
    static let bark = UIColor(hex: 0x152E14)          // --brand-bark / --forest-900, primary button
    static let forest = UIColor(hex: 0x2C412B)        // --brand-forest
    static let brandRed = UIColor(hex: 0x662C23)      // --brand-red, numbered badges
    static let stage = UIColor(hex: 0xF7F7F8)         // --brand-stage-light
    static let border = UIColor(hex: 0xE7E7E7)        // --border
    static let muted = UIColor(hex: 0xA1A1A1)         // --brand-moss
    static let live = UIColor(hex: 0x54BF6E)          // green-500, live / success
    static let ink = UIColor(hex: 0x011E01)           // body text on light surfaces

    static let amber = Color(uiColor: HighlightController.accentColor)
    static let headerColor = Color(uiColor: headerGreen)
    static let barkColor = Color(uiColor: bark)
    static let forestColor = Color(uiColor: forest)
    static let redColor = Color(uiColor: brandRed)
    static let stageColor = Color(uiColor: stage)
    static let borderColor = Color(uiColor: border)
    static let mutedColor = Color(uiColor: muted)
    static let liveColor = Color(uiColor: live)
    static let inkColor = Color(uiColor: ink)

    // Radii (rem * 16): control .5, capsule .625, card .75, composer .875.
    static let radiusControl: CGFloat = 8
    static let radiusCapsule: CGFloat = 10
    static let radiusCard: CGFloat = 12
    static let radiusComposer: CGFloat = 14

    // Type: Inter in the web, SF (system) here; weights 500 / 600, web sizes 14 / 13 / 12.
    static let body = Font.system(size: 14, weight: .medium)
    static let bodySmall = Font.system(size: 13, weight: .medium)
    static let caption = Font.system(size: 12, weight: .semibold)
    static let button = Font.system(size: 15, weight: .semibold)

    /// --shadow-card: hairline ring plus a soft drop.
    static func cardShadow<V: View>(_ view: V) -> some View {
        view.shadow(color: .black.opacity(0.10), radius: 1, y: 1)
            .shadow(color: .black.opacity(0.22), radius: 8, y: 4)
    }
}

extension UIColor {
    convenience init(hex: UInt32, alpha: CGFloat = 1) {
        self.init(red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                  blue: CGFloat(hex & 0xFF) / 255, alpha: alpha)
    }
}

/// Dark-green app-header surface (Done, scene menu): solid, white text, 10 pt radius.
struct HologramCapsule<Content: View>: View {
    var tint: Color = .white
    @ViewBuilder var content: Content

    var body: some View {
        content
            .font(HologramStyle.bodySmall)
            .foregroundStyle(tint)
            .padding(.horizontal, 12).padding(.vertical, 8)
            .background(HologramStyle.headerColor,
                        in: RoundedRectangle(cornerRadius: HologramStyle.radiusCapsule, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: HologramStyle.radiusCapsule, style: .continuous)
                .stroke(.white.opacity(0.14), lineWidth: 1))
            .shadow(color: .black.opacity(0.28), radius: 6, y: 2)
    }
}

/// White card surface for status hints, matching the web card.
struct HologramCardPill<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        HologramStyle.cardShadow(
            content
                .font(HologramStyle.bodySmall)
                .foregroundStyle(HologramStyle.inkColor)
                .padding(.horizontal, 12).padding(.vertical, 8)
                .background(Color.white,
                            in: RoundedRectangle(cornerRadius: HologramStyle.radiusCapsule, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: HologramStyle.radiusCapsule, style: .continuous)
                    .stroke(HologramStyle.borderColor, lineWidth: 1))
        )
    }
}

/// Brand primary button (dark-green fill, white text), as on the web.
struct HologramPrimaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(HologramStyle.button)
            .foregroundStyle(Color.white)
            .padding(.horizontal, 28).frame(height: 48)
            .background(HologramStyle.barkColor.opacity(isEnabled ? (configuration.isPressed ? 0.85 : 1) : 0.55),
                        in: RoundedRectangle(cornerRadius: HologramStyle.radiusCard, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: HologramStyle.radiusCard, style: .continuous)
                .stroke(.white.opacity(isEnabled ? 0.2 : 0.1), lineWidth: 1))
            .shadow(color: .black.opacity(0.3), radius: 8, y: 3)
    }
}

/// Composer-style mic: white circle, dark-green icon, level ring; red while listening.
struct ARMicButton: View {
    @ObservedObject var voice: ARVoiceController
    let docID: String?
    let onAnswer: (VoiceAnswer) -> Void

    var body: some View {
        Button {
            if let docID { voice.toggle(docID: docID, onAnswer: onAnswer) }
        } label: {
            ZStack {
                Circle().fill(voice.isRecording ? HologramStyle.redColor : Color.white)
                Circle().stroke(voice.isRecording ? Color.white.opacity(0.3) : HologramStyle.borderColor, lineWidth: 1)
                Circle()
                    .trim(from: 0, to: voice.isRecording ? max(CGFloat(voice.level), 0.04) : 0)
                    .stroke(Color.white, style: StrokeStyle(lineWidth: 3, lineCap: .round))
                    .padding(3)
                    .rotationEffect(.degrees(-90))
                    .animation(.linear(duration: 0.1), value: voice.level)
                if voice.isBusy {
                    ProgressView().tint(HologramStyle.barkColor)
                } else {
                    Image(systemName: voice.isRecording ? "stop.fill" : "mic.fill")
                        .font(.system(size: 20, weight: .semibold))
                        .foregroundStyle(voice.isRecording ? Color.white : HologramStyle.barkColor)
                }
            }
            .frame(width: 56, height: 56)
            .shadow(color: .black.opacity(0.28), radius: 8, y: 3)
        }
        .disabled(voice.isBusy || docID == nil)
        .accessibilityLabel(voice.isRecording ? "Send voice question" : "Ask by voice")
        .accessibilityIdentifier("ar-voice-mic")
    }
}

/// Transcript and answer as a compact answer card (at most two lines of answer).
struct ARSubtitle: View {
    @ObservedObject var voice: ARVoiceController

    private var visible: Bool {
        voice.isRecording || voice.isBusy || !voice.answerText.isEmpty || !voice.transcript.isEmpty
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            if voice.isRecording {
                HStack(spacing: 6) {
                    Circle().fill(HologramStyle.liveColor).frame(width: 7, height: 7)
                    Text("Listening… \(voice.seconds) / 15 s").font(HologramStyle.caption).monospacedDigit()
                }
            } else if !voice.answerText.isEmpty {
                if !voice.transcript.isEmpty {
                    Text(voice.transcript).font(.system(size: 12, weight: .medium)).lineLimit(1)
                        .foregroundStyle(HologramStyle.mutedColor)
                }
                Text((try? AttributedString(markdown: voice.answerText)) ?? AttributedString(voice.answerText))
                    .font(HologramStyle.body).foregroundStyle(HologramStyle.inkColor)
                    .lineLimit(2).multilineTextAlignment(.leading)
                    .accessibilityIdentifier("ar-voice-answer")
            } else if voice.isBusy || !voice.transcript.isEmpty {
                Text(voice.isBusy ? voice.status : voice.transcript).font(HologramStyle.bodySmall)
                    .foregroundStyle(HologramStyle.inkColor).lineLimit(2)
            }
        }
        .foregroundStyle(HologramStyle.inkColor)
        .frame(maxWidth: 420, alignment: .leading)
        .padding(.horizontal, 14).padding(.vertical, 10)
        .background(Color.white, in: RoundedRectangle(cornerRadius: HologramStyle.radiusCard, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: HologramStyle.radiusCard, style: .continuous)
            .stroke(HologramStyle.borderColor, lineWidth: 1))
        .shadow(color: .black.opacity(0.22), radius: 8, y: 3)
        .opacity(visible ? 1 : 0)
        .animation(.easeInOut(duration: 0.2), value: voice.answerText)
    }
}
