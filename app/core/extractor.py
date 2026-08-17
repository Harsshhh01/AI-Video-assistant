"""Extract action items, key decisions and open questions from a transcript."""

from __future__ import annotations

from app.core.llm import map_reduce

_ACTION_ITEMS = (
    "You are an expert meeting analyst. From this meeting transcript, extract "
    "every action item.\n\n"
    "Any statement where someone takes on work counts — 'Priya will audit the "
    "spend', 'Dev is handling the copy', 'we need to rewrite the pricing "
    "table'. Include it even if no deadline was given and even if the owner is "
    "the whole team. Only reply that there are none if nobody committed to "
    "doing anything at all.\n\n"
    "For each action item give:\n"
    "- Task description\n"
    "- Owner (who is responsible, or 'Unassigned')\n"
    "- Deadline (if mentioned, otherwise 'Not specified')\n\n"
    "Format as a numbered markdown list. If there are genuinely none, reply "
    "exactly: No action items found."
)

_DECISIONS = (
    "You are an expert meeting analyst. From this meeting transcript, extract "
    "every key decision that was made. Format as a numbered markdown list. "
    "If there are none, reply exactly: No key decisions found."
)

_QUESTIONS = (
    "From this meeting transcript, extract every unresolved question or topic "
    "that needs follow-up. Format as a numbered markdown list. If there are "
    "none, reply exactly: No open questions found."
)

_MERGE = (
    "Merge these numbered lists extracted from consecutive parts of one meeting "
    "into a single numbered markdown list. Remove duplicates, keep the original "
    "wording where possible, and drop any 'none found' placeholders unless every "
    "list says so.\n\n"
    "Output the list and nothing else: no preamble, no closing commentary, and "
    "do not wrap it in a ``` code fence."
)


def _extract(transcript: str, prompt: str, on_progress=None) -> str:
    return map_reduce(
        transcript,
        map_prompt=prompt,
        reduce_prompt=_MERGE,
        temperature=0.2,
        on_progress=on_progress,
    )


def extract_action_items(transcript: str, on_progress=None) -> str:
    return _extract(transcript, _ACTION_ITEMS, on_progress)


def extract_key_decisions(transcript: str, on_progress=None) -> str:
    return _extract(transcript, _DECISIONS, on_progress)


def extract_questions(transcript: str, on_progress=None) -> str:
    return _extract(transcript, _QUESTIONS, on_progress)
