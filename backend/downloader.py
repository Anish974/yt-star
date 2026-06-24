import asyncio
import os
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yt_dlp

from models import (
    DownloadProgress,
    DownloadRequest,
    FormatInfo,
    VideoInfoResponse,
)

DOWNLOADS_DIR = Path(__file__).parent / "downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)

# Cache of already-converted files, keyed by video + quality. A repeat request
# for the same video/quality is served instantly — this is what makes services
# like ytmp3 feel "20 second fast": popular videos are pre-converted.
CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# Hard cap on the cache directory. When exceeded, the least-recently-used files
# are evicted first (LRU) — popular videos stay, stale ones get removed, and the
# disk never fills up.
CACHE_MAX_BYTES = 5 * 1024 * 1024 * 1024  # 5 GB

# Auto-cleanup downloads older than 1 hour
DOWNLOAD_TTL_SECONDS = 3600

# Cap how many downloads run at once. Each download can open 16 aria2c
# connections and spawn an ffmpeg merge, so letting unlimited jobs run in
# parallel thrashes CPU/disk and makes *every* download slower. Extra requests
# queue (status "pending") until a slot frees up.
MAX_CONCURRENT_DOWNLOADS = 4

# How long a resolved /api/info result stays fresh. Re-resolving a URL hits
# YouTube and waits 1-3s; serving from this cache makes repeat lookups instant.
INFO_CACHE_TTL_SECONDS = 300
INFO_CACHE_MAX_ENTRIES = 256

# aria2c bypasses YouTube's per-connection throttle by opening many parallel
# connections — the single biggest speed win when it's installed. Prefer a
# copy bundled in backend/bin/ (so the project is self-contained), otherwise
# fall back to whatever is on the system PATH.
def _find_aria2c() -> str | None:
    bundled = Path(__file__).parent / "bin" / ("aria2c.exe" if os.name == "nt" else "aria2c")
    if bundled.exists():
        return str(bundled)
    return shutil.which("aria2c")


ARIA2C_PATH = _find_aria2c()

# On a cloud/datacenter IP, YouTube often demands "confirm you're not a bot".
# Two ways to authenticate past the bot wall:
#   1. Drop a Netscape-format cookies.txt next to this file (exported from a
#      logged-in browser). yt-dlp will use it automatically.
#   2. Or set YTSTAR_COOKIES_BROWSER=firefox (or chrome/edge/brave) and yt-dlp
#      reads cookies straight from that browser — no file to manage. Firefox is
#      most reliable on Windows; Chrome/Edge may need the browser fully closed.
COOKIES_FILE = Path(__file__).parent / "cookies.txt"
COOKIES_BROWSER = os.environ.get("YTSTAR_COOKIES_BROWSER", "").strip().lower()


def _apply_common_opts(opts: dict) -> dict:
    """Inject options shared by both info-extraction and download."""
    opts["cachedir"] = False  # don't reuse stale extraction cache
    # Prefer an explicit, non-empty cookies.txt; otherwise fall back to reading
    # cookies directly from a configured browser. (An empty cookies.txt is
    # ignored so a stray blank file doesn't break extraction.)
    if COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 0:
        opts["cookiefile"] = str(COOKIES_FILE)
    elif COOKIES_BROWSER:
        opts["cookiesfrombrowser"] = (COOKIES_BROWSER,)
    return opts


def _safe(s: str | None) -> str:
    """Strip anything that isn't filesystem-safe."""
    return re.sub(r"[^A-Za-z0-9_-]", "", s or "")


def _cache_key(request: DownloadRequest) -> str | None:
    """Deterministic key for a (video, quality) combo. None if uncacheable."""
    if not request.video_id:
        return None
    if request.audio_only:
        mode = f"a-{_safe(request.audio_format)}"
    elif request.format_id:
        mode = f"f-{_safe(request.format_id)}"
    else:
        mode = f"v-{_safe(request.quality or 'best')}"
    return f"{_safe(request.video_id)}__{mode}"


def _find_cached(key: str | None) -> Path | None:
    """Return the cached file for a key, if one exists."""
    if not key:
        return None
    for f in CACHE_DIR.glob(f"{key}.*"):
        if f.is_file():
            return f
    return None


class DownloadCancelled(Exception):
    """Raised when a download is cancelled by the user."""
    pass


