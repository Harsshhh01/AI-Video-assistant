"""Shared Mistral chat model factory and long-transcript map/reduce helper."""

from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_mistralai import ChatMistralAI
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app import config


class MissingApiKey(RuntimeError):
    """Raised with an actionable message instead of a vague 401 from the API."""


def get_llm(temperature: float = 0.3) -> ChatMistralAI:
    key = config.mistral_api_key()
    if not key:
        raise MissingApiKey(
            "MISTRAL_API_KEY is not set. Copy .env.example to .env and add your "
            "key from https://console.mistral.ai/api-keys/"
        )
    # Passed by alias so it works across langchain-mistralai versions.
    return ChatMistralAI(
        model=config.mistral_model(),
        api_key=key,
        temperature=temperature,
        timeout=120,
        max_retries=3,
    )


def split_text(text: str, chunk_size: int = 3000, chunk_overlap: int = 200) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    return splitter.split_text(text)


def build_chain(system_prompt: str, temperature: float = 0.3):
    """A plain `text -> string` chain, so callers can `.invoke("some text")`."""
    prompt = ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("human", "{text}")]
    )
    return prompt | get_llm(temperature) | StrOutputParser()


def map_reduce(
    transcript: str,
    map_prompt: str,
    reduce_prompt: str,
    temperature: float = 0.3,
    on_progress=None,
) -> str:
    """Run `map_prompt` over each slice of the transcript, then fold the results.

    The original code fed whole transcripts to the extractors in one shot, which
    fails on anything longer than roughly half an hour of speech.
    """
    chunks = split_text(transcript)
    if not chunks:
        return ""

    map_chain = build_chain(map_prompt, temperature)

    if len(chunks) == 1:
        return map_chain.invoke({"text": chunks[0]}).strip()

    partials = []
    for i, chunk in enumerate(chunks, start=1):
        if on_progress:
            on_progress(f"part {i}/{len(chunks)}")
        partials.append(map_chain.invoke({"text": chunk}).strip())

    reduce_chain = build_chain(reduce_prompt, temperature)
    return reduce_chain.invoke({"text": "\n\n".join(partials)}).strip()
