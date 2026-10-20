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

## Roadmap

- [ ] Establish the repository and local development environment
- [ ] Connect FastAPI to PostgreSQL using SQLAlchemy and Alembic
- [ ] Define investigation, media asset, and analysis job models
- [ ] Implement validated media uploads and SHA-256 hashing
- [ ] Add Redis and Celery background processing
- [ ] Implement metadata extraction and perceptual hashing
- [ ] Add video frame extraction and media comparison
- [ ] Build the investigation dashboard and evidence visualization
- [ ] Add structured reports and analysis provenance
- [ ] Implement integration tests, observability, and deployment automation

## License

A license has not yet been selected. Until one is added, do not assume others have permission to reuse, distribute, or modify this project.
