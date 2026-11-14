import XCTest
@testable import Hologram

/// The "remove the front door, is it still compliant?" turn: hide command plus a sourced violation card.
@MainActor
final class AdvisorEditTests: XCTestCase {
    static let answerJSON = #"""
    {"answer":{"text_md":"Door D34 is hidden. **Not compliant after this edit:** Fewer than two exits left on Erdgeschoss (33 §)."},
     "evidence":{"boxes":[],"scene":{"doc_id":"ifc_bench__ac20-arc","highlight_item_ids":[],"camera_target_item_id":null,
       "commands":[{"op":"hide","item_ids":["door-34"],"labels":{"door-34":"D34"}}]}},
     "advisor_cards":[
      {"card_id":"adv:exits:Erdgeschoss:1","kind":"warning","title":"Fewer than two exits left on Erdgeschoss",
       "body":"Violation of 848/2017 §33: hiding D34 leaves 1 exit on Erdgeschoss.","item_ids":["door-34"],
       "source":{"type":"rule","ref":"fi-fire-exits-per-storey","title":"848/2017, 33 §","quote":"Each evacuation area"},
       "severity":"violation","checked":["fi-fire-exit-width","fi-fire-exits-per-storey","fi-use-headroom","a","b"]},
      {"card_id":"s1","kind":"option","title":"Only 1 exit found","body":"Inferred.","item_ids":["door-1"],
       "source":{"type":"rule","ref":"r","title":"t","quote":"q"},"severity":"suggestion"}]}
    """#

    private func answer() throws -> VoiceAnswer {
        try JSONDecoder().decode(VoiceAnswer.self, from: Data(Self.answerJSON.utf8))
    }

    func testVoiceAnswerCarriesSeverityCheckedAndHideCommand() throws {
        let answer = try answer()
        XCTAssertEqual(answer.evidence.scene.commands?.first?.op, .hide)
        let cards = try XCTUnwrap(answer.advisor_cards)
        XCTAssertEqual(cards.count, 2)
        XCTAssertEqual(cards[0].level, .violation)
        XCTAssertEqual(cards[0].checked?.count, 5)
        XCTAssertEqual(AdvisorCard.mostSevere(cards.reversed())?.id, "adv:exits:Erdgeschoss:1")
    }

    func testAnswerWithoutCardsStillDecodes() throws {
        let plain = #"{"answer":{"text_md":"x"},"evidence":{"boxes":[],"scene":{"doc_id":"d","highlight_item_ids":[]}}}"#
        XCTAssertNil(try JSONDecoder().decode(VoiceAnswer.self, from: Data(plain.utf8)).advisor_cards)
    }

    func testLevelFallsBackToKindWhenServerSendsNoSeverity() throws {
        var card = try XCTUnwrap(try answer().advisor_cards?.first)
        card.severity = nil
        XCTAssertEqual(card.level, .violation)
        XCTAssertEqual(AdvisorCallout.chipLabel(card.level), "Violation")
    }

    func testCheckedLineIsShortAndNamesTheRest() throws {
        let card = try XCTUnwrap(try answer().advisor_cards?.first)
        XCTAssertEqual(AdvisorCallout.checkedLine(card),
                       "Checked: fi-fire-exit-width, fi-fire-exits-per-storey, fi-use-headroom +2 more")
    }

    func testEditCardsSpotlightViolationAndUndoClearsThem() throws {
        let controller = AdvisorCardsController()
        let cards = try XCTUnwrap(try answer().advisor_cards)
        controller.setEditCards(cards.reversed(), docID: "ifc_bench__ac20-arc")
        XCTAssertEqual(controller.spotlight?.level, .violation)
        XCTAssertEqual(controller.cards.count, 2)
        controller.clearEditCards()
        XCTAssertNil(controller.spotlight)
        XCTAssertTrue(controller.cards.isEmpty)
    }

    /// Opt in with `TEST_RUNNER_HOLOGRAM_LIVE_API=1`: asks by the voice path (the same VoiceClient the mic
    /// uses) in a fresh chat on the deployed API, then reads the chat back as the laptop would.
    func testLiveVoiceTurnLandsInTheChatWithAdvisorCard() async throws {
        guard ProcessInfo.processInfo.environment["HOLOGRAM_LIVE_API"] == "1" else {
            throw XCTSkip("set TEST_RUNNER_HOLOGRAM_LIVE_API=1 to run against the deployed API")
        }
        let base = URL(string: "https://hologram-khaki.vercel.app")!
        let doc = "ifc_bench__ac20-arc"
        var create = URLRequest(url: base.appendingPathComponent("api/chats"))
        create.httpMethod = "POST"
        create.setValue("application/json", forHTTPHeaderField: "Content-Type")
        create.httpBody = try JSONSerialization.data(withJSONObject: ["doc_ids": [doc], "title": "smoke-ios-voice"])
        let (created, _) = try await URLSession.shared.data(for: create)
        let chatID = try XCTUnwrap((try JSONSerialization.jsonObject(with: created) as? [String: Any])?["id"] as? String)

        let client = VoiceClient(baseURL: base)
        let hide = try await client.ask("remove the front door, is it still compliant?", docID: doc, chatID: chatID) { _ in }
        XCTAssertEqual(hide.evidence.scene.commands?.first?.op, .hide)
        let card = try XCTUnwrap(hide.advisor_cards?.first)
        XCTAssertEqual(card.level, .violation)
        XCTAssertTrue(card.body.contains("848/2017"))
        let undo = try await client.ask("put it back", docID: doc, chatID: chatID) { _ in }
        XCTAssertEqual(undo.evidence.scene.commands?.first?.op, .restore)

        let (chat, _) = try await URLSession.shared.data(from: base.appendingPathComponent("api/chats/\(chatID)"))
        let text = String(decoding: chat, as: UTF8.self)
        XCTAssertTrue(text.contains("remove the front door"))
        XCTAssertTrue(text.contains("put it back"))
        XCTAssertTrue(text.contains("Fewer than two exits"))
    }
}
