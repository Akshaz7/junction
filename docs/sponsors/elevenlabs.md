# Hologram × ElevenLabs

**ElevenLabs reads a Hologram answer aloud.** The answer's playback button sends plain text to the backend, which generates speech through the shared model layer and returns audio to the browser. The client can stop playback and falls back to device speech when server audio is unavailable.

**Where it is set out:**

- `web/src/components/answer-card.tsx::AnswerCard` renders `web/src/components/voice-controls.tsx::SpeakButton`.
- `web/src/lib/voice.ts::stripSpeechMarkdown` and `speakAnswer` prepare text, call `POST /api/tts`, play the returned audio and handle device fallback.
- `server/speech_routes.py::tts` and `_tts_sync` validate the text and call `engine.models.call("tts", ...)`.
- `engine/models/models.yaml`, task `tts`, selects ElevenLabs `eleven_flash_v2_5` before the Runware speech fallback. `engine/models/providers.py::elevenlabs` returns the generated audio; `engine/models/core.py::call` supplies caching and cost logging.

**Recorded evidence:** `results/costs.jsonl` contains an uncached `tts` record at `2026-11-14T03:38:11+0200`, request `s08-real`, with `provider: elevenlabs`, model `eleven_flash_v2_5`, `cost_usd: 0.00731` and `latency_ms: 282`. This is one speech-generation request, not a playback latency benchmark. The adapter estimates logged cost from text length and the configured price table; this is not an invoice.

Screenshot placeholder: `docs/sponsors/img/elevenlabs.png` — LEAD to capture an answer with its playback control active.

**Honest limits:** ElevenLabs handles spoken output here, not microphone transcription. Playback depends on browser audio support; device fallback is labelled `device voice` in `SpeakButton`. A recorded backend request and existing UI wiring do not establish a completed browser playback test. Missing credentials, budget limits or provider failures can select the configured fallback or device speech.
