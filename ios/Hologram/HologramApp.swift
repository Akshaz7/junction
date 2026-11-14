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

    var body: some Scene {
        WindowGroup {
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
                                webSession.prepareForAR()
                                presentation.showFromToolbar()
                            }
                        }
                    }
            }
            .fullScreenCover(item: $presentation.arRequest) { request in
                ARScreen(docID: request.docID, chatID: request.chatID, highlightedItemIDs: request.itemIDs)
                    .id(request.docID)
            }
            .task {
                #if DEBUG
                if AppConfiguration.advisorFixtureURL != nil {
                    presentation.showAR(ARRequest(docID: "fixture__ios", itemIDs: []))
                }
                #endif
            }
        }
    }
}
