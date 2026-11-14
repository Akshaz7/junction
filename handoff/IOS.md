# Handoff: IOS (Codex worker)

Row ID: I-01 (attempt 1)
Task: Create the iOS app in `ios/` with XcodeGen (`ios/project.yml`). App name "Hologram", bundle id `com.teamrs3.hologram`, iOS 18+ deployment target, SwiftUI. Development team from env `APPLE_TEAM_ID` is NOT needed for the simulator; leave `DEVELOPMENT_TEAM` read from an `ios/Config/Local.xcconfig` that is git-ignored, with a committed `ios/Config/Local.example.xcconfig`. The shell is a SwiftUI `WKWebView` that loads `WEB_URL` from Info.plist (default `http://localhost:5173`), with `NSAppTransportSecurity` allowing local networking, and a script message handler named `ar` registered (it can just log for now; CONTRACT 5.10 says the web app posts `{doc_id, item_ids}` to it). Add a unit-test target `HologramTests` with one trivial test. Add camera usage description now (AR comes in I-02).
Rules: only edit `ios/`. Heavy commands go through `scripts/heavy.sh`. Always build with `-derivedDataPath ios/build/DerivedData` (git-ignored) so the build stays inside the repo. AR does not run in the simulator; that is fine.
Input files: CONTRACT.md 5.10, AGENTS.md
Done test command: `cd ios && xcodegen generate && cd .. && scripts/heavy.sh xcodebuild -project ios/Hologram.xcodeproj -scheme Hologram -destination 'generic/platform=iOS Simulator' -derivedDataPath ios/build/DerivedData build CODE_SIGNING_ALLOWED=NO | tail -3`  (must end with `** BUILD SUCCEEDED **`)
Last failed attempt (if any): none

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->
RESULT: I-01 passed on attempt 1: XcodeGen SwiftUI/WKWebView shell, WEB_URL/local ATS, validated ar bridge, camera permission, optional ignored signing config; done test ** BUILD SUCCEEDED **; unit-test target ** TEST BUILD SUCCEEDED ** (compiled only; sandbox CoreSimulator unavailable).
