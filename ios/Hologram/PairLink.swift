import Foundation

/// `hologram://pair?code=XXXX` from the laptop's "Pair a phone" QR. Opens the app's web chat on the pair page.
struct PairLink: Equatable {
    let code: String

    init?(url: URL) {
        guard url.scheme?.lowercased() == "hologram",
              url.host?.lowercased() == "pair" || url.path.lowercased() == "/pair",
              let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems,
              let raw = items.first(where: { $0.name == "code" })?.value else { return nil }
        let code = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-_"))
        guard (1...64).contains(code.count), code.unicodeScalars.allSatisfy(allowed.contains) else { return nil }
        self.code = code
    }

    /// The web app's own pair route, on the configured web origin: `<web>/#/pair?code=XXXX`.
    func webURL(base: URL) -> URL? {
        var parts = URLComponents(url: base, resolvingAgainstBaseURL: false)
        parts?.path = "/"
        parts?.query = nil
        parts?.fragment = "/pair?code=\(code)"
        return parts?.url
    }
}
