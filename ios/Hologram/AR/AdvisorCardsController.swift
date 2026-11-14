import Combine
import Foundation
import OSLog

struct AdvisorClient {
    var baseURL: URL = AppConfiguration.apiURL
    var session: URLSession = .shared

    func advise(docID: String) async throws -> AdvisorCardsResponse {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/advise"))
        request.httpMethod = "POST"
        request.timeoutInterval = 15
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["doc_id": docID])
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
        return try JSONDecoder().decode(AdvisorCardsResponse.self, from: data)
    }
}

@MainActor
final class AdvisorCardsController: ObservableObject {
    @Published private(set) var cards: [AdvisorCard] = []
    /// The most severe card from the latest edit: shown anchored on the model until dismissed or undone.
    @Published private(set) var spotlight: AdvisorCard?
    private(set) var docID: String?
    private var revision = 0
    private let client: AdvisorClient

    init(client: AdvisorClient = AdvisorClient()) { self.client = client }

    func clear() {
        revision += 1
        docID = nil
        cards = []
        spotlight = nil
    }

    /// Cards that came with a voice answer (an edit such as "remove the front door").
    func setEditCards(_ newCards: [AdvisorCard], docID: String) {
        revision += 1
        self.docID = docID
        cards = Array(newCards.prefix(3))
        spotlight = AdvisorCard.mostSevere(cards)
    }

    /// Edit undone or reset: the checks no longer describe the model.
    func clearEditCards() {
        revision += 1
        cards = []
        spotlight = nil
    }

    func dismissSpotlight() { spotlight = nil }

    func load(docID: String, fixtureURL: URL? = nil) async {
        revision += 1
        let loadingRevision = revision
        self.docID = docID
        cards = []
        spotlight = nil
        do {
            let response: AdvisorCardsResponse
            if let fixtureURL {
                response = try JSONDecoder().decode(AdvisorCardsResponse.self, from: Data(contentsOf: fixtureURL))
            } else {
                response = try await client.advise(docID: docID)
            }
            try Task.checkCancellation()
            // A live update or a different scene supersedes an in-flight POST.
            guard revision == loadingRevision else { return }
            cards = response.cards
        } catch is CancellationError {
            return
        } catch {
            Logger(subsystem: "com.teamrs3.hologram", category: "Advisor")
                .debug("Advisor cards unavailable for the current scene.")
        }
    }

    func receive(_ event: AdvisorCardsEvent) {
        guard event.doc_id == docID else { return }
        revision += 1
        cards = event.cards
        spotlight = AdvisorCard.mostSevere(event.cards)
    }

    @discardableResult
    func select(_ card: AdvisorCard, highlight: (ARRequest) -> Void) -> Bool {
        guard let docID, cards.contains(card) else { return false }
        highlight(ARRequest(docID: docID, itemIDs: card.item_ids))
        return true
    }
}
