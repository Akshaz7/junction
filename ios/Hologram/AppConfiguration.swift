import Foundation

enum AppConfiguration {
    static var webURL: URL {
        let configured = value(for: "WEB_URL")
        if let configured, let url = URL(string: configured),
           let scheme = url.scheme, ["http", "https"].contains(scheme),
           url.host != nil {
            return url
        }
        return URL(string: "http://localhost:5173")!
    }

    static var apiURL: URL {
        apiURL(webURL: webURL, configured: value(for: "API_URL"))
    }

    static func value(for key: String, arguments: [String] = ProcessInfo.processInfo.arguments,
                      environment: [String: String] = ProcessInfo.processInfo.environment,
                      configured: String? = nil) -> String? {
        if let index = arguments.firstIndex(of: "-\(key)"), arguments.indices.contains(index + 1) {
            let value = arguments[index + 1].trimmingCharacters(in: .whitespacesAndNewlines)
            if !value.isEmpty, !value.hasPrefix("-") { return value }
        }
        if let value = environment[key]?.trimmingCharacters(in: .whitespacesAndNewlines), !value.isEmpty {
            return value
        }
        return configured ?? Bundle.main.object(forInfoDictionaryKey: key) as? String
    }

    static var advisorFixtureURL: URL? {
        #if DEBUG
        guard value(for: "ADVISOR_FIXTURE") == "advisor_cards" else { return nil }
        return Bundle.main.url(forResource: "advisor_cards", withExtension: "json")
        #else
        return nil
        #endif
    }

    #if DEBUG
    // Exercise the actual JavaScript -> WKScriptMessageHandler path in XCUITest.
    static var debugBridgeScript: String? {
        guard let payload = value(for: "AR_BRIDGE_MESSAGE"),
              let body = try? JSONSerialization.jsonObject(with: Data(payload.utf8)),
              ARRequest(body: body) != nil,
              let data = try? JSONSerialization.data(withJSONObject: body),
              let json = String(data: data, encoding: .utf8) else { return nil }
        return "window.webkit.messageHandlers.ar.postMessage(\(json));"
    }
    #endif

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
