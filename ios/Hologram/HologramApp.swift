import SwiftUI

final class ShellPresentation: ObservableObject {
    @Published var showingAR = false
}

@main
struct HologramApp: App {
    @StateObject private var presentation = ShellPresentation()

    var body: some Scene {
        WindowGroup {
            NavigationStack {
                WebShell(url: AppConfiguration.webURL)
                    .toolbar {
                        ToolbarItem(placement: .topBarTrailing) {
                            Button("Show on table", systemImage: "arkit") { presentation.showingAR = true }
                        }
                    }
            }
            .fullScreenCover(isPresented: $presentation.showingAR) { ARScreen() }
        }
    }
}
