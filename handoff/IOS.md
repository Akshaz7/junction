# Handoff: IOS (Codex worker)

Row ID: I-08 (attempt 1)
Task: Tap to identify in AR: a tap on a placed scene entity resolves to its `item_id` (reverse of SceneIndex: usd_name -> item_id using the scene.json `items` map, which the AR screen should load next to the USDZ; the fixture has `fixture.scene.json`) and shows a SwiftUI card with name, kind, storey and properties when available (from scene.json; for IFC scenes later also from `GET /api/docs/{doc_id}` + elements). The tapped item gets a light outline/glow distinct from the answer highlight; tapping empty space dismisses the card.
Put the hit-test → item_id logic in a testable type (`ItemPicker`: given an Entity, walk up parents to the first entity whose name is a known usd_name, return the item_id).
Unit tests: ItemPicker resolves a child mesh of `window-001`'s prim to `window-001`; unknown entity returns nil; card model shows kind "window".
Rules: only edit `ios/`. `-derivedDataPath ios/build/DerivedData`; heavy commands via scripts/heavy.sh; simulator unavailable in your sandbox: build-for-testing must pass; the LEAD runs the tests.
Done test (LEAD runs): `scripts/heavy.sh xcodebuild test -project ios/Hologram.xcodeproj -scheme Hologram -destination 'platform=iOS Simulator,name=Hologram iPhone' -derivedDataPath ios/build/DerivedData CODE_SIGNING_ALLOWED=NO` → `** TEST SUCCEEDED **`
Last failed attempt (if any): none

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->

RESULT: I-08 implemented manifest-backed ItemPicker, metadata card, separate pale blue selection outline and empty-tap dismissal; four unit tests added; heavy.sh xcodebuild build-for-testing passed (ios/build/I-08-build.log); simulator test execution remains with LEAD.
