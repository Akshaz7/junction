import OSLog
import SwiftUI
import WebKit

struct ARRequest {
    let docID: String
    let itemIDs: [String]

    init?(body: Any) {
        guard let payload = body as? [String: Any],
              let docID = payload["doc_id"] as? String, !docID.isEmpty,
              let itemIDs = payload["item_ids"] as? [String] else {
            return nil
        }
        self.docID = docID
        self.itemIDs = itemIDs
    }
}

struct WebShell: UIViewRepresentable {
    let url: URL

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.add(context.coordinator, name: "ar")
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.allowsBackForwardNavigationGestures = true
        webView.load(URLRequest(url: url))
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {}

    static func dismantleUIView(_ webView: WKWebView, coordinator: Coordinator) {
        webView.stopLoading()
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "ar")
    }

    final class Coordinator: NSObject, WKScriptMessageHandler {
        private let logger = Logger(subsystem: "com.teamrs3.hologram", category: "ARBridge")

        func userContentController(_ userContentController: WKUserContentController,
                                   didReceive message: WKScriptMessage) {
            guard message.name == "ar", let request = ARRequest(body: message.body) else {
                logger.debug("Ignored an invalid AR bridge message.")
                return
            }
            // I-02 will present the native AR screen using this request.
            logger.debug("Received AR bridge request with \(request.itemIDs.count) selected items.")
        }
    }
}
