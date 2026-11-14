# Handoff: IOS (Codex worker)

Row ID: I-11 (attempt 1)
Task: Offline demo scenes. Copy the real scenes into the app bundle and add a "Demo scenes" picker on the AR screen:
- `artifacts/ifc_bench__ac20-arc/scene.usdz` + `scene.json` (IFC building, KIT licence: publishable) and `artifacts/cubicasa5k__colorful-11397/scene.usdz` + `scene.json` (extruded plan; CC BY-NC-SA: OK for this non-commercial demo; show its credit). Put them under `ios/Hologram/Resources/DemoScenes/<doc_id>/`. Add a small script `ios/scripts/sync_demo_scenes.sh` that copies them from artifacts/ (so they can be refreshed later), and run it once. Check `publishable` in scene.json and refuse false.
- Loading order for a doc_id: network (API) first; if unreachable or not built, the bundled copy; then the old 5-box fixture.
- Show the licence credit for the scene in the AR overlay (from scene.json/doc: ac20 "KIT", colorful-11397 the CubiCasa5K credit; read them from `artifacts/<doc_id>/doc.json` `credit` when syncing and store them next to the scene).
Unit test: load the bundled ac20 USDZ, build SceneIndex, find a door prim by `usd_name` from its scene.json; the loader picks the bundled copy when the network fetch fails (inject a failing fetcher).
Rules: only edit `ios/`. Keep total added resources under 30 MB (report the size). `-derivedDataPath ios/build/DerivedData`; heavy commands via scripts/heavy.sh; simulator unavailable in your sandbox: build-for-testing must pass; the LEAD runs the tests.
Done test (LEAD runs): `scripts/heavy.sh xcodebuild test -project ios/Hologram.xcodeproj -scheme Hologram -destination 'platform=iOS Simulator,name=Hologram iPhone' -derivedDataPath ios/build/DerivedData CODE_SIGNING_ALLOWED=NO` → `** TEST SUCCEEDED **`
Last failed attempt (if any): none

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->
RESULT: I-11 implemented offline scene picker, API → bundled scene → labelled fixture fallback, source credits/licences and publishable-only sync; added resources total 1,715,251 bytes (under 30 MB); build-for-testing passed with ios/build/DerivedData, sync refusal and built bundle checks passed; real AC20 door SceneIndex and injected-fetch fallback tests compiled; LEAD must run simulator done test (CoreSimulator unavailable in sandbox). Xcode's State macro requires sandboxed plugin execution, so picker selection uses the existing ObservableObject.
