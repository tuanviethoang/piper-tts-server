#!/usr/bin/env python3
"""
Cloud TTS server for TypingTrainer (Render.com).
POST /tts {text, lang, speed} -> MP3 audio.

Two quality tiers, per the app's "real-time first, best quality when ready" design:
  * English: Google Cloud Text-to-Speech (WaveNet/Neural2 British voice) when GOOGLE_TTS_API_KEY
    is set — the highest-quality "Google UK English" voice, consistent on every device. If no key
    is configured (or a Google call fails), it falls back to edge-tts so English still works.
  * Vietnamese (and English fallback): edge-tts — Microsoft Edge's free online Neural voices (the
    same Azure Neural voices Edge's "Read Aloud" uses), reachable with NO API key or billing.

Both are lightweight async NETWORK relays (no local ONNX model, tiny memory) — this replaced an
earlier per-request Piper (`python -m piper`) approach that sounded robotic AND spawned a
model-loading subprocess per request, starving the free tier's ~0.1 vCPU/512MB (concurrent
requests ballooned to ~60s each). The filename stays `piper_server.py` only so render.yaml /
Dockerfile references don't need touching — it no longer uses Piper.

The HTTP contract (POST /tts {text, lang, speed} -> audio bytes, GET /health) is unchanged, so the
app's fetchTtsUrl() works as-is; both tiers return MP3, which the browser's <audio> plays.
"""

import asyncio
import base64
import json
import os
import urllib.request

import edge_tts
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

PORT = int(os.environ.get("PORT", 8080))

# edge-tts voices (the always-available tier). Overridable via env vars.
# Sonia = natural British-English female (the user likes the "Google UK English" style; Sonia is
# the same British-female character, rendered server-side so it's identical on every device).
# Hoài My = the exact Vietnamese voice the app already prefers.
EDGE_VOICES = {
    "en": os.environ.get("TTS_VOICE_EN", "en-GB-SoniaNeural"),
    "vi": os.environ.get("TTS_VOICE_VI", "vi-VN-HoaiMyNeural"),
}

# Google Cloud TTS (the "best" English tier). Only used when an API key is set. Neural2 is Google's
# high-quality WaveNet-tier; en-GB-Neural2-A is a natural British female. Change via GOOGLE_VOICE_EN.
GOOGLE_TTS_API_KEY = os.environ.get("GOOGLE_TTS_API_KEY", "").strip()
GOOGLE_VOICES = {
    "en": ("en-GB", os.environ.get("GOOGLE_VOICE_EN", "en-GB-Neural2-A")),
}

SYNTH_TIMEOUT = 30  # seconds; a single sentence streams in well under this

app = FastAPI(title="Cloud TTS Server")

# CORS: the typing app is served from Firebase Hosting (a different origin), so the browser needs
# these headers to be allowed to fetch the audio.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class TTSRequest(BaseModel):
    text: str
    lang: str = "en"
    speed: float = 1.0


def _rate_str(speed: float) -> str:
    """edge-tts wants a relative percentage string: 1.0 -> '+0%', 0.8 -> '-20%', 1.5 -> '+50%'."""
    if not 0.3 <= speed <= 3.0:
        speed = 1.0
    pct = round((speed - 1.0) * 100)
    return f"+{pct}%" if pct >= 0 else f"{pct}%"


async def _synth_edge(text: str, voice: str, rate: str) -> bytes:
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    buf = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.extend(chunk["data"])
    return bytes(buf)


def _google_synth_sync(text: str, lang_code: str, voice_name: str, speed: float) -> bytes:
    body = json.dumps({
        "input": {"text": text},
        "voice": {"languageCode": lang_code, "name": voice_name},
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": max(0.25, min(4.0, speed))},
    }).encode("utf-8")
    url = "https://texttospeech.googleapis.com/v1/text:synthesize?key=" + GOOGLE_TTS_API_KEY
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=SYNTH_TIMEOUT) as r:
        resp = json.loads(r.read().decode("utf-8"))
    return base64.b64decode(resp["audioContent"])


async def _synth_google(text: str, lang: str, speed: float) -> bytes:
    lang_code, voice_name = GOOGLE_VOICES[lang]
    # urllib is blocking — run it off the event loop so it doesn't stall other requests.
    return await asyncio.to_thread(_google_synth_sync, text, lang_code, voice_name, speed)


@app.post("/tts")
async def tts(req: TTSRequest):
    text = (req.text or "").strip()
    lang = (req.lang or "en").strip().lower()
    speed = float(req.speed or 1.0)

    if not text:
        raise HTTPException(status_code=400, detail="Text is empty")
    if lang not in EDGE_VOICES:
        raise HTTPException(status_code=400, detail=f"Unsupported lang: {lang}")

    audio = None
    # Best tier: Google Cloud TTS for English when a key is configured. Any failure falls through
    # to edge-tts below, so English is never left silent because of a Google hiccup.
    if lang in GOOGLE_VOICES and GOOGLE_TTS_API_KEY:
        try:
            audio = await asyncio.wait_for(_synth_google(text, lang, speed), timeout=SYNTH_TIMEOUT)
        except Exception as e:
            print("Google TTS failed, falling back to edge-tts:", str(e)[:200])
            audio = None

    if audio is None:
        try:
            audio = await asyncio.wait_for(
                _synth_edge(text, EDGE_VOICES[lang], _rate_str(speed)), timeout=SYNTH_TIMEOUT
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="TTS timeout")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"TTS failed: {str(e)[:300]}")

    if not audio:
        raise HTTPException(status_code=502, detail="No audio produced")
    return Response(content=audio, media_type="audio/mpeg")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "supported_languages": list(EDGE_VOICES.keys()),
        "english_engine": "google" if GOOGLE_TTS_API_KEY else "edge",
        "edge_voices": EDGE_VOICES,
        "google_voice_en": GOOGLE_VOICES["en"][1] if GOOGLE_TTS_API_KEY else None,
    }


@app.get("/")
def root():
    return {
        "name": "Cloud TTS Server",
        "endpoints": {
            "POST /tts": "JSON {text, lang: en|vi, speed} -> audio/mpeg (MP3)",
            "GET /health": "Health check",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
