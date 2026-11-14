import OSLog
import SwiftUI
import WebKit

struct ARRequest: Equatable, Identifiable {
    let docID: String
    let itemIDs: [String]
    var id: String { docID }

    init(docID: String, itemIDs: [String]) {
        self.docID = docID
        self.itemIDs = itemIDs
    }

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
    var onARRequest: (ARRequest) -> Void = { _ in }

    func makeCoordinator() -> Coordinator {
        Coordinator(onARRequest: onARRequest)
    }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.add(context.coordinator, name: "ar")
        #if DEBUG
        if let script = AppConfiguration.debugBridgeScript {
            configuration.userContentController.addUserScript(WKUserScript(
                source: script, injectionTime: .atDocumentEnd, forMainFrameOnly: true))
        }
        #endif
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.accessibilityIdentifier = "web-shell"
        webView.allowsBackForwardNavigationGestures = true
        webView.load(URLRequest(url: url))
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        context.coordinator.onARRequest = onARRequest
    }

    static func dismantleUIView(_ webView: WKWebView, coordinator: Coordinator) {
        webView.stopLoading()
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "ar")
    }

    @MainActor
    final class Coordinator: NSObject, WKScriptMessageHandler {
        private let logger = Logger(subsystem: "com.teamrs3.hologram", category: "ARBridge")
        var onARRequest: (ARRequest) -> Void

        init(onARRequest: @escaping (ARRequest) -> Void = { _ in }) {
            self.onARRequest = onARRequest
        }

        func userContentController(_ userContentController: WKUserContentController,
                                   didReceive message: WKScriptMessage) {
            handleMessage(name: message.name, body: message.body)
        }

        // The WKScriptMessage entry point and unit tests share the same parsing path.
        func handleMessage(name: String, body: Any) {
            guard name == "ar", let request = ARRequest(body: body) else {
                logger.debug("Ignored an invalid AR bridge message.")
                return
            }
            onARRequest(request)
        }
    }
}
