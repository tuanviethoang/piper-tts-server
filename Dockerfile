FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    espeak-ng \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY piper_server.py .

# Expose port
EXPOSE 8080

# Run server
CMD ["uvicorn", "piper_server:app", "--host", "0.0.0.0", "--port", "8080"]
