"""Standalone worker process entry point.

Usage::

    chemistry-video-worker
    python -m app.workers.runner

The worker claims queued jobs from the configured repository, so it can run in a
separate container from the API while sharing SQLite storage.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from app.config import Settings
from app.container import Container
from app.observability.logging import log_event

logger = logging.getLogger(__name__)


async def _run(settings: Settings, *, once: bool = False) -> int:
    container = Container(settings)
    container.log_startup()
    await container.start_workers()
    log_event(logger, "worker_ready", **settings.public_dict())

    if once:
        try:
            while True:
                job = await asyncio.to_thread(container.repository.claim_next_queued)
                if job is None:
                    break
                await asyncio.to_thread(container.pipeline.run, job.job_id)
        finally:
            await container.shutdown()
        return 0

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):
            signal.signal(
                sig,
                lambda *_args, _loop=loop: _loop.call_soon_threadsafe(stop_event.set),
            )

    try:
        await stop_event.wait()
    finally:
        await container.shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the chemistry video worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Drain currently queued jobs and exit (useful for cron/batch runs)",
    )
    args = parser.parse_args(argv)

    base = Settings()
    settings = base.model_copy(update={"worker_mode": "standalone"})
    try:
        return asyncio.run(_run(settings, once=args.once))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
