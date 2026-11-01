# Chemistry Video Service

An asynchronous FastAPI backend that turns one of three curated chemistry
questions into a validated, narrated MP4 explainer.

The service is deterministic by default: curated scripts, a deterministic
storyboard, pre-generated narration assets, and Pillow/FFmpeg rendering. It
exposes job polling, artifact downloads, structured logs, metrics, optional API
key authentication, rate limiting, and request-size limits.

## Required concepts

| Query | Concept ID |
| --- | --- |
| `How does the pH scale work?` | `ph-scale` |
| `Why do atoms form covalent bonds?` | `covalent-bonding` |
| `What is the difference between ionic and covalent bonding?` | `ionic-vs-covalent` |

Unknown queries return `422 UNSUPPORTED_CONCEPT`.

## Pipeline

Each job moves through the following stages and persists every transition so a
client can poll `status`, `stage`, and `progress`:

```text
queued
  -> concept_resolution
  -> script_selection
  -> script_validation
  -> storyboard_generation
  -> narration_generation
  -> scene_rendering
  -> video_composition
  -> artifact_validation
  -> completed
```

A failure keeps the stage where it occurred and stores a stable error code in
the job. No stack trace is ever returned to an API client.

Artifacts are written atomically to:

```text
artifacts/{job_id}/
  video.mp4
  metadata.json
  script.json
  storyboard.json
  subtitles.vtt
  thumbnail.jpg
  validation.json
```

## Requirements

- Python 3.11+
- FFmpeg and FFprobe (the service auto-discovers common install locations,
  including winget on Windows)
- Optional local TTS engine: Windows SAPI (PowerShell) or `espeak-ng`
- Pillow and the Python dependencies from `pyproject.toml`

The three required concepts ship with pre-generated canonical narration WAVs in
`assets/narration`, so the default configuration does not need network access or
a runtime TTS engine. If an asset is missing, the provider falls back to a local
engine (`espeak`, then Windows SAPI on Windows).

## Quick start

### Windows PowerShell

```powershell
cd chemistry-video-service
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"

Copy-Item .env.example .env
# Edit .env if needed. The defaults use canonical_cache narration.

# Optional: regenerate narration assets with Windows SAPI.
python scripts\generate_narration_assets.py

uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Linux / macOS

```bash
cd chemistry-video-service
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"

cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Verify the service:

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz
```

### First job

```bash
curl -X POST http://127.0.0.1:8000/v1/video-jobs \
  -H "Content-Type: application/json" \
  -d '{"query":"How does the pH scale work?"}'
```

The response is `202 Accepted` and includes a `job_id`. Poll it:

```bash
curl http://127.0.0.1:8000/v1/video-jobs/<job_id>
```

When `status` is `completed`, download the artifacts:

```bash
curl -O http://127.0.0.1:8000/v1/video-jobs/<job_id>/artifact/video.mp4
curl http://127.0.0.1:8000/v1/video-jobs/<job_id>/artifact
```

Interactive OpenAPI documentation is available at `/docs`.

## API

All `/v1` routes require `X-API-Key` only when `API_KEY` is configured.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/healthz` | Liveness |
| `GET` | `/readyz` | Readiness checks (configuration, storage, FFmpeg, repository) |
| `GET` | `/metrics` | Prometheus-style process metrics |
| `POST` | `/v1/video-jobs` | Create a job (`202`) |
| `GET` | `/v1/video-jobs/{job_id}` | Poll status/stage/progress |
| `GET` | `/v1/video-jobs` | List jobs (`status`, `concept_id`, `limit`, `cursor`) |
| `GET` | `/v1/video-jobs/{job_id}/artifact` | Artifact metadata |
| `GET` | `/v1/video-jobs/{job_id}/artifact/video.mp4` | MP4 download |
| `GET` | `/v1/video-jobs/{job_id}/artifact/subtitles.vtt` | WebVTT subtitles |
| `GET` | `/v1/video-jobs/{job_id}/artifact/thumbnail.jpg` | JPEG thumbnail |
| `GET` | `/v1/concepts` | Supported concept catalog |

### Error envelope

```json
{
  "error": {
    "code": "ARTIFACT_NOT_READY",
    "message": "The video artifact is not ready yet.",
    "status": "running",
    "stage": "scene_rendering",
    "progress": 70,
    "retryable": true
  }
}
```