class DownloadJob:
    """Tracks a single download job's state and progress."""

    def __init__(self, job_id: str, url: str, request: DownloadRequest):
        self.job_id = job_id
        self.url = url
        self.request = request
        self.status = "pending"
        self.percent = 0.0
        self.speed: str | None = None
        self.eta: str | None = None
        self.filename: str | None = None
        self.filepath: Path | None = None
        self.total_bytes: int | None = None
        self.downloaded_bytes: int | None = None
        self.error: str | None = None
        self.created_at = time.time()
        self._listeners: list[asyncio.Queue] = []
        self._cancel_event = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def cancel(self):
        self._cancel_event.set()

    def to_progress(self) -> DownloadProgress:
        return DownloadProgress(
            job_id=self.job_id,
            status=self.status,
            percent=self.percent,
            speed=self.speed,
            eta=self.eta,
            filename=self.filename,
            total_bytes=self.total_bytes,
            downloaded_bytes=self.downloaded_bytes,
            error=self.error,
        )

    def add_listener(self, loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._listeners.append(q)
        self._loop = loop
        return q

    def remove_listener(self, q: asyncio.Queue):
        if q in self._listeners:
            self._listeners.remove(q)

    def notify_listeners(self):
        progress = self.to_progress()
        loop = self._loop
        for q in self._listeners:
            try:
                if loop and loop.is_running():
                    loop.call_soon_threadsafe(q.put_nowait, progress)
                else:
                    q.put_nowait(progress)
            except (asyncio.QueueFull, RuntimeError):
                pass


def _format_speed(bps: float | None) -> str | None:
    if bps is None:
        return None
    if bps >= 1_048_576:
        return f"{bps / 1_048_576:.1f} MB/s"
    if bps >= 1024:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps:.0f} B/s"


