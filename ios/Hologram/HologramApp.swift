import SwiftUI

@main
struct HologramApp: App {
    var body: some Scene {
        WindowGroup {
            WebShell(url: AppConfiguration.webURL)
        }
    }
}
