# Handoff: IOS (Codex worker)

Row ID: I-04 (attempt 1)
Task: Bridge and live link (native side; the web "Show on table" button is W-11 and comes later):
- The `ar` WKScriptMessageHandler (exists from I-01) parses `{doc_id, item_ids}` (CONTRACT 5.10) and opens the AR screen for that doc with those items highlighted (HighlightController, labels "1".."n" in the given order).
- Scene loading by doc_id: fetch `GET {API_BASE}/api/docs/{doc_id}/scene` (scene.json; CONTRACT 5.5 and docs/API.md), then the USDZ from `GET {API_BASE}/api/docs/{doc_id}/files/scene.usdz` into a cache dir; fall back to the bundled fixture when the network fails or the scene isn't built (404 `{"status":"not_built"}`). API_BASE derives from WEB_URL (same host, port 8000 for local dev; configurable in Info.plist as `API_URL`).
- Live link: a `LiveSocket` (URLSessionWebSocketTask) to `{API_BASE}/ws` that receives `scene.highlight {doc_id, item_ids}` and applies it when the doc matches the open AR scene, and SENDS `scene.highlight` when the user taps "highlight this" on an identified item (I-08 card). Reconnect with backoff; answer server `ping` with `pong` (see docs/API.md /ws section).
Unit tests: a test bridge message `{doc_id:"fixture__ios", item_ids:["window-001","door-001"]}` through the handler sets the router state to the AR screen with that doc_id and items; LiveSocket's message decoder turns a sample `scene.highlight` JSON into the right command; a non-matching doc is ignored.
Rules: only edit `ios/`. `-derivedDataPath ios/build/DerivedData`; heavy commands via scripts/heavy.sh; simulator unavailable in your sandbox: build-for-testing must pass; the LEAD runs the tests.
Done test (LEAD runs): `scripts/heavy.sh xcodebuild test -project ios/Hologram.xcodeproj -scheme Hologram -destination 'platform=iOS Simulator,name=Hologram iPhone' -derivedDataPath ios/build/DerivedData CODE_SIGNING_ALLOWED=NO` → `** TEST SUCCEEDED **`
Last failed attempt (if any): none

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->
RESULT: I-04 implemented native AR bridge routing, API_URL/WEB_URL resolution, manifest + cached USDZ downloads with labelled fixture fallback, and bidirectional live highlights with ping/pong and reconnect backoff; bridge/live/fallback unit tests added. Local scripts/heavy.sh xcodebuild build-for-testing -project ios/Hologram.xcodeproj -scheme Hologram -destination 'generic/platform=iOS Simulator' -derivedDataPath ios/build/DerivedData CODE_SIGNING_ALLOWED=NO passed (** TEST BUILD SUCCEEDED **); LEAD must run the simulator done test because CoreSimulator is inaccessible in the worker sandbox. XcodeGen project regenerated; no commit.
