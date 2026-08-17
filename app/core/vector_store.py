"""Chroma vector store for transcript retrieval.

Each analysis gets its own collection. The original code reused a single
persistent collection, so chunks from every previously analysed video stayed in
the index and leaked into later answers.
"""

from __future__ import annotations

import shutil

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app import config

try:  # the maintained package
    from langchain_huggingface import HuggingFaceEmbeddings
except ImportError:  # pragma: no cover - older installs
    from langchain_community.embeddings import HuggingFaceEmbeddings

from langchain_chroma import Chroma

_embeddings = None


def get_embeddings():
    """Cached embeddings — loading the sentence-transformer takes a few seconds."""
    global _embeddings
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(
            model_name=config.embedding_model(),
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
    return _embeddings


def collection_dir(collection_name: str):
    return config.VECTOR_DIR / collection_name


def build_vector_store(transcript: str, collection_name: str = "transcript") -> Chroma:
    print(f"Building vector store ({collection_name}) ...")
    drop_collection(collection_name)

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)

    chunks = splitter.split_text(transcript)
    docs = [
        Document(page_content=chunk, metadata={"chunk_index": i})
        for i, chunk in enumerate(chunks)
    ]

    return Chroma.from_documents(
        documents=docs,
        embedding=get_embeddings(),
        collection_name=collection_name,
        persist_directory=str(collection_dir(collection_name)),
    )


def load_vector_store(collection_name: str = "transcript") -> Chroma:
    return Chroma(
        collection_name=collection_name,
        embedding_function=get_embeddings(),
        persist_directory=str(collection_dir(collection_name)),
    )


def drop_collection(collection_name: str) -> None:
    """Delete a collection's contents, then its directory.

    Deleting through Chroma's own API matters on Windows: while a client still
    holds the SQLite file open, `rmtree` fails silently and the old documents
    survive, so a rebuilt collection would append to the previous transcript
    instead of replacing it.
    """
    directory = collection_dir(collection_name)
    if directory.exists():
        try:
            Chroma(
                collection_name=collection_name,
                embedding_function=get_embeddings(),
                persist_directory=str(directory),
            ).delete_collection()
        except Exception as exc:  # a missing collection is not an error here
            print(f"Note: could not delete collection {collection_name}: {exc}")

    shutil.rmtree(directory, ignore_errors=True)


def get_retriever(vector_store: Chroma, k: int = 4):
    return vector_store.as_retriever(search_type="similarity", search_kwargs={"k": k})
