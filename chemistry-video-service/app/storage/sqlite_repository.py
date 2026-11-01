"""SQLite-backed job repository for durable, multi-process operation."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any
from uuid import UUID

from app.domain.models import VideoJob, utc_now
from app.domain.states import JobStatus, status_for_stage
from app.storage.job_repository import (
    JobFilters,
    JobPage,
    JobRepository,
    decode_cursor,
    encode_cursor,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    concept_id TEXT,
    normalized_query TEXT NOT NULL,
    idempotency_key TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    progress INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at, job_id);
CREATE INDEX IF NOT EXISTS idx_jobs_concept_created ON jobs(concept_id, created_at, job_id);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at, job_id);
CREATE INDEX IF NOT EXISTS idx_jobs_idempotency ON jobs(idempotency_key);
"""


class SQLiteJobRepository(JobRepository):
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            str(self._path),
            check_same_thread=False,
            timeout=30.0,
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=NORMAL")
            self._connection.execute("PRAGMA busy_timeout=10000")
            self._connection.executescript(_SCHEMA)
            self._connection.commit()

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> VideoJob:
        return VideoJob.model_validate_json(row["payload"])

    def create(self, job: VideoJob) -> VideoJob:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO jobs (
                    job_id, status, stage, concept_id, normalized_query,
                    idempotency_key, created_at, updated_at, attempts, progress, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(job.job_id),
                    job.status.value,
                    job.stage.value,
                    job.concept_id,
                    job.normalized_query,
                    job.idempotency_key,
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                    job.attempts,
                    job.progress,
                    job.model_dump_json(),
                ),
            )
        return job.model_copy(deep=True)

    def get(self, job_id: UUID) -> VideoJob | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM jobs WHERE job_id = ?", (str(job_id),)
            ).fetchone()
        return self._row_to_job(row) if row else None

    def find_by_idempotency_key(self, key: str) -> VideoJob | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT payload FROM jobs
                WHERE idempotency_key = ?
                ORDER BY created_at ASC, job_id ASC
                LIMIT 1
                """,
                (key,),
            ).fetchone()
        return self._row_to_job(row) if row else None

    def list(self, filters: JobFilters) -> JobPage:
        clauses: list[str] = []
        params: list[Any] = []
        if filters.status is not None:
            clauses.append("status = ?")
            params.append(filters.status.value)
        if filters.concept_id is not None:
            clauses.append("concept_id = ?")
            params.append(filters.concept_id)

        if filters.cursor:
            cursor_time, cursor_id = decode_cursor(filters.cursor)
            clauses.append("(created_at < ? OR (created_at = ? AND job_id < ?))")
            params.extend([cursor_time.isoformat(), cursor_time.isoformat(), cursor_id])

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(filters.limit + 1)
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT payload FROM jobs
                {where}
                ORDER BY created_at DESC, job_id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        jobs = [self._row_to_job(row) for row in rows]
        has_more = len(jobs) > filters.limit
        page = jobs[: filters.limit]
        next_cursor = encode_cursor(page[-1]) if has_more and page else None
        return JobPage(jobs=page, next_cursor=next_cursor)

    def update(self, job_id: UUID, updates: dict[str, Any]) -> VideoJob | None:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT payload FROM jobs WHERE job_id = ?", (str(job_id),)
            ).fetchone()
            if row is None:
                return None
            current = self._row_to_job(row)
            payload = {**current.model_dump(), **updates}
            if "updated_at" not in updates:
                payload["updated_at"] = utc_now()
            updated = VideoJob.model_validate(payload)
            self._connection.execute(
                """
                UPDATE jobs SET
                    status = ?, stage = ?, concept_id = ?, normalized_query = ?,
                    idempotency_key = ?, created_at = ?, updated_at = ?,
                    attempts = ?, progress = ?, payload = ?
                WHERE job_id = ?
                """,
                (
                    updated.status.value,
                    updated.stage.value,
                    updated.concept_id,
                    updated.normalized_query,
                    updated.idempotency_key,
                    updated.created_at.isoformat(),
                    updated.updated_at.isoformat(),
                    updated.attempts,
                    updated.progress,
                    updated.model_dump_json(),
                    str(job_id),
                ),
            )
        return updated.model_copy(deep=True)

    def claim_next_queued(self) -> VideoJob | None:
        with self._lock:
            for _ in range(5):
                with self._connection:
                    row = self._connection.execute(
                        """
                        SELECT payload FROM jobs
                        WHERE status = ?
                        ORDER BY created_at ASC, job_id ASC
                        LIMIT 1
                        """,
                        (JobStatus.QUEUED.value,),
                    ).fetchone()
                    if row is None:
                        return None
                    job = self._row_to_job(row)
                    started = job.mark_started()
                    cursor = self._connection.execute(
                        """
                        UPDATE jobs SET
                            status = ?, stage = ?, progress = ?, updated_at = ?,
                            attempts = ?, payload = ?
                        WHERE job_id = ? AND status = ?
                        """,
                        (
                            started.status.value,
                            started.stage.value,
                            started.progress,
                            started.updated_at.isoformat(),
                            started.attempts,
                            started.model_dump_json(),
                            str(started.job_id),
                            JobStatus.QUEUED.value,
                        ),
                    )
                    if cursor.rowcount == 1:
                        return started.model_copy(deep=True)
        return None

    def count(self) -> int:
        with self._lock:
            row = self._connection.execute("SELECT COUNT(*) AS total FROM jobs").fetchone()
        return int(row["total"]) if row else 0

    def count_by_status(self) -> dict[str, int]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT status, COUNT(*) AS total FROM jobs GROUP BY status"
            ).fetchall()
        counts = {status.value: 0 for status in JobStatus}
        for row in rows:
            counts[str(row["status"])] = int(row["total"])
        return counts

    def healthcheck(self) -> bool:
        try:
            with self._lock:
                self._connection.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    # Convenience for tests and administrative tooling.
    def set_status_for_test(self, job_id: UUID, status: JobStatus) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE jobs SET status = ? WHERE job_id = ?", (status.value, str(job_id))
            )

    @staticmethod
    def derive_status(stage: str) -> str:
        from app.domain.states import JobStage

        return status_for_stage(JobStage(stage)).value