Stable codes include `INVALID_REQUEST`, `UNSUPPORTED_CONCEPT`,
`JOB_NOT_FOUND`, `ARTIFACT_NOT_READY`, `ARTIFACT_NOT_AVAILABLE`,
`IDEMPOTENCY_CONFLICT`, `UNAUTHORIZED`, `RATE_LIMITED`, `REQUEST_TOO_LARGE`,
and the pipeline failures (`SCRIPT_VALIDATION_FAILED`, `NARRATION_GENERATION_FAILED`,
`RENDER_FAILED`, `VIDEO_VALIDATION_FAILED`, `JOB_TIMEOUT`, `INTERNAL_ERROR`, ...).

### Idempotency

Send an `Idempotency-Key` header to reuse the same job for the same query.
Reusing the key with a different query returns `409 IDEMPOTENCY_CONFLICT`.

## Configuration

Settings are loaded through Pydantic Settings from environment variables and an
optional `.env` file. Invalid values fail fast at startup. See `.env.example`
for the full list and comments.

Key variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_ENV` | `local` | `local`, `test`, `staging`, or `production` |
| `API_KEY` | unset | Require `X-API-Key` on `/v1` routes |
| `RATE_LIMIT_PER_MINUTE` | `0` | Per-IP sliding window; `0` disables |
| `MAX_REQUEST_BYTES` | `65536` | Declared request body limit |
| `ARTIFACT_DIR` / `DATA_DIR` | `./artifacts` / `./data` | Writable storage |
| `ASSETS_DIR` | `./assets` | Canonical narration assets |
| `JOB_REPOSITORY` | `memory` | `memory` or `sqlite` |
| `DATABASE_URL` | `sqlite:///./data/app.db` | SQLite path when enabled |
| `VIDEO_WIDTH` / `VIDEO_HEIGHT` | `1280` / `720` | H.264 output size (must be even) |
| `VIDEO_FPS` | `30` | Output frame rate |
| `VIDEO_QUALITY` | `high` | `low`, `medium`, or `high` |
| `MAX_CONCURRENT_JOBS` | `2` | Embedded/standalone worker concurrency |
| `JOB_TIMEOUT_SECONDS` | `900` | Hard per-job deadline |
| `SCRIPT_SOURCE` | `canonical` | `canonical` or `canonical_with_llm_fallback` |
| `TTS_PROVIDER` | `canonical_cache` | `canonical_cache`, `windows_sapi`, `espeak`, `openai`, `mock` |
| `ALLOW_PLACEHOLDER_AUDIO` | `false` | Permit synthetic narration |
| `GENERATION_MODE` | `real` | `fake` is for tests/local integration only |
| `WORKER_MODE` | `embedded` | `embedded`, `api_only`, or `standalone` |

`GENERATION_MODE=fake` and `TTS_PROVIDER=mock` are rejected when
`APP_ENV=production`.

### Worker modes

- `embedded` (default): the API process starts the bounded worker pool.
- `api_only`: only the API; run a separate worker process.
- `standalone`: run the worker pool without serving HTTP. The
  `chemistry-video-worker` entry point forces this mode.

For multiple processes or containers, use `JOB_REPOSITORY=sqlite` so everyone
shares queued jobs. SQLite uses WAL mode and a busy timeout.

## Demos and verification

The API must already be running. Both Bash and PowerShell versions are
provided.

```bash
# Single query; video is written to downloads/
bash scripts/demo.sh "How does the pH scale work?"

# All three required queries, followed by FFprobe verification
bash scripts/run_required_jobs.sh

# Verify any MP4 (video stream, audio stream, duration >= 10s)
bash scripts/verify_artifact.sh downloads/ph_scale.mp4
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\demo.ps1 `
  -Query "How does the pH scale work?"

powershell -ExecutionPolicy Bypass -File scripts\run_required_jobs.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_artifact.ps1 downloads\ph_scale.mp4
```

Environment variables for the demo scripts:

- `API_BASE_URL` (default `http://127.0.0.1:8000`)
- `API_KEY` when authentication is enabled
- `POLL_TIMEOUT_SECONDS` (default `900`)

The scripts download the MP4, print the local artifact path, and exit non-zero
if generation fails or verification does not pass.

## Tests

