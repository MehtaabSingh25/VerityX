# VerityX Frontend

Next.js App Router frontend for the VerityX digital media forensics project.

## Local development

1. Install dependencies with `npm ci`.
2. Copy `.env.example` to `.env.local` and configure the backend URL and, if enabled, the server-side service API key.
3. Start the FastAPI backend at the configured URL.
4. Run `npm run dev` and open `http://localhost:3000`.

## Backend connection

The browser talks to a same-origin Next.js route handler at `/api/backend/...`. That server-side proxy forwards requests to `VERITYX_BACKEND_URL` and attaches `VERITYX_API_KEY` when configured. Never expose the service API key through a `NEXT_PUBLIC_*` variable.

Supported live actions in this milestone:

- Check backend reachability through `/health`.
- Create investigations with `POST /api/v1/investigations`.
- Upload selected media with `POST /api/v1/investigations/{id}/media`.
- Submit SHA-256 integrity jobs with `POST /api/v1/media/{media_asset_id}/analysis-jobs`.
- Refresh a submitted job using `GET /api/v1/analysis-jobs/{job_id}`.

Investigation-scoped tokens returned by the backend (if configured) are held in `sessionStorage` for the current browser session and sent only to the same-origin server proxy. This is a development integration, not a replacement for a mature account/session system.

The overview's preloaded investigation rows and summary counts are illustrative sample data. The current workspace shows files selected during the active browser session; it does not yet fetch a complete stored investigation/media inventory after a page reload. The investigation report page loads the stored report, evidence inventory, analysis results, embedded lifecycle events, and live similarity candidates. Job event timelines can be refreshed per job, and the report can be exported as JSON. The dashboard inventory remains illustrative; a full list of stored investigations is a separate integration task.

## Validation

Run `npm run lint` and `npm run build` before committing frontend changes.
