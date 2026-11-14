# Handoff: IOS (Codex worker)

Row ID: I-12 (attempt 1)
Task: Add a UI test target `HologramUITests` (XCUITest) via project.yml with a smoke flow against the LOCAL stack (web on http://localhost:5173 or the stable build http://localhost:4173, API on http://localhost:8000; the simulator reaches the Mac's localhost directly):
1. Launch the app with a launch argument `-WEB_URL http://localhost:4173` (support overriding Info.plist WEB_URL via launch arguments/environment).
2. Wait for the web shell: the WKWebView shows the chat start screen (query the web view's static text, e.g. "Where shall we start?", or an accessibility identifier you expose).
3. Open the native Demo scenes picker, choose ac20. AR doesn't run in the simulator: make the AR screen show a clear non-AR fallback in the simulator (`#if targetEnvironment(simulator)`: a SceneKit/RealityKit non-AR preview of the scene, or at minimum a "AR needs an iPhone" panel listing the loaded scene name, item count and credit); assert the credit text is visible.
4. Simulate a bridge message (a debug-only launch argument that injects `{doc_id:"ifc_bench__ac20-arc", item_ids:[…two door GUIDs from its scene.json…]}`) and assert the AR route opened with that doc_id.
Attach screenshots with XCTAttachment at each step.
Rules: only edit `ios/`. Simulator unavailable in your sandbox: `build-for-testing` must pass; the LEAD runs the UI tests with the stack up.
Done test (LEAD runs): `scripts/heavy.sh xcodebuild test -project ios/Hologram.xcodeproj -scheme Hologram -destination 'platform=iOS Simulator,name=Hologram iPhone' -derivedDataPath ios/build/DerivedData CODE_SIGNING_ALLOWED=NO` → `** TEST SUCCEEDED **` including HologramUITests
Last failed attempt (if any): none

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->
RESULT: I-12 worker validation passed: xcodegen + scripts/heavy.sh xcodebuild build-for-testing (generic iOS Simulator, ios/build/DerivedData, CODE_SIGNING_ALLOWED=NO) -> ** TEST BUILD SUCCEEDED ** with HologramTests and HologramUITests; added launch argument/environment WEB_URL/API_URL overrides, simulator metadata/credit panel, and two screenshot-attaching live smoke tests including actual WebKit bridge injection with AC20 door GUIDs. LEAD must run the assigned simulator done test with web :4173 and API :8000 up; UI execution remains unverified in this sandbox. Details: ios/HologramUITests/README.md; build log: ios/build/I-12-build.log.
