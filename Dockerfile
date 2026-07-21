FROM python:3.11-slim

WORKDIR /app

# Install deps. edge-tts is a lightweight async network client — no ONNX models to pre-download
# (unlike the old Piper build), so the image is small and runtime starts instantly.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code (still named piper_server.py so render.yaml / this CMD don't need changing;
# it now uses edge-tts, not Piper — see the file header).
COPY piper_server.py .

EXPOSE 8080

CMD ["uvicorn", "piper_server:app", "--host", "0.0.0.0", "--port", "8080"]
