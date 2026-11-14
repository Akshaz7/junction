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

@MainActor
final class WebSession: ObservableObject {
    let webView: WKWebView
    let coordinator: WebShell.Coordinator
    #if DEBUG
    let allowsUITestInspection = ProcessInfo.processInfo.arguments.contains("-UITEST")
    @Published private(set) var uiTestWebState = "idle"
    private var uiTestReadID = 0

    // Read the live DOM without relying on WebKit's regenerated accessibility
    // nodes after a full-screen presentation. This never changes the page.
    func inspectWebStateForUITest() {
        guard allowsUITestInspection else { return }
        uiTestReadID += 1
        uiTestWebState = "reading"
        webView.evaluateJavaScript("""
            (() => {
                const composer = document.querySelector('textarea#question');
                const rect = composer?.getBoundingClientRect();
                return JSON.stringify({
                    readID: \(uiTestReadID),
                    draft: composer?.value ?? null,
                    href: location.href,
                    timeOrigin: performance.timeOrigin,
                    composerVisible: !!rect && rect.width > 100 && rect.height > 20
                        && rect.bottom > 0 && rect.top < innerHeight
                        && rect.right > 0 && rect.left < innerWidth
                        && getComputedStyle(composer).visibility !== 'hidden'
                        && getComputedStyle(composer).display !== 'none',
                    composerEnabled: !!composer && !composer.disabled
                });
            })()
            """) { [weak self] result, error in
                if let error {
                    self?.uiTestWebState = "error: \(error.localizedDescription)"
                } else {
                    self?.uiTestWebState = result as? String ?? "error: no web state"
                }
            }
    }
    #endif

    init(url: URL) {
        coordinator = WebShell.Coordinator()
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.add(coordinator, name: "ar")
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = coordinator
        webView.accessibilityIdentifier = "web-shell"
        webView.allowsBackForwardNavigationGestures = true
        // Load once for this session, independent of SwiftUI mounting the view.
        webView.load(URLRequest(url: url))
    }

    func prepareForAR() {
        webView.endEditing(true)
    }
}

struct WebShell: UIViewControllerRepresentable {
    let session: WebSession
    var onARRequest: (ARRequest) -> Void = { _ in }

    func makeCoordinator() -> Coordinator {
        session.coordinator.onARRequest = onARRequest
        return session.coordinator
    }

    func makeUIViewController(context: Context) -> WebShellController {
        WebShellController(webView: session.webView)
    }

    func updateUIViewController(_ controller: WebShellController, context: Context) {
        context.coordinator.onARRequest = onARRequest
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
            message.webView?.endEditing(true)
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

@MainActor
final class WebShellController: UIViewController {
    let webView: WKWebView

    init(webView: WKWebView) {
        self.webView = webView
        super.init(nibName: nil, bundle: nil)
    }

    required init?(coder: NSCoder) {
        fatalError("Use init(webView:)")
    }

    override func loadView() {
        view = UIView()
        // Reattach the session's existing web view if SwiftUI remounts the host.
        webView.removeFromSuperview()
        webView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(webView)
        NSLayoutConstraint.activate([
            webView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            webView.topAnchor.constraint(equalTo: view.topAnchor),
            webView.bottomAnchor.constraint(equalTo: view.bottomAnchor)
        ])
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        // A full-screen cover detaches the presenting hierarchy. Lay out its
        // restored bounds after dismissal without loading the page again.
        view.setNeedsLayout()
        view.layoutIfNeeded()
        webView.setNeedsLayout()
        webView.layoutIfNeeded()
    }
}
