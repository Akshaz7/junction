import SwiftUI

@MainActor
final class ShellPresentation: ObservableObject {
    @Published var arRequest: ARRequest?

    func showAR(_ request: ARRequest) {
        arRequest = request
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
                                presentation.showAR(ARRequest(docID: "fixture__ios", itemIDs: []))
                            }
                        }
                    }
            }
            .fullScreenCover(item: $presentation.arRequest) { request in
                ARScreen(docID: request.docID, highlightedItemIDs: request.itemIDs)
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
