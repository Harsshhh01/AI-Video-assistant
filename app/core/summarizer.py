"""Meeting title and summary generation."""

from __future__ import annotations

from app.core.llm import build_chain, map_reduce

MAP_PROMPT = (
    "You are summarising one portion of a longer meeting transcript. "
    "Capture the concrete points — who said what, numbers, dates, commitments. "
    "Be concise and do not speculate about parts you cannot see."
)

REDUCE_PROMPT = (
    "You are an expert meeting summariser. Combine these partial summaries into "
    "one final professional meeting summary as markdown bullet points. Merge "
    "duplicates, keep chronological sense, and do not invent details.\n\n"
    "Output the summary and nothing else: no preamble such as 'Here is the "
    "summary', no closing commentary, and do not wrap it in a ``` code fence."
)

TITLE_PROMPT = (
    "Based on this meeting transcript, generate a short professional meeting "
    "title of at most 8 words. Return only the title — no quotes, no prefix, "
    "no explanation."
)


def summarize(transcript: str, on_progress=None) -> str:
    return map_reduce(
        transcript,
        map_prompt=MAP_PROMPT,
        reduce_prompt=REDUCE_PROMPT,
        temperature=0.3,
        on_progress=on_progress,
    )


def generate_title(transcript: str) -> str:
    chain = build_chain(TITLE_PROMPT, temperature=0.3)
    raw = chain.invoke({"text": transcript[:2000]}).strip()
    first_line = next((ln.strip(" \"'*#") for ln in raw.splitlines() if ln.strip(" \"'*#")), "")
    return first_line or "Untitled meeting"
