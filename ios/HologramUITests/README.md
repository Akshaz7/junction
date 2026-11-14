I-12 tests use the running local web app (`http://localhost:4173`) and API
(`http://localhost:8000`). Start the stable web preview or local dev stack first.
The simulator reaches the Mac through localhost.

Generate the project after changing `project.yml`:

```sh
xcodegen generate --spec ios/project.yml
scripts/heavy.sh xcodebuild build-for-testing -project ios/Hologram.xcodeproj -scheme Hologram -destination 'generic/platform=iOS Simulator' -derivedDataPath ios/build/DerivedData CODE_SIGNING_ALLOWED=NO
```

The LEAD runs the UI tests outside the worker sandbox:

```sh
scripts/heavy.sh xcodebuild test -project ios/Hologram.xcodeproj -scheme Hologram -destination 'platform=iOS Simulator,name=Hologram iPhone' -derivedDataPath ios/build/DerivedData CODE_SIGNING_ALLOWED=NO
```

`WEB_URL` and `API_URL` support app launch arguments (`-WEB_URL URL`,
`-API_URL URL`) and environment variables, before Info.plist values. The tests
default to ports 4173/8000; the runner can use `WEB_URL=http://localhost:5173`.
They require scene metadata from the live API; an offline bundled fallback
does not satisfy the live smoke test.
The tests explicitly load `#/chat`, independent of the phone's default tab.
The composer is located by its accessible label “Ask about your drawings” or
placeholder “Ask anything. Type @ to include a document”. It must be hittable,
over 100 points wide and over 20 points tall, excluding the 2x2 sr-only label.
Native text views/fields take priority over ARIA combobox/other elements.
Typing starts only after the software keyboard appears.

Debug builds accept `-AR_BRIDGE_MESSAGE '{"doc_id":"…","item_ids":["…"]}'`
(or the matching environment variable). After the first navigation finishes,
the navigation delegate calls `evaluateJavaScript` to post this payload through
the actual `ar` message handler. The hook runs once per web view. Release builds
exclude this hook. The two AC20 door IDs in the test come from its bundled
`scene.json`.

The bridge test asserts the requested document and exactly two door highlights,
then checks that the native toolbar reopens the same selection and closing AR
returns to the chat starter. A separate draft test types an unsent draft and
checks that opening and closing AR preserves it in the original web view.
As permitted by the I-04 attempt 3 handoff, only the draft test skips if WebKit
exposes no full-sized input or cannot focus it; a screenshot and explicit reason
are attached. Routing and two-door assertions remain mandatory in their own test.

The simulator panel loads scene metadata and attribution without an AR session.
Each milestone saves a named screenshot attachment in the Xcode test results.
Its state uses `ObservableObject`/`StateObject`: this SDK's `State` macro cannot
launch its compiler plugin inside the worker sandbox.
