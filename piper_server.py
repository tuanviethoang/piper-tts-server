#!/usr/bin/env python3
"""
Piper TTS server for TypingTrainer (Render.com).
POST /tts {text, lang, speed} -> WAV audio.
Uses the piper CLI (python -m piper) so it works with piper-tts 1.2.0 as-is.
"""

import os
import subprocess
import tempfile

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

PORT = int(os.environ.get("PORT", 8080))
VOICES = {
    "en": "en_US-amy-medium",
    "vi": "vi_VN-vais1000-medium",
}
# Voices are pre-downloaded into the image at build time (see Dockerfile)
DATA_DIR = os.environ.get("PIPER_DATA_DIR", "/app/voices")

app = FastAPI(title="Piper TTS Server")

# CORS: the typing app is served from Firebase Hosting (different origin),
# so the browser needs these headers to be allowed to fetch audio.
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


@app.post("/tts")
def tts(req: TTSRequest):
    text = (req.text or "").strip()
    lang = (req.lang or "en").strip().lower()
    speed = float(req.speed or 1.0)

    if not text:
        raise HTTPException(status_code=400, detail="Text is empty")
    if lang not in VOICES:
        raise HTTPException(status_code=400, detail=f"Unsupported lang: {lang}")
    if not 0.3 <= speed <= 3.0:
        speed = 1.0

    length_scale = 1.0 / speed

    out_path = None
    try:
        fd, out_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        cmd = [
            "python", "-m", "piper",
            "--model", VOICES[lang],
            "--download-dir", DATA_DIR,
            "--data-dir", DATA_DIR,
            "--length-scale", str(length_scale),
            "--output_file", out_path,
        ]
        proc = subprocess.run(
            cmd,
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=120,
        )
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", "replace")[-500:]
            raise HTTPException(status_code=500, detail=f"Piper failed: {err}")

        with open(out_path, "rb") as f:
            wav = f.read()
        if not wav:
            raise HTTPException(status_code=500, detail="Piper produced no audio")
        return Response(content=wav, media_type="audio/wav")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="TTS timeout")
    finally:
        if out_path:
            try:
                os.remove(out_path)
            except OSError:
                pass


@app.get("/health")
def health():
    return {"status": "ok", "supported_languages": list(VOICES.keys())}


@app.get("/")
def root():
    return {
        "name": "Piper TTS Server",
        "endpoints": {
            "POST /tts": "JSON {text, lang: en|vi, speed} -> audio/wav",
            "GET /health": "Health check",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
