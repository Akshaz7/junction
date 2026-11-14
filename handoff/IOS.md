# Handoff: IOS (Codex worker)

Row ID: I-09 (attempt 1)  — Advisor cards in AR (tier 3; build against a fixture, ENGINE's E-16 lands later)
Read CONTRACT.md §5.12 (advisor card shape, v3.1) and §5.8 (voice guide).
Do:
1. `AdvisorCard` Codable model exactly per §5.12; decode from `POST /api/advise` responses and from `/ws` event `advisor.cards` in LiveSocket.
2. AR overlay: up to 3 compact cards stacked at the bottom (glass material, kind icon, title, body, source title + quote in a disclosure). Tapping a card highlights its item_ids in the AR scene like a citation (reuse the existing highlight path) and shows their tags. Cards without a `source` are dropped and never rendered (log once).
3. Fixture `ios/HologramTests/Fixtures/advisor_cards.json` (3 cards, one with no source to prove it is dropped), unit tests for decoding + dropping + tap→highlight, and an XCUITest that injects the fixture (launch argument) and sees 2 cards.
Rules: only ios/. No device install. Build via scripts/heavy.sh with CODE_SIGNING_ALLOWED=NO.
Done test (LEAD runs): `scripts/heavy.sh xcodebuild test -project ios/Hologram.xcodeproj -scheme Hologram -destination 'platform=iOS Simulator,name=Hologram iPhone' -derivedDataPath ios/build/DerivedData CODE_SIGNING_ALLOWED=NO` → `** TEST SUCCEEDED **`
Last failed attempt (if any): none

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->
