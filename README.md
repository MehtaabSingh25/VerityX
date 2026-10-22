# VerityX

**Digital Media Intelligence & Forensics**

VerityX is a digital media forensics platform in development, designed to help users examine images and videos, compare related media, investigate possible media provenance, and document evidence-backed findings.

This solo project focuses on backend engineering, asynchronous processing, reliable data pipelines, and explainable media analysis.

> **Status:** Early development. Features in the roadmap are planned and should not be considered implemented until they are available and tested.

## Project Goals

- Securely ingest and validate image and video files.
- Calculate cryptographic hashes to identify exact file matches.
- Extract media metadata and video frames.
- Run computationally expensive analysis through background workers.
- Compare media using perceptual hashes and, where appropriate, pretrained embeddings.
- Maintain structured investigation records and analysis history.
- Visualize possible relationships between media with supporting evidence and uncertainty.
- Generate reproducible investigation reports.

VerityX is intended to support investigations, not make definitive authenticity claims. Metadata, similarity measurements, and model predictions are signals that require context; none independently proves that media is authentic or manipulated.

## Technology Stack

| Component             | Technology                        | Purpose                                              |
| --------------------- | --------------------------------- | ---------------------------------------------------- |
| Frontend              | Next.js, React, TypeScript        | Investigation dashboard and evidence visualization   |
| Backend API           | Python, FastAPI, Pydantic         | API endpoints and request validation                 |
| Database              | PostgreSQL, SQLAlchemy, Alembic   | Relational data modeling and schema migrations       |
| Background processing | Celery, Redis                     | Asynchronous jobs, retries, and task status          |
| Media processing      | OpenCV, FFmpeg, hashing libraries | Media inspection, frame extraction, and fingerprints |
| Object storage        | S3-compatible storage             | Original uploads and derived artifacts               |
| Testing               | Pytest                            | Unit and integration tests                           |
| Code quality          | Ruff, mypy                        | Linting and static type checking                     |
| Infrastructure        | Docker Compose                    | Reproducible development environment                 |
| CI                    | GitHub Actions                    | Automated testing and quality checks                 |

The stack will be introduced incrementally. This list describes the intended architecture, not a claim that every component is already implemented.

## Planned Architecture

```text
Next.js Frontend
       |
       v
FastAPI Application
       |
       +------ PostgreSQL
       |
       +------ Redis Task Queue
                    |
                    v
              Celery Workers
                    |
                    +---- Media validation and hashing
                    +---- Metadata and frame extraction
                    +---- Similarity analysis
                    +---- Findings and report generation
                    |
                    v
              Object Storage
```

The initial design favors a modular backend and a separate worker process instead of premature microservices.

## Repository Structure

```text
VerityX/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── models/
│   │   ├── schemas/
│   │   └── services/
│   ├── tests/
│   └── requirements.txt
├── frontend/
├── docs/
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

The structure may evolve as development progresses.

## Getting Started

### Prerequisites

- Git
- Python 3.12 or another explicitly supported Python version
- Node.js LTS and npm
- Docker Desktop with WSL2 on Windows, or Docker Engine on Linux/macOS

### 1. Clone the Repository

```bash
git clone <YOUR_GITHUB_REPOSITORY_URL>
cd VerityX
```

### 2. Configure Environment Variables

Create a local `.env` file using `.env.example` as a template when available. Configure a strong development-only database password.

**Never commit `.env`, API keys, passwords, or production secrets.**

### 3. Start Infrastructure

Once the Docker Compose configuration is ready:

```bash
docker compose up -d
docker compose ps
```

### 4. Set Up the Backend

```bash
cd backend
python -m venv .venv
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

On macOS/Linux:

```bash
source .venv/bin/activate
```

Install dependencies and start the API:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload
```

When the API scaffold is configured, visit:

- API: `http://127.0.0.1:8000`
- Interactive API documentation: `http://127.0.0.1:8000/docs`
- Health endpoint: `http://127.0.0.1:8000/health`

### 5. Set Up the Frontend

In a separate terminal:

```bash
cd frontend
npm install
npm run dev
```

Visit `http://localhost:3000`.

These instructions assume the corresponding configuration and application files exist in the current checkout.

## Testing and Code Quality

Planned backend checks include:

