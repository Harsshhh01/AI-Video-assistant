"""Speech-to-text: local Whisper for English, Sarvam AI for Hinglish."""

from __future__ import annotations

import os
from pathlib import Path

import requests
from pydub import AudioSegment

from app import config

SARVAM_STT_TRANSLATE_URL = "https://api.sarvam.ai/speech-to-text-translate"

_model = None
_model_name: str | None = None


def load_model():
    """Load (and cache) the Whisper model. First call downloads the weights."""
    global _model, _model_name

    import whisper  # imported lazily so the web server starts without torch loaded

    wanted = config.whisper_model_name()
    if _model is None or _model_name != wanted:
        print(f"Loading Whisper model: {wanted} ...")
        _model = whisper.load_model(wanted)
        _model_name = wanted
        print("Whisper model loaded.")
    return _model


def transcribe_chunk_whisper(chunk_path: str | Path) -> str:
    model = load_model()
    result = model.transcribe(str(chunk_path), task="transcribe", fp16=False)
    return (result.get("text") or "").strip()


def _send_to_sarvam(piece_path: Path) -> str:
    """Send one <=30s WAV file to Sarvam and return the English transcript."""
    headers = {"api-subscription-key": config.sarvam_api_key()}
    with open(piece_path, "rb") as handle:
        response = requests.post(
            SARVAM_STT_TRANSLATE_URL,
            headers=headers,
            files={"file": (piece_path.name, handle, "audio/wav")},
            data={"model": config.sarvam_model(), "with_diarization": "false"},
            timeout=120,
        )

    if not response.ok:
        raise RuntimeError(
            f"Sarvam API returned {response.status_code}: {response.text[:300]}"
        )
    return response.json().get("transcript", "")


def transcribe_chunk_sarvam(chunk_path: str | Path, on_progress=None) -> str:
    """Sarvam's sync endpoint caps at 30s, so slice the chunk before sending."""
    if not config.sarvam_api_key():
        raise RuntimeError(
            "SARVAM_API_KEY is not set — required for Hinglish. Add it to .env, "
            "or switch the language to English to use local Whisper instead."
        )

    chunk_path = Path(chunk_path)
    audio = AudioSegment.from_file(chunk_path)
    piece_ms = config.SARVAM_PIECE_SECONDS * 1000
    total = max(1, (len(audio) + piece_ms - 1) // piece_ms)

    parts: list[str] = []
    for i, start in enumerate(range(0, len(audio), piece_ms)):
        piece_path = chunk_path.with_name(f"{chunk_path.stem}_sv_{i:03d}.wav")
        audio[start : start + piece_ms].export(piece_path, format="wav")
        try:
            if on_progress:
                on_progress(f"piece {i + 1}/{total}")
            parts.append(_send_to_sarvam(piece_path))
        finally:
            if piece_path.exists():
                os.remove(piece_path)

    return " ".join(p for p in parts if p).strip()


def transcribe_chunk(
    chunk_path: str | Path, language: str = "english", on_progress=None
) -> str:
    if language.lower() == "hinglish":
        return transcribe_chunk_sarvam(chunk_path, on_progress)
    return transcribe_chunk_whisper(chunk_path)


def transcribe_all(chunks: list, language: str = "english", on_progress=None) -> str:
    engine = "Sarvam AI" if language.lower() == "hinglish" else "Whisper"
    print(f"Using {engine} for transcription.")

    pieces: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        if on_progress:
            on_progress(f"{engine} · chunk {i}/{len(chunks)}")
        print(f"Transcribing chunk {i}/{len(chunks)} ...")

        def sub(detail: str, i=i):
            if on_progress:
                on_progress(f"{engine} · chunk {i}/{len(chunks)} · {detail}")

        pieces.append(transcribe_chunk(chunk, language=language, on_progress=sub))

    transcript = " ".join(p for p in pieces if p).strip()
    if not transcript:
        raise RuntimeError(
            "No speech was detected in the audio. Check that the file actually "
            "contains an audio track."
        )
    print("Transcription complete.")
    return transcript
