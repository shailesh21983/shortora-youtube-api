# Shortora AI — YouTube Extractor API
# This is the server component that will run on a service such as Render.
# It is intentionally kept separate from shortora.com/ so the Hostinger pipeline stays safe.

import os
import re
import time
import uuid
import shutil
import subprocess
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from yt_dlp import YoutubeDL

app = FastAPI(title="Shortora YouTube Extractor", version="1.0")

API_KEY = os.getenv("SHORTORA_API_KEY", "").strip()
DOWNLOAD_DIR = Path("/tmp/shortora-downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

YOUTUBE_RE = re.compile(
    r"^https?://(www\.)?(youtube\.com|youtu\.be)/",
    re.I
)

class VideoRequest(BaseModel):
    url: str

def check_key(x_api_key: str | None):
    if not API_KEY:
        raise HTTPException(
            status_code=500,
            detail="SHORTORA_API_KEY is not configured on the extractor server."
        )
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key.")

def check_youtube(url: str):
    if not YOUTUBE_RE.match(url.strip()):
        raise HTTPException(status_code=400, detail="Only public YouTube URLs are accepted.")

@app.get("/")
def health():
    return {
        "ok": True,
        "service": "Shortora YouTube Extractor",
        "status": "online"
    }

@app.post("/info")
def info(req: VideoRequest, x_api_key: str | None = Header(default=None)):
    check_key(x_api_key)
    check_youtube(req.url)

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
    }

    try:
        with YoutubeDL(opts) as ydl:
            data = ydl.extract_info(req.url, download=False)

        return {
            "ok": True,
            "id": data.get("id"),
            "title": data.get("title"),
            "channel": data.get("channel") or data.get("uploader"),
            "duration": data.get("duration"),
            "thumbnail": data.get("thumbnail"),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

@app.post("/download")
def download(req: VideoRequest, x_api_key: str | None = Header(default=None)):
    check_key(x_api_key)
    check_youtube(req.url)

    job_id = uuid.uuid4().hex
    job_dir = DOWNLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    output_template = str(job_dir / "source.%(ext)s")

    # MP4 is preferred. yt-dlp may select separate streams and ffmpeg merges them.
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
        "merge_output_format": "mp4",
        "outtmpl": output_template,
        "restrictfilenames": True,
    }

    try:
        with YoutubeDL(opts) as ydl:
            data = ydl.extract_info(req.url, download=True)

        files = list(job_dir.glob("source.*"))
        files = [p for p in files if p.is_file() and p.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}]

        if not files:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(status_code=502, detail="Video download completed but no media file was created.")

        media = max(files, key=lambda p: p.stat().st_size)

        return {
            "ok": True,
            "job_id": job_id,
            "title": data.get("title"),
            "duration": data.get("duration"),
            "download_url": f"/file/{job_id}/{media.name}"
        }

    except HTTPException:
        raise
    except Exception as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=502, detail=str(e))

@app.get("/file/{job_id}/{filename}")
def file(job_id: str, filename: str):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID.")

    if filename not in {"source.mp4", "source.webm", "source.mkv", "source.mov"}:
        raise HTTPException(status_code=400, detail="Invalid file name.")

    path = DOWNLOAD_DIR / job_id / filename

    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found or it has expired.")

    return FileResponse(
        path,
        media_type="video/mp4" if path.suffix.lower() == ".mp4" else "application/octet-stream",
        filename=filename,
    )

@app.on_event("startup")
def cleanup_old_files():
    now = time.time()
    for item in DOWNLOAD_DIR.iterdir():
        try:
            if item.is_dir() and now - item.stat().st_mtime > 3600:
                shutil.rmtree(item, ignore_errors=True)
        except Exception:
            pass
