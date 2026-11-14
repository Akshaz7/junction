#if targetEnvironment(simulator)
import Combine
import SwiftUI

/// The simulator loads real scene metadata without starting a camera or AR session.
struct SimulatorScenePanel: View {
    let docID: String
    var chatID: String?
    var manifestURL: URL?
    var highlightedItemIDs: [String] = []
    @StateObject private var preview = SimulatorSceneMetadata()
    @StateObject private var liveSocket = LiveSocket()
    @StateObject private var advisor = AdvisorCardsController()
    @Environment(\.dismiss) private var dismiss

    private var requestedDocID: String { preview.selectedDocID ?? docID }

    var body: some View {
        VStack(spacing: 20) {
            HStack {
                Text("Show on table").font(.headline)
                Spacer()
                Button("Done") { dismiss() }
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Label("AR needs an iPhone", systemImage: "arkit")
                        .font(.title2.bold())
                        .accessibilityIdentifier("simulator-ar-fallback")
                    Text("Scene metadata is available here. Open this scene on an iPhone to place it in AR.")
                        .foregroundStyle(.secondary)
                    Picker("Demo scenes", selection: Binding(
                        get: { requestedDocID }, set: { preview.selectedDocID = $0 }
                    )) {
                        if !DemoScenes.all.contains(where: { $0.id == requestedDocID }) {
                            Text("Choose a scene").tag(requestedDocID)
                        }
                        ForEach(DemoScenes.all) { demo in
                            Text(demo.title).tag(demo.id)
                        }
                    }
                    .pickerStyle(.menu)
                    .accessibilityIdentifier("demo-scenes-picker")

                    Text(preview.manifest?.doc_id ?? requestedDocID).font(.caption.monospaced())
                        .accessibilityIdentifier("ar-document-id")
                    if let manifest = preview.manifest {
                        Text(preview.identity.title)
                            .font(.headline)
                            .accessibilityIdentifier("scene-name")
                        if let notice = preview.identity.notice {
                            Text(notice).accessibilityIdentifier("ar-fallback-notice")
                        }
                        Text("\(manifest.items.count) items")
                            .accessibilityIdentifier("scene-item-count")
                        Text("\(preview.hiddenItemIDs.count) hidden items")
                            .accessibilityIdentifier("hidden-item-count")
                        if let attribution = preview.attribution {
                            Text("\(attribution.credit) · \(attribution.licence)")
                                .font(.caption)
                                .accessibilityIdentifier("scene-credit")
                        }
                        if let note = manifest.note { Text(note).font(.caption) }
                        if !preview.itemIDs.isEmpty {
                            Text("Highlighted items").font(.headline)
                            ForEach(Array(preview.itemIDs.enumerated()), id: \.offset) { index, itemID in
                                Text("\(index + 1) · \(itemID)")
                                    .font(.caption.monospaced())
                                    .accessibilityIdentifier("highlighted-item-\(index + 1)")
                                if let tag = preview.labels[itemID] ?? manifest.items[itemID]?.tag {
                                    Text(tag).font(.caption)
                                        .accessibilityIdentifier("highlighted-tag-\(index + 1)")
                                }
                            }
                        }
                    }
                    Text(preview.status).font(.callout).accessibilityIdentifier("ar-status")
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            if !advisor.cards.isEmpty {
                ScrollView {
                    AdvisorCardsOverlay(cards: advisor.cards) { card in
                        advisor.select(card) { request in
                            applyHighlight(request)
                            Task { await liveSocket.sendHighlight(docID: request.docID, itemIDs: request.itemIDs) }
                        }
                    }
                }
                .frame(maxHeight: 300)
            }
        }
        .padding()
        .task(id: requestedDocID) {
            liveSocket.stop()
            liveSocket.onHighlight = applyHighlight
            liveSocket.onEdit = { preview.apply(.edit($0), docID: requestedDocID) }
            liveSocket.onState = { preview.apply(.state($0), docID: requestedDocID) }
            liveSocket.onAdvisorCards = { advisor.receive($0) }
            advisor.clear()
            await preview.load(docID: requestedDocID,
                               manifestURL: requestedDocID == docID ? manifestURL : nil,
                               itemIDs: requestedDocID == docID ? highlightedItemIDs : [])
            guard !Task.isCancelled else { return }
            guard preview.manifest?.doc_id == requestedDocID else { return }
            liveSocket.start(docID: requestedDocID, chatID: requestedDocID == docID ? chatID : nil,
                             entryItemIDs: requestedDocID == docID ? highlightedItemIDs : [])
            await advisor.load(docID: requestedDocID, fixtureURL: AppConfiguration.advisorFixtureURL)
        }
        .onDisappear {
            liveSocket.stop()
            liveSocket.onHighlight = nil
            liveSocket.onEdit = nil
            liveSocket.onState = nil
            liveSocket.onAdvisorCards = nil
        }
    }

    private func applyHighlight(_ request: ARRequest) {
        preview.apply(.highlight(request), docID: requestedDocID)
    }
}

@MainActor
final class SimulatorSceneMetadata: ObservableObject {
    @Published var selectedDocID: String?
    @Published var manifest: SceneManifest?
    @Published var attribution: SceneAttribution?
    @Published var itemIDs: [String] = []
    @Published var hiddenItemIDs: Set<String> = []
    @Published var labels: [String: String] = [:]
    private var appliedEditIDs: Set<String> = []
    @Published var status = "Loading scene metadata…"
    @Published private(set) var identity = SceneIdentity(requestedDocID: nil, manifest: nil)

