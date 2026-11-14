# Handoff: IOS (Codex worker)

Row ID: I-06 (attempt 1)
Task: Walk mode at 1:1 on the AR screen: a "Walk" toggle that sets scale to 1:1 and aligns the model's floor (lowest storey elevation, or y=0) to the detected floor plane; a small "you are here" mini-map overlay (top-down 2D of the scene's bounding boxes from scene.json, a dot for the camera position projected into model coordinates, highlighted items in accent colour); and a guide arrow (a 3D arrow entity in front of the camera, or a 2D compass arrow in the overlay) pointing toward the highlighted item / camera target, with the distance in metres.
Put the maths in a pure Swift type `WalkGuide` (input: camera transform in model space, target bbox centre; output: bearing in degrees relative to the camera's heading, horizontal distance in metres, arrived flag under 1 m) so it is unit-testable without AR.
Unit tests for WalkGuide: target straight ahead gives bearing 0; target to the right gives +90; behind gives 180; arrived under 1 m; mini-map projection maps the scene bbox into the map rect.
Rules: only edit `ios/`. Build with `-derivedDataPath ios/build/DerivedData`; heavy commands via `scripts/heavy.sh`. Simulator unavailable in your sandbox: `build-for-testing` must pass; the LEAD runs tests.
Done test (LEAD runs): `scripts/heavy.sh xcodebuild test -project ios/Hologram.xcodeproj -scheme Hologram -destination 'platform=iOS Simulator,name=Hologram iPhone' -derivedDataPath ios/build/DerivedData CODE_SIGNING_ALLOWED=NO` → `** TEST SUCCEEDED **`
Last failed attempt (if any): none

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->
RESULT: I-06 implemented 1:1 Walk toggle with detected-floor placement and lowest-storey alignment, scene.json mini-map/camera dot, highlighted target arrow and metre distance; build-for-testing passed (ios/build/i06-build-for-testing.log), all 11 pure WalkGuide/manifest tests passed on the host (ios/build/i06-walk-guide-tests.log); simulator done test remains for LEAD as instructed.
