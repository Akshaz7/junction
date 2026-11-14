import SwiftUI

struct ARScreen: View {
    var docID: String? = nil
    var sceneURL: URL? = nil
    var manifestURL: URL? = nil
    var highlightedItemIDs: [String] = []
    var cameraTargetItemID: String? = nil
    @StateObject private var controller = ARSceneController()
    @StateObject private var liveSocket = LiveSocket()
    @StateObject private var voice = ARVoiceController()
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.dismiss) private var dismiss

    private var requestedDocID: String? { controller.demoDocID ?? docID }

    var body: some View {
        #if targetEnvironment(simulator)
        SimulatorScenePanel(docID: docID ?? "fixture__ios", manifestURL: manifestURL,
                            highlightedItemIDs: highlightedItemIDs)
        #else
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
                if let item = controller.selectedItem {
                    ItemDetailsCard(item: item, onDismiss: controller.dismissSelectedItem,
                                    onHighlight: { highlightItem(item.id) })
                }
                ARVoicePanel(voice: voice, docID: controller.activeDocID) { answer in
                    controller.applyVoiceAnswer(answer)
                }
                ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Picker("Demo scenes", selection: Binding(
                        get: { requestedDocID ?? "" },
                        set: { voice.stop(); controller.demoDocID = $0 }
                    )) {
                        if !DemoScenes.all.contains(where: { $0.id == requestedDocID }) {
                            Text("Choose a scene").tag(requestedDocID ?? "")
                        }
                        ForEach(DemoScenes.all) { demo in
                            Text(demo.title).tag(demo.id)
                        }
                    }
                    .pickerStyle(.menu)
                    .accessibilityIdentifier("demo-scenes-picker")
                    if controller.isFixture {
                        if let docID = requestedDocID, docID != "fixture__ios" {
                            Text("Requested model unavailable. Showing sample.").font(.caption)
                        }
                        Text("Sample model · generated for demo")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    if controller.isBundledDemo {
                        Text("Bundled demo scene").font(.caption).foregroundStyle(.secondary)
                    }
                    if let attribution = controller.attribution {
                        Text("\(attribution.credit) · \(attribution.licence)")
                            .font(.caption2).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier("scene-credit")
                    }
                    if let note = controller.manifest?.note {
                        Text(note).font(.caption2).foregroundStyle(.secondary)
                    }
                    Text(controller.status).font(.callout)
                        .accessibilityIdentifier("ar-status")
                    Toggle("Show roof", isOn: Binding(get: { controller.showRoof },
                                                      set: { controller.setShowRoof($0) }))
                        .disabled(!controller.isLoaded)
                        .accessibilityIdentifier("show-roof-toggle")
                    HStack {
                        Text("Storey")
                        Spacer()
                        Button { controller.stepStorey(-1) } label: {
                            Image(systemName: "chevron.down")
                        }
                        .accessibilityLabel("Lower storey")
                        .disabled(!controller.canStepStoreyDown)
                        Text(controller.activeStorey ?? "Unavailable").font(.callout)
                            .accessibilityIdentifier("active-storey")
                        Button { controller.stepStorey(1) } label: {
                            Image(systemName: "chevron.up")
                        }
                        .accessibilityLabel("Higher storey")
                        .disabled(!controller.canStepStoreyUp)
                    }
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
                .padding()
                }
                .frame(maxHeight: 420)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
            }.padding()
        }
        .task {
            liveSocket.onHighlight = { request in
                controller.applyLiveHighlight(request)
            }
            liveSocket.start()
        }
        .task(id: requestedDocID) {
            await controller.load(docID: requestedDocID, url: sceneURL, manifestURL: manifestURL,
                                  itemIDs: requestedDocID == docID ? highlightedItemIDs : [],
                                  cameraTargetItemID: requestedDocID == docID ? cameraTargetItemID : nil)
        }
        .onDisappear {
            voice.stop()
            liveSocket.stop()
            liveSocket.onHighlight = nil
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .background { voice.stop() }
        }
        .onChange(of: highlightedItemIDs) { _, items in
            if requestedDocID == controller.activeDocID {
                controller.setHighlights(items, cameraTargetItemID: cameraTargetItemID)
            }
        }
        .onChange(of: cameraTargetItemID) { _, target in
            if requestedDocID == controller.activeDocID {
                controller.setHighlights(highlightedItemIDs, cameraTargetItemID: target)
            }
        }
        #endif
    }

    private func highlightItem(_ itemID: String) {
        guard let activeDocID = controller.activeDocID else { return }
        controller.setHighlights([itemID])
        Task { await liveSocket.sendHighlight(docID: activeDocID, itemIDs: [itemID]) }
    }
}
