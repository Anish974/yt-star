# YTStar — single FastAPI service that serves both the API and the frontend.
FROM python:3.12-slim

# System deps:
#   ffmpeg  -> yt-dlp uses it to merge video+audio and extract audio
#   aria2   -> parallel-connection downloader (big speed win; auto-detected on PATH)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg aria2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so this layer is cached across code changes.
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# App code. main.py expects ../frontend relative to backend/, so keep both.
COPY backend ./backend
COPY frontend ./frontend

WORKDIR /app/backend

# Render injects $PORT (usually 10000); default to 8000 for local `docker run`.
ENV PORT=8000 PYTHONUNBUFFERED=1
EXPOSE 8000

# Shell form so ${PORT} expands at runtime. No --reload in production.
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
