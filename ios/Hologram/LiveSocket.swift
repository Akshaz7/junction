import Combine
import Foundation

@MainActor
protocol LiveSocketConnection: AnyObject {
    func receive() async throws -> URLSessionWebSocketTask.Message
    func send(_ message: URLSessionWebSocketTask.Message) async throws
    func close()
}

@MainActor
private final class SessionLiveConnection: LiveSocketConnection {
    private let task: URLSessionWebSocketTask

    init(url: URL) {
        task = URLSession.shared.webSocketTask(with: url)
        task.resume()
    }

    func receive() async throws -> URLSessionWebSocketTask.Message { try await task.receive() }
    func send(_ message: URLSessionWebSocketTask.Message) async throws { try await task.send(message) }
    func close() { task.cancel(with: .goingAway, reason: nil) }
}

@MainActor
final class LiveSocket: ObservableObject {
    enum Command: Equatable {
        case highlight(ARRequest), edit(SceneEditEvent), state(SceneStateEvent)
        case advisorCards(AdvisorCardsEvent), ping, ignored
    }

    private struct Event: Codable {
        let type: String
        var doc_id: String? = nil
        var item_ids: [String]? = nil
        var chat_id: String? = nil
    }

    var onHighlight: ((ARRequest) -> Void)?
    var onEdit: ((SceneEditEvent) -> Void)?
    var onState: ((SceneStateEvent) -> Void)?
    var onAdvisorCards: ((AdvisorCardsEvent) -> Void)?
    private let apiURL: URL
    private var docID: String?
    private var chatID: String?
    private let makeConnection: (URL) -> any LiveSocketConnection
    private var connection: (any LiveSocketConnection)?
    private var receiveTask: Task<Void, Never>?

    init(apiURL: URL = AppConfiguration.apiURL,
         makeConnection: ((URL) -> any LiveSocketConnection)? = nil) {
        self.apiURL = apiURL
        self.makeConnection = makeConnection ?? { SessionLiveConnection(url: $0) }
    }

    nonisolated static func decode(_ data: Data) throws -> Command {
        let event = try JSONDecoder().decode(Event.self, from: data)
        switch event.type {
        case "ping": return .ping
        case "advisor.cards":
            let cards = try JSONDecoder().decode(AdvisorCardsEvent.self, from: data)
            return cards.doc_id.isEmpty ? .ignored : .advisorCards(cards)
        case "scene.edit":
            let edit = try JSONDecoder().decode(SceneEditEvent.self, from: data)
            return edit.doc_id.isEmpty ? .ignored : .edit(edit)
        case "scene.state":
            let state = try JSONDecoder().decode(SceneStateEvent.self, from: data)
            return state.doc_id.isEmpty ? .ignored : .state(state)
        case "scene.highlight":
            guard let docID = event.doc_id, !docID.isEmpty, let itemIDs = event.item_ids else {
                return .ignored
            }
            return .highlight(ARRequest(docID: docID, itemIDs: itemIDs, chatID: event.chat_id))
        default: return .ignored
        }
    }

    func start(docID: String? = nil, chatID: String? = nil) {
        if self.docID != docID || self.chatID != chatID { stop() }
        self.docID = docID
        self.chatID = chatID
        guard receiveTask == nil else { return }
        receiveTask = Task { [weak self] in
            var failures = 0
            while !Task.isCancelled {
                guard let socket = self?.openConnection() else { return }
                do {
                    while !Task.isCancelled {
                        let message = try await socket.receive()
                        try Task.checkCancellation()
                        let data: Data
                        switch message {
                        case .string(let text): data = Data(text.utf8)
                        case .data(let bytes): data = bytes
                        @unknown default: continue
                        }
                        // Other app events and malformed messages must not break live AR.
                        guard let event = try? JSONDecoder().decode(Event.self, from: data),
                              self?.accepts(event) == true,
                              let command = try? Self.decode(data) else { continue }
                        failures = 0
                        switch command {
                        case .highlight(let request): self?.onHighlight?(request)
                        case .edit(let edit): self?.onEdit?(edit)
                        case .state(let state): self?.onState?(state)
                        case .advisorCards(let event): self?.onAdvisorCards?(event)
                        case .ping: try await socket.send(.string("{\"type\":\"pong\"}"))
                        case .ignored: break
                        }
                    }
                } catch {
                    // Receive/send failure closes this connection before reconnecting.
                }
                socket.close()
                guard !Task.isCancelled else { return }
                let delay = Self.reconnectDelay(failures: failures)
                failures += 1
                do { try await Task.sleep(for: .seconds(delay)) }
                catch { return }
            }
        }
    }

    func stop() {
        receiveTask?.cancel()
        receiveTask = nil
        connection?.close()
        connection = nil
    }

    func sendHighlight(docID: String, itemIDs: [String]) async {
        guard let connection,
              let data = try? JSONEncoder().encode(Event(type: "scene.highlight", doc_id: docID,
                                                        item_ids: itemIDs, chat_id: chatID)),
              let text = String(data: data, encoding: .utf8) else { return }
        do { try await connection.send(.string(text)) }
        catch { connection.close() } // Wakes the receive loop and uses the same reconnect path.
    }

    nonisolated static func reconnectDelay(failures: Int) -> Double {
        min(pow(2, Double(min(max(failures, 0), 5))), 30)
    }

    private func openConnection() -> any LiveSocketConnection {
        var components = URLComponents(url: AppConfiguration.socketURL(apiURL: apiURL),
                                       resolvingAgainstBaseURL: false)!
        var query: [URLQueryItem] = []
        if let docID { query.append(URLQueryItem(name: "doc_id", value: docID)) }
        if let chatID { query.append(URLQueryItem(name: "chat_id", value: chatID)) }
        if !query.isEmpty { components.queryItems = query }
        let socket = makeConnection(components.url!)
        connection = socket
        return socket
    }

    private func accepts(_ event: Event) -> Bool {
        if let docID, let eventDoc = event.doc_id, eventDoc != docID { return false }
        if let chatID, let eventChat = event.chat_id, eventChat != chatID { return false }
        return true
    }
}
