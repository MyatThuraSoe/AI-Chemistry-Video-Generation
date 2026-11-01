"""Artifact path containment and allowlist enforcement."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.storage.artifact_store import (
    UnsafeArtifactPathError,
    safe_artifact_path,
    safe_job_dir,
)


def test_artifact_path_accepts_uuid(tmp_path: Path) -> None:
    job_id = uuid4()
    path = safe_artifact_path(tmp_path, job_id, "video.mp4")
    assert path == (tmp_path / str(job_id) / "video.mp4").resolve()
    assert safe_job_dir(tmp_path, str(job_id)) == (tmp_path / str(job_id)).resolve()


@pytest.mark.parametrize(
    "job_id",
    [
        "../../etc",
        "..",
        "/etc/passwd",
        "not-a-uuid",
        "",
    ],
)
def test_artifact_path_rejects_path_traversal(tmp_path: Path, job_id: str) -> None:
    with pytest.raises(UnsafeArtifactPathError):
        safe_artifact_path(tmp_path, job_id, "video.mp4")


@pytest.mark.parametrize(
    "filename",
    [
        "../video.mp4",
        "..\\video.mp4",
        "/etc/passwd",
        ".hidden",
        "video.mp4/../../escape",
        "secrets.txt",
    ],
)
def test_artifact_path_rejects_unsafe_filenames(tmp_path: Path, filename: str) -> None:
    with pytest.raises(UnsafeArtifactPathError):
        safe_artifact_path(tmp_path, uuid4(), filename)


def test_artifact_path_rejects_unlisted_filename(tmp_path: Path) -> None:
    with pytest.raises(UnsafeArtifactPathError):
        safe_artifact_path(tmp_path, uuid4(), "arbitrary.bin")
