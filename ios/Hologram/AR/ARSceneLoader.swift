import Foundation
import RealityKit

@MainActor
enum ARSceneLoader {
    struct LoadedScene {
        let entity: Entity
        let isFixture: Bool
    }

    static func load(url: URL?) async throws -> LoadedScene {
        if let url {
            do {
                return LoadedScene(entity: try await loadEntity(from: url), isFixture: false)
            } catch {
                try Task.checkCancellation()
                // A missing or unavailable remote model still permits the offline demo.
            }
        }
        guard let fixtureURL = Bundle.main.url(forResource: "fixture", withExtension: "usdz") else {
            throw LoaderError.missingFixture
        }
        return LoadedScene(entity: try await Entity(contentsOf: fixtureURL), isFixture: true)
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
