from pydantic import BaseModel
from typing import Optional


class FormatInfo(BaseModel):
    format_id: str
    ext: str
    resolution: Optional[str] = None
    fps: Optional[float] = None
    vcodec: Optional[str] = None
    acodec: Optional[str] = None
    filesize: Optional[int] = None
    filesize_approx: Optional[int] = None
    tbr: Optional[float] = None
    quality_label: Optional[str] = None
    has_video: bool = True
    has_audio: bool = True


class VideoInfoResponse(BaseModel):
    id: str
    title: str
    thumbnail: Optional[str] = None
    duration: Optional[int] = None
    duration_string: Optional[str] = None
    channel: Optional[str] = None
    view_count: Optional[int] = None
    upload_date: Optional[str] = None
    description: Optional[str] = None
    webpage_url: str
    formats: list[FormatInfo] = []
    extractor: Optional[str] = None


class DownloadRequest(BaseModel):
    url: str
    format_id: Optional[str] = None
    audio_only: bool = False
    audio_format: str = "mp3"
    quality: Optional[str] = None  # e.g. "best", "720", "480"
    video_id: Optional[str] = None  # from /api/info — used as the cache key
    title: Optional[str] = None  # nice filename for cache hits


class DownloadProgress(BaseModel):
    job_id: str
    status: str  # pending, downloading, processing, done, error
    percent: float = 0.0
    speed: Optional[str] = None
    eta: Optional[str] = None
    filename: Optional[str] = None
    total_bytes: Optional[int] = None
    downloaded_bytes: Optional[int] = None
    error: Optional[str] = None
