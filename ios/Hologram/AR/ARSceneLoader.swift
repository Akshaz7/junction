import Foundation
import RealityKit

@MainActor
enum ARSceneLoader {
    struct LoadedScene {
        let entity: Entity
        let isFixture: Bool
        let manifest: SceneManifest?
    }

    static func load(docID: String? = nil, apiURL: URL = AppConfiguration.apiURL,
                     url: URL?, manifestURL: URL? = nil,
                     repository: SceneRepository? = nil) async throws -> LoadedScene {
        if let docID {
            do {
                let files = try await (repository ?? SceneRepository(apiURL: apiURL)).fetch(docID: docID)
                return try await load(url: files.modelURL, manifestURL: files.manifestURL)
            } catch {
                try Task.checkCancellation()
                return try await load(url: nil)
            }
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
        case missingFixture, downloadFailed

        var errorDescription: String? {
            switch self {
            case .missingFixture: "The bundled demo model is unavailable."
            case .downloadFailed: "The model could not be downloaded."
            }
        }
    }
}
