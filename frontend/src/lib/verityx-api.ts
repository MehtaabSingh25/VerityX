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

export type InvestigationListItem = {
  id: string;
  title: string;
  description: string | null;
  status: string;
  created_at: string;
  media_asset_count: number;
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

  const url = `/api/backend/api/v1${path}`;
  let response = await fetch(url, {
    ...options,
    headers,
    cache: "no-store",
  });
  let payload = await response.json().catch(() => null) as { detail?: unknown; message?: unknown } | null;

  // Older investigations may have a token that was lost when the browser session ended.
  // Recover only on the explicit backend token-rejection response, rotate through the
  // trusted same-origin proxy, store the new scoped token for this session, and retry once.
  if (
    response.status === 403 &&
    investigationId &&
    payload?.detail === "Missing or invalid investigation token"
  ) {
    const rotation = await fetch(
      `/api/backend/api/v1/investigations/${encodeURIComponent(investigationId)}/access-token/rotate`,
      {
        method: "POST",
        headers: { "X-Investigation-ID": investigationId },
        cache: "no-store",
      },
    );
    const rotated = await rotation.json().catch(() => null) as { access_token?: unknown } | null;
    if (rotation.ok && typeof rotated?.access_token === "string" && typeof window !== "undefined") {
      window.sessionStorage.setItem(`verityx:investigation-token:${investigationId}`, rotated.access_token);
      headers.set("X-Investigation-Token", rotated.access_token);
      response = await fetch(url, { ...options, headers, cache: "no-store" });
      payload = await response.json().catch(() => null) as { detail?: unknown; message?: unknown } | null;
    }
  }

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

export function listInvestigations() {
  return requestJson<InvestigationListItem[]>("/investigations");
}

export function createInvestigation(payload: { title: string; description: string | null }) {
  return requestJson<InvestigationResponse>("/investigations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function listInvestigationMedia(investigationId: string) {
  return requestJson<MediaResponse[]>(
    `/investigations/${encodeURIComponent(investigationId)}/media`,
    {},
    investigationId,
  );
}

export function deleteInvestigationMedia(investigationId: string, mediaAssetId: string) {
  return requestJson<void>(
    `/investigations/${encodeURIComponent(investigationId)}/media/${encodeURIComponent(mediaAssetId)}`,
    { method: "DELETE" },
    investigationId,
  );
}

export async function uploadMedia(investigationId: string, file: File) {
  const body = new FormData();
  body.append("file", file);

  // Vercel Functions impose a request-body limit. When configured, send large
  // evidence uploads directly to the Render API; all other API traffic remains
  // behind the same-origin server-side proxy.
  const directApiUrl = process.env.NEXT_PUBLIC_VERITYX_API_URL?.replace(/\/+$/, "");
  if (!directApiUrl) {
    return requestJson<MediaResponse>(`/investigations/${encodeURIComponent(investigationId)}/media`, {
      method: "POST",
      body,
    }, investigationId);
  }

  const token = investigationToken(investigationId);
  if (!token) throw new Error("Investigation access token is missing. Reopen the investigation and try again.");
  const response = await fetch(
    `${directApiUrl}/api/v1/investigations/${encodeURIComponent(investigationId)}/media`,
    { method: "POST", headers: { "X-Investigation-Token": token }, body, cache: "no-store" },
  );
  const payload = await response.json().catch(() => null) as MediaResponse | { detail?: unknown } | null;
  if (!response.ok) {
    const detail = payload && "detail" in payload ? payload.detail : null;
    throw new Error(typeof detail === "string" ? detail : `Upload failed (${response.status})`);
  }
  return payload as MediaResponse;
}

export function createIntegrityJob(investigationId: string, mediaAssetId: string) {
  return requestJson<AnalysisJobResponse>(`/media/${encodeURIComponent(mediaAssetId)}/analysis-jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ analysis_type: "integrity_check" }),
  }, investigationId);
}

export function createAiDetectionJob(investigationId: string, mediaAssetId: string) {
  return requestJson<AnalysisJobResponse>(`/media/${encodeURIComponent(mediaAssetId)}/analysis-jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ analysis_type: "ai_image_detection" }),
  }, investigationId);
}

