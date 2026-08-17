"""FastAPI application: JSON API plus the static website."""

from __future__ import annotations

import os
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import __version__, config
from app.jobs import store
from app.pipeline import result_to_markdown

ALLOWED_MEDIA_SUFFIXES = {
    ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wma",
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".flv",
}

# This module is an entry point (`python -m uvicorn app.server:app`), so the
# console fix belongs here — the pipeline prints progress from worker threads.
config.enable_utf8_console()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Clear orphaned scratch data on boot.

    Jobs live in memory only, so anything left under data/work or data/vector_db
    belongs to a previous process and can never be reached again. Chroma keeps
    its SQLite file open for the life of the process, which is why these
    directories survive their own cleanup and have to be swept here instead.
    """
    for directory in (config.WORK_DIR, config.VECTOR_DIR, config.UPLOAD_DIR):
        shutil.rmtree(directory, ignore_errors=True)
        directory.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="AI Video Assistant", version=__version__, lifespan=lifespan)


class ChatRequest(BaseModel):
    question: str


def _safe_name(name: str) -> str:
    """Strip any directory component and unusual characters from an upload name."""
    stem = Path(name).name
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", stem).strip() or "upload"
    return cleaned[:120]


@app.get("/api/health")
def health():
    return {"version": __version__, **config.health()}


@app.get("/api/jobs")
def list_jobs():
    return {"jobs": store.list()}


@app.post("/api/jobs", status_code=202)
async def create_job(
    source: str = Form(""),
    language: str = Form("english"),
    file: UploadFile | None = File(None),
):
    language = language.lower().strip()
    if language not in config.SUPPORTED_LANGUAGES:
        raise HTTPException(400, f"Unsupported language: {language}")
    if language == "hinglish" and not config.sarvam_api_key():
        raise HTTPException(
            400,
            "Hinglish transcription needs SARVAM_API_KEY in your .env file. "
            "Use English to transcribe locally with Whisper.",
        )
    if not config.mistral_api_key():
        raise HTTPException(
            400,
            "MISTRAL_API_KEY is not set. Copy .env.example to .env and add your key.",
        )
    if config.ffmpeg_path() is None:
        raise HTTPException(
            400,
            "ffmpeg was not found on your PATH. Install it with "
            "`winget install Gyan.FFmpeg` and restart the server.",
        )

    upload_path: Path | None = None
    source = source.strip()

    if file is not None and file.filename:
        suffix = Path(file.filename).suffix.lower()
        if suffix not in ALLOWED_MEDIA_SUFFIXES:
            raise HTTPException(400, f"Unsupported file type: {suffix or 'unknown'}")

        upload_path = config.UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}_{_safe_name(file.filename)}"
        written = 0
        try:
            with open(upload_path, "wb") as out:
                while chunk := await file.read(1024 * 1024):
                    written += len(chunk)
                    if written > config.MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            413,
                            f"File is larger than the "
                            f"{config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
                        )
                    out.write(chunk)
        except HTTPException:
            upload_path.unlink(missing_ok=True)
            raise
        finally:
            await file.close()

        label = _safe_name(file.filename)
        job = store.create(str(upload_path), language, label, upload_path=upload_path)
    else:
        if not source:
            raise HTTPException(400, "Provide a YouTube URL or upload a media file.")
        if not source.startswith(("http://", "https://")):
            local = Path(source).expanduser()
            if not local.is_file():
                raise HTTPException(400, f"No such file: {source}")
            source = str(local)
            label = local.name
        else:
            label = source
        job = store.create(source, language, label)

    return job.public()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job — it may have expired.")
    return job.public()


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str):
    if not store.delete(job_id):
        raise HTTPException(404, "Unknown job.")
    return None


@app.post("/api/jobs/{job_id}/chat")
def chat(job_id: str, payload: ChatRequest):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job — it may have expired.")
    if job.status == "error":
        raise HTTPException(409, f"That analysis failed, so there is nothing to ask: {job.error}")
    if job.status != "done":
        raise HTTPException(409, "The analysis is still running — try again once it finishes.")

    question = payload.question.strip()
    if not question:
        raise HTTPException(400, "Ask an actual question.")

    try:
        answer = store.ask(job, question)
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
    return {"answer": answer, "chat": job.chat}


@app.delete("/api/jobs/{job_id}/chat", status_code=204)
def clear_chat(job_id: str):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job.")
    job.chat.clear()
    return None


@app.get("/api/jobs/{job_id}/export")
def export_job(job_id: str):
    job = store.get(job_id)
    if job is None or not job.result:
        raise HTTPException(404, "No finished analysis with that id.")

    slug = re.sub(r"[^a-z0-9]+", "-", job.result["title"].lower()).strip("-") or "meeting"
    return PlainTextResponse(
        result_to_markdown(job.result),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{slug}.md"'},
    )


@app.get("/favicon.svg", include_in_schema=False)
def favicon():
    return FileResponse(config.WEB_DIR / "favicon.svg")


# Mounted last so the API routes above take precedence.
app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")


def main() -> None:
    """`python -m app.server` — start the server.

    HOST and PORT come from the environment so the same entry point works behind
    a platform that dictates the port (Hugging Face Spaces uses 7860).
    """
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))

    print(f"\n  AI Video Assistant v{__version__}")
    print(f"  Listening on http://{host}:{port}\n")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
