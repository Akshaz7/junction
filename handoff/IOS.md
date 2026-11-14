# Handoff: IOS (Codex worker)

Row ID: I-02 (attempt 1)
Task: AR screen with RealityKit + ARKit in `ios/Hologram/AR/`:
- `ARSceneView` (SwiftUI wrapper of `ARView`): horizontal plane detection, coaching overlay, tap to place the scene on a detected surface.
- Load a USDZ scene (`Entity.load` / `ModelEntity`) from a URL, or from the bundled fixture `ios/Hologram/Resources/fixture.usdz` as the fallback.
- Gestures: pinch to scale, rotate, drag (`installGestures`), plus a scale slider from 1:100 to 1:1 (log scale; label shows "1:100" … "1:1") and a reset button.
- `SceneIndex`: walk the loaded entity tree and build `[usd_name: Entity]` (prim names are `usd_name`, CONTRACT 5.1: `"i_" + first 16 hex chars of sha1(item_id)`); also `func usdName(for itemId: String) -> String` (use CryptoKit Insecure.SHA1) so callers can look up by item_id.
- A way to open the AR screen from the shell (a toolbar button is fine for now; the bridge comes in I-04).
Fixture: the LEAD will drop `ios/Hologram/Resources/fixture.usdz` and `ios/Hologram/Resources/fixture.scene.json` (5 box prims; scene.json maps item_id -> usd_name) within ~20 minutes. Write the code first; if the files are not there yet when you reach the tests, wait/poll for them (check every 60 s, up to 20 min). Add them to the app target and the test target resources in `project.yml`.
Unit test (`HologramTests`): load the fixture USDZ (it loads without an ARView), build the SceneIndex, and find the entity for item_id `window-001` via `usdName(for:)`. Also test `usdName(for:)` against the value in fixture.scene.json.
Rules: only edit `ios/`. Heavy commands through `scripts/heavy.sh`. Build with `-derivedDataPath ios/build/DerivedData`. AR does not run in the simulator; unit tests that only load the entity are fine. If the simulator is not available in your sandbox, at least `build-for-testing` must succeed; the LEAD runs the tests outside the sandbox.
Input files: CONTRACT.md 5.1, 5.2, 5.5, 5.10; AGENTS.md
Done test command (LEAD runs): `cd ios && xcodegen generate && cd .. && scripts/heavy.sh xcodebuild test -project ios/Hologram.xcodeproj -scheme Hologram -destination 'platform=iOS Simulator,name=Hologram iPhone' -derivedDataPath ios/build/DerivedData CODE_SIGNING_ALLOWED=NO | tail -5` (must show `** TEST SUCCEEDED **`)
Last failed attempt (if any): none

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->
RESULT: I-02 implemented AR placement/coaching, URL loading with bundled demo fallback, pinch/rotate/drag, logarithmic 1:100–1:1 scale and reset, shell toolbar entry, and SHA-1 SceneIndex with fixture tests; xcodegen + heavy.sh xcodebuild build-for-testing succeeded with fixtures in both bundles (ios/build/i02-attempt3.log); CoreSimulator is unavailable in the sandbox, so LEAD must run the assigned test command.
