"""Small in-memory metrics registry exposed at /metrics."""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class StageMetric:
    count: int = 0
    total_seconds: float = 0.0
    max_seconds: float = 0.0


@dataclass
class MetricsRegistry:
    counters: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    stages: dict[str, StageMetric] = field(default_factory=lambda: defaultdict(StageMetric))
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def inc(self, name: str, value: float = 1.0) -> None:
        with self._lock:
            self.counters[name] += value

    def observe_stage(self, stage: str, duration_seconds: float) -> None:
        duration_seconds = max(0.0, float(duration_seconds))
        with self._lock:
            metric = self.stages[stage]
            metric.count += 1
            metric.total_seconds += duration_seconds
            metric.max_seconds = max(metric.max_seconds, duration_seconds)

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return dict(self.counters)

    def prometheus(self, *, job_counts: dict[str, int] | None = None) -> str:
        lines: list[str] = []
        with self._lock:
            counters = dict(self.counters)
            stages = {name: StageMetric(**vars(metric)) for name, metric in self.stages.items()}

        lines.append("# HELP chemistry_jobs_active Jobs currently in each status.")
        lines.append("# TYPE chemistry_jobs_active gauge")
        for status, count in sorted((job_counts or {}).items()):
            lines.append(f'chemistry_jobs_active{{status="{status}"}} {count}')

        lines.append("# HELP chemistry_events_total Lifecycle events emitted by the service.")
        lines.append("# TYPE chemistry_events_total counter")
        for name, value in sorted(counters.items()):
            counter_name = name if name.startswith("chemistry_") else f"chemistry_{name}"
            lines.append(f"{counter_name} {value:g}")

        lines.append("# HELP chemistry_job_stage_duration_seconds Time spent in each job stage.")
        lines.append("# TYPE chemistry_job_stage_duration_seconds summary")
        for stage, stage_metric in sorted(stages.items()):
            lines.append(
                f'chemistry_job_stage_duration_seconds_sum{{stage="{stage}"}} '
                f"{stage_metric.total_seconds:.6f}"
            )
            lines.append(
                f'chemistry_job_stage_duration_seconds_count{{stage="{stage}"}} '
                f"{stage_metric.count}"
            )
            lines.append(
                f'chemistry_job_stage_duration_seconds_max{{stage="{stage}"}} '
                f"{stage_metric.max_seconds:.6f}"
            )
        return "\n".join(lines) + "\n"
