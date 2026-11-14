import SwiftUI

struct ARScreen: View {
    var sceneURL: URL? = nil
    var manifestURL: URL? = nil
    var highlightedItemIDs: [String] = []
    var cameraTargetItemID: String? = nil
    @StateObject private var controller = ARSceneController()
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            ARSceneView(controller: controller).ignoresSafeArea()
            VStack(spacing: 16) {
                HStack {
                    Text(controller.isWalking ? "Walk at 1:1" : "Show on table").font(.headline)
                    Spacer()
                    Button("Done") { dismiss() }
                }
                .padding().background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
                if controller.isWalking {
                    HStack {
                        if let manifest = controller.manifest {
                            WalkMiniMap(manifest: manifest, cameraTransform: controller.cameraInModel,
                                        highlightedItemIDs: controller.highlightedItemIDs,
                                        guide: controller.guide, targetItemID: controller.targetItemID,
                                        onSelectItem: controller.selectTarget)
                        } else {
                            Text("Scene map unavailable.").font(.caption).padding()
                                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
                        }
                        Spacer()
                    }
                }
                Spacer()
                VStack(alignment: .leading, spacing: 12) {
                    if controller.isFixture {
                        Text("Sample model · generated for demo")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    Text(controller.status).font(.callout)
                        .accessibilityIdentifier("ar-status")
                    Toggle("Walk", isOn: Binding(get: { controller.isWalking },
                                                 set: { controller.setWalking($0) }))
                        .disabled(!controller.isLoaded)
                        .accessibilityIdentifier("walk-toggle")
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
                    .disabled(!controller.isLoaded || controller.isWalking)
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
        .task {
            await controller.load(url: sceneURL, manifestURL: manifestURL,
                                  itemIDs: highlightedItemIDs, cameraTargetItemID: cameraTargetItemID)
        }
        .onChange(of: highlightedItemIDs) { _, items in
            controller.setHighlights(items, cameraTargetItemID: cameraTargetItemID)
        }
        .onChange(of: cameraTargetItemID) { _, target in
            controller.setHighlights(highlightedItemIDs, cameraTargetItemID: target)
        }
    }
}
