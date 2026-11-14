"""POST /api/tts and POST /api/speech-intent (S-08). Both go through engine.models.call().

When no provider can serve the request (no keys, budget cap, provider errors) they return 200
{"fallback": "device", ...} so the client uses the browser's own speech.
"""
import asyncio
import base64
import hashlib
import re

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

router = APIRouter(prefix="/api")

MAX_TTS_CHARS = 1500  # protects the ElevenLabs budget cap
MAX_AUDIO_BYTES = 5 * 1024 * 1024
VOICE_RE = re.compile(r"^[A-Za-z0-9]{10,40}$")
AUDIO_MIMES = {"audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3", "audio/ogg", "audio/flac", "audio/aac",
               "audio/aiff", "audio/webm", "audio/mp4", "audio/x-m4a", "video/webm"}

INTENTS = ["ask", "visualise", "show_on_table", "changes", "other"]
INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "intent": {"enum": INTENTS},
    },
    "required": ["text", "intent"],
}
INTENT_PROMPT = (
    "You hear a short voice command spoken to an app that answers questions about construction drawings. "
    "Transcribe it exactly in English into `text` (empty string if there is no speech). Then classify `intent`: "
    "ask = a question about the drawing; visualise = show it in 3D; show_on_table = show it in augmented reality on a table; "
    "changes = compare versions or what changed; other = anything else."
)


def fallback(reason: str) -> JSONResponse:
    return JSONResponse({"fallback": "device", "reason": reason})


def _usable(task: str) -> bool:
    from engine.models import core
    if core._forced_fake():
        return False
    # only Gemini accepts audio input; the other adapters reject it, so do not spend calls on them
    ok = {"gemini"} if task == "speech_intent" else None
    return any(s["provider"] != "fake" and (ok is None or s["provider"] in ok) and core.api_key(s["provider"])
               for s in core.chain_for(task))


class TTSRequest(BaseModel):
    text: str
    voice: str | None = None


def _tts_sync(text: str, voice: str | None):
    from engine.models import call
    msgs = [{"role": "user", "content": text}]
    if voice:
        msgs.insert(0, {"role": "system", "content": f"voice={voice}"})
    return call("tts", msgs, request_id="api-tts")


@router.post("/tts")
async def tts(body: TTSRequest):
    from engine.models.providers import ProviderError as ModelError
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "text is empty")
    if len(text) > MAX_TTS_CHARS:
        raise HTTPException(413, f"text longer than {MAX_TTS_CHARS} characters")
    if body.voice and not VOICE_RE.match(body.voice):
        raise HTTPException(400, "bad voice id")
    if not _usable("tts"):
        return fallback("no tts provider configured")
    try:
        res = await asyncio.to_thread(_tts_sync, text, body.voice)
    except ModelError as e:
        return fallback(f"tts unavailable: {type(e).__name__}")
    if res.provider == "fake":
        return fallback("no tts provider configured")
    data = None
    b64 = res.extra.get("audio_b64")
    if b64:
        data = base64.b64decode(b64)
    elif res.audio_url and res.audio_url.startswith("https://"):
        try:
            r = await asyncio.to_thread(lambda: httpx.get(res.audio_url, timeout=60, follow_redirects=True))
            r.raise_for_status()
            data = r.content
        except httpx.HTTPError:
            return fallback("could not fetch audio")
    if not data:
        return fallback("provider returned no audio")
    return Response(data, media_type="audio/mpeg", headers={
        "X-TTS-Provider": res.provider, "X-TTS-Cache": "hit" if res.cache_hit else "miss",
        "Cache-Control": "public, max-age=86400", "ETag": hashlib.sha1(data).hexdigest()})


def _intent_sync(audio: bytes, mime: str):
    from engine.models import call
    from engine.models.providers import Image
    img = Image(mime=mime, data=audio, sha=hashlib.sha256(audio).hexdigest())
    return call("speech_intent",
                [{"role": "system", "content": INTENT_PROMPT},
                 {"role": "user", "content": "Transcribe and classify this audio."}],
                images=[img], schema=INTENT_SCHEMA, request_id="api-speech-intent")


@router.post("/speech-intent")
async def speech_intent(file: UploadFile = File(...)):
    from engine.models.providers import ProviderError as ModelError
    mime = (file.content_type or "").split(";")[0].strip().lower()
    if mime not in AUDIO_MIMES:
        raise HTTPException(415, f"unsupported audio type {mime or '(none)'}")
    data = await file.read(MAX_AUDIO_BYTES + 1)
    if not data:
        raise HTTPException(400, "empty audio")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "audio too large")
    if mime in ("video/webm", "audio/x-wav", "audio/mp3", "audio/x-m4a"):
        mime = {"video/webm": "audio/webm", "audio/x-wav": "audio/wav", "audio/mp3": "audio/mpeg",
                "audio/x-m4a": "audio/mp4"}[mime]
    if not _usable("speech_intent"):
        return fallback("no speech provider configured")
    try:
        res = await asyncio.to_thread(_intent_sync, data, mime)
    except ModelError as e:
        return fallback(f"speech unavailable: {type(e).__name__}")
    if res.provider == "fake" or not isinstance(res.json, dict):
        return fallback("no speech provider configured")
    return {"text": res.json["text"], "intent": res.json["intent"], "provider": res.provider}
