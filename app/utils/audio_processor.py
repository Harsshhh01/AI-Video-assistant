"""Turn a YouTube URL or a local media file into 16 kHz mono WAV chunks."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yt_dlp
from pydub import AudioSegment

from app import config
from app.utils.text import strip_ansi


class AudioError(RuntimeError):
    pass


_pydub_wired = False


def _require_ffmpeg() -> None:
    """Confirm ffmpeg exists and point pydub straight at it.

    pydub picks its converter at import time from whatever PATH it saw then, so
    a copy of ffmpeg discovered later (see config.ffmpeg_path) has to be handed
    to it explicitly.
    """
    global _pydub_wired

    exe = config.ffmpeg_path()
    if exe is None:
        raise AudioError(
            "ffmpeg was not found. Install it with `winget install Gyan.FFmpeg`, "
            "then restart the server (or open a new terminal first)."
        )

    if not _pydub_wired:
        probe = Path(exe).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        AudioSegment.converter = exe
        if probe.exists():
            AudioSegment.ffprobe = str(probe)
            AudioSegment.prober = str(probe)
        _pydub_wired = True


# YouTube serves different formats to different client apps, and which ones are
# actually downloadable changes every few weeks — a client whose media URLs need
# a PO token returns HTTP 403 at download time even though extraction succeeded.
# So we try several, starting with yt-dlp's own choice.
YOUTUBE_CLIENTS = (None, "tv_embedded", "android", "web_safari", "ios", "mweb")


class _QuietLogger:
    """Swallow yt-dlp's own console output.

    `quiet` does not cover `report_error`, so a recovered attempt still printed
    scary "ERROR: HTTP Error 403" lines. We log one tidy line per failed client
    instead.
    """

    def debug(self, msg): pass

    def info(self, msg): pass

    def warning(self, msg): pass

    def error(self, msg): pass


def _ydl_opts(dest_dir: Path, client: str | None) -> dict:
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(dest_dir / "%(title).80B [%(id)s].%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }
        ],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "noprogress": True,
        "no_color": True,
        "retries": 3,
        "fragment_retries": 3,
        "logger": _QuietLogger(),
    }
    if client:
        opts["extractor_args"] = {"youtube": {"player_client": [client]}}
    return opts


def _resolve_downloaded(info: dict, ydl, dest_dir: Path, url: str) -> Path:
    """Find what yt-dlp actually wrote.

    yt-dlp is the authority on the final filename — the container extension
    depends on what the site served and the extract-audio post-processor rewrites
    it — so read it back from the result instead of guessing at replacements.
    """
    path = None
    for requested in info.get("requested_downloads") or []:
        path = requested.get("filepath") or requested.get("_filename")
        if path:
            break
    if not path:
        path = ydl.prepare_filename(info)

    candidate = Path(path)
    if candidate.exists():
        return candidate

    wav = candidate.with_suffix(".wav")
    if wav.exists():
        return wav

    matches = sorted(dest_dir.glob(glob_escape(candidate.stem) + ".*"))
    if not matches:
        raise AudioError(f"Downloaded audio not found for {url}")
    return matches[0]


def glob_escape(text: str) -> str:
    """Escape glob metacharacters — video titles routinely contain [] and *."""
    return re.sub(r"([\[\]*?])", r"[\1]", text)


def download_youtube_audio(
    url: str, dest_dir: Path | None = None, on_progress=None
) -> Path:
    """Download the best audio track, trying each client until one works."""
    _require_ffmpeg()
    dest_dir = Path(dest_dir or config.DOWNLOAD_DIR)
    dest_dir.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []

    for attempt, client in enumerate(YOUTUBE_CLIENTS, start=1):
        label = client or "default"
        if on_progress and attempt > 1:
            on_progress(f"retrying as {label}")

        try:
            with yt_dlp.YoutubeDL(_ydl_opts(dest_dir, client)) as ydl:
                info = ydl.extract_info(url, download=True)
                return _resolve_downloaded(info, ydl, dest_dir, url)
        except AudioError:
            raise
        except Exception as exc:
            message = strip_ansi(str(exc)).replace("\n", " ").strip()
            print(f"yt-dlp client '{label}' failed: {message}")
            errors.append(f"{label}: {message}")

    detail = errors[-1] if errors else "no downloader succeeded"
    raise AudioError(
        f"Could not download audio from that link. {detail}\n\n"
        "This is usually YouTube changing its API. Update the downloader with:\n"
        "  .\\.venv\\Scripts\\python.exe -m pip install -U yt-dlp\n"
        "Private, members-only and age-restricted videos cannot be downloaded "
        "at all — download the audio yourself and use the upload tab instead."
    )


def convert_to_wav(input_path: str | Path, dest_dir: Path | None = None) -> Path:
    """Normalise any audio/video file to the 16 kHz mono WAV that STT expects."""
    _require_ffmpeg()
    src = Path(input_path)
    if not src.exists():
        raise AudioError(f"File not found: {src}")

    dest_dir = Path(dest_dir or config.WORK_DIR)
    dest_dir.mkdir(parents=True, exist_ok=True)
    output_path = dest_dir / (src.stem + "_16k.wav")

    try:
        audio = AudioSegment.from_file(src)
    except Exception as exc:  # pydub raises bare exceptions from ffmpeg
        raise AudioError(f"Could not decode {src.name}: {exc}") from exc

    audio.set_channels(1).set_frame_rate(16000).export(output_path, format="wav")
    return output_path


def chunk_audio(
    wav_path: str | Path,
    chunk_minutes: int | None = None,
    dest_dir: Path | None = None,
) -> list[Path]:
    _require_ffmpeg()
    wav_path = Path(wav_path)
    chunk_minutes = chunk_minutes or config.CHUNK_MINUTES
    dest_dir = Path(dest_dir or config.WORK_DIR)
    dest_dir.mkdir(parents=True, exist_ok=True)

    audio = AudioSegment.from_file(wav_path)
    if len(audio) == 0:
        raise AudioError("The audio track is empty — nothing to transcribe.")

    chunk_ms = chunk_minutes * 60 * 1000
    chunks: list[Path] = []
    for i, start in enumerate(range(0, len(audio), chunk_ms)):
        chunk_path = dest_dir / f"{wav_path.stem}_chunk_{i:03d}.wav"
        audio[start : start + chunk_ms].export(chunk_path, format="wav")
        chunks.append(chunk_path)
    return chunks


def process_input(
    source: str, work_dir: Path | None = None, on_progress=None
) -> tuple[list[Path], str]:
    """Return (chunk paths, human-readable label for the source)."""
    work_dir = Path(work_dir or config.WORK_DIR)

    if source.startswith(("http://", "https://")):
        if on_progress:
            on_progress("downloading audio")
        downloaded = download_youtube_audio(source, work_dir, on_progress=on_progress)
        label = downloaded.stem
        if on_progress:
            on_progress("normalising audio")
        wav_path = convert_to_wav(downloaded, work_dir)
    else:
        label = Path(source).name
        if on_progress:
            on_progress("normalising audio")
        wav_path = convert_to_wav(source, work_dir)

    if on_progress:
        on_progress("splitting into chunks")
    chunks = chunk_audio(wav_path, dest_dir=work_dir)
    if on_progress:
        on_progress(f"{len(chunks)} chunk(s) ready")
    return chunks, label


def cleanup(paths) -> None:
    for path in paths:
        try:
            os.remove(path)
        except OSError:
            pass