```bash
pytest
ruff check .
mypy app
```

Frontend linting, integration testing, and CI checks will be documented as those workflows are configured.

## Security and Evidence Principles

- Validate file size, content, and actual file format rather than trusting filename extensions.
- Treat uploaded files and embedded metadata as untrusted input.
- Keep uploaded media outside publicly served directories.
- Preserve original-file hashes and distinguish original files from derived artifacts.
- Record analysis methods and versions where reproducibility matters.
- Apply least-privilege access controls and protect credentials.
- Label model predictions, inferred relationships, and uncertainty explicitly.
- Never present an AI-generated score as definitive proof of authenticity or manipulation.


## Asynchronous analysis jobs

The asynchronous analysis pipeline supports three jobs: checking whether a stored file's SHA-256 hash still matches its ingestion record, extracting basic image properties with a conservative EXIF allowlist, and computing a 64-bit difference hash (dHash) for coarse image similarity. PostgreSQL stores job status, results, and append-only lifecycle events; Redis is used as the Celery broker. Image analysis uses Pillow. Video analysis uses OpenCV to inspect basic stream properties and sample a bounded set of frames for dHash fingerprints; it does not require a GPU. Video results depend on codec support in the installed OpenCV build and are not authenticity verdicts.

The metadata extractor intentionally omits GPS coordinates and arbitrary EXIF fields from its returned result. dHash is a similarity fingerprint, not a cryptographic integrity check and not proof that two files are identical or manipulated.

Install the additional worker dependencies from the backend directory:

```bash
pip install -r requirements-async.txt
```

Start PostgreSQL and Redis from the repository root:

```bash
docker compose up -d postgres redis
```

In one backend terminal, start the API:

```bash
uvicorn app.main:app --reload
```

In another backend terminal, start a development worker. On Windows, `--pool=solo` is the practical local-development option; Linux containers are recommended for production workers:

```bash
celery -A app.celery_app:celery_app worker --loglevel=INFO --pool=solo
```

Submit an analysis job for a media asset:

```http
POST /api/v1/media/{media_asset_id}/analysis-jobs
Content-Type: application/json

{"analysis_type": "integrity_check"}
```

For image assets, the supported `analysis_type` values also include:

- `metadata_extract` — basic dimensions, format, mode, and an EXIF allowlist.
- `perceptual_hash` — a 64-bit difference hash for coarse visual similarity.

For video assets, the supported `analysis_type` values also include:

- `video_metadata` — container/stream properties reported by OpenCV, including dimensions, FPS, frame count, and estimated duration.
- `video_frame_fingerprints` — samples up to 12 evenly spaced frames and computes a dHash for each sampled frame.

Install the async/video dependencies with `python -m pip install -r requirements-async.txt`. OpenCV support depends on the installed build and the video's codec. Frame fingerprints are coarse similarity cues, not proof of authenticity or manipulation.

The API returns a job record with a UUID and initial status. Poll its status using:

```http
GET /api/v1/analysis-jobs/{job_id}
```

Possible states are `queued`, `running`, `completed`, and `failed`. Retrieve the recorded lifecycle with `GET /api/v1/analysis-jobs/{job_id}/events`; events include queueing, worker start, completion, retry scheduling, and terminal failure. Apply database changes with `alembic upgrade head` before using this endpoint. The integrity check compares the stored file's computed SHA-256 digest with the digest recorded during ingestion. Image jobs return structured metadata or a dHash result in the job's `result` field. A mismatch is a completed check with `matches: false`, not proof of malicious manipulation.

## Observability and health checks

The API emits one JSON log object per line. HTTP request logs include a request ID, method, matched route template, response status, and duration; analysis-worker logs include the job ID, analysis type, lifecycle event, duration when completed or failed, and exception type. Logs intentionally avoid media contents, request bodies, credentials, and raw exception messages in structured fields. A stack trace may still appear for worker exceptions to support debugging.

Use `GET /health` to check PostgreSQL and Redis connectivity. It returns `200` when both are reachable and `503` when a dependency is unavailable. `GET /metrics` exposes Prometheus-format metrics for API HTTP request counts and durations, submitted analysis jobs, and enqueue failures. The metrics endpoint is intended for a trusted local or monitoring network; restrict access when deploying publicly.

