import CryptoKit
import Foundation

/// Downloads the manifest first so unavailable scenes never reach RealityKit.
struct SceneRepository {
    struct Files {
        let modelURL: URL
        let manifestURL: URL
        var documentTitle: String? = nil
        /// Present when the server has a scene.glb; used when the USDZ is missing or does not match the manifest.
        var glbURL: URL? = nil
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

        // Uploaded drawings may have only scene.glb (the server cannot always write USDZ) or a stale USDZ, so both
        // are fetched when present; ARSceneLoader prefers a USDZ that matches the manifest, else builds from the GLB.
        let usdz = await download(documentURL.appendingPathComponent("files/scene.usdz"), request: request)
        let glb = await download(documentURL.appendingPathComponent("files/scene.glb"), request: request)
        defer { for url in [usdz, glb] { if let url { try? FileManager.default.removeItem(at: url) } } }
        guard usdz != nil || glb != nil else { throw RepositoryError.unavailable }
        try Task.checkCancellation()

        // Hash IDs rather than using untrusted bridge strings as local paths.
        let key = SHA256.hash(data: Data(docID.utf8)).map { String(format: "%02x", $0) }.joined()
        let directory = cacheDirectory.appendingPathComponent(key, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let modelURL = directory.appendingPathComponent("scene.usdz")
        let glbURL = directory.appendingPathComponent("scene.glb")
        let manifestURL = directory.appendingPathComponent("scene.json")
        try store(usdz, at: modelURL)
        try store(glb, at: glbURL)
        try metadata.write(to: manifestURL, options: .atomic)
        let title = await documentTitle(docID: docID)
        try Task.checkCancellation()
        return Files(modelURL: modelURL, manifestURL: manifestURL, documentTitle: title,
                     glbURL: glb == nil ? nil : glbURL)
    }

    /// Downloads one file; nil when the server does not have it (404) or the request fails.
    private func download(_ url: URL, request template: URLRequest) async -> URL? {
        var request = template
        request.url = url
        request.timeoutInterval = 60
        guard let (file, response) = try? await session.download(for: request),
              (response as? HTTPURLResponse).map({ (200..<300).contains($0.statusCode) }) == true else { return nil }
        // The session deletes its temp file when the call returns; keep a copy for the caller.
        let copy = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        return (try? FileManager.default.copyItem(at: file, to: copy)) == nil ? nil : copy
    }

    /// Replaces the cached file, or removes it when the server no longer has one (never keep a stale copy).
    private func store(_ download: URL?, at destination: URL) throws {
        guard let download else { try? FileManager.default.removeItem(at: destination); return }
        if FileManager.default.fileExists(atPath: destination.path) {
            _ = try FileManager.default.replaceItemAt(destination, withItemAt: download)
        } else {
            try FileManager.default.moveItem(at: download, to: destination)
        }
    }

    func documentTitle(docID: String) async -> String? {
        struct Document: Decodable { let doc_id: String; let title: String? }
        var request = URLRequest(url: apiURL.appendingPathComponent("api/docs").appending(component: docID))
        request.timeoutInterval = 5
        guard let (data, response) = try? await session.data(for: request),
              (response as? HTTPURLResponse).map({ (200..<300).contains($0.statusCode) }) == true,
              let document = try? JSONDecoder().decode(Document.self, from: data),
              document.doc_id == docID else { return nil }
        return document.title.flatMap { $0.isEmpty ? nil : $0 }
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
