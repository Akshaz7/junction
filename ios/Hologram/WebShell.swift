import OSLog
import SwiftUI
import WebKit

struct ARRequest: Equatable, Identifiable {
    let docID: String
    let itemIDs: [String]
    let chatID: String?
    var id: String { docID }

    init(docID: String, itemIDs: [String], chatID: String? = nil) {
        self.docID = docID
        self.itemIDs = itemIDs
        self.chatID = chatID
    }

    init?(body: Any, pageURL: URL? = nil) {
        guard let payload = body as? [String: Any],
              let docID = payload["doc_id"] as? String,
              !docID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              let itemIDs = payload["item_ids"] as? [String],
              itemIDs.allSatisfy({ !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }),
              payload["chat_id"] == nil || payload["chat_id"] is String else {
            return nil
        }
        self.docID = docID
        self.itemIDs = itemIDs
        let explicitChat = (payload["chat_id"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
        let fragment = pageURL.flatMap { URLComponents(url: $0, resolvingAgainstBaseURL: false)?.percentEncodedFragment }
        let query = fragment.flatMap { URLComponents(string: $0)?.queryItems }
        let pageChat = query?.first { $0.name == "chat" }?.value
        self.chatID = explicitChat.flatMap { $0.isEmpty ? nil : $0 }
            ?? pageChat.flatMap { $0.isEmpty ? nil : $0 }
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
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
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
        webView.navigationDelegate = nil
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "ar")
    }

    @MainActor
    final class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
        private let logger = Logger(subsystem: "com.teamrs3.hologram", category: "ARBridge")
        var onARRequest: (ARRequest) -> Void
        #if DEBUG
        private var injectedBridgeMessage = false
        #endif

        init(onARRequest: @escaping (ARRequest) -> Void = { _ in }) {
            self.onARRequest = onARRequest
        }

        func userContentController(_ userContentController: WKUserContentController,
                                   didReceive message: WKScriptMessage) {
            guard message.frameInfo.isMainFrame else { return }
            handleMessage(name: message.name, body: message.body, pageURL: message.webView?.url)
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            #if DEBUG
            if !injectedBridgeMessage, let script = AppConfiguration.debugBridgeScript {
                injectedBridgeMessage = true
                webView.evaluateJavaScript(script)
            }
            #endif
        }

        // The WKScriptMessage entry point and unit tests share the same parsing path.
        func handleMessage(name: String, body: Any, pageURL: URL? = nil) {
            guard name == "ar", let request = ARRequest(body: body, pageURL: pageURL) else {
                logger.debug("Ignored an invalid AR bridge message.")
                return
            }
            onARRequest(request)
        }
    }
}
