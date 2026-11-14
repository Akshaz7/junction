# Handoff: IOS (Codex worker)

Row ID: I-07 (attempt 1)  [tier 3; dependencies I-04 native side and S-08 are done]
Task: Voice in AR: a microphone button on the AR screen. Record with AVAudioRecorder (m4a/wav, max 15 s, visual level meter), then POST it to `{API_BASE}/api/speech-intent` (multipart `file`; docs/API.md). If the response is `{"fallback":"device"}` (no Gemini key yet; this is the CURRENT behaviour), transcribe on device with SFSpeechRecognizer (en-US) instead. Send the text as a chat message (`POST /api/chats/{id}/messages` with the AR screen's doc_id; create a chat if none), read the SSE stream, show the answer text in an overlay, apply its `evidence.scene.highlight_item_ids` + box labels to the AR highlight, and speak the answer: `POST /api/tts {text}` → play mp3 (AVAudioPlayer); if that returns `{"fallback":"device"}`, use AVSpeechSynthesizer. Add the mic and speech-recognition usage descriptions to Info.plist.
Unit tests (no network, no audio hardware): the request builder for speech-intent multipart; the SSE parser turns a sample stream (status/trace/answer) into an answer model; the fallback decision (`{"fallback":"device"}` → device path); the highlight mapping from an answer.
Rules: only edit `ios/`. `-derivedDataPath ios/build/DerivedData`; heavy commands via scripts/heavy.sh; simulator unavailable in your sandbox: build-for-testing must pass; the LEAD runs the tests.
Done test (LEAD runs): `scripts/heavy.sh xcodebuild test -project ios/Hologram.xcodeproj -scheme Hologram -destination 'platform=iOS Simulator,name=Hologram iPhone' -derivedDataPath ios/build/DerivedData CODE_SIGNING_ALLOWED=NO` → `** TEST SUCCEEDED **`
Last failed attempt (if any): none

---
<!-- Worker appends RESULT: or NEEDS: lines below. -->

RESULT: I-07 implemented: 15 s m4a recording + level meter, speech-intent/device en-US transcription, document-scoped chat SSE, answer overlay + numbered AR highlights, server/device speech, and usage descriptions. Local build-for-testing: ** TEST BUILD SUCCEEDED ** (ios/build/voice-build.log); 7 Foundation voice tests passed on macOS without network/audio hardware (ios/build/voice-host-tests.log), including byte-fragmented SSE; all 8 new voice tests compile for iOS. LEAD must run the assigned simulator done test; physical microphone/AR playback remains unverified.
