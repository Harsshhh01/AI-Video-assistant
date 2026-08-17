"""Command-line interface: `python -m app.cli [source] [--language ...]`."""

from __future__ import annotations

import argparse
import sys

from app import config
from app.core.rag_engine import ask_question
from app.core.vector_store import drop_collection
from app.pipeline import result_to_markdown, run_pipeline

RULE = "=" * 68


def _print_step(key: str, state: str, detail: str = "") -> None:
    # ASCII only: a Windows console can be running any legacy code page.
    if state == "active" and detail:
        print(f"  ... {key}: {detail}")
    elif state == "active":
        print(f"  ... {key}")
    elif state == "done":
        print(f"  [ok] {key}{f' ({detail})' if detail else ''}")


def main(argv: list[str] | None = None) -> int:
    config.enable_utf8_console()

    parser = argparse.ArgumentParser(
        prog="ai-video-assistant",
        description="Transcribe, summarise and chat with a meeting recording.",
    )
    parser.add_argument("source", nargs="?", help="YouTube URL or local media file")
    parser.add_argument(
        "--language", default="english", choices=list(config.SUPPORTED_LANGUAGES)
    )
    parser.add_argument("--output", help="Write the full report to this markdown file")
    parser.add_argument("--no-chat", action="store_true", help="Skip the Q&A session")
    args = parser.parse_args(argv)

    source = args.source or input("YouTube URL or local file path: ").strip()
    if not source:
        parser.error("a source is required")

    if not config.mistral_api_key():
        print("MISTRAL_API_KEY is not set. Add it to .env first.", file=sys.stderr)
        return 1
    if config.ffmpeg_path() is None:
        print(
            "ffmpeg not found on PATH. Install it with `winget install Gyan.FFmpeg`.",
            file=sys.stderr,
        )
        return 1

    collection = "cli_session"
    result = run_pipeline(
        source, args.language, on_step=_print_step, collection_name=collection
    )

    print(f"\n{RULE}")
    print(f"TITLE: {result['title']}")
    print(RULE)
    for heading, key in [
        ("SUMMARY", "summary"),
        ("ACTION ITEMS", "action_items"),
        ("KEY DECISIONS", "key_decisions"),
        ("OPEN QUESTIONS", "open_questions"),
    ]:
        print(f"\n{heading}\n{'-' * 68}\n{result[key]}")
    print(f"\n{RULE}")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(result_to_markdown(result))
        print(f"\nReport written to {args.output}")

    if args.no_chat:
        drop_collection(collection)
        return 0

    print("\nChat with your meeting (type 'exit' to quit)\n")
    rag_chain = result["rag_chain"]
    try:
        while True:
            question = input("You: ").strip()
            if question.lower() in ("exit", "quit", "q"):
                break
            if not question:
                continue
            print(f"\nAssistant: {ask_question(rag_chain, question)}\n")
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        drop_collection(collection)

    print("Goodbye!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
