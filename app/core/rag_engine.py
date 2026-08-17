"""Retrieval-augmented chat over a meeting transcript."""

from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnablePassthrough

from app.core.llm import get_llm
from app.core.vector_store import (
    build_vector_store,
    get_retriever,
    load_vector_store,
)

SYSTEM_PROMPT = """You are an expert meeting assistant. Answer the user's question \
based ONLY on the meeting transcript context provided below.

If the answer is not found in the context, say:
"I could not find this information in the meeting transcript."

Always be concise and precise. If quoting someone, mention it clearly.

Context from meeting transcript:
{context}"""


def format_docs(docs) -> str:
    return "\n\n".join(doc.page_content for doc in docs)


def _chain_from_retriever(retriever):
    prompt = ChatPromptTemplate.from_messages(
        [("system", SYSTEM_PROMPT), ("human", "{question}")]
    )
    return (
        {
            "context": retriever | RunnableLambda(format_docs),
            "question": RunnablePassthrough(),
        }
        | prompt
        | get_llm(temperature=0.3)
        | StrOutputParser()
    )


def build_rag_chain(transcript: str, collection_name: str = "transcript"):
    """Index the transcript and return a `question -> answer` chain."""
    vector_store = build_vector_store(transcript, collection_name)
    return _chain_from_retriever(get_retriever(vector_store, k=4))


def load_rag_chain(collection_name: str = "transcript"):
    """Rebuild a chain over an already-persisted collection."""
    vector_store = load_vector_store(collection_name)
    return _chain_from_retriever(get_retriever(vector_store, k=4))


def ask_question(rag_chain, question: str) -> str:
    return rag_chain.invoke(question).strip()
