import SwiftUI

/// Small pieces of AR chrome: dark capsules with a cyan hairline, a glowing mic with a level ring,
/// and a movie-style subtitle line. Nothing here is a card.
enum HologramStyle {
    static let cyan = Color(uiColor: HighlightController.hologramColor)
    static let amber = Color(uiColor: HighlightController.accentColor)
}

struct HologramCapsule<Content: View>: View {
    var tint: Color = HologramStyle.cyan
    @ViewBuilder var content: Content

    var body: some View {
        content
            .font(.footnote.weight(.semibold))
            .foregroundStyle(tint)
            .padding(.horizontal, 14).padding(.vertical, 8)
            .background(.black.opacity(0.55), in: Capsule())
            .overlay(Capsule().stroke(tint.opacity(0.55), lineWidth: 1))
    }
}

struct ARMicButton: View {
    @ObservedObject var voice: ARVoiceController
    let docID: String?
    let onAnswer: (VoiceAnswer) -> Void

    var body: some View {
        Button {
            if let docID { voice.toggle(docID: docID, onAnswer: onAnswer) }
        } label: {
            ZStack {
                Circle().fill(.black.opacity(0.6))
                Circle().stroke(HologramStyle.cyan.opacity(0.35), lineWidth: 2)
                Circle()
                    .trim(from: 0, to: voice.isRecording ? max(CGFloat(voice.level), 0.04) : 0)
                    .stroke(HologramStyle.cyan, style: StrokeStyle(lineWidth: 3, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                    .animation(.linear(duration: 0.1), value: voice.level)
                if voice.isBusy {
                    ProgressView().tint(HologramStyle.cyan)
                } else {
                    Image(systemName: voice.isRecording ? "stop.fill" : "mic.fill")
                        .font(.title3.weight(.semibold))
                        .foregroundStyle(voice.isRecording ? HologramStyle.amber : HologramStyle.cyan)
                }
            }
            .frame(width: 56, height: 56)
            .shadow(color: HologramStyle.cyan.opacity(voice.isRecording ? 0.9 : 0.5), radius: 10)
        }
        .disabled(voice.isBusy || docID == nil)
        .accessibilityLabel(voice.isRecording ? "Send voice question" : "Ask by voice")
        .accessibilityIdentifier("ar-voice-mic")
    }
}

/// Transcript and answer as a short subtitle (at most two lines each), never a card.
struct ARSubtitle: View {
    @ObservedObject var voice: ARVoiceController

    var body: some View {
        VStack(spacing: 4) {
            if voice.isRecording {
                Text("Listening… \(voice.seconds) / 15 s").font(.caption.monospacedDigit())
                    .foregroundStyle(HologramStyle.cyan)
            } else if !voice.answerText.isEmpty {
                if !voice.transcript.isEmpty {
                    Text(voice.transcript).font(.caption2).lineLimit(1)
                        .foregroundStyle(HologramStyle.cyan.opacity(0.85))
                }
                Text((try? AttributedString(markdown: voice.answerText)) ?? AttributedString(voice.answerText))
                    .font(.callout.weight(.medium)).foregroundStyle(.white)
                    .lineLimit(2).multilineTextAlignment(.center)
                    .accessibilityIdentifier("ar-voice-answer")
            } else if voice.isBusy || !voice.transcript.isEmpty {
                Text(voice.isBusy ? voice.status : voice.transcript).font(.caption)
                    .foregroundStyle(HologramStyle.cyan).lineLimit(2).multilineTextAlignment(.center)
            }
        }
        .padding(.horizontal, 12).padding(.vertical, 6)
        .background(.black.opacity(0.5), in: RoundedRectangle(cornerRadius: 10))
        .shadow(color: .black.opacity(0.6), radius: 4)
        .opacity(voice.isRecording || voice.isBusy || !voice.answerText.isEmpty || !voice.transcript.isEmpty ? 1 : 0)
        .animation(.easeInOut(duration: 0.2), value: voice.answerText)
    }
}
