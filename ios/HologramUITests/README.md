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

Debug builds accept `-AR_BRIDGE_MESSAGE '{"doc_id":"…","item_ids":["…"]}'`
(or the matching environment variable). A main-frame WKUserScript posts this
payload at document end through the actual `ar` message handler. Release builds
exclude this hook. The two AC20 door IDs in the test come from its bundled
`scene.json`.

The simulator panel loads scene metadata and attribution without an AR session.
Each milestone saves a named screenshot attachment in the Xcode test results.
Its state uses `ObservableObject`/`StateObject`: this SDK's `State` macro cannot
launch its compiler plugin inside the worker sandbox.
