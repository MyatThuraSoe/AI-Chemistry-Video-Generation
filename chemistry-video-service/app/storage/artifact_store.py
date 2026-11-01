"""Artifact storage boundary with strict path-traversal protection."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

ALLOWED_ARTIFACT_FILES: frozenset[str] = frozenset(
    {
        "video.mp4",
        "metadata.json",
        "script.json",
        "storyboard.json",
        "subtitles.vtt",
        "thumbnail.jpg",
        "validation.json",
    }
)

_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class UnsafeArtifactPathError(ValueError):
    """Raised when a job ID or filename could escape the artifact root."""


def _validate_job_id(job_id: UUID | str) -> UUID:
    if isinstance(job_id, UUID):
        return job_id
    try:
        return UUID(str(job_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise UnsafeArtifactPathError("Job ID must be a valid UUID.") from exc


def _validate_filename(filename: str) -> str:
    if not filename or not _FILENAME_PATTERN.fullmatch(filename):
        raise UnsafeArtifactPathError(f"Invalid artifact filename: {filename!r}")
    if ".." in filename or filename.startswith("."):
        raise UnsafeArtifactPathError(f"Invalid artifact filename: {filename!r}")
    return filename


def safe_job_dir(root: Path, job_id: UUID | str) -> Path:
    """Return ``root/<uuid>`` after validating the ID and containment."""
    root = root.resolve()
    validated = _validate_job_id(job_id)
    candidate = (root / str(validated)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafeArtifactPathError("Artifact path escapes the storage root.") from exc
    return candidate


def safe_artifact_path(
    root: Path,
    job_id: UUID | str,
    filename: str,
    *,
    require_allowlisted: bool = True,
) -> Path:
    """Build and validate an artifact file path.

    ``job_id`` must be a UUID and ``filename`` must be a plain filename from the
    allowlist. Both values are checked before any filesystem path is built.
    """
    if require_allowlisted and filename not in ALLOWED_ARTIFACT_FILES:
        raise UnsafeArtifactPathError(f"Artifact file is not allowlisted: {filename!r}")
    _validate_filename(filename)
    job_dir = safe_job_dir(root, job_id)
    candidate = (job_dir / filename).resolve()
    try:
        candidate.relative_to(job_dir)
    except ValueError as exc:
        raise UnsafeArtifactPathError("Artifact path escapes the job directory.") from exc
    return candidate


class ArtifactStore(ABC):
    """Persistence boundary for generated files."""

    @abstractmethod
    def job_dir(self, job_id: UUID | str) -> Path: ...

    @abstractmethod
    def ensure_job_dir(self, job_id: UUID | str) -> Path: ...

    @abstractmethod
    def path_for(self, job_id: UUID | str, filename: str) -> Path: ...

    @abstractmethod
    def write_text(self, job_id: UUID | str, filename: str, content: str) -> Path: ...

    @abstractmethod
    def write_json(self, job_id: UUID | str, filename: str, payload: Any) -> Path: ...

    @abstractmethod
    def write_bytes(self, job_id: UUID | str, filename: str, content: bytes) -> Path: ...

    @abstractmethod
    def exists(self, job_id: UUID | str, filename: str) -> bool: ...

    @abstractmethod
    def read_text(self, job_id: UUID | str, filename: str) -> str: ...

    @abstractmethod
    def checksum_sha256(self, job_id: UUID | str, filename: str) -> str: ...

    @abstractmethod
    def work_dir(self, job_id: UUID | str) -> Path: ...

    @abstractmethod
    def remove_work_dir(self, job_id: UUID | str) -> None: ...

    @abstractmethod
    def healthcheck(self) -> bool: ...


class LocalArtifactStore(ArtifactStore):
    def __init__(self, root: Path, work_root: Path) -> None:
        self.root = Path(root).resolve()
        self.work_root = Path(work_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.work_root.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: UUID | str) -> Path:
        return safe_job_dir(self.root, job_id)

    def ensure_job_dir(self, job_id: UUID | str) -> Path:
        directory = self.job_dir(job_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def path_for(self, job_id: UUID | str, filename: str) -> Path:
        return safe_artifact_path(self.root, job_id, filename)

    def write_text(self, job_id: UUID | str, filename: str, content: str) -> Path:
        path = self.path_for(job_id, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            temp.write_text(content, encoding="utf-8")
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
        return path

    def write_json(self, job_id: UUID | str, filename: str, payload: Any) -> Path:
        return self.write_text(
            job_id,
            filename,
            json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        )

    def write_bytes(self, job_id: UUID | str, filename: str, content: bytes) -> Path:
        path = self.path_for(job_id, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            temp.write_bytes(content)
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
        return path

    def exists(self, job_id: UUID | str, filename: str) -> bool:
        try:
            return self.path_for(job_id, filename).is_file()
        except UnsafeArtifactPathError:
            return False

    def read_text(self, job_id: UUID | str, filename: str) -> str:
        return self.path_for(job_id, filename).read_text(encoding="utf-8")

    def checksum_sha256(self, job_id: UUID | str, filename: str) -> str:
        path = self.path_for(job_id, filename)
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def work_dir(self, job_id: UUID | str) -> Path:
        directory = safe_job_dir(self.work_root, job_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def remove_work_dir(self, job_id: UUID | str) -> None:
        directory = safe_job_dir(self.work_root, job_id)
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)

    def healthcheck(self) -> bool:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            fd, probe = tempfile.mkstemp(prefix=".ready-", dir=self.root)
            os.close(fd)
            Path(probe).unlink(missing_ok=True)
            return True
        except OSError:
            return False


@runtime_checkable
class ObjectStorageAdapter(Protocol):
    """Future S3-compatible adapter contract.

    The rest of the application depends only on :class:`ArtifactStore`, so a
    production object store can implement this protocol and expose presigned URLs
    without changing the pipeline.
    """

    def put_object(self, key: str, data: bytes, content_type: str) -> str: ...

    def get_object(self, key: str) -> bytes: ...

    def presigned_url(self, key: str, expires_seconds: int = 900) -> str: ...
