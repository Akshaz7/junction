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
}
