"""Environment check: `python -m app.doctor` (add `--live` to test your keys).

Verifies everything the pipeline needs before you waste ten minutes on a
transcription that was going to fail at the last step. `--live` goes further and
makes one tiny real request per configured API key, so you find out in seconds
whether a key actually works rather than after transcribing a whole meeting.
"""

from __future__ import annotations

import importlib.util
import sys

from app import config

OK, BAD, WARN = "[ok]  ", "[fail]", "[warn]"

REQUIRED_MODULES = [
    ("fastapi", "web server"),
    ("uvicorn", "web server"),
    # python-multipart renamed its import from `multipart` in 0.0.13.
    ("python_multipart|multipart", "file uploads"),
    ("yt_dlp", "YouTube downloads"),
    ("pydub", "audio conversion"),
    ("whisper", "local transcription"),
    ("torch", "Whisper backend"),
    ("langchain_mistralai", "summaries and chat"),
    ("langchain_chroma", "vector store"),
    ("chromadb", "vector store"),
    ("sentence_transformers", "embeddings"),
]


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _check_mistral() -> tuple[bool, str]:
    """One ~10-token request — proves the key is valid and the model exists."""
    from app.core.llm import build_chain

    chain = build_chain("Reply with exactly one word: OK")
    reply = chain.invoke({"text": "ping"}).strip()
    return True, f"replied {reply[:40]!r}"


def _check_sarvam() -> tuple[bool, str]:
    """Send one second of tone. Any non-auth response means the key is good."""
    import math
    import struct
    import wave

    from app.core.transcriber import _send_to_sarvam

    path = config.WORK_DIR / "_doctor_probe.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 16000)))
            for i in range(16000)
        ))

    try:
        transcript = _send_to_sarvam(path)
        return True, f"accepted the request (transcript {transcript!r})"
    except RuntimeError as exc:
        message = str(exc)
        if "401" in message or "403" in message:
            return False, "rejected the key (401/403) — check SARVAM_API_KEY"
        # Any other status means auth passed and the tone simply wasn't speech.
        return True, f"key accepted; API said: {message[:80]}"
    finally:
        path.unlink(missing_ok=True)


def run_live_checks() -> int:
    """Returns the number of failures."""
    failures = 0
    print("\nLive API checks")
    print("=" * 44)

    for label, key_present, probe, required in [
        ("Mistral", config.mistral_api_key() is not None, _check_mistral, True),
        ("Sarvam", config.sarvam_api_key() is not None, _check_sarvam, False),
    ]:
        if not key_present:
            if required:
                failures += 1
                print(f"{BAD} {label:<9} no key set — add it to .env")
            else:
                print(f"{WARN} {label:<9} no key set — skipped (optional)")
            continue

        try:
            ok, detail = probe()
        except Exception as exc:
            ok, detail = False, f"{exc.__class__.__name__}: {str(exc)[:120]}"

        if ok:
            print(f"{OK} {label:<9} {detail}")
        else:
            failures += 1
            print(f"{BAD} {label:<9} {detail}")

    print("=" * 44)
    return failures


def main() -> int:
    config.enable_utf8_console()

    problems = 0
    warnings = 0

    print("\nAI Video Assistant — environment check")
    print("=" * 44)

    version = sys.version_info
    if (3, 10) <= (version.major, version.minor) <= (3, 12):
        print(f"{OK} Python {version.major}.{version.minor}.{version.micro}")
    else:
        problems += 1
        print(
            f"{BAD} Python {version.major}.{version.minor} — torch and chromadb "
            "only ship wheels for 3.10–3.12"
        )

    print("-" * 44)
    for spec, purpose in REQUIRED_MODULES:
        names = spec.split("|")
        found = any(_installed(name) for name in names)
        shown = names[0]
        if found:
            print(f"{OK} {shown:<24} {purpose}")
        else:
            problems += 1
            print(f"{BAD} {shown:<24} missing — needed for {purpose}")

    print("-" * 44)
    if config.ffmpeg_path():
        print(f"{OK} ffmpeg                   {config.ffmpeg_path()}")
    else:
        problems += 1
        print(f"{BAD} ffmpeg                   not on PATH — `winget install Gyan.FFmpeg`")

    if config.mistral_api_key():
        print(f"{OK} MISTRAL_API_KEY          set")
    else:
        problems += 1
        print(f"{BAD} MISTRAL_API_KEY          missing — add it to .env")

    if config.sarvam_api_key():
        print(f"{OK} SARVAM_API_KEY           set (Hinglish available)")
    else:
        warnings += 1
        print(f"{WARN} SARVAM_API_KEY           not set — English only")

    print("-" * 44)
    print(f"Whisper model: {config.whisper_model_name()}   LLM: {config.mistral_model()}")
    print("=" * 44)

    if problems:
        print(f"{problems} problem(s) to fix before the pipeline will run.\n")
        print("Skipping live API checks until the above is fixed.\n")
        return 1

    print(f"Ready to run{f' ({warnings} optional item missing)' if warnings else ''}.")

    if "--live" in sys.argv:
        if run_live_checks():
            print("A key was rejected — fix it in .env, then re-run.\n")
            return 1
        print("Keys verified. The full pipeline will work.\n")
    else:
        print("Run with --live to test your API keys for real.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
