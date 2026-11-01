"""Deadline enforcement and timeout error semantics."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.container import Container
from app.domain.errors import JobTimeoutError
from tests.conftest import build_settings


def test_check_deadline_raises_job_timeout_with_current_stage(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, generation_mode="real", job_timeout_seconds=10)
    container = Container(settings)
    reporter = SimpleNamespace(current_stage="scene_rendering")

    with pytest.raises(JobTimeoutError) as caught:
        container.pipeline._check_deadline(  # type: ignore[union-attr]
            time.monotonic() - 1,
            reporter,
        )

    assert caught.value.code == "JOB_TIMEOUT"
    assert caught.value.stage == "scene_rendering"
    assert caught.value.retryable is False
    assert caught.value.details == {"timeout_seconds": 10}
