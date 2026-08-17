"""Central configuration for the AI Video Assistant.

Importing this module is what loads the `.env` file, so every other module in the
project imports it (directly or indirectly) before touching an API key. All
secrets are read through functions rather than module-level constants — reading
them at import time was the reason the original project silently lost
SARVAM_API_KEY.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"

# Load .env before deriving any paths, so DATA_DIR can be set there too.
load_dotenv(BASE_DIR / ".env")

# Overridable because a deployed container often has only one writable location
# (a mounted volume, or $HOME) that differs from the source tree.
DATA_DIR = Path(os.getenv("DATA_DIR") or BASE_DIR / "data")
UPLOAD_DIR = DATA_DIR / "uploads"
DOWNLOAD_DIR = DATA_DIR / "downloads"
WORK_DIR = DATA_DIR / "work"
VECTOR_DIR = DATA_DIR / "vector_db"

for _d in (DATA_DIR, UPLOAD_DIR, DOWNLOAD_DIR, WORK_DIR, VECTOR_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Upload ceiling. Whisper is slow on CPU, so a 500 MB cap is already generous.
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "500")) * 1024 * 1024

# Audio is transcribed in slices this long. Whisper handles long files fine but
# smaller slices give us useful progress reporting.
CHUNK_MINUTES = int(os.getenv("CHUNK_MINUTES", "10"))

# Sarvam's synchronous STT-translate endpoint rejects audio longer than 30s.
SARVAM_PIECE_SECONDS = 25

SUPPORTED_LANGUAGES = ("english", "hinglish")


def enable_utf8_console() -> None:
    """Stop Windows' legacy cp1252 console from crashing on model output.

    Transcripts and summaries can contain anything — Devanagari, curly quotes,
    emoji — and a bare `print` of those raises UnicodeEncodeError on a default
    Windows console. Called from the entry points, not on import.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # already wrapped, or not a TextIO
            pass


def mistral_api_key() -> str | None:
    return os.getenv("MISTRAL_API_KEY") or None


def sarvam_api_key() -> str | None:
    return os.getenv("SARVAM_API_KEY") or None


def whisper_model_name() -> str:
    """tiny | base | small | medium | large — bigger is slower but better."""
    return os.getenv("WHISPER_MODEL", "small")


def sarvam_model() -> str:
    return os.getenv("SARVAM_STT_MODEL", "saaras:v2.5")


def mistral_model() -> str:
    return os.getenv("MISTRAL_MODEL", "mistral-small-latest")


def embedding_model() -> str:
    return os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")


_ffmpeg_cache: str | None = None


def _persisted_path_dirs() -> list[str]:
    """Read PATH as Windows has it stored, not as this process inherited it.

    A terminal opened before `winget install Gyan.FFmpeg` keeps the old PATH for
    its whole life, and every child process inherits that stale copy — so ffmpeg
    looks missing until the user opens a new terminal. Going to the registry
    finds it anyway.
    """
    if sys.platform != "win32":
        return []

    import winreg

    dirs: list[str] = []
    for root, subkey in (
        (winreg.HKEY_CURRENT_USER, "Environment"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ),
    ):
        try:
            with winreg.OpenKey(root, subkey) as key:
                value, _ = winreg.QueryValueEx(key, "Path")
        except OSError:
            continue
        dirs += [
            os.path.expandvars(part.strip().strip('"'))
            for part in str(value).split(os.pathsep)
            if part.strip()
        ]
    return dirs


def _extra_ffmpeg_dirs() -> list[str]:
    """Well-known install locations, for when PATH was never updated at all."""
    if sys.platform != "win32":
        return ["/usr/bin", "/usr/local/bin", "/opt/homebrew/bin"]

    local = os.environ.get("LOCALAPPDATA", "")
    candidates: list[str] = []

    winget_packages = Path(local) / "Microsoft" / "WinGet" / "Packages"
    if winget_packages.is_dir():
        # e.g. Gyan.FFmpeg_.../ffmpeg-9.0-full_build/bin/ffmpeg.exe
        candidates += [str(p.parent) for p in winget_packages.glob("*FFmpeg*/**/bin/ffmpeg.exe")]

    candidates += [
        str(Path(local) / "Microsoft" / "WinGet" / "Links"),
        r"C:\ProgramData\chocolatey\bin",
        r"C:\ffmpeg\bin",
        str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ffmpeg" / "bin"),
    ]
    return candidates


def ffmpeg_path() -> str | None:
    """Absolute path to ffmpeg, or None.

    ffmpeg is a hard requirement: pydub and Whisper both shell out to it. When it
    is found somewhere outside this process's PATH, that directory is prepended
    to PATH so those subprocess calls succeed too — detecting it is not enough.
    """
    global _ffmpeg_cache
    if _ffmpeg_cache:
        return _ffmpeg_cache

    found = shutil.which("ffmpeg")
    if found:
        _ffmpeg_cache = found
        return found

    for directory in _persisted_path_dirs() + _extra_ffmpeg_dirs():
        if not directory:
            continue
        candidate = shutil.which("ffmpeg", path=directory)
        if candidate:
            os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")
            print(f"Found ffmpeg outside PATH, using {candidate}")
            _ffmpeg_cache = candidate
            return candidate

    return None  # not cached, so a later install is picked up without a restart


def health() -> dict:
    """Snapshot of what is and isn't configured — surfaced in the web UI."""
    return {
        "ffmpeg": ffmpeg_path() is not None,
        "mistral_key": mistral_api_key() is not None,
        "sarvam_key": sarvam_api_key() is not None,
        "whisper_model": whisper_model_name(),
        "mistral_model": mistral_model(),
        "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
    }