    func load(docID: String, manifestURL: URL?, itemIDs: [String]) async {
        manifest = nil
        identity = SceneIdentity(requestedDocID: docID, manifest: nil)
        attribution = nil
        self.itemIDs = itemIDs
        hiddenItemIDs = []
        labels = [:]
        appliedEditIDs = []
        status = "Loading scene metadata…"
        do {
            let data: Data
            var bundled = false
            if docID == "fixture__ios",
               let url = Bundle.main.url(forResource: "fixture.scene", withExtension: "json") {
                data = try Data(contentsOf: url)
                bundled = true
            } else if let manifestURL, manifestURL.isFileURL {
                data = try Data(contentsOf: manifestURL)
            } else {
                do {
                    let url = AppConfiguration.apiURL.appendingPathComponent("api/docs")
                        .appending(component: docID).appendingPathComponent("scene")
                    var request = URLRequest(url: url)
                    request.timeoutInterval = 10
                    let (download, response) = try await URLSession.shared.data(for: request)
                    guard let response = response as? HTTPURLResponse,
                          (200..<300).contains(response.statusCode) else { throw URLError(.badServerResponse) }
                    // Check the document before deciding whether to use the matching bundle.
                    guard try JSONDecoder().decode(SceneManifest.self, from: download).doc_id == docID
                    else { throw URLError(.cannotParseResponse) }
                    data = download
                } catch {
                    try Task.checkCancellation()
                    guard let files = DemoScenes.files(for: docID) else { throw error }
                    data = try Data(contentsOf: files.manifestURL)
                    bundled = true
                }
            }
            try Task.checkCancellation()
            let loaded = try JSONDecoder().decode(SceneManifest.self, from: data)
            guard loaded.doc_id == docID else { throw URLError(.cannotParseResponse) }
            let title = bundled ? nil : await SceneRepository(apiURL: AppConfiguration.apiURL).documentTitle(docID: docID)
            try Task.checkCancellation()
            manifest = loaded
            identity = SceneIdentity(requestedDocID: docID, manifest: loaded, documentTitle: title, isBundled: bundled)
            if let credit = loaded.credit, let licence = loaded.licence {
                attribution = SceneAttribution(credit: credit, licence: licence)
            } else {
                attribution = DemoScenes.attribution(for: loaded.doc_id)
            }
            status = bundled ? "Bundled scene metadata loaded." : "Scene metadata loaded from the API."
        } catch is CancellationError {
            return
        } catch {
            status = "Unable to load scene metadata. \(error.localizedDescription)"
        }
    }

    func apply(_ command: LiveSocket.Command, docID: String) {
        switch command {
        case .highlight(let request) where request.docID == docID:
            itemIDs = request.itemIDs
            labels = [:]
        case .state(let state) where state.doc_id == docID:
            hiddenItemIDs = Set(state.hidden)
            itemIDs = state.highlighted
            labels = state.labels
        case .edit(let event) where event.doc_id == docID:
            if let id = event.edit_id, !appliedEditIDs.insert(id).inserted { return }
            let edit = event.command
            switch edit.op {
            case .highlight: itemIDs = edit.item_ids; labels = edit.labels ?? [:]
            case .hide: hiddenItemIDs.formUnion(edit.item_ids)
            case .restore: hiddenItemIDs.subtract(edit.item_ids)
            case .isolate:
                hiddenItemIDs = Set(manifest?.items.keys.map { $0 } ?? []).subtracting(edit.item_ids)
            case .reset: hiddenItemIDs = []; itemIDs = []; labels = [:]
            }
        default: break
        }
    }
}
#endif
