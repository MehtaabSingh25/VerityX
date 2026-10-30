# VerityX

**Digital Media Intelligence & Forensics**  
*A backend-focused platform for media examination, evidence management, and provenance research.*

VerityX is a full-stack digital media investigation platform built around a modular **FastAPI backend** and an asynchronous analysis pipeline. It lets users create investigations, securely ingest image and video evidence, run integrity and media-analysis jobs, compare visual fingerprints, search for visually related public-web images, and generate structured investigation reports.

The project emphasizes practical backend and systems engineering: durable job orchestration, transactional messaging, scoped access tokens, database-backed audit history, media validation, observability, and containerized deployment.

> **Important:** VerityX provides investigative signals, not definitive authenticity verdicts. Similarity results, metadata, reverse-image-search matches, and AI-detector scores require human review and corroborating evidence.

---

## What it does

### Investigation and evidence management

- Create and manage investigation workspaces.
- Upload image and video evidence with server-side validation and configurable upload-size limits.
- Store evidence files outside publicly served frontend assets.
- Calculate SHA-256 hashes at ingestion to identify and later verify the integrity of stored files.
- Maintain evidence inventory and investigation-scoped access.
- Rotate investigation access tokens; store token digests rather than plaintext tokens.

### Asynchronous media analysis

Analysis is submitted through the API and processed by Celery workers rather than blocking upload or request handling. Supported analysis jobs include:

| Job | What it does |
|---|---|
| `integrity_check` | Recomputes SHA-256 and compares it with the ingestion record. |
| `metadata_extract` | Extracts basic image properties and a conservative EXIF allowlist. GPS coordinates and arbitrary EXIF fields are intentionally omitted. |
| `perceptual_hash` | Computes a 64-bit difference hash (dHash) for coarse image similarity. |
| `video_metadata` | Reads basic video/container properties using OpenCV. |
| `video_frame_fingerprints` | Samples up to 12 evenly spaced video frames and computes dHash fingerprints. |
| `ai_image_detection` | Runs the local Smaug AI-image detector against image evidence. |

Job records and lifecycle events are persisted in PostgreSQL. Clients can inspect job status and event history, including queueing, worker start, completion, retry scheduling, and failure.

### Similarity and provenance research

- Compare completed image dHash and sampled-video frame fingerprints within an investigation.
- Search for visually related public-web images.
- Use SerpApi Google Lens when `SERPAPI_API_KEY` is configured.
- Fall back to Openverse and Wikimedia Commons when SerpApi is not configured or its request fails.
- Generate a structured JSON investigation report from stored evidence, analysis jobs, lifecycle events, and similarity results.

Reverse-image-search results are leads for further research. They do not independently establish image identity, ownership, source, or publication date. The SerpApi workflow sends a compressed evidence image to SerpApi; only submit media you are authorized to share.

### AI-generated image analysis

VerityX runs **Abacus.AI's Smaug-AI-Image-Detector** locally in the Celery worker. The model produces an AI-generation score from 0 to 1. The configured threshold (default `0.5`) determines the displayed classification.

