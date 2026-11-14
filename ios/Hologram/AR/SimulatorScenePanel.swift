#if targetEnvironment(simulator)
import Combine
import SwiftUI

/// The simulator loads real scene metadata without starting a camera or AR session.
struct SimulatorScenePanel: View {
    let docID: String
    var manifestURL: URL?
    var highlightedItemIDs: [String] = []
    @StateObject private var preview = SimulatorSceneMetadata()
    @StateObject private var liveSocket = LiveSocket()
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

                    Text(requestedDocID).font(.caption.monospaced())
                        .accessibilityIdentifier("ar-document-id")
                    if let manifest = preview.manifest {
                        Text(DemoScenes.all.first { $0.id == manifest.doc_id }?.title
                             ?? (manifest.doc_id == "fixture__ios" ? "Sample model · generated for demo" : "Scene"))
                            .font(.headline)
                            .accessibilityIdentifier("scene-name")
                        Text("\(manifest.items.count) items")
                            .accessibilityIdentifier("scene-item-count")
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
                            }
                        }
                    }
                    Text(preview.status).font(.callout).accessibilityIdentifier("ar-status")
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding()
        .task(id: requestedDocID) {
            await preview.load(docID: requestedDocID,
                               manifestURL: requestedDocID == docID ? manifestURL : nil,
                               itemIDs: requestedDocID == docID ? highlightedItemIDs : [])
        }
        .task {
            liveSocket.onHighlight = { request in
                guard request.docID == requestedDocID else { return }
                preview.itemIDs = request.itemIDs
            }
            liveSocket.start()
        }
        .onDisappear {
            liveSocket.stop()
            liveSocket.onHighlight = nil
        }
    }
}

@MainActor
private final class SimulatorSceneMetadata: ObservableObject {
    @Published var selectedDocID: String?
    @Published var manifest: SceneManifest?
    @Published var attribution: SceneAttribution?
    @Published var itemIDs: [String] = []
    @Published var status = "Loading scene metadata…"

    func load(docID: String, manifestURL: URL?, itemIDs: [String]) async {
        manifest = nil
        attribution = nil
        self.itemIDs = itemIDs
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
            manifest = loaded
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
}
#endif
