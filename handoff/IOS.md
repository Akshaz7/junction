# Handoff: IOS (Codex worker)

Row ID: I-10 (attempt 1)
Task: Cutaway view in AR (Ash's request: roofs hide the answer items). When a scene loads on the table: hide roof elements and every storey above the active storey (active = the storey of the answer's camera target / first highlighted item; else the lowest storey with elevation >= 0). Identify roofs/storeys from scene.json `items[item_id].kind` ("roof", or IfcCovering of roof type in `kind`/props if present) and `items[..].storey` / `storeys[]` elevations (CONTRACT 5.5). Add a "Show roof" toggle and a storey stepper (up/down) in the AR overlay. Walk mode (1:1) keeps the cutaway but allows the toggle.
Put the visibility logic in a pure type `CutawayPolicy` (input: scene manifest + active storey + showRoof; output: set of usd_names to hide).
Unit tests: a manifest with 3 storeys + a roof: default hides the roof and storeys above the active one; showRoof=true shows the roof; active storey from the highlighted item.
Rules: only edit `ios/`. `-derivedDataPath ios/build/DerivedData`; heavy commands via scripts/heavy.sh; simulator unavailable in your sandbox: build-for-testing must pass; the LEAD runs the tests.
Done test (LEAD runs): `scripts/heavy.sh xcodebuild test -project ios/Hologram.xcodeproj -scheme Hologram -destination 'platform=iOS Simulator,name=Hologram iPhone' -derivedDataPath ios/build/DerivedData CODE_SIGNING_ALLOWED=NO` → `** TEST SUCCEEDED **`
Last failed attempt (if any): none

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->
RESULT: I-10 implemented pure CutawayPolicy, answer-selected storey cutaway, Show roof toggle, bounded storey controls, hidden item/label handling, and walk-mode persistence; six unit/integration tests added; scripts/heavy.sh xcodebuild build-for-testing -project ios/Hologram.xcodeproj -scheme Hologram -destination 'generic/platform=iOS Simulator' -derivedDataPath ios/build/DerivedData CODE_SIGNING_ALLOWED=NO passed (** TEST BUILD SUCCEEDED **); simulator test execution remains for LEAD per handoff.
