import SwiftUI

@MainActor
final class ShellPresentation: ObservableObject {
    @Published var arRequest: ARRequest?
    private(set) var lastBridgeRequest: ARRequest?

    func showAR(_ request: ARRequest) {
        lastBridgeRequest = request
        arRequest = request
    }

    func showFromToolbar() {
        arRequest = lastBridgeRequest ?? ARRequest(docID: DemoScenes.all[0].id, itemIDs: [])
    }
}

@main
struct HologramApp: App {
    @StateObject private var presentation = ShellPresentation()
    @StateObject private var webSession = WebSession(url: AppConfiguration.webURL)
    // UI tests (and debugging) pass -NATIVE_TOOLBAR to get the native AR/demo entry points.
    private let showsNativeToolbar = ProcessInfo.processInfo.arguments.contains("-NATIVE_TOOLBAR")

    var body: some Scene {
        WindowGroup {
            Group {
                if showsNativeToolbar {
                    NavigationStack {
                        WebShell(session: webSession, onARRequest: presentation.showAR)
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                            .toolbar {
                                #if DEBUG
                                if webSession.allowsUITestInspection {
                                    ToolbarItem(placement: .topBarLeading) {
                                        Button("Inspect web state", systemImage: "stethoscope") {
                                            webSession.inspectWebStateForUITest()
                                        }
                                        .accessibilityIdentifier("inspect-web-state")
                                        .accessibilityValue(webSession.uiTestWebState)
                                    }
                                }
                                #endif
                                ToolbarItem(placement: .topBarTrailing) {
                                    Button("Show on table", systemImage: "arkit") {
                                        presentation.showFromToolbar()
                                    }
                                }
                            }
                    }
                } else {
                    // Stoa 1:1: the web page owns the whole screen (green header under the status bar,
                    // tab bar over the home indicator); AR opens from the web's own "Show on table".
                    WebShell(session: webSession, onARRequest: presentation.showAR)
                        .ignoresSafeArea()
                        .background(Color(red: 0.004, green: 0.118, blue: 0.004).ignoresSafeArea())
                }
            }
            .onChange(of: presentation.arRequest) { _, request in
                if request != nil { webSession.prepareForAR() }
            }
            .fullScreenCover(item: $presentation.arRequest, onDismiss: webSession.resumeAfterAR) { request in
                ARScreen(docID: request.docID, chatID: request.chatID, highlightedItemIDs: request.itemIDs)
                    .id(request.id)
            }
            .task {
                // Test build (AR_DEMO=1 install): open the bundled AC20 hologram straight away, six doors lit.
                if Bundle.main.object(forInfoDictionaryKey: "AR_DEMO") as? String == "YES" {
                    presentation.showAR(ARRequest(docID: DemoScenes.all[0].id, itemIDs: [
                        "3qloCPnZDEQBom1ZjBlwJP", "0_flqizUv5_A_EGt7DzP3T", "17n0YjYkvEshOmsrIPLGOb",
                        "31Gx3VvgP1fvwL2I0a9YtY", "0Xbk1qGZnCY9arQDkkuJ8L"]))
                    return
                }
                #if DEBUG
                if AppConfiguration.advisorFixtureURL != nil {
                    presentation.showAR(ARRequest(docID: "fixture__ios", itemIDs: []))
                }
                #endif
            }
        }
    }
}