export type PublicWebImageSearchResponse = {
  provider?: string;
  fallback_notice?: string | null;
  search_type?: "visual_similarity_search" | "keyword_image_search";
  query?: string;
  query_source?: "user_keywords" | "auto_caption";
  ranking_method?: "clip_cosine" | "dhash" | "none";
  result_count?: number;
  results?: {
    title?: string | null;
    page_url: string;
    image_url?: string | null;
    thumbnail_url?: string | null;
    creator?: string | null;
    license?: string | null;
    source?: string | null;
    visual_similarity?: number | null;
    visual_distance_bits?: number | null;
    near_duplicate?: boolean;
  }[];
  limitations?: string[];
};

export function searchPublicWebImage(investigationId: string, mediaAssetId: string, query?: string) {
  const keywords = query?.trim();
  return requestJson<PublicWebImageSearchResponse>(
    `/media/${encodeURIComponent(mediaAssetId)}/web-image-search`,
    {
      method: "POST",
      ...(keywords
        ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: keywords }) }
        : {}),
    },
    investigationId,
  );
}

export function getAnalysisJob(investigationId: string, jobId: string) {
  return requestJson<AnalysisJobResponse>(`/analysis-jobs/${encodeURIComponent(jobId)}`, {}, investigationId);
}


export type ReportEvent = {
  event_type?: string;
  status?: string;
  message?: string | null;
  created_at?: string | null;
};

export type ReportJob = {
  id: string;
  media_asset_id?: string;
  analysis_type?: string;
  status?: string;
  result?: Record<string, unknown> | null;
  error_message?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  events?: ReportEvent[];
};

export type ReportMediaAsset = {
  id: string;
  filename?: string;
  mime_type?: string;
  size_bytes?: number;
  sha256?: string;
  created_at?: string | null;
  analysis_job_count?: number;
};

export type SimilarityMatch = Record<string, unknown>;

export type InvestigationReport = {
  report_schema_version?: string;
  generated_at?: string;
  investigation?: {
    id?: string;
    title?: string;
    description?: string | null;
    status?: string;
    created_at?: string | null;
    updated_at?: string | null;
  };
  summary?: {
    media_asset_count?: number;
    analysis_job_count?: number;
    analysis_jobs_by_status?: Record<string, number>;
    analysis_jobs_by_type?: Record<string, number>;
    integrity_mismatch_count?: number;
    similarity_match_count?: number;
  };
  findings?: {
    integrity_mismatches?: Record<string, unknown>[];
    similarity_matches?: SimilarityMatch[];
  };
  media_assets?: ReportMediaAsset[];
  analysis_jobs?: ReportJob[];
  methodology?: {
    limitations?: string[];
    [key: string]: unknown;
  };
};

export type SimilarityResponse = {
  result_count?: number;
  matches?: SimilarityMatch[];
  limitations?: string[];
  algorithm?: string;
};

export function getInvestigationReport(
  investigationId: string,
  maxDistance = 10,
  similarityLimit = 100,
) {
  const query = new URLSearchParams({ max_distance: String(maxDistance), similarity_limit: String(similarityLimit) });
  return requestJson<InvestigationReport>(
    `/investigations/${encodeURIComponent(investigationId)}/report?${query.toString()}`,
    {},
    investigationId,
  );
}

export function getInvestigationSimilarity(
  investigationId: string,
  maxDistance = 10,
  limit = 100,
) {
  const query = new URLSearchParams({ max_distance: String(maxDistance), limit: String(limit) });
  return requestJson<SimilarityResponse>(
    `/investigations/${encodeURIComponent(investigationId)}/similarity?${query.toString()}`,
    {},
    investigationId,
  );
}

export function getAnalysisJobEvents(investigationId: string, jobId: string) {
  return requestJson<ReportEvent[]>(
    `/analysis-jobs/${encodeURIComponent(jobId)}/events`,
    {},
    investigationId,
  );
}


export type OperationsSummary = {
  generated_at?: string;
  total_jobs?: number;
  jobs_by_status?: Record<string, number>;
  jobs_by_analysis_type?: Record<string, number>;
  lifecycle_events_by_type?: Record<string, number>;
};

export function getOperationsSummary() {
  return requestJson<OperationsSummary>("/operations/summary");
}
