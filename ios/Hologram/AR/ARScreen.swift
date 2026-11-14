import SwiftUI

struct ARScreen: View {
    var docID: String? = nil
    var chatID: String? = nil
    var sceneURL: URL? = nil
    var manifestURL: URL? = nil
    var highlightedItemIDs: [String] = []
    var cameraTargetItemID: String? = nil
    @StateObject private var controller = ARSceneController()
    @StateObject private var liveSocket = LiveSocket()
    @StateObject private var voice = ARVoiceController()
    @StateObject private var advisor = AdvisorCardsController()
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.dismiss) private var dismiss

    private var requestedDocID: String? { controller.demoDocID ?? docID }

    var body: some View {
        #if targetEnvironment(simulator)
        SimulatorScenePanel(docID: docID ?? "fixture__ios", chatID: chatID, manifestURL: manifestURL,
                            highlightedItemIDs: highlightedItemIDs)
        #else
        ZStack {
            ARSceneView(controller: controller).ignoresSafeArea()
            AdvisorCallout(card: advisor.spotlight, anchor: controller.advisorAnchor,
                           onDismiss: { advisor.dismissSpotlight() },
                           onShow: { card in selectAdvisorCard(card) })
            VStack(spacing: 10) {
                topBar
                placementPill
                kindLegend
                spotlightCaption
                storeyChip
                if controller.isWalking && controller.isPlaced {
                    HStack {
                        if let manifest = controller.manifest {
                            WalkMiniMap(manifest: manifest, cameraTransform: controller.cameraInModel,
                                        highlightedItemIDs: controller.highlightedItemIDs,
                                        guide: controller.guide, targetItemID: controller.targetItemID,
                                        onSelectItem: controller.selectTarget)
                        }
                        Spacer()
                    }
                }
                Spacer()
                ARSubtitle(voice: voice)
                editChips
                if let state = controller.buildState, controller.isPlaced, !controller.isWalking {
                    BuildScrubber(state: state, onPrevious: { controller.previousBuildStep() },
                                  onToggle: { state.playing ? controller.pauseBuild() : controller.playBuild() },
                                  onNext: { controller.nextBuildStep() },
                                  onSelect: { controller.setBuildStep($0) })
                }
                bottomBar
            }
            .padding(.horizontal, 16).padding(.vertical, 8)
        }
        .task(id: requestedDocID) {
            controller.onActivateSelectedItem = { highlightItem($0) }
            liveSocket.stop()
            liveSocket.onHighlight = { request in
                controller.applyLiveHighlight(request)
            }
            liveSocket.onEdit = { controller.applyLiveCommand(.edit($0)) }
            liveSocket.onState = { controller.applyLiveCommand(.state($0)) }
            liveSocket.onAdvisorCards = { advisor.receive($0) }
            advisor.clear()
            await controller.load(docID: requestedDocID, url: sceneURL, manifestURL: manifestURL,
                                  itemIDs: requestedDocID == docID ? highlightedItemIDs : [],
                                  cameraTargetItemID: requestedDocID == docID ? cameraTargetItemID : nil)
            guard !Task.isCancelled else { return }
            guard controller.activeDocID == requestedDocID else { return }
            voice.chatID = requestedDocID == docID ? chatID : nil
            liveSocket.start(docID: controller.activeDocID, chatID: requestedDocID == docID ? chatID : nil,
                             entryItemIDs: requestedDocID == docID ? highlightedItemIDs : [])
            if let activeDocID = controller.activeDocID {
                await advisor.load(docID: activeDocID, fixtureURL: AppConfiguration.advisorFixtureURL)
            }
        }
        .onDisappear {
            voice.stop()
            liveSocket.stop()
            liveSocket.onHighlight = nil
            liveSocket.onEdit = nil
            liveSocket.onState = nil
            liveSocket.onAdvisorCards = nil
        }
        .onChange(of: advisor.spotlight) { _, card in
            controller.trackAdvisorAnchor(itemIDs: card?.item_ids ?? [])
        }
        .onChange(of: controller.hasHiddenItems) { _, hidden in
            // "Put it back" / "reset the model": the violation no longer applies.
            if !hidden { advisor.clearEditCards() }
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

    private var sceneName: String {
        controller.sceneIdentity.title
    }

    private var isPlacing: Bool { controller.isLoaded && !controller.isPlaced }

    private var topBar: some View {
        HStack(alignment: .top) {
            Button { dismiss() } label: {
                HologramCapsule { Label("Done", systemImage: "xmark").labelStyle(.titleAndIcon) }
            }
            .accessibilityIdentifier("ar-done")
            Spacer()
            sceneMenu
        }
    }

    /// Current level with step buttons, shown for multi-storey models.
    @ViewBuilder private var storeyChip: some View {
        if controller.isPlaced, controller.cutawayStoreys.count > 1, let label = controller.activeStoreyLabel {
            HologramCardPill {
                HStack(spacing: 10) {
                    Button { controller.stepStorey(-1) } label: { Image(systemName: "chevron.down") }
                        .disabled(!controller.canStepStoreyDown)
                    Text(label).monospacedDigit().accessibilityIdentifier("ar-storey-chip")
                    Button { controller.stepStorey(1) } label: { Image(systemName: "chevron.up") }
                        .disabled(!controller.canStepStoreyUp)
                }
            }
        }
    }

    /// "12 doors" counting up while the voice answer lights items one by one.
    @ViewBuilder private var spotlightCaption: some View {
        if let spotlight = controller.spotlight {
            HologramCardPill {
                HStack(spacing: 8) {
                    Circle().fill(Color(uiColor: spotlight.color)).frame(width: 10, height: 10)
                    Text(spotlight.text).font(.system(size: 17, weight: .semibold)).monospacedDigit()
                }
            }
            .accessibilityIdentifier("ar-spotlight-caption")
        }
    }

    /// "Doors 11 · Windows 11": one colour dot per highlighted kind, shown when two or more kinds are lit.
    @ViewBuilder private var kindLegend: some View {
        let rows = controller.highlightLegend
        if rows.count >= 2 {
            HologramCardPill {
                HStack(spacing: 10) {
                    ForEach(rows, id: \.style.key) { row in
                        HStack(spacing: 5) {
                            Circle().fill(Color(uiColor: row.style.color)).frame(width: 9, height: 9)
                            Text("\(row.style.plural) \(row.count)").monospacedDigit()
                        }
                    }
                }
            }
            .accessibilityIdentifier("ar-kind-legend")
        }
    }

    @ViewBuilder private var placementPill: some View {
        if controller.isLoaded, let notice = controller.sceneIdentity.notice {
            HologramCardPill { Text(notice).lineLimit(3) }
                .accessibilityIdentifier("ar-fallback-notice")
        }
        if !controller.isLoaded || controller.status.hasPrefix("Unable") || controller.status.hasPrefix("Augmented") {
            if !(controller.status.hasPrefix("Move your device") && controller.isLoaded) {
                HologramCardPill { Text(controller.status).lineLimit(2) }
            }
        } else if isPlacing {
            HologramCardPill {
                Text(controller.canPlace
                     ? (controller.isWalking ? "Tap to place on the floor" : "Tap to place your model")
                     : (controller.isWalking ? "Aim at the floor" : "Aim at a flat surface"))
            }
        }
    }

    private var bottomBar: some View {
        ZStack(alignment: .bottom) {
            HStack(alignment: .bottom) {
                ARMicButton(voice: voice, docID: controller.activeDocID) { answer in
                    controller.applyVoiceAnswer(answer)
                    handleVoiceEdit(answer)
                }
                Spacer()
                if !advisor.cards.isEmpty { advisorPill }
            }
            if isPlacing {
                Button { controller.confirmPlacement() } label: { Text("Place model") }
                    .buttonStyle(HologramPrimaryButtonStyle())
                .disabled(!controller.canPlace)
                .accessibilityIdentifier("ar-place-model")
            }
        }
    }

    /// Hide ids from a voice answer's commands (the server already ran the checks and sends cards with the answer).
    private func handleVoiceEdit(_ answer: VoiceAnswer) {
        let docID = answer.evidence.scene.doc_id
        if let cards = answer.advisor_cards, !cards.isEmpty {
            advisor.setEditCards(cards, docID: docID)
            return
        }
        let hidden = (answer.evidence.scene.commands ?? []).filter { $0.op == .hide }.flatMap(\.item_ids)
        guard !hidden.isEmpty else { return }
        // The answer carried no cards for a hide: ask the advisor ourselves rather than show nothing.
        Task { await advisor.checkHide(itemIDs: hidden, docID: docID, chatID: voice.chatID) }
    }

    private func hideSelected() {
        guard let docID = controller.activeDocID, let id = controller.hideSelectedItem() else { return }
        Task { await advisor.checkHide(itemIDs: [id], docID: docID, chatID: requestedDocID == self.docID ? chatID : nil) }
    }

    /// Tap-to-hide and put-back, plus the rule-check status line. Shown only for a placed model.
    @ViewBuilder private var editChips: some View {
        if controller.isPlaced {
            if let message = advisor.status.message {
                HologramCardPill { Text(message).lineLimit(3) }
                    .accessibilityIdentifier("advisor-status")
            }
            HStack(spacing: 8) {
                if let item = controller.selectedItem {
                    Button { hideSelected() } label: {
                        HologramCapsule { Label("Hide \(item.name)", systemImage: "eye.slash").lineLimit(1) }
                    }
                    .accessibilityIdentifier("ar-hide-item")
                }
                if controller.hasHiddenItems {
                    Button { controller.restoreHiddenItems() } label: {
                        HologramCapsule { Label("Put it back", systemImage: "arrow.uturn.backward") }
                    }
                    .accessibilityIdentifier("ar-restore-items")
                }
            }
        }
    }

    /// One small pill instead of stacked advisor cards; each check is a menu entry.
    private var advisorPill: some View {
        Menu {
            ForEach(advisor.cards.prefix(3)) { card in
                Button { selectAdvisorCard(card) } label: {
                    Label(card.title, systemImage: advisorIcon(card.kind))
                }
                .accessibilityIdentifier("advisor-card-\(card.id)")
            }
        } label: {
            HologramCardPill {
                Label("\(min(advisor.cards.count, 3)) checks", systemImage: "scope")
            }
        }
        .accessibilityIdentifier("advisor-checks")
    }

    private func advisorIcon(_ kind: AdvisorCard.Kind) -> String {
        switch kind {
        case .warning: return "exclamationmark.triangle"
        case .option: return "lightbulb"
        case .info: return "info.circle"
        }
    }

    private var sceneMenu: some View {
        Menu {
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
            Section {
                Toggle("Show roof", isOn: Binding(get: { controller.showRoof },
                                                  set: { controller.setShowRoof($0) }))
                    .disabled(!controller.isLoaded)
                    .accessibilityIdentifier("show-roof-toggle")
                Button { controller.stepStorey(1) } label: { Label("Storey up", systemImage: "chevron.up") }
                    .disabled(!controller.canStepStoreyUp)
                Button { controller.stepStorey(-1) } label: { Label("Storey down", systemImage: "chevron.down") }
                    .disabled(!controller.canStepStoreyDown)
                Text("Storey: \(controller.activeStorey ?? "Unavailable")")
                    .accessibilityIdentifier("active-storey")
                Toggle("Walk at 1:1", isOn: Binding(get: { controller.isWalking },
                                                    set: { controller.setWalking($0) }))
                    .disabled(!controller.isLoaded)
                    .accessibilityIdentifier("walk-toggle")
            }
            Section("Scale \(controller.scaleLabel)") {
                ForEach([100, 50, 20, 10], id: \.self) { denominator in
                    Button("1:\(denominator)") { controller.setScale(1 / Float(denominator)) }
                        .disabled(!controller.isLoaded || controller.isWalking)
                }
            }
            Button("Replay build", systemImage: "play.circle") { controller.replayBuild() }
                .disabled(!controller.canReplayBuild)
                .accessibilityIdentifier("replay-build")
            Button("Reset placement", systemImage: "arrow.counterclockwise") { controller.reset() }
                .disabled(!controller.isPlaced)
            Section {
                if controller.isFixture {
                    if let docID = requestedDocID, docID != "fixture__ios" {
                        Text("Requested model unavailable. Showing sample.")
                    }
                    Text("Sample model · generated for demo")
                }
                if controller.isBundledDemo { Text("Bundled demo scene") }
                if let attribution = controller.attribution {
                    Text("\(attribution.credit) · \(attribution.licence)")
                        .accessibilityIdentifier("scene-credit")
                }
                if let note = controller.manifest?.note { Text(note) }
                Text(controller.status).accessibilityIdentifier("ar-status")
            }
        } label: {
            HologramCapsule {
                HStack(spacing: 6) {
                    Text(controller.isWalking ? "Walk · \(sceneName)" : sceneName).lineLimit(1)
                        .accessibilityIdentifier("scene-name")
                    Image(systemName: "chevron.down").font(.system(size: 10, weight: .bold))
                }
                .frame(maxWidth: 220)
            }
        }
        .accessibilityIdentifier("ar-scene-menu")
    }

    private func highlightItem(_ itemID: String) {
        guard let activeDocID = controller.activeDocID else { return }
        controller.setHighlights([itemID])
        Task { await liveSocket.sendHighlight(docID: activeDocID, itemIDs: [itemID]) }
    }

    private func selectAdvisorCard(_ card: AdvisorCard) {
        advisor.select(card) { request in
            guard controller.applyLiveHighlight(request) else { return }
            Task { await liveSocket.sendHighlight(docID: request.docID, itemIDs: request.itemIDs) }
        }
    }
}
