"""In-memory job store with a single background worker.

Analysis takes minutes, so the HTTP request that starts it returns immediately
with a job id and the browser polls for progress. Jobs are serialised through one
worker thread because Whisper is CPU-bound — running two at once just makes both
slower.
"""

from __future__ import annotations

import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from app import config
from app.core.rag_engine import ask_question
from app.core.vector_store import drop_collection
from app.pipeline import STEPS, run_pipeline
from app.utils.text import strip_ansi

MAX_JOBS_KEPT = 20


@dataclass
class Job:
    id: str
    source: str
    source_label: str
    language: str
    status: str = "queued"  # queued | running | done | error
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    steps: dict = field(default_factory=dict)
    result: dict | None = None
    rag_chain: object | None = None
    chat: list = field(default_factory=list)
    upload_path: Path | None = None
    cancelled: bool = False
    future: object | None = None

    def public(self, include_result: bool = True) -> dict:
        data = {
            "id": self.id,
            "status": self.status,
            "error": self.error,
            "language": self.language,
            "source_label": self.source_label,
            "created_at": self.created_at,
            "elapsed": round((self.finished_at or time.time()) - self.created_at, 1),
            "steps": [
                {
                    "key": key,
                    "label": label,
                    "state": self.steps.get(key, {}).get("state", "pending"),
                    "detail": self.steps.get(key, {}).get("detail", ""),
                }
                for key, label in STEPS
            ],
            "chat": self.chat,
        }
        if include_result and self.result:
            data["result"] = {
                k: v for k, v in self.result.items() if k != "rag_chain"
            }
        return data


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pipeline")

    def create(
        self,
        source: str,
        language: str,
        source_label: str,
        upload_path: Path | None = None,
    ) -> Job:
        job = Job(
            id=uuid.uuid4().hex[:12],
            source=source,
            source_label=source_label,
            language=language,
            upload_path=upload_path,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._evict_old()
        job.future = self._pool.submit(self._run, job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return [
            {
                "id": j.id,
                "status": j.status,
                "source_label": j.source_label,
                "title": (j.result or {}).get("title"),
                "created_at": j.created_at,
            }
            for j in jobs
        ]

    def delete(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.pop(job_id, None)
        if job is None:
            return False

        # A job waiting its turn must not run after being deleted — the worker
        # holds its own reference, so dropping it from the store is not enough.
        job.cancelled = True
        if job.future is not None:
            job.future.cancel()  # no-op once it has started

        self._cleanup(job)
        return True

    def ask(self, job: Job, question: str) -> str:
        if job.rag_chain is None:
            raise RuntimeError("This analysis is not ready for questions yet.")
        answer = ask_question(job.rag_chain, question)
        job.chat.append({"role": "user", "content": question})
        job.chat.append({"role": "assistant", "content": answer})
        return answer

    # ── internals ──────────────────────────────────────────────────────────────

    def _run(self, job: Job) -> None:
        if job.cancelled:  # deleted while it sat in the queue
            return

        job.status = "running"
        work_dir = config.WORK_DIR / job.id

        def on_step(key: str, state: str, detail: str = "") -> None:
            job.steps[key] = {"state": state, "detail": detail}

        try:
            result = run_pipeline(
                job.source,
                job.language,
                on_step=on_step,
                collection_name=f"job_{job.id}",
                work_dir=work_dir,
            )
            job.rag_chain = result.pop("rag_chain")
            job.result = result
            job.source_label = result.get("source_label") or job.source_label
            job.status = "done"
        except Exception as exc:  # surfaced to the UI, minus terminal colour codes
            job.status = "error"
            job.error = strip_ansi(str(exc)).strip() or exc.__class__.__name__
            for key, _ in STEPS:
                if job.steps.get(key, {}).get("state") == "active":
                    job.steps[key] = {"state": "error", "detail": ""}
            print(f"[job {job.id}] failed: {exc}")
        finally:
            job.finished_at = time.time()
            shutil.rmtree(work_dir, ignore_errors=True)
            if job.upload_path:
                try:
                    job.upload_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _evict_old(self) -> None:
        if len(self._jobs) <= MAX_JOBS_KEPT:
            return
        finished = sorted(
            (j for j in self._jobs.values() if j.status in ("done", "error")),
            key=lambda j: j.created_at,
        )
        for job in finished[: len(self._jobs) - MAX_JOBS_KEPT]:
            self._jobs.pop(job.id, None)
            self._cleanup(job)

    @staticmethod
    def _cleanup(job: Job) -> None:
        drop_collection(f"job_{job.id}")
        shutil.rmtree(config.WORK_DIR / job.id, ignore_errors=True)


store = JobStore()
