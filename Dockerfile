FROM python:3.10-slim

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download both voice models into the image (first run also verifies piper works).
# This makes runtime start instantly with no network dependency.
RUN mkdir -p /app/voices && \
    echo "hello" | python -m piper --model en_US-amy-medium \
        --download-dir /app/voices --data-dir /app/voices \
        --output_file /tmp/warmup_en.wav && \
    echo "xin chao" | python -m piper --model vi_VN-vais1000-medium \
        --download-dir /app/voices --data-dir /app/voices \
        --output_file /tmp/warmup_vi.wav && \
    rm -f /tmp/warmup_en.wav /tmp/warmup_vi.wav

# Copy server code
COPY piper_server.py .

# Expose port
EXPOSE 8080

# Run server
CMD ["uvicorn", "piper_server:app", "--host", "0.0.0.0", "--port", "8080"]
