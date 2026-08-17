"""The end-to-end analysis pipeline, shared by the web server and the CLI."""

from __future__ import annotations

import shutil
from pathlib import Path

from app import config
from app.core.extractor import (
    extract_action_items,
    extract_key_decisions,
    extract_questions,
)
from app.core.rag_engine import build_rag_chain
from app.core.summarizer import generate_title, summarize
from app.core.transcriber import transcribe_all
from app.utils.audio_processor import process_input

STEPS = (
    ("audio", "Audio processing"),
    ("transcript", "Transcription"),
    ("title", "Title generation"),
    ("summary", "Summarisation"),
    ("extract", "Insight extraction"),
    ("rag", "Building RAG index"),
)


def run_pipeline(
    source: str,
    language: str = "english",
    on_step=None,
    collection_name: str = "transcript",
    work_dir: Path | None = None,
    keep_audio: bool = False,
) -> dict:
    """Run every stage and return the assembled result.

    `on_step(key, state, detail)` is called as each stage moves through
    "active" -> "done"; `state` is one of active/done/error.
    """

    def emit(key: str, state: str, detail: str = "") -> None:
        if on_step:
            on_step(key, state, detail)

    work_dir = Path(work_dir or config.WORK_DIR)
    work_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[Path] = []

    try:
        emit("audio", "active")
        chunks, label = process_input(
            source, work_dir=work_dir, on_progress=lambda d: emit("audio", "active", d)
        )
        emit("audio", "done", f"{len(chunks)} chunk(s)")

        emit("transcript", "active")
        transcript = transcribe_all(
            chunks, language, on_progress=lambda d: emit("transcript", "active", d)
        )
        emit("transcript", "done", f"{len(transcript.split())} words")

        emit("title", "active")
        title = generate_title(transcript)
        emit("title", "done")

        emit("summary", "active")
        summary = summarize(transcript, on_progress=lambda d: emit("summary", "active", d))
        emit("summary", "done")

        emit("extract", "active", "action items")
        action_items = extract_action_items(transcript)
        emit("extract", "active", "key decisions")
        decisions = extract_key_decisions(transcript)
        emit("extract", "active", "open questions")
        questions = extract_questions(transcript)
        emit("extract", "done")

        emit("rag", "active")
        rag_chain = build_rag_chain(transcript, collection_name=collection_name)
        emit("rag", "done")

        return {
            "title": title,
            "source_label": label,
            "language": language,
            "transcript": transcript,
            "summary": summary,
            "action_items": action_items,
            "key_decisions": decisions,
            "open_questions": questions,
            "rag_chain": rag_chain,
        }
    finally:
        if not keep_audio:
            shutil.rmtree(work_dir, ignore_errors=True)


def result_to_markdown(result: dict) -> str:
    """Render a finished result as a shareable markdown document."""
    return "\n".join(
        [
            f"# {result['title']}",
            "",
            f"*Source: {result.get('source_label', 'unknown')} · "
            f"Language: {result.get('language', 'english')}*",
            "",
            "## Summary",
            "",
            result["summary"],
            "",
            "## Action Items",
            "",
            result["action_items"],
            "",
            "## Key Decisions",
            "",
            result["key_decisions"],
            "",
            "## Open Questions",
            "",
            result["open_questions"],
            "",
            "## Full Transcript",
            "",
            result["transcript"],
            "",
        ]
    )