Because the API and Celery worker run as separate processes, `/metrics` describes the API process only. Worker execution outcomes are currently observable through structured worker logs and persisted job/event records; worker-level Prometheus aggregation is a future improvement.

`GET /api/v1/operations/summary` provides database-backed counts of analysis jobs by status and analysis type, plus lifecycle events by event type. It intentionally excludes media content and free-form error messages. Treat this endpoint as operational information and restrict access to trusted operators when deploying beyond a local development environment.

## Roadmap

- [ ] Establish the repository and local development environment
- [ ] Connect FastAPI to PostgreSQL using SQLAlchemy and Alembic
- [ ] Define investigation, media asset, and analysis job models
- [ ] Implement validated media uploads and SHA-256 hashing
- [ ] Add Redis and Celery background processing
- [x] Implement initial image metadata extraction and difference hashing
- [x] Add bounded video frame sampling and frame-level dHash fingerprints
- [ ] Build the investigation dashboard and evidence visualization
- [x] Add initial video stream metadata extraction with OpenCV
- [x] Record analysis-job lifecycle events for basic processing provenance
- [ ] Add structured reports and expanded analysis provenance
- [x] Add initial API request metrics, dependency health checks, and structured worker logs
- [x] Add end-to-end API workflow tests for upload, analysis, events, and reports
- [ ] Expand worker-level metrics aggregation and deployment automation

## License

A license has not yet been selected. Until one is added, do not assume others have permission to reuse, distribute, or modify this project.

## Investigation similarity search

VerityX can compare completed image `perceptual_hash` jobs with other image fingerprints and with sampled frames from completed `video_frame_fingerprints` jobs. Use `GET /api/v1/investigations/{investigation_id}/similarity`; the optional `max_distance` query parameter controls the maximum dHash Hamming distance (0–64), and `limit` caps returned matches (1–500). Smaller distances indicate closer bit patterns. The API returns the best sampled-frame match for each pair of media assets, along with frame index/timestamp where available. This is a candidate-discovery aid only: scores are not probabilities, sampled frames can miss content, and similarity does not establish authenticity, common origin, or manipulation.

- [x] Add bounded investigation-level image/video fingerprint similarity search

## Investigation reports

Generate an on-demand JSON report for an investigation with `GET /api/v1/investigations/{investigation_id}/report`. Optional query parameters `max_distance` (0–64, default 10) and `similarity_limit` (1–500, default 100) control candidate similarity findings. The report includes an inventory of media assets, analysis-job statuses and results, recorded job lifecycle events, integrity mismatches, and cross-media similarity candidates.

Reports are generated from the current database records and include a generation timestamp and schema version; they are not immutable exports or tamper-proof audit artifacts. Export or preserve a report separately if a fixed snapshot is required. The report excludes GPS coordinates and arbitrary EXIF fields. Similarity matches are candidate leads only, and a SHA-256 mismatch indicates a difference from the ingestion digest rather than proving malicious tampering.

## Containerized backend stack

The backend can be run with Docker Compose alongside PostgreSQL and Redis. Set `POSTGRES_PASSWORD` in a root `.env` file before starting the stack; use a strong local-only value and never commit the file. The API container runs Alembic migrations before starting FastAPI, and the Celery worker starts only after the API health check succeeds. Both containers mount the same private media volume so uploaded files are available to background jobs.

Build and start the complete backend stack from the repository root:

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f api worker
```

The API is bound to `127.0.0.1:8000` by default. Check `http://127.0.0.1:8000/health` and `http://127.0.0.1:8000/docs`. PostgreSQL and Redis ports remain bound to localhost for development. This Compose configuration is a reproducible single-host deployment baseline, not a hardened public production deployment; add TLS, authentication/authorization, secret management, backups, and network restrictions before exposing it to untrusted users.

## End-to-end workflow tests

`backend/tests/test_investigation_workflow.py` exercises investigation creation, media upload, analysis-job execution, event retrieval, and report generation against an isolated SQLite database. The tests run the real analysis task body synchronously and replace only the Celery broker handoff, so they do not require local PostgreSQL or Redis services. Run them with `python -m pytest -q` from `backend`; production-like broker and database behavior should still be smoke-tested with Docker Compose separately.
