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
        case highlight(ARRequest), ping, ignored
    }

    private struct Event: Codable {
        let type: String
        var doc_id: String? = nil
        var item_ids: [String]? = nil
    }

    var onHighlight: ((ARRequest) -> Void)?
    private let url: URL
    private let makeConnection: (URL) -> any LiveSocketConnection
    private var connection: (any LiveSocketConnection)?
    private var receiveTask: Task<Void, Never>?

    init(apiURL: URL = AppConfiguration.apiURL,
         makeConnection: ((URL) -> any LiveSocketConnection)? = nil) {
        url = AppConfiguration.socketURL(apiURL: apiURL)
        self.makeConnection = makeConnection ?? { SessionLiveConnection(url: $0) }
    }

    nonisolated static func decode(_ data: Data) throws -> Command {
        let event = try JSONDecoder().decode(Event.self, from: data)
        switch event.type {
        case "ping": return .ping
        case "scene.highlight":
            guard let docID = event.doc_id, !docID.isEmpty, let itemIDs = event.item_ids else {
                return .ignored
            }
            return .highlight(ARRequest(docID: docID, itemIDs: itemIDs))
        default: return .ignored
        }
    }

    func start() {
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
                        guard let command = try? Self.decode(data) else { continue }
                        failures = 0
                        switch command {
                        case .highlight(let request): self?.onHighlight?(request)
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
                                                        item_ids: itemIDs)),
              let text = String(data: data, encoding: .utf8) else { return }
        do { try await connection.send(.string(text)) }
        catch { connection.close() } // Wakes the receive loop and uses the same reconnect path.
    }

    nonisolated static func reconnectDelay(failures: Int) -> Double {
        min(pow(2, Double(min(max(failures, 0), 5))), 30)
    }

    private func openConnection() -> any LiveSocketConnection {
        let socket = makeConnection(url)
        connection = socket
        return socket
    }
}