def _format_eta(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


class DownloadManager:
    """Manages all download jobs, wraps yt-dlp as a Python library."""

    def __init__(self):
        self.jobs: dict[str, DownloadJob] = {}
        # Bounded worker pool — extra downloads queue instead of all running
        # at once and starving each other of bandwidth/CPU.
        self._executor = ThreadPoolExecutor(
            max_workers=MAX_CONCURRENT_DOWNLOADS,
            thread_name_prefix="ytstar-dl",
        )
        # TTL cache of resolved video metadata, keyed by URL.
        self._info_cache: dict[str, tuple[float, VideoInfoResponse]] = {}
        self._info_cache_lock = threading.Lock()
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def _cleanup_loop(self):
        """Periodically remove old completed downloads."""
        while True:
            time.sleep(300)  # Check every 5 minutes
            now = time.time()
            expired = [
                jid
                for jid, job in self.jobs.items()
                if job.status in ("done", "error", "cancelled")
                and (now - job.created_at) > DOWNLOAD_TTL_SECONDS
            ]
            for jid in expired:
                job = self.jobs.pop(jid, None)
                # Only delete the temp download — never the cached master copy.
                if (
                    job
                    and job.filepath
                    and job.filepath.exists()
                    and job.filepath.parent == DOWNLOADS_DIR
                ):
                    try:
                        job.filepath.unlink()
                    except OSError:
                        pass

            # Keep the cache under its size cap (LRU eviction).
            self._enforce_cache_limit()

            # Drop stale metadata-cache entries so it can't grow unbounded.
            with self._info_cache_lock:
                stale = [
                    u for u, (ts, _) in self._info_cache.items()
                    if (now - ts) > INFO_CACHE_TTL_SECONDS
                ]
                for u in stale:
                    self._info_cache.pop(u, None)

    def _enforce_cache_limit(self):
        """Evict least-recently-used cache files until under CACHE_MAX_BYTES."""
        try:
            files = [f for f in CACHE_DIR.iterdir() if f.is_file()]
        except OSError:
            return
        total = sum(f.stat().st_size for f in files)
        if total <= CACHE_MAX_BYTES:
            return
        # Oldest access time (mtime) first — a cache hit "touches" the file,
        # so frequently-used videos survive and stale ones are dropped.
        for f in sorted(files, key=lambda p: p.stat().st_mtime):
            try:
                size = f.stat().st_size
                f.unlink()
                total -= size
            except OSError:
                continue
            if total <= CACHE_MAX_BYTES:
                break

    def fetch_info(self, url: str) -> VideoInfoResponse:
        """Extract single-video info without downloading.

        If the URL points at a playlist (or a video inside one), only the
        single video is resolved — playlists are intentionally not supported.

        Results are memoised for INFO_CACHE_TTL_SECONDS so re-resolving the
        same URL (e.g. switching video<->audio in the UI) is instant.
        """
        now = time.time()
        with self._info_cache_lock:
            hit = self._info_cache.get(url)
            if hit and (now - hit[0]) <= INFO_CACHE_TTL_SECONDS:
                return hit[1]

        ydl_opts = _apply_common_opts({
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,  # only the single video, never the playlist
        })
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if info is None:
            raise ValueError("Could not extract info from URL")

        # If a bare playlist URL slipped through, fall back to its first entry.
        if info.get("_type") == "playlist" or "entries" in info:
            entries = [e for e in info.get("entries", []) if e]
            if not entries:
                raise ValueError("No downloadable video found at this URL")
            info = entries[0]

        formats = []
        seen = set()
        for f in info.get("formats", []):
            fid = f.get("format_id", "")
            if fid in seen:
                continue
            seen.add(fid)

            vcodec = f.get("vcodec", "none")
            acodec = f.get("acodec", "none")
            has_video = vcodec != "none" and vcodec is not None
            has_audio = acodec != "none" and acodec is not None

            height = f.get("height")
            resolution = f.get("resolution") or (f"{height}p" if height else None)

            formats.append(
                FormatInfo(
                    format_id=fid,
                    ext=f.get("ext", "?"),
                    resolution=resolution,
                    fps=f.get("fps"),
                    vcodec=vcodec if has_video else None,
                    acodec=acodec if has_audio else None,
                    filesize=f.get("filesize"),
                    filesize_approx=f.get("filesize_approx"),
                    tbr=f.get("tbr"),
                    quality_label=f.get("format_note"),
                    has_video=has_video,
                    has_audio=has_audio,
                )
            )

        thumbnail = info.get("thumbnail")
        if not thumbnail and info.get("thumbnails"):
            thumbnail = info["thumbnails"][-1].get("url")

        result = VideoInfoResponse(
            id=info.get("id", ""),
            title=info.get("title", "Unknown"),
            thumbnail=thumbnail,
            duration=info.get("duration"),
            duration_string=info.get("duration_string"),
            channel=info.get("channel") or info.get("uploader"),
            view_count=info.get("view_count"),
            upload_date=info.get("upload_date"),
            description=info.get("description"),
            webpage_url=info.get("webpage_url", url),
            formats=formats,
            extractor=info.get("extractor"),
        )

        with self._info_cache_lock:
            # Cap size: if full, evict the oldest entry before inserting.
            if len(self._info_cache) >= INFO_CACHE_MAX_ENTRIES:
                oldest = min(self._info_cache, key=lambda u: self._info_cache[u][0])
                self._info_cache.pop(oldest, None)
            self._info_cache[url] = (time.time(), result)

        return result

    def start_download(self, request: DownloadRequest) -> str:
        """Start a download in a background thread. Returns job ID."""
        job_id = str(uuid.uuid4())[:8]
        job = DownloadJob(job_id, request.url, request)
        self.jobs[job_id] = job

        # Hand off to the bounded pool. If all workers are busy the job waits
        # here as "pending" until a slot frees up.
        self._executor.submit(self._run_download, job)
        return job_id

    def _run_download(self, job: DownloadJob):
        """Execute the yt-dlp download (runs in a background thread)."""
        try:
            # Cancelled while still queued in the pool — bail before any work.
            if job.is_cancelled:
                raise DownloadCancelled("Download cancelled by user")

            # ── Cache hit: serve an already-converted file instantly ───────
            cache_key = _cache_key(job.request)
            cached = _find_cached(cache_key)
            if cached:
                # Mark as recently used so LRU eviction keeps popular videos.
                try:
                    cached.touch()
                except OSError:
                    pass
                job.filepath = cached
                nice = _safe(job.request.title) or cached.stem
                job.filename = f"{job.request.title or nice}{cached.suffix}"
                job.status = "done"
                job.percent = 100.0
                job.notify_listeners()
                return

            job.status = "downloading"
            job.notify_listeners()

            output_template = str(DOWNLOADS_DIR / f"{job.job_id}_%(title)s.%(ext)s")

            ydl_opts: dict = _apply_common_opts({
                "outtmpl": output_template,
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,  # one link → one video
                # ── Speed: beat YouTube's per-connection throttle ──────────
                # Parallel fragments for DASH/HLS formats (no effect on a
                # single progressive file, harmless otherwise).
                "concurrent_fragment_downloads": 8,
                # Pull each stream in 10 MB chunks — keeps throughput high and
                # avoids a single throttled long-lived request.
                "http_chunk_size": 10 * 1024 * 1024,
                "progress_hooks": [lambda d: self._progress_hook(job, d)],
                "postprocessor_hooks": [lambda d: self._postprocessor_hook(job, d)],
            })

            # If aria2c is installed, hand the actual download to it with many
            # parallel connections — the biggest single throttle-bypass win.
            if ARIA2C_PATH:
                ydl_opts["external_downloader"] = "aria2c"
                ydl_opts["external_downloader_args"] = {
                    "aria2c": ["-x", "16", "-s", "16", "-k", "1M"]
                }

            if job.request.audio_only:
                ydl_opts["format"] = "bestaudio/best"
                ydl_opts["postprocessors"] = [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": job.request.audio_format,
                        "preferredquality": "192",
                    }
                ]
            elif job.request.format_id:
                # If user picked a specific format
                ydl_opts["format"] = job.request.format_id
            else:
                # Honour the quality the user actually picked. High resolutions
                # (1080p+) only exist as separate video+audio DASH streams, so
                # we grab both and let ffmpeg merge (a fast remux, not a
                # re-encode). Speed is handled by aria2c / parallel fragments
                # above, not by avoiding the merge.
                quality = job.request.quality
                if not quality or quality == "best":
                    ydl_opts["format"] = "bestvideo+bestaudio/best"
                else:
                    ydl_opts["format"] = (
                        f"bestvideo[height<={quality}]+bestaudio/"
                        f"best[height<={quality}]/best"
                    )
                # Merge separate streams into a single mp4 container.
                ydl_opts["merge_output_format"] = "mp4"

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([job.url])

            # Check if cancelled during post-processing
            if job.is_cancelled:
                raise DownloadCancelled("Download cancelled by user")

            # Find the output file
            if job.filepath is None or not job.filepath.exists():
                # Search for the file by job_id prefix
                for f in DOWNLOADS_DIR.iterdir():
                    if f.name.startswith(job.job_id) and f.is_file():
                        job.filepath = f
                        job.filename = f.name[len(job.job_id) + 1 :]  # Remove ID prefix
                        break

            # Save into the cache so the next identical request is instant,
            # then immediately trim the cache back under its size cap.
            self._save_to_cache(cache_key, job.filepath)
            self._enforce_cache_limit()

            job.status = "done"
            job.percent = 100.0

        except DownloadCancelled:
            job.status = "cancelled"
            job.error = "Download cancelled"
            self._cleanup_partial_files(job)

        except Exception as e:
            if job.is_cancelled:
                job.status = "cancelled"
                job.error = "Download cancelled"
                self._cleanup_partial_files(job)
            else:
                job.status = "error"
                job.error = str(e)

        finally:
            job.notify_listeners()

    def _save_to_cache(self, key: str | None, filepath: Path | None):
        """Link a finished download into the cache under its deterministic key.

        downloads/ and cache/ live on the same filesystem, so a hardlink is
        instant and uses zero extra disk — the two paths share the same blocks.
        Deleting the temp download later just drops one link; the cache copy
        survives. Falls back to a real copy only across devices.
        """
        if not key or not filepath or not filepath.exists():
            return
        if _find_cached(key):  # already cached
            return
        dest = CACHE_DIR / f"{key}{filepath.suffix}"
        try:
            os.link(filepath, dest)
        except OSError:
            try:
                shutil.copy2(filepath, dest)
            except OSError:
                pass

    def _cleanup_partial_files(self, job: DownloadJob):
        """Remove any partial/temp files from a cancelled download."""
        try:
            for f in DOWNLOADS_DIR.iterdir():
                if f.name.startswith(job.job_id) and f.is_file():
                    f.unlink(missing_ok=True)
        except OSError:
            pass

    def _progress_hook(self, job: DownloadJob, d: dict):
        """Called by yt-dlp during download with progress data."""
        # Check if cancelled — raise to abort yt-dlp
        if job.is_cancelled:
            raise DownloadCancelled("Download cancelled by user")

        status = d.get("status")

        if status == "downloading":
            job.status = "downloading"
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0)

            if total and total > 0:
                job.percent = round((downloaded / total) * 100, 1)
            else:
                # Fallback: use fragment index if available
                frag_idx = d.get("fragment_index")
                frag_count = d.get("fragment_count")
                if frag_idx and frag_count:
                    job.percent = round((frag_idx / frag_count) * 100, 1)

            job.total_bytes = total
            job.downloaded_bytes = downloaded
            job.speed = _format_speed(d.get("speed"))
            job.eta = _format_eta(d.get("eta"))

            filepath = d.get("filename")
            if filepath:
                job.filepath = Path(filepath)
                job.filename = Path(filepath).name

        elif status == "finished":
            filepath = d.get("filename")
            if filepath:
                job.filepath = Path(filepath)
                job.filename = Path(filepath).name
            job.percent = 100.0

        job.notify_listeners()

    def _postprocessor_hook(self, job: DownloadJob, d: dict):
        """Called by yt-dlp during post-processing."""
        status = d.get("status")
        if status == "started":
            job.status = "processing"
            job.notify_listeners()
        elif status == "finished":
            filepath = d.get("filename")
            if filepath:
                job.filepath = Path(filepath)
                job.filename = Path(filepath).name

    def get_job(self, job_id: str) -> DownloadJob | None:
        return self.jobs.get(job_id)

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a running download job. Returns True if found and cancelled."""
        job = self.jobs.get(job_id)
        if not job:
            return False
        if job.status in ("done", "error", "cancelled"):
            return False
        job.cancel()
        return True
