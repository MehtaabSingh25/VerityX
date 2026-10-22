export type InvestigationResponse = {
  id: string;
  title: string;
  description: string | null;
  status?: string;
  created_at?: string;
  investigation_token?: string;
  access_token?: string;
  token?: string;
};

export type MediaResponse = {
  id: string;
  investigation_id: string;
  original_filename: string;
  sha256: string;
  mime_type: string;
  size_bytes: number;
  created_at: string;
};

export type AnalysisJobResponse = {
  id: string;
  media_asset_id: string;
  analysis_type: string;
  status: string;
  result?: Record<string, unknown> | null;
  error_message?: string | null;
};

function investigationToken(id: string): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(`verityx:investigation-token:${id}`);
}

async function requestJson<T>(
  path: string,
  options: RequestInit = {},
  investigationId?: string,
): Promise<T> {
  const headers = new Headers(options.headers);
  if (investigationId) {
    const token = investigationToken(investigationId);
    if (token) headers.set("X-Investigation-Token", token);
    // The ID is only a lookup hint for the proxy; the backend must validate the token.
    headers.set("X-Investigation-ID", investigationId);
  }

  const response = await fetch(`/api/backend/api/v1${path}`, {
    ...options,
    headers,
    cache: "no-store",
  });
  const payload = await response.json().catch(() => null) as { detail?: unknown; message?: unknown } | null;
  if (!response.ok) {
    const detail = payload?.detail ?? payload?.message;
    const message = typeof detail === "string" ? detail : `Request failed (${response.status})`;
    throw new Error(message);
  }

  // Some deployments return a scoped token once when an investigation is created.
  // Keep it for this browser session only; never persist it in localStorage.
  if (payload && typeof payload === "object" && "id" in payload && typeof payload.id === "string") {
    const token = "investigation_token" in payload && typeof payload.investigation_token === "string"
      ? payload.investigation_token
      : "access_token" in payload && typeof payload.access_token === "string"
        ? payload.access_token
        : "token" in payload && typeof payload.token === "string"
          ? payload.token
          : null;
    if (token && typeof window !== "undefined") {
      window.sessionStorage.setItem(`verityx:investigation-token:${payload.id}`, token);
    }
  }
  return payload as T;
}

export async function checkBackendHealth(): Promise<boolean> {
  try {
    const response = await fetch("/api/backend/health", { cache: "no-store" });
    return response.ok;
  } catch {
    return false;
  }
}

export function createInvestigation(payload: { title: string; description: string | null }) {
  return requestJson<InvestigationResponse>("/investigations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function uploadMedia(investigationId: string, file: File) {
  const body = new FormData();
  body.append("file", file);
  return requestJson<MediaResponse>(`/investigations/${encodeURIComponent(investigationId)}/media`, {
    method: "POST",
    body,
  }, investigationId);
}

export function createIntegrityJob(investigationId: string, mediaAssetId: string) {
  return requestJson<AnalysisJobResponse>(`/media/${encodeURIComponent(mediaAssetId)}/analysis-jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ analysis_type: "integrity_check" }),
  }, investigationId);
}

export function getAnalysisJob(investigationId: string, jobId: string) {
  return requestJson<AnalysisJobResponse>(`/analysis-jobs/${encodeURIComponent(jobId)}`, {}, investigationId);
}
