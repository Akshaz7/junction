import CryptoKit
import Foundation

/// Downloads the manifest first so unavailable scenes never reach RealityKit.
struct SceneRepository {
    struct Files {
        let modelURL: URL
        let manifestURL: URL
    }

    let apiURL: URL
    var session: URLSession = .shared
    var cacheDirectory: URL = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        .appendingPathComponent("ARScenes", isDirectory: true)

    func fetch(docID: String) async throws -> Files {
        let documentURL = apiURL.appendingPathComponent("api/docs").appending(component: docID)
        var request = URLRequest(url: documentURL.appendingPathComponent("scene"))
        request.timeoutInterval = 15
        let (metadata, response) = try await session.data(for: request)
        try validate(response)
        let manifest = try JSONDecoder().decode(SceneManifest.self, from: metadata)
        guard manifest.doc_id == docID else { throw RepositoryError.wrongDocument }

        request.url = documentURL.appendingPathComponent("files/scene.usdz")
        request.timeoutInterval = 60
        let (download, modelResponse) = try await session.download(for: request)
        defer { try? FileManager.default.removeItem(at: download) }
        try validate(modelResponse)
        try Task.checkCancellation()

        // Hash IDs rather than using untrusted bridge strings as local paths.
        let key = SHA256.hash(data: Data(docID.utf8)).map { String(format: "%02x", $0) }.joined()
        let directory = cacheDirectory.appendingPathComponent(key, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let modelURL = directory.appendingPathComponent("scene.usdz")
        let manifestURL = directory.appendingPathComponent("scene.json")
        if FileManager.default.fileExists(atPath: modelURL.path) {
            _ = try FileManager.default.replaceItemAt(modelURL, withItemAt: download)
        } else {
            try FileManager.default.moveItem(at: download, to: modelURL)
        }
        try metadata.write(to: manifestURL, options: .atomic)
        return Files(modelURL: modelURL, manifestURL: manifestURL)
    }

    private func validate(_ response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw RepositoryError.unavailable
        }
    }

    private enum RepositoryError: Error {
        case unavailable, wrongDocument
    }
}
