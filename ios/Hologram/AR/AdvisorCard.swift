import Foundation
import OSLog

struct AdvisorCard: Codable, Equatable, Identifiable {
    enum Kind: String, Codable { case warning, option, info }
    struct Source: Codable, Equatable {
        enum SourceType: String, Codable { case rule, material_table, document }
        let type: SourceType
        let ref: String
        let title: String
        let quote: String
    }

    let card_id: String
    let kind: Kind
    let title: String
    let body: String
    let item_ids: [String]
    let source: Source
    /// "violation" | "suggestion" | "info"; absent on older servers.
    var severity: String? = nil
    /// Rule ids that were checked for this edit ("Checked: ..." line).
    var checked: [String]? = nil
    var id: String { card_id }

    enum Level: String { case violation, suggestion, info }

    /// Severity as the web card shows it; falls back to the kind when the server sent none.
    var level: Level {
        if let severity, let level = Level(rawValue: severity) { return level }
        switch kind {
        case .warning: return .violation
        case .option: return .suggestion
        case .info: return .info
        }
    }

    static func mostSevere(_ cards: [AdvisorCard]) -> AdvisorCard? {
        let order: [Level: Int] = [.violation: 0, .suggestion: 1, .info: 2]
        return cards.min { (order[$0.level] ?? 3) < (order[$1.level] ?? 3) }
    }
}

/// Shared by the POST response and WebSocket event. An unsupported claim never
/// becomes an AdvisorCard, so every rendering and selection path requires a source.
struct AdvisorCardsResponse: Decodable, Equatable {
    let cards: [AdvisorCard]
    private enum CodingKeys: String, CodingKey { case cards }
    private enum CardKeys: String, CodingKey { case source }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        var entries = try values.nestedUnkeyedContainer(forKey: .cards)
        var supported: [AdvisorCard] = []
        while !entries.isAtEnd {
            let entry = try entries.superDecoder()
            let fields = try entry.container(keyedBy: CardKeys.self)
            guard fields.contains(.source), try !fields.decodeNil(forKey: .source) else {
                AdvisorDiagnostics.missingSource()
                continue
            }
            let card = try AdvisorCard(from: entry)
            if supported.count < 3, !supported.contains(where: { $0.id == card.id }) {
                supported.append(card)
            }
        }
        cards = supported
    }
}

struct AdvisorCardsEvent: Decodable, Equatable {
    let doc_id: String
    let chat_id: String?
    let cards: [AdvisorCard]
    private enum CodingKeys: String, CodingKey { case doc_id, chat_id }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        doc_id = try values.decode(String.self, forKey: .doc_id)
        chat_id = try values.decodeIfPresent(String.self, forKey: .chat_id)
        cards = try AdvisorCardsResponse(from: decoder).cards
    }
}

private enum AdvisorDiagnostics {
    private static let lock = NSLock()
    private static var didLogMissingSource = false
    private static let logger = Logger(subsystem: "com.teamrs3.hologram", category: "Advisor")

    static func missingSource() {
        lock.lock()
        defer { lock.unlock() }
        guard !didLogMissingSource else { return }
        didLogMissingSource = true
        logger.warning("Dropped advisor card without a source. Further missing-source cards will be dropped silently.")
    }
}
