# VerityX Frontend

The frontend is a Next.js App Router application built with React, TypeScript, and Tailwind CSS. The first milestone provides a responsive investigation dashboard prototype.

## Run locally

```bash
npm install
npm run dev
```

Open <http://localhost:3000>.

## Current scope

- Responsive dashboard layout and navigation.
- Sample investigation records, status filtering, and text search.
- A local-only “new investigation” dialog to exercise the interface.
- Sample activity, job queue, and integrity summary panels.
- Explicit demo-state messaging so sample counts are not mistaken for backend data.

**Important:** this milestone does not connect to FastAPI or persist newly created demo records. The UI uses illustrative data. API integration, safe credential handling, live job polling, and authenticated evidence operations are subsequent milestones. Never place a private service API key in a `NEXT_PUBLIC_*` variable.

## Checks

```bash
npm run lint
npm run build
```
