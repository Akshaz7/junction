import Foundation

/// Display identity comes from the loaded manifest, never the requested route.
struct SceneIdentity {
    let docID: String?
    let title: String
    let notice: String?

    init(requestedDocID: String?, manifest: SceneManifest?, documentTitle: String? = nil,
         isBundled: Bool = false) {
        let loadedDocID = manifest?.doc_id
        docID = loadedDocID
        if loadedDocID == "fixture__ios" {
            title = "Sample model · generated"
        } else {
            title = documentTitle ?? manifest?.title
                ?? DemoScenes.all.first { $0.id == loadedDocID }?.title ?? loadedDocID ?? "Scene unavailable"
        }
        if let requestedDocID, docID != requestedDocID {
            notice = "Requested scene unavailable: \(requestedDocID). Showing \(title)."
        } else if isBundled {
            notice = "Offline copy · \(title)"
        } else {
            notice = nil
        }
    }
}
