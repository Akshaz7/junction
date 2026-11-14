import OSLog
import SwiftUI
import WebKit

struct ARRequest: Equatable, Identifiable {
    let docID: String
    let itemIDs: [String]
    let chatID: String?
    var id: String { docID + "\n" + (chatID ?? "") }

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
    private var viewportNeedsRestoration = false
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
                const style = composer && getComputedStyle(composer);
                const facts = (element) => element && ({
                    tag: element.tagName, className: element.className,
                    hidden: element.hidden, rect: element.getBoundingClientRect().toJSON(),
                    display: getComputedStyle(element).display,
                    visibility: getComputedStyle(element).visibility,
                    overflow: getComputedStyle(element).overflow
                });
                return JSON.stringify({
                    readID: \(uiTestReadID),
                    draft: composer?.value ?? null,
                    href: location.href,
                    timeOrigin: performance.timeOrigin,
                    visibilityState: document.visibilityState,
                    innerWidth, innerHeight, scrollX, scrollY,
                    visualViewport: window.visualViewport && {
                        width: visualViewport.width, height: visualViewport.height,
                        scale: visualViewport.scale,
                        offsetLeft: visualViewport.offsetLeft, offsetTop: visualViewport.offsetTop
                    },
                    composerRect: rect?.toJSON() ?? null,
                    composerStyle: style && { display: style.display, visibility: style.visibility,
                        fontSize: style.fontSize },
                    activeElement: document.activeElement?.id,
                    activeTabs: Array.from(document.querySelectorAll('[aria-current], [role=tab][aria-selected=true]'))
                        .map(element => ({ text: element.textContent, href: element.getAttribute('href'),
                            current: element.getAttribute('aria-current') })),
                    layout: ['.app-shell', '.workspace', '.chat-workspace', '.composer-area']
                        .map(selector => ({ selector, ...facts(document.querySelector(selector)) })),
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
                    guard let self, let json = result as? String,
                          let data = json.data(using: .utf8),
                          var state = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
                    else { self?.uiTestWebState = "error: no web state"; return }
                    let scroll = self.webView.scrollView
                    state["native"] = [
                        "frame": String(describing: self.webView.frame),
                        "bounds": String(describing: self.webView.bounds),
                        "safeArea": String(describing: self.webView.safeAreaInsets),
                        "attachedToWindow": self.webView.window != nil,
                        "contentOffset": String(describing: scroll.contentOffset),
                        "contentSize": String(describing: scroll.contentSize),
                        "adjustedInset": String(describing: scroll.adjustedContentInset),
                        "zoomScale": scroll.zoomScale, "minimumZoomScale": scroll.minimumZoomScale,
                        "maximumZoomScale": scroll.maximumZoomScale,
                        "pageZoom": self.webView.pageZoom
                    ]
                    if let data = try? JSONSerialization.data(withJSONObject: state, options: [.sortedKeys]) {
                        self.uiTestWebState = String(decoding: data, as: UTF8.self)
                    }
                }
            }
    }
    #endif

    /// Load the web app's pair page; it pairs this phone and shows the laptop's chat.
    func openPair(_ link: PairLink) {
        guard let url = link.webURL(base: webView.url ?? AppConfiguration.webURL) else { return }
        webView.load(URLRequest(url: url))
    }

    init(url: URL) {
        coordinator = WebShell.Coordinator()
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.add(coordinator, name: "ar")
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = coordinator
        webView.scrollView.delegate = coordinator
        coordinator.pinZoom(in: webView.scrollView)
        webView.accessibilityIdentifier = "web-shell"
        // Let the page draw under the status bar and home indicator; it pads itself with env(safe-area-inset-*).
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.scrollView.backgroundColor = .clear
        webView.allowsBackForwardNavigationGestures = true
        // Load once for this session, independent of SwiftUI mounting the view.
        webView.load(URLRequest(url: url))
    }

    func prepareForAR() {
        viewportNeedsRestoration = true
        webView.endEditing(true)
        // A native cover keeps this page loaded, so WebKit need not emit its
        // normal page lifecycle events. Suspend the web's existing listeners.
        webView.evaluateJavaScript("window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true }))")
    }

    func resumeAfterAR() {
        // onDismiss may run before UIKit has reattached the presenting view.
        // viewDidAppear retries the same restoration after that attachment.
        DispatchQueue.main.async { [weak self] in self?.restoreViewportAfterAR() }
    }

    func restoreViewportAfterAR() {
        guard viewportNeedsRestoration, webView.window != nil,
              webView.bounds.width > 0, webView.bounds.height > 0 else { return }
        webView.superview?.setNeedsLayout()
        webView.superview?.layoutIfNeeded()
        webView.layoutIfNeeded()
        let scroll = webView.scrollView
        // Restore at the device-width scale, rather than preserving a scale
        // that WebKit may already have enlarged while focusing the composer.
        coordinator.pinZoom(in: scroll)
        let inset = scroll.adjustedContentInset
        scroll.setContentOffset(CGPoint(x: -inset.left, y: -inset.top), animated: false)
        viewportNeedsRestoration = false
        // Notify the page only after restoring its native viewport. Its existing
        // pageshow handler reveals the composer on the next animation frame.
        webView.evaluateJavaScript("window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }))")
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
        WebShellController(webView: session.webView, onAppear: session.restoreViewportAfterAR,
                           onLayout: { session.coordinator.pinZoom(in: session.webView.scrollView) })
    }

    func updateUIViewController(_ controller: WebShellController, context: Context) {
        context.coordinator.onARRequest = onARRequest
    }

    @MainActor
    final class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate, UIScrollViewDelegate {
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
            pinZoom(in: webView.scrollView)
            #if DEBUG
            if !injectedBridgeMessage, let script = AppConfiguration.debugBridgeScript {
                injectedBridgeMessage = true
                webView.evaluateJavaScript(script)
            }
            #endif
        }

        func pinZoom(in scrollView: UIScrollView) {
            // WebKit recalculates these limits when the keyboard or native
            // cover changes the viewport. Reapply after navigation and layout.
            scrollView.minimumZoomScale = 1
            scrollView.maximumZoomScale = 1
            scrollView.bouncesZoom = false
            if abs(scrollView.zoomScale - 1) > 0.001 {
                scrollView.setZoomScale(1, animated: false)
            }
        }

        func viewForZooming(in scrollView: UIScrollView) -> UIView? { nil }

        func scrollViewDidZoom(_ scrollView: UIScrollView) {
            pinZoom(in: scrollView)
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
    private let onAppear: () -> Void
    private let onLayout: () -> Void

    init(webView: WKWebView, onAppear: @escaping () -> Void, onLayout: @escaping () -> Void) {
        self.webView = webView
        self.onAppear = onAppear
        self.onLayout = onLayout
        super.init(nibName: nil, bundle: nil)
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        onLayout()
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
        onAppear()
    }
}