```bash
# Fast suite: domain, API contract, hardening (fake pipeline)
pytest tests/unit tests/integration

# Real pipeline at 426x240 / 5 fps with deterministic placeholder narration
pytest tests/e2e -m e2e

# Individual suites
pytest tests/unit
pytest tests/integration
pytest tests/e2e -m "e2e and not reliability"
pytest tests/e2e -m reliability
```

E2E tests cover all three required queries and a three-run pH reliability test.
They are marked `e2e` so fast CI can skip them. Integration tests use the fake
pipeline and cover the required contract names, idempotency, validation errors,
failed-job artifacts, authentication, rate limiting, request size, metrics, and
readiness.

Quality checks:

```bash
ruff check .
ruff format --check .
mypy app
```

Logs can be emitted as JSON (`LOG_FORMAT=json`) for ingestion or as readable text
(`LOG_FORMAT=text`). Every request carries `X-Request-ID`; job logs include
`job_id`, `concept_id`, `stage`, and stable event names.

## Make targets

`make` is optional. These targets mirror the direct commands:

```bash
make install
make run
make worker
make test
make test-e2e
make lint
make typecheck
make demo
make docker-build
make docker-run
```

On Windows without `make`, use the PowerShell commands in the Quick start and
the `.ps1` demo scripts.

## Docker

Build and run the single-container service:

```bash
docker build -t chemistry-video-service .
docker run --rm -p 8000:8000 \
  -v "$PWD/artifacts:/app/artifacts" \
  -v "$PWD/data:/app/data" \
  chemistry-video-service
```

The image installs FFmpeg and DejaVu fonts, runs as a non-root user, and uses
`TTS_PROVIDER=canonical_cache` with the bundled narration assets.

API + standalone worker with shared SQLite and artifacts:

```bash
docker compose up --build
```

Compose runs the API with `WORKER_MODE=api_only` and a separate worker with
`WORKER_MODE=standalone`. Both share the `artifacts` and `data` volumes and the
SQLite database. The API is exposed on port `8000`.

## CI

The GitHub Actions workflow installs FFmpeg, caches pip dependencies, and runs:

```bash
pip install -e ".[dev]"
ruff check .
mypy app
pytest tests/unit
pytest tests/integration
```

E2E tests run on a nightly schedule and on manual dispatch. The workflow is
included at both the repository root (for the current monorepo layout) and in
this project directory (for standalone extraction).

## Design notes

- **Validation first.** Scripts are validated before narration or rendering;
  audio and the final MP4 are validated before a job is marked complete.
- **Bounded retries.** Narration synthesis retries once, rendering retries
  once, and an artifact validation failure triggers one re-render while staying
  in `artifact_validation`. Timeouts are enforced at every major boundary.
- **Deterministic rendering.** Raw RGB frames are streamed to FFmpeg, encoded as
  H.264/AAC, concatenated with stream copy (with a re-encode fallback), and
  checksummed. Subtitles and a thumbnail are generated alongside the video.
- **Safe artifacts.** Job IDs are parsed as UUIDs and artifact paths are
  allowlisted and contained under the artifact root.
- **No secret leakage.** Error payloads are normalized; unexpected exceptions
  are logged server-side and returned as `INTERNAL_ERROR`.
- **Optional LLM scripts.** `SCRIPT_SOURCE=canonical_with_llm_fallback` can use
  an OpenAI-compatible endpoint, but generated scripts must pass the same
  validation and fall back to canonical content on failure.

## Extending content

1. Add a `ConceptPack` in `app/generation/content/canonical_scripts.py` (or a new
   content module).
2. Register it in `app/generation/content/__init__.py`.
3. Add or reuse a renderer layout in `app/generation/visuals/layouts.py`.
4. Add narration assets with `python scripts/generate_narration_assets.py`, or
   let the configured TTS provider synthesize them on first use.
5. Add the concept to unit and E2E tests.

## Limitations

- The in-process rate limiter is per API instance; use a shared store such as
  Redis for multi-instance abuse protection.
- The built-in repository supports memory and SQLite. PostgreSQL/Redis/S3
  adapters are intentionally left as production extensions; the artifact store
  exposes a protocol so an object-storage backend can be added.
- SAPI asset generation requires Windows. The bundled WAVs make runtime
  narration portable; `espeak` is the Linux fallback.
