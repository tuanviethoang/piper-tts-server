#!/usr/bin/env python3
"""
Piper TTS server for TypingTrainer.
Runs on Google Cloud Run, accepts text and language, returns MP3 audio.
"""

import os
import io
import sys
import json
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Import Piper TTS
try:
    from piper.voice import PiperVoice
    from piper.download import find_voices_dir, ensure_voice_exists
except ImportError:
    print("ERROR: Piper TTS not installed. Run: pip install piper-tts")
    sys.exit(1)

# ---- Configuration ----
PORT = int(os.environ.get("PORT", 8080))
PIPER_VOICES = {
    "en": "en_US-amy-medium",
    "vi": "vi_VN-vais1000-medium",
}

# ---- Global state ----
voices = {}  # lang -> PiperVoice instance
voices_lock = asyncio.Lock()


async def init_voices():
    """Initialize Piper voices on startup."""
    global voices
    async with voices_lock:
        if voices:
            return  # Already initialized

        try:
            # Ensure voices are downloaded
            for lang, voice_name in PIPER_VOICES.items():
                print(f"Ensuring {lang} voice: {voice_name}")
                try:
                    ensure_voice_exists(voice_name, download_dir=None, progress_callback=None)
                except Exception as e:
                    print(f"Warning: Could not ensure voice: {e}")

            # Load voices
            voices_dir = find_voices_dir()
            print(f"Voices directory: {voices_dir}")

            for lang, voice_name in PIPER_VOICES.items():
                try:
                    voice = PiperVoice.load(voice_name, voices_dir=voices_dir)
                    voices[lang] = voice
                    print(f"Loaded {lang} voice: {voice_name}")
                except Exception as e:
                    print(f"ERROR loading {lang} voice: {e}")
                    raise
        except Exception as e:
            print(f"FATAL: Could not initialize voices: {e}")
            raise


# ---- Request/Response models ----
class TTSRequest(BaseModel):
    text: str
    lang: str = "en"
    speed: float = 1.0  # Optional speech rate


# ---- FastAPI lifespan ----
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize Piper voices on startup."""
    print("Starting Piper TTS server...")
    await init_voices()
    print("Piper TTS server ready!")
    yield
    print("Piper TTS server shutting down...")


# ---- FastAPI app ----
app = FastAPI(title="Piper TTS Server", lifespan=lifespan)


@app.post("/tts")
async def tts(request: TTSRequest, background_tasks: BackgroundTasks):
    """
    Generate speech from text using Piper TTS.
    Returns MP3 audio data.

    POST /tts
    {
        "text": "Hello world",
        "lang": "en",
        "speed": 1.0
    }
    """
    text = str(request.text or "").strip()
    lang = str(request.lang or "en").strip().lower()
    speed = float(request.speed or 1.0)

    if not text:
        raise HTTPException(status_code=400, detail="Text is empty")

    if lang not in PIPER_VOICES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language: {lang}. Supported: {list(PIPER_VOICES.keys())}"
        )

    if speed < 0.5 or speed > 2.0:
        raise HTTPException(status_code=400, detail="Speed must be between 0.5 and 2.0")

    try:
        # Ensure voice is loaded
        if lang not in voices:
            raise HTTPException(status_code=503, detail=f"Voice {lang} not loaded")

        voice = voices[lang]

        # Generate audio (WAV format)
        wav_data = io.BytesIO()
        voice.synthesize(text, wav_data, speaker=None, length_scale=1.0 / speed)
        wav_data.seek(0)

        # Return WAV audio
        return StreamingResponse(
            iter([wav_data.getvalue()]),
            media_type="audio/wav",
            headers={"Content-Disposition": "inline"}
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR: TTS synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "voices_loaded": list(voices.keys()),
        "supported_languages": list(PIPER_VOICES.keys())
    }


@app.get("/")
async def root():
    """Root endpoint - server info."""
    return {
        "name": "Piper TTS Server",
        "version": "1.0",
        "endpoints": {
            "POST /tts": "Generate speech (expects JSON: {text, lang, speed})",
            "GET /health": "Health check",
            "GET /": "This message"
        }
    }


if __name__ == "__main__":
    import uvicorn
    print(f"Starting Piper TTS server on port {PORT}")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level="info"
    )