- Model: [`abacusai/Smaug-AI-Image-Detector`](https://huggingface.co/abacusai/Smaug-AI-Image-Detector)
- Model execution: local worker inference; image bytes are not sent to a hosted inference API for this step.
- Configuration: `VERITYX_AI_DETECTION_THRESHOLD`
- Model score: not independently calibrated for VerityX and not proof of image origin.

The model can produce false positives and false negatives, including on new generators, edited photographs, compressed images, or unfamiliar image sources. Treat the output as one signal among several and do not use it alone for consequential decisions. See [`backend/AI_DETECTION.md`](backend/AI_DETECTION.md) for runtime details and limitations.

---

## Architecture

```text
                   Browser
                      |
                      v
             Next.js / React UI
                      |
             Next.js backend proxy
                      |
                      v
                FastAPI API
                 /       \
                /         \
               v           v
          PostgreSQL      Redis
       investigations,     |
       evidence, jobs,     | Celery broker
       events, outbox      v
                       Celery worker
                    media and AI analysis
                           |
                           v
                    Shared media volume

             Outbox dispatcher
          PostgreSQL outbox -> Redis
```

### Reliability design

- **PostgreSQL** is the source of truth for investigations, media assets, analysis jobs, job events, evidence audit records, and outbox messages.
- **Redis** is used as the Celery message broker.
- **Celery** executes long-running analysis tasks outside API request handling.
- **Transactional outbox** writes the queued job and its dispatch message in the same database transaction. A separate dispatcher retries publishing when Redis is unavailable. Delivery is at least once, so task handling is designed to tolerate duplicate delivery.
- **Idempotency keys** allow clients to safely retry job submissions without unintentionally creating duplicate work for the same media asset and analysis type.
- **Scoped investigation tokens** limit access to investigation resources; service-key-protected operations handle trusted administrative actions.
- **Structured logs, request IDs, health checks, and Prometheus metrics** support operational diagnosis.

The application is organized as a modular backend with separate API, worker, and outbox-dispatcher processes rather than a collection of independently deployed microservices.

---

## Technology stack

| Layer | Technologies | Responsibility |
|---|---|---|
| Frontend | Next.js 16, React 19, TypeScript | Investigation workspace, evidence views, job status, and reports |
| API | Python 3.12, FastAPI, Pydantic | REST endpoints, validation, access control |
| Persistence | PostgreSQL 16, SQLAlchemy, Alembic | Relational data and schema migrations |
| Queue and workers | Redis 7, Celery | Background job execution and retries |
| Media processing | Pillow, OpenCV, FFmpeg | Image validation, metadata, video inspection, frame sampling |
| Integrity and similarity | SHA-256, dHash | Exact-file integrity checks and coarse visual similarity |
| AI analysis | PyTorch (CPU), Transformers, Sentence Transformers, Smaug | Local AI-generated image scoring |
| Public image search | SerpApi Google Lens, Openverse, Wikimedia Commons | Reverse-image/provenance research |
| Observability | Structured logging, Prometheus metrics | Request/job telemetry and health monitoring |
| Infrastructure | Docker, Docker Compose, Caddy | Local stack and optional HTTPS single-host deployment |
| Testing and CI | Pytest, GitHub Actions | Backend regression tests and automated quality gate |

---

## Repository layout

```text
VerityX/
├── backend/
│   ├── app/
│   │   ├── api/              # REST endpoints
│   │   ├── core/             # Configuration, security, access, observability
│   │   ├── db/               # SQLAlchemy database setup
│   │   ├── models/           # Persistence models
│   │   ├── schemas/          # Request/response schemas
│   │   ├── services/         # Media, AI, similarity, search, reporting
│   │   ├── tasks/            # Celery tasks
│   │   ├── celery_app.py
│   │   ├── outbox.py
│   │   └── outbox_dispatcher.py
│   ├── migrations/           # Alembic migrations
│   ├── tests/                # Backend test suite
│   ├── Dockerfile
│   ├── requirements.txt
│   └── requirements-async.txt
├── frontend/
│   └── src/app/              # Next.js application and investigation views
├── .github/workflows/        # CI quality gate
├── Caddyfile                 # Optional production reverse proxy
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Getting started with Docker Compose

### Prerequisites

- Git
- Docker Desktop with the WSL 2 backend (Windows), or Docker Engine and the Compose plugin (Linux)
- Internet access for pulling container images and downloading the Smaug model on first inference
- Sufficient disk space for container images, PostgreSQL data, uploaded media, and the model cache

### 1. Clone the repository

```bash
git clone https://github.com/MehtaabSingh25/VerityX.git
cd VerityX
```

### 2. Configure environment variables

Copy the example environment file:

```powershell
Copy-Item .env.example .env
```

Set at least these values in `.env`:

```dotenv
POSTGRES_PASSWORD=your-long-url-safe-password
VERITYX_API_KEY=your-long-random-service-key
MAX_UPLOAD_SIZE_BYTES=52428800
VERITYX_AI_DETECTION_THRESHOLD=0.5
SERPAPI_API_KEY=
```

`SERPAPI_API_KEY` is optional. Without it, the public image-search service uses the available free-index fallback. `.env.example` also contains `VERITYX_DOMAIN` for the optional production profile.

Generate secrets rather than reusing passwords. Keep `.env` private and never commit API keys or production credentials.

### 3. Build and start the application

From the repository root:

```bash
docker compose up --build -d
docker compose ps
```

The default Compose stack starts PostgreSQL, Redis, the FastAPI API, the Celery worker, the outbox dispatcher, and the Next.js frontend. The API container applies Alembic migrations before starting the application.

Open:

- Frontend: http://localhost:3000
- API health: http://localhost:8000/health
- API documentation: http://localhost:8000/docs

The API and frontend host ports are bound to localhost in the supplied Compose file. PostgreSQL and Redis are also bound to localhost; they are not intended to be exposed publicly.

### 4. Useful Docker commands

```bash
# Follow application and worker logs
docker compose logs -f api worker outbox-dispatcher

# View service status
docker compose ps

# Rebuild after changing backend dependencies or source
docker compose up --build -d

# Stop services without deleting persisted volumes
docker compose down
```

**Do not use `docker compose down -v` unless you intentionally want to delete the PostgreSQL and media volumes.**

---

## API overview

The interactive OpenAPI documentation at `/docs` is the authoritative reference for request schemas and response details. The main API capabilities include:

| Capability | Endpoint |
|---|---|
| Health and dependency status | `GET /health` |
| Create an investigation | `POST /api/v1/investigations` |
| Upload evidence | `POST /api/v1/investigations/{investigation_id}/media` |
| List investigation evidence | `GET /api/v1/investigations/{investigation_id}/media` |
| Submit an analysis job | `POST /api/v1/media/{media_asset_id}/analysis-jobs` |
| Read analysis job status | `GET /api/v1/analysis-jobs/{job_id}` |
| Read job lifecycle events | `GET /api/v1/analysis-jobs/{job_id}/events` |
| Search public web images | `POST /api/v1/media/{media_asset_id}/web-image-search` |
| Compare visual fingerprints | `GET /api/v1/investigations/{investigation_id}/similarity` |
| Generate an investigation report | `GET /api/v1/investigations/{investigation_id}/report` |
| Operational job summary | `GET /api/v1/operations/summary` |
| Prometheus metrics | `GET /metrics` |

Investigation creation and token rotation use the service API key. Investigation-scoped operations use the `X-Investigation-Token` header returned when an investigation is created or its token is rotated. The frontend's Next.js backend proxy communicates with FastAPI using the configured service credential; the service key is not intended to be exposed to browser code.

For the exact upload fields, supported analysis types, and authentication requirements, use `/docs` and the backend API schemas.

---

## Analysis workflow example

A typical workflow is:

1. Create an investigation from the workspace.
2. Upload an image or video as evidence.
3. Submit one or more analysis jobs for the stored media asset.
4. Poll the job endpoint or inspect its event history while the worker processes it.
5. Run similarity comparison or public-web image search when relevant.
6. Review the evidence and analysis history, then retrieve the investigation report.

Analysis jobs are asynchronous. A successful submission means the job was accepted; it does not mean the analysis has completed. Job states include `queued`, `running`, `completed`, and `failed`.

For a detailed example, submit a job with the `analysis_type` field, for example:

```json
{
  "analysis_type": "integrity_check"
}
```

An optional `Idempotency-Key` header can be used when submitting jobs. Repeating the same key and analysis type for the same media asset returns the existing job instead of creating duplicate work. Reusing a key for a different analysis type returns a conflict.

---

## Testing

The backend test suite is located in `backend/tests`. Run it from the backend directory:

```bash
cd backend
python -m pip install -r requirements.txt -r requirements-async.txt
python -m pytest -q
```

The repository includes tests covering health checks, media validation, security, investigation workflows, AI detection behavior, analysis tasks and events, worker reliability, transactional outbox behavior, evidence auditing, reports, similarity, video analysis, web-image search, and observability.

A GitHub Actions workflow is defined in `.github/workflows/quality-gate.yml`. Run the checks in the workflow when preparing changes for merge. A passing unit/integration suite does not replace a real Docker-based smoke test of PostgreSQL, Redis, Celery message delivery, and worker process recovery.

---

## Configuration reference

| Variable | Purpose | Default / requirement |
|---|---|---|
| `POSTGRES_PASSWORD` | PostgreSQL password used by Compose | Required |
| `VERITYX_API_KEY` | Trusted service/admin API credential | Required |
| `MAX_UPLOAD_SIZE_BYTES` | Maximum accepted upload size | `52428800` (50 MiB) |
| `VERITYX_AI_DETECTION_THRESHOLD` | Smaug AI-generation classification threshold | `0.5` |
| `SERPAPI_API_KEY` | Enables Google Lens via SerpApi | Optional |
| `VERITYX_DOMAIN` | Domain for optional Caddy production profile | Used with production profile |
| `DATABASE_URL` | SQLAlchemy database connection | Set by Compose services |
| `REDIS_URL` | Redis connection / Celery broker | Set by Compose services |
| `MEDIA_STORAGE_DIR` | Persistent media storage directory | `/app/data/media` in Compose |
| `HF_HOME` | Hugging Face model cache | `/app/data/media/.hf_cache` in Compose |

---

## Optional HTTPS deployment

The Compose file includes a `production` profile with Caddy as a reverse proxy. It is intended for a Linux server with a domain configured to point to the host and inbound TCP ports 80 and 443 open.

Set `VERITYX_DOMAIN` in `.env`, then run:

```bash
docker compose --profile production up --build -d
```

Caddy handles HTTPS certificates and proxies public requests to the frontend. The API, frontend, PostgreSQL, and Redis are not directly exposed on public interfaces by the default port bindings. This is a **single-host deployment**, not a high-availability architecture. Configure off-host backups, monitor disk usage, and review authentication, rate limiting, retention, and privacy requirements before accepting untrusted users.

---

## Security, privacy, and forensic limitations

- Uploaded files are untrusted input; validate actual content and enforce size limits.
- Original media is stored in the persistent media volume and should be protected with appropriate host and volume access controls.
- Investigation tokens are scoped to investigation access; the database stores their SHA-256 digests.
- Keep service keys and third-party API credentials server-side.
- The SerpApi Google Lens path sends a compressed copy of the submitted image to SerpApi. Review its terms and your authorization to share the evidence before enabling it.
- Free image-search fallbacks cover openly indexed sources and are not equivalent to a whole-web search.
- dHash measures coarse visual similarity; it is not a cryptographic integrity check.
- Sampled video frames may miss content between samples, and video processing depends on codec support.
- AI-detection scores can be wrong and are not independently calibrated for VerityX.
- Similarity, metadata, reverse-image matches, and model predictions do not independently prove authenticity, manipulation, ownership, identity, or provenance.

Use VerityX as an investigative aid and retain human review and corroborating evidence in the decision process.

---

## Project focus

VerityX is designed to demonstrate backend and systems engineering through a practical media-investigation workflow: API design, relational data modeling, secure file handling, background processing, durable job dispatch, idempotency, auditability, observability, and containerized operations.

The emphasis is on building a dependable evidence-processing system—not claiming that any single detector or similarity algorithm can determine the truth about a piece of media.
