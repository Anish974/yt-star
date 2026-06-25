import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from downloader import DownloadManager, humanize_error
from models import DownloadRequest

app = FastAPI(title="YTStar", description="Self-hosted video downloader powered by yt-dlp")

# CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_cache_for_assets(request: Request, call_next):
    """Stop the browser caching HTML/CSS/JS so UI changes always show up.

    Without this, editing style.css/app.js often shows nothing until a manual
    hard-refresh. We force revalidation on the page and its static assets.
    """
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".html", ".css", ".js")):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Download manager singleton
manager = DownloadManager()

# Frontend static files
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


# ── API Routes ──────────────────────────────────────────────────────────────


@app.get("/api/info")
def get_video_info(url: str, response: Response):
    """Fetch single-video metadata without downloading.

    Declared as a sync `def` on purpose: fetch_info does blocking network I/O,
    so FastAPI runs it in its threadpool instead of stalling the event loop
    (which would freeze every other request, including live progress streams).
    """
    # Never let the browser cache metadata — a new URL must always re-resolve.
    response.headers["Cache-Control"] = "no-store"
    try:
        info = manager.fetch_info(url)
        return info
    except Exception as e:
        print(f"[ytstar] info failed for {url}: {e}", flush=True)
        raise HTTPException(status_code=400, detail=humanize_error(e))


@app.post("/api/download")
async def start_download(request: DownloadRequest):
    """Start a download job. Returns a job ID for progress tracking."""
    try:
        job_id = manager.start_download(request)
        return {"job_id": job_id}
    except Exception as e:
        print(f"[ytstar] download start failed: {e}", flush=True)
        raise HTTPException(status_code=400, detail=humanize_error(e))


@app.get("/api/progress/{job_id}")
async def stream_progress(job_id: str, request: Request):
    """SSE endpoint streaming real-time download progress."""
    job = manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        queue = job.add_listener(asyncio.get_running_loop())

        try:
            # Send current state immediately
            progress = job.to_progress()
            yield f"data: {json.dumps(progress.model_dump())}\n\n"

            # If already done/error, close
            if job.status in ("done", "error", "cancelled"):
                return

            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                try:
                    progress = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(progress.model_dump())}\n\n"

                    if progress.status in ("done", "error", "cancelled"):
                        break
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield ": keepalive\n\n"

        finally:
            job.remove_listener(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/file/{job_id}")
async def download_file(job_id: str):
    """Serve the completed download file."""
    job = manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "done":
        raise HTTPException(status_code=400, detail=f"Job status: {job.status}")
    if not job.filepath or not job.filepath.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=str(job.filepath),
        filename=job.filename or job.filepath.name,
        media_type="application/octet-stream",
    )


@app.get("/api/jobs")
async def list_jobs():
    """List all current download jobs."""
    return [job.to_progress().model_dump() for job in manager.jobs.values()]


@app.post("/api/cancel/{job_id}")
async def cancel_download(job_id: str):
    """Cancel a running download."""
    success = manager.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found or already finished")
    return {"status": "cancelled", "job_id": job_id}


# ── Frontend Serving ────────────────────────────────────────────────────────


@app.get("/")
async def serve_index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


# Mount static files (CSS, JS) — must be AFTER API routes
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")


# ── Entrypoint ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
