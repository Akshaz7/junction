import Foundation

enum AppConfiguration {
    static var webURL: URL {
        let configured = Bundle.main.object(forInfoDictionaryKey: "WEB_URL") as? String
        if let configured, let url = URL(string: configured),
           let scheme = url.scheme, ["http", "https"].contains(scheme),
           url.host != nil {
            return url
        }
        return URL(string: "http://localhost:5173")!
    }

    static var apiURL: URL {
        apiURL(webURL: webURL, configured: Bundle.main.object(forInfoDictionaryKey: "API_URL") as? String)
    }

    static func apiURL(webURL: URL, configured: String?) -> URL {
        if let configured, let url = URL(string: configured),
           ["http", "https"].contains(url.scheme ?? ""), url.host != nil {
            return url
        }
        var components = URLComponents(url: webURL, resolvingAgainstBaseURL: false)!
        let host = components.host ?? ""
        if ["localhost", "127.0.0.1", "::1", "[::1]"].contains(host)
            || host.hasSuffix(".local") || host.hasPrefix("192.168.") || host.hasPrefix("10.")
            || (host.split(separator: ".").count == 4 && host.hasPrefix("172.")
                && (16...31).contains(Int(host.split(separator: ".")[1]) ?? 0))
            || [5173, 4173].contains(components.port ?? 0) {
            components.port = 8000
        }
        components.path = ""
        components.query = nil
        components.fragment = nil
        return components.url!
    }

    static func socketURL(apiURL: URL) -> URL {
        var components = URLComponents(url: apiURL.appendingPathComponent("ws"),
                                       resolvingAgainstBaseURL: false)!
        components.scheme = apiURL.scheme == "https" ? "wss" : "ws"
        return components.url!
    }
}
