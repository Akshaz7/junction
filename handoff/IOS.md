# Handoff: IOS (Codex worker)

Row ID: I-14 (attempt 1)
Task: Scene commands in AR (Ash's idea: "show me all the windows" → each window glows with its tag W1..Wn; "remove window W7" → it disappears live on the table). Read CONTRACT.md 5.11 (new, v3). The server side (S-10) and engine side (E-20) are being built now; build the client to the contract:
- Decode `scene.edit` and `scene.state` from the existing LiveSocket (/ws) and `evidence.scene.commands` from chat answers (voice flow from I-07).
- Apply in order to the open AR scene: `highlight` (HighlightController with `labels` as the tag text above each item), `hide` (fade out ~250 ms, then disable the entity; keep it restorable), `restore` (fade in), `isolate` (hide everything except the given ids), `reset` (show all, clear highlight). Ignore events for other doc_ids.
- Tag labels: use `labels` when given, else `scene.json items[id].tag` when present.
- Keep the CutawayPolicy (I-10): an item hidden by cutaway stays hidden; a highlight on a hidden storey switches the storey.
Unit tests (fixture scene): a `scene.edit` hide removes window-001 from the visible set and restore brings it back; isolate leaves only the given ids; reset clears; `scene.state` on join reproduces hidden + highlighted; events for another doc are ignored; tag labels render from `labels`.
Rules: only edit `ios/`. `-derivedDataPath ios/build/DerivedData`; heavy commands via scripts/heavy.sh; simulator unavailable in your sandbox: build-for-testing must pass; the LEAD runs the tests.
Done test (LEAD runs): `scripts/heavy.sh xcodebuild test -project ios/Hologram.xcodeproj -scheme Hologram -destination 'platform=iOS Simulator,name=Hologram iPhone' -derivedDataPath ios/build/DerivedData CODE_SIGNING_ALLOWED=NO` → `** TEST SUCCEEDED **`
Last failed attempt (if any): none

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->

RESULT: I-14 implemented ordered scene.edit/scene.state and voice commands, restorable 250 ms fades, isolate/reset, explicit/manifest tag labels, document filtering and cutaway precedence; fixture and socket-order tests added. Local build-for-testing: ** TEST BUILD SUCCEEDED **; generic iOS build: ** BUILD SUCCEEDED ** (both via heavy.sh, CODE_SIGNING_ALLOWED=NO, ios/build/DerivedData). Logs: ios/build/I-14-build-for-testing.log and ios/build/I-14-device-build.log. Runtime done test remains for LEAD outside the CoreSimulator-restricted sandbox; no commits.
