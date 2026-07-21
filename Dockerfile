FROM python:3.10-slim

WORKDIR /app

# Install system dependencies for Piper TTS
RUN apt-get update && apt-get install -y \
    espeak-ng \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Copy Python requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Download Piper binary and voice models
RUN mkdir -p /piper && cd /piper && \
    pip install piper-tts && \
    # Download English and Vietnamese voices
    python -c "from piper.download import ensure_voice_exists; ensure_voice_exists('en_US-amy-medium'); ensure_voice_exists('vi_VN-vais1000-medium')"

# Copy Piper server code
COPY piper_server.py .

# Run server on port 8080
EXPOSE 8080
CMD ["uvicorn", "piper_server:app", "--host", "0.0.0.0", "--port", "8080"]
