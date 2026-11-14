import SwiftUI

struct ARScreen: View {
    var sceneURL: URL? = nil
    @StateObject private var controller = ARSceneController()
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            ARSceneView(controller: controller).ignoresSafeArea()
            VStack(spacing: 16) {
                HStack {
                    Text("Show on table").font(.headline)
                    Spacer()
                    Button("Done") { dismiss() }
                }
                .padding().background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
                Spacer()
                VStack(alignment: .leading, spacing: 12) {
                    if controller.isFixture {
                        Text("Sample model · generated for demo")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    Text(controller.status).font(.callout)
                        .accessibilityIdentifier("ar-status")
                    HStack {
                        Text("Scale")
                        Spacer()
                        Text(controller.scaleLabel).monospacedDigit()
                    }
                    Slider(value: Binding(
                        get: { log10(Double(controller.scale)) },
                        set: { controller.setScale(Float(pow(10, $0))) }
                    ), in: -2...0)
                    .accessibilityLabel("Model scale")
                    .accessibilityValue(controller.scaleLabel)
                    .disabled(!controller.isLoaded)
                    HStack {
                        Text("1:100")
                        Spacer()
                        Text("1:1")
                    }.font(.caption).foregroundStyle(.secondary)
                    Button("Reset placement", systemImage: "arrow.counterclockwise") { controller.reset() }
                        .disabled(!controller.isPlaced)
                }
                .padding().background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
            }.padding()
        }
        .task { await controller.load(url: sceneURL) }
    }
}
