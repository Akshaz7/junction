# IOS: row I-17 (Codex). AR correctness fixes
Scope: ios/ only.
1. The AR top-right scene label must show the document actually loaded. In one test it said "AC20 · IFC building" while a different house model was shown. Find out why: requestedDocID vs the loaded manifest doc_id, demo fallback, or the web request docID. Show the real title, and say clearly when a fallback scene is shown.
2. Opening AR from the web for document X must load X, and highlight the answer items from that chat.
3. Answer tags: stagger by projected SCREEN position every few frames (not model position), so tags that line up along the view direction never overlap. Hide the far one if two still collide.
4. Keep the AR_DEMO switch, the occlusion settings (personSegmentationWithDepth + sceneReconstruction), real materials and amber highlights.
Done test:
- unit + UI tests on the simulator via scripts/heavy.sh xcodebuild (see ios/README.md) all pass.
- a generic iOS device build compiles.
Do not commit. Do not install to the device. Append a RESULT: line.

IMPLEMENTED: I-17 — title now follows the loaded manifest/document metadata with visible fallback/offline notice; reject USDZ prims inconsistent with the manifest; retain bridge answer items during initial chat-state restore; reset native route per document/chat; project and stagger tags every fourth frame, reserving nearer tags and hiding farther collisions. AR_DEMO, occlusion and amber/real materials preserved.
CHECKS: Simulator build-for-testing PASS (arm64/x86_64); unsigned generic iOS device build PASS; two projected-layout checks PASS in a host assertion runner. Logs: ios/build/I-17-simulator-build.log, ios/build/I-17-device-build.log, ios/build/I-17-simulator-tests.log. No commit or device install. Concurrent CutawayPolicy.swift/keep changes were preserved and included in the final successful builds.
blocked: I-17 simulator unit/UI execution cannot start: CoreSimulatorService connection invalid; xcodebuild cannot find Hologram iPhone (exit 70). Full done test pending; no passing RESULT recorded.
NEEDS: LEAD run scripts/heavy.sh xcodebuild test -project ios/Hologram.xcodeproj -scheme Hologram -destination 'platform=iOS Simulator,name=Hologram iPhone' -derivedDataPath ios/build/DerivedData CODE_SIGNING_ALLOWED=NO outside the worker sandbox with the stable web/API running; append RESULT only if the suite passes.
