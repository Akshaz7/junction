import Foundation
import RealityKit

@MainActor
enum ARSceneLoader {
    struct LoadedScene {
        let entity: Entity
        let isFixture: Bool
        let manifest: SceneManifest?
        var isBundledDemo = false
        var documentTitle: String? = nil

        var attribution: SceneAttribution? {
            if let credit = manifest?.credit, let licence = manifest?.licence {
                return SceneAttribution(credit: credit, licence: licence)
            }
            return DemoScenes.attribution(for: manifest?.doc_id)
        }
    }

    static func load(docID: String? = nil, apiURL: URL = AppConfiguration.apiURL,
                     url: URL?, manifestURL: URL? = nil,
                     repository: SceneRepository? = nil,
                     fetcher: ((String) async throws -> SceneRepository.Files)? = nil) async throws -> LoadedScene {
        if let docID {
            do {
                let files: SceneRepository.Files
                if let fetcher {
                    files = try await fetcher(docID)
                } else {
                    files = try await (repository ?? SceneRepository(apiURL: apiURL)).fetch(docID: docID)
                }
                return try await loadDocument(files: files, docID: docID, isBundledDemo: false)
            } catch {
                try Task.checkCancellation()
            }
            if let files = DemoScenes.files(for: docID) {
                do {
                    return try await loadDocument(files: files, docID: docID, isBundledDemo: true)
                } catch {
                    try Task.checkCancellation()
                }
            }
            return try await load(url: nil)
        }
        if let url {
            do {
                let entity = try await loadEntity(from: url)
                let metadataURL = manifestURL ?? url.deletingLastPathComponent().appendingPathComponent("scene.json")
                let manifest = try? await loadManifest(from: metadataURL)
                try Task.checkCancellation()
                return LoadedScene(entity: entity, isFixture: false, manifest: manifest)
            } catch {
                try Task.checkCancellation()
                // A missing or unavailable remote model still permits the offline demo.
            }
        }
        guard let fixtureURL = Bundle.main.url(forResource: "fixture", withExtension: "usdz") else {
            throw LoaderError.missingFixture
        }
        let manifestURL = Bundle.main.url(forResource: "fixture.scene", withExtension: "json")
        let manifest = try manifestURL.map { try Data(contentsOf: $0) }
            .map { try JSONDecoder().decode(SceneManifest.self, from: $0) }
        return LoadedScene(entity: try await Entity(contentsOf: fixtureURL), isFixture: true, manifest: manifest)
    }

    private static func loadDocument(files: SceneRepository.Files, docID: String,
                                     isBundledDemo: Bool) async throws -> LoadedScene {
        let manifest = try await loadManifest(from: files.manifestURL)
        guard manifest.doc_id == docID else { throw LoaderError.wrongDocument }
        let entity = try await loadEntity(from: files.modelURL)
        try Task.checkCancellation()
        // A correct JSON response can still accompany a stale or wrong USDZ.
        let names = Set(SceneIndex(root: entity).entitiesByUSDName.keys.filter { $0.hasPrefix("i_") })
        let expected = Set(manifest.items.values.map(\.usd_name))
        guard !names.isDisjoint(with: expected), names.isSubset(of: expected) else {
            throw LoaderError.wrongDocument
        }
        return LoadedScene(entity: entity, isFixture: false, manifest: manifest,
                           isBundledDemo: isBundledDemo, documentTitle: files.documentTitle)
    }

    private static func loadManifest(from url: URL) async throws -> SceneManifest {
        let data: Data
        if url.isFileURL {
            data = try Data(contentsOf: url)
        } else {
            var request = URLRequest(url: url)
            request.timeoutInterval = 15
            let (download, response) = try await URLSession.shared.data(for: request)
            guard let response = response as? HTTPURLResponse, (200..<300).contains(response.statusCode) else {
                throw LoaderError.downloadFailed
            }
            data = download
        }
        return try JSONDecoder().decode(SceneManifest.self, from: data)
    }

    private static func loadEntity(from url: URL) async throws -> Entity {
        if url.isFileURL {
            return try await Entity(contentsOf: url)
        }
        let (downloadURL, response) = try await URLSession.shared.download(from: url)
        defer { try? FileManager.default.removeItem(at: downloadURL) }
        guard let response = response as? HTTPURLResponse, (200..<300).contains(response.statusCode) else {
            throw LoaderError.downloadFailed
        }
        // RealityKit uses the extension to determine the asset format.
        let modelURL = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString).appendingPathExtension("usdz")
        try FileManager.default.moveItem(at: downloadURL, to: modelURL)
        defer { try? FileManager.default.removeItem(at: modelURL) }
        try Task.checkCancellation()
        return try await Entity(contentsOf: modelURL)
    }

    private enum LoaderError: LocalizedError {
        case missingFixture, downloadFailed, wrongDocument

        var errorDescription: String? {
            switch self {
            case .missingFixture: "The bundled demo model is unavailable."
            case .downloadFailed: "The model could not be downloaded."
            case .wrongDocument: "The model belongs to a different document."
            }
        }
    }
}
