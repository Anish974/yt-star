# 🌟 YTStar - Self-Hosted Video & Audio Downloader

> A fast, modern, self-hosted web application for downloading videos and audio from YouTube and 1000+ supported platforms, powered by **FastAPI** and **yt-dlp**.

![YTStar Banner](https://img.shields.io/badge/YTStar-v1.0-blue?style=for-the-badge&logo=youtube)
![Python](https://img.shields.io/badge/Python-3.9+-yellow?style=for-the-badge&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green?style=for-the-badge&logo=fastapi)
![yt-dlp](https://img.shields.io/badge/yt--dlp-Latest-red?style=for-the-badge)

---

## ✨ Features

- 🎥 **Multi-Platform Support**: Download videos from YouTube, Vimeo, Twitter, TikTok, Instagram, and 1000+ other sites supported by `yt-dlp`.
- ⚡ **Real-Time Progress Tracking**: Live download speed, percentage, ETA, and status streaming via **Server-Sent Events (SSE)**.
- 🎵 **Audio Extraction**: Easily convert videos to MP3 / M4A audio files.
- ⚙️ **Quality Selection**: Choose specific video resolutions (1080p, 720p, 4K) or audio qualities before downloading.
- 🌐 **Instant Public Sharing**: Included `run_local.bat` / `run_local.ps1` automatically sets up a secure **Cloudflare Tunnel**, giving you a shareable online URL without port forwarding!
- 🐳 **Docker & Cloud Ready**: Ready-to-use `Dockerfile` and `render.yaml` for 1-click cloud deployment.

---

## 🚀 Quick Start (Windows 1-Click Setup)

If you are on Windows, you can start YTStar and generate a public shareable URL with a single click:

1. Double-click **`run_local.bat`**.
2. The script will automatically:
   - Verify Python installation.
   - Install required dependencies (`requirements.txt`).
   - Download `cloudflared.exe` if not present.
   - Start the FastAPI backend server on `http://localhost:8000`.
   - Launch a **Cloudflare Tunnel** and output a public `.trycloudflare.com` URL.

---

## 💻 Manual Local Installation

### Prerequisites
- **Python 3.9+** installed and added to PATH.
- **FFmpeg** (Recommended for merging best video + audio streams).

### Setup Steps

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Anish974/yt-star.git
   cd yt-star
   ```

2. **Install Backend Dependencies:**
   ```bash
   pip install -r backend/requirements.txt
   ```

3. **Start the Backend Server:**
   ```bash
   cd backend
   python main.py
   ```
   *(or run via Uvicorn directly)*:
   ```bash
   uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
   ```

4. **Access the Web App:**
   Open your browser and navigate to `http://localhost:8000`.

---

## 🐳 Running with Docker

You can containerize and run YTStar using Docker:

```bash
# Build the Docker image
docker build -t ytstar .

# Run the container on port 8000
docker run -d -p 8000:8000 --name ytstar-app ytstar
```

Visit `http://localhost:8000` in your web browser.

---

## ☁️ Deployment (Render / Cloud)

YTStar is pre-configured for deployment on **Render**:

1. Fork/Push this repository to GitHub.
2. Log into [Render](https://render.com/).
3. Create a new **Blueprint** or **Web Service** using `render.yaml`.
4. Render will automatically build the container and deploy the app.

---

## 🛠️ Project Structure

```
ytstar/
├── backend/
│   ├── main.py          # FastAPI application & API endpoints
│   ├── downloader.py    # Download manager wrapping yt-dlp
│   ├── models.py        # Pydantic data models
│   ├── requirements.txt # Python dependencies
│   └── cookies.txt      # (Optional) YouTube authentication cookies
├── frontend/
│   ├── index.html       # Web UI main layout
│   ├── style.css        # Responsive styling & themes
│   └── app.js           # Frontend logic & SSE listener
├── Dockerfile           # Docker container configuration
├── render.yaml          # Render deployment manifest
├── run_local.bat        # Windows 1-click batch launcher
└── run_local.ps1        # PowerShell automated launcher script
```

---

## 🛡️ License

This project is licensed under the [MIT License](LICENSE).

---

## ⚠️ Disclaimer

This tool is intended for personal use and downloading content you have the right to access. Please respect copyright laws and the terms of service of supported platforms.
