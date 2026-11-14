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

    var body: some Scene {
        WindowGroup {
            NavigationStack {
                WebShell(url: AppConfiguration.webURL, onARRequest: presentation.showAR)
                    .toolbar {
                        ToolbarItem(placement: .topBarTrailing) {
                            Button("Show on table", systemImage: "arkit") {
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
