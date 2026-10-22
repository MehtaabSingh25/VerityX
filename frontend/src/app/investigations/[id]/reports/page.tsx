"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  getAnalysisJobEvents,
  getInvestigationReport,
  getInvestigationSimilarity,
  type InvestigationReport,
  type ReportEvent,
  type ReportJob,
  type SimilarityMatch,
  type SimilarityResponse,
} from "@/lib/verityx-api";

function displayDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function pretty(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function matchLabel(match: SimilarityMatch, keys: string[]) {
  for (const key of keys) {
    const value = match[key];
    if (typeof value === "string" || typeof value === "number") return String(value);
  }
  return "—";
}

function matchSideLabel(match: SimilarityMatch, side: "left" | "right") {
  const nested = match[side];
  if (nested && typeof nested === "object" && !Array.isArray(nested)) {
    const record = nested as Record<string, unknown>;
    for (const key of ["filename", "media_asset_id", "frame_index"]) {
      const value = record[key];
      if (typeof value === "string" || typeof value === "number") return String(value);
    }
  }
  return matchLabel(match, side === "left"
    ? ["filename_a", "source_filename", "media_a_filename", "asset_a_filename", "media_asset_id_a", "asset_a_id", "source_media_asset_id"]
    : ["filename_b", "matched_filename", "media_b_filename", "asset_b_filename", "media_asset_id_b", "asset_b_id", "matched_media_asset_id"]);
}

function statusClass(status?: string) {
  const normalized = (status || "unknown").toLowerCase().replace(/[^a-z0-9_-]/g, "-");
  return `report-status report-status-${normalized}`;
}

export default function InvestigationReportPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const investigationId = decodeURIComponent(params.id);
  const [report, setReport] = useState<InvestigationReport | null>(null);
  const [similarity, setSimilarity] = useState<SimilarityResponse | null>(null);
  const [eventOverrides, setEventOverrides] = useState<Record<string, ReportEvent[]>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [similarityError, setSimilarityError] = useState("");
  const [maxDistance, setMaxDistance] = useState("10");
  const [limit, setLimit] = useState("100");

  const loadReport = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true); else setLoading(true);
    setError("");
    try {
      const nextReport = await getInvestigationReport(investigationId, Number(maxDistance), Number(limit));
      setReport(nextReport);
      setSimilarityError("");
      try {
        const nextSimilarity = await getInvestigationSimilarity(investigationId, Number(maxDistance), Number(limit));
        setSimilarity(nextSimilarity);
      } catch (similarityLoadError) {
        setSimilarity(null);
        setSimilarityError(similarityLoadError instanceof Error ? similarityLoadError.message : "Similarity results are unavailable.");
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load the investigation report.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [investigationId, maxDistance, limit]);

  useEffect(() => { void loadReport(); }, [loadReport]);

  const jobs = report?.analysis_jobs ?? [];
  const mediaAssets = report?.media_assets ?? [];
  const integrityFindings = report?.findings?.integrity_mismatches ?? [];
  const similarityMatches = similarity?.matches ?? report?.findings?.similarity_matches ?? [];
  const summary = report?.summary;
  const isRealInvestigation = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(investigationId);

  const reportJson = useMemo(() => report ? JSON.stringify(report, null, 2) : "", [report]);

  function downloadReport() {
    if (!reportJson) return;
    const blob = new Blob([reportJson], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `verityx-report-${investigationId}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function refreshEvents(job: ReportJob) {
    if (!job.id) return;
    try {
      const events = await getAnalysisJobEvents(investigationId, job.id);
      setEventOverrides((current) => ({ ...current, [job.id]: events }));
    } catch (eventError) {
      setError(eventError instanceof Error ? eventError.message : "Could not refresh job events.");
    }
  }

  return (
    <main className="workspace-page report-page">
      <header className="workspace-topbar">
        <button className="workspace-back" onClick={() => router.push(`/investigations/${encodeURIComponent(investigationId)}`)}>← <span>Back to workspace</span></button>
        <div className="workspace-topbar-brand"><span className="workspace-brand-mark">V</span><strong>VerityX</strong><span>MEDIA FORENSICS</span></div>
        <span className="workspace-demo-chip workspace-api-chip"><i /> REPORT VIEW</span>
      </header>

      <div className="workspace-content">
        <div className="workspace-breadcrumb"><button onClick={() => router.push("/")}>Investigations</button><span>/</span><button onClick={() => router.push(`/investigations/${encodeURIComponent(investigationId)}`)}>Workspace</button><span>/</span><strong>Report & findings</strong></div>
        <section className="workspace-heading report-heading">
          <div><div className="workspace-eyebrow">FORENSIC SUMMARY</div><h1>Report & findings</h1><p>Review stored analysis results, lifecycle events, and similarity candidates for this investigation.</p></div>
          <div className="report-heading-actions"><button className="workspace-text-button" onClick={() => void loadReport(true)} disabled={loading || refreshing}>{refreshing ? "Refreshing…" : "Refresh report"}</button><button className="workspace-primary-button" onClick={downloadReport} disabled={!report}>Export JSON</button></div>
        </section>

        {!isRealInvestigation && <div className="workspace-demo-notice"><span>ⓘ</span><div><strong>Sample case ID</strong><p>Reports are available only for a real investigation created by the backend.</p></div></div>}
        {error && <div className="workspace-error" role="alert">{error}</div>}
        {loading && <section className="workspace-panel report-empty"><strong>Loading investigation report…</strong><p>Fetching stored media, analysis results, and evidence history.</p></section>}
        {!loading && error && <section className="workspace-panel report-empty"><strong>Report could not be loaded</strong><p>Check the backend URL, investigation token, and API availability, then retry.</p><button className="workspace-primary-button" onClick={() => void loadReport(true)}>Try again</button></section>}

        {!loading && report && <>
          <section className="workspace-stats report-stats" aria-label="Report summary">
            <article><span>MEDIA ASSETS</span><strong>{summary?.media_asset_count ?? mediaAssets.length}</strong><small>Files recorded in this case</small></article>
            <article><span>ANALYSIS JOBS</span><strong>{summary?.analysis_job_count ?? jobs.length}</strong><small>{Object.entries(summary?.analysis_jobs_by_status ?? {}).map(([key, value]) => `${value} ${key}`).join(" · ") || "No jobs recorded"}</small></article>
            <article><span>INTEGRITY MISMATCHES</span><strong>{summary?.integrity_mismatch_count ?? integrityFindings.length}</strong><small>Findings requiring human review</small></article>
          </section>

          <section className="workspace-panel">
            <div className="workspace-panel-header"><div><h2>{report.investigation?.title || "Investigation"}</h2><p>Report schema {report.report_schema_version || "—"} · Generated {displayDate(report.generated_at)}</p></div><span className="workspace-step">CASE SUMMARY</span></div>
            <div className="report-case-meta"><div><span>INVESTIGATION ID</span><code>{report.investigation?.id || investigationId}</code></div><div><span>STATUS</span><strong>{report.investigation?.status || "—"}</strong></div><div><span>CREATED</span><strong>{displayDate(report.investigation?.created_at)}</strong></div></div>
            {report.investigation?.description && <p className="report-description">{report.investigation.description}</p>}
          </section>

          <section className="workspace-panel">
            <div className="workspace-panel-header"><div><h2>Evidence inventory <span className="workspace-count">{mediaAssets.length}</span></h2><p>Persisted media records and ingestion digests</p></div><span className="workspace-step">EVIDENCE</span></div>
            {mediaAssets.length === 0 ? <div className="workspace-empty"><strong>No media assets recorded</strong><p>Upload evidence in the investigation workspace first.</p></div> : <div className="report-table-wrap"><table className="report-table"><thead><tr><th>FILE</th><th>TYPE</th><th>SIZE</th><th>SHA-256</th><th>UPLOADED</th></tr></thead><tbody>{mediaAssets.map((asset) => <tr key={asset.id}><td><strong>{asset.filename || asset.id}</strong><small>{asset.id}</small></td><td>{asset.mime_type || "—"}</td><td>{typeof asset.size_bytes === "number" ? `${(asset.size_bytes / (1024 * 1024)).toFixed(2)} MiB` : "—"}</td><td><code className="report-hash">{asset.sha256 || "—"}</code></td><td>{displayDate(asset.created_at)}</td></tr>)}</tbody></table></div>}
          </section>

          <section className="workspace-panel">
            <div className="workspace-panel-header"><div><h2>Analysis jobs <span className="workspace-count">{jobs.length}</span></h2><p>Persisted task status, results, errors, and lifecycle events</p></div><span className="workspace-step">PROCESSING HISTORY</span></div>
            {jobs.length === 0 ? <div className="workspace-empty"><strong>No analysis jobs recorded</strong><p>Queue an analysis job from the evidence workspace.</p></div> : <div className="report-job-list">{jobs.map((job) => {
              const events = eventOverrides[job.id] ?? job.events ?? [];
              return <article className="report-job-card" key={job.id}>
                <div className="report-job-heading"><div><strong>{job.analysis_type || "Analysis"}</strong><small>{job.id}</small></div><span className={statusClass(job.status)}>{job.status || "unknown"}</span></div>
                {job.error_message && <div className="report-job-error">{job.error_message}</div>}
                {job.result && <details className="report-details"><summary>View analysis result</summary><pre>{JSON.stringify(job.result, null, 2)}</pre></details>}
                <div className="report-event-heading"><strong>Lifecycle events ({events.length})</strong><button className="workspace-text-button" onClick={() => void refreshEvents(job)}>Refresh events</button></div>
                {events.length === 0 ? <p className="report-muted">No lifecycle events are included in this report.</p> : <ol className="report-timeline">{events.map((event, index) => <li key={`${job.id}-${event.event_type}-${event.created_at}-${index}`}><span className="report-timeline-dot" /><div><strong>{event.event_type || event.status || "event"}</strong><time>{displayDate(event.created_at)}</time>{event.message && <p>{event.message}</p>}</div></li>)}</ol>}
              </article>;
            })}</div>}
          </section>

          <section className="workspace-panel">
            <div className="workspace-panel-header"><div><h2>Similarity candidates <span className="workspace-count">{similarityMatches.length}</span></h2><p>Candidate matches based on perceptual fingerprints, not proof of origin</p></div><span className="workspace-step">CROSS-MEDIA</span></div>
            <div className="report-filter-row"><label>Max Hamming distance <select value={maxDistance} onChange={(event) => setMaxDistance(event.target.value)}><option value="4">4 bits</option><option value="8">8 bits</option><option value="10">10 bits</option><option value="16">16 bits</option><option value="24">24 bits</option><option value="32">32 bits</option><option value="64">64 bits</option></select></label><label>Result limit <select value={limit} onChange={(event) => setLimit(event.target.value)}><option value="25">25</option><option value="50">50</option><option value="100">100</option><option value="250">250</option><option value="500">500</option></select></label><button className="workspace-primary-button" onClick={() => void loadReport(true)} disabled={refreshing}>Apply filters</button></div>
            {similarityError && <div className="report-inline-warning" role="status">Live similarity endpoint unavailable: {similarityError}. Showing report snapshot results instead.</div>}
            {similarityMatches.length === 0 ? <div className="workspace-empty"><strong>No similarity candidates found</strong><p>Run completed perceptual-hash or video-frame fingerprint jobs first, then refresh this report.</p></div> : <div className="report-table-wrap"><table className="report-table"><thead><tr><th>ASSET A</th><th>ASSET B</th><th>HAMMING DISTANCE</th><th>SCORE / DETAILS</th></tr></thead><tbody>{similarityMatches.map((match, index) => <tr key={`${matchLabel(match, ["media_asset_id_a", "asset_a_id", "source_media_asset_id", "left_media_asset_id"])}-${matchLabel(match, ["media_asset_id_b", "asset_b_id", "matched_media_asset_id", "right_media_asset_id"])}-${index}`}><td>{matchSideLabel(match, "left")}</td><td>{matchSideLabel(match, "right")}</td><td>{matchLabel(match, ["hamming_distance", "distance", "min_hamming_distance"])}</td><td>{matchLabel(match, ["similarity_score", "score", "similarity"])}</td></tr>)}</tbody></table></div>}
            {(similarity?.limitations ?? report.methodology?.limitations ?? []).length > 0 && <ul className="report-limitations">{(similarity?.limitations ?? report.methodology?.limitations ?? []).map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul>}
          </section>

          <section className="workspace-panel">
            <div className="workspace-panel-header"><div><h2>Integrity findings</h2><p>Automated flags that require investigator review</p></div><span className="workspace-step">FINDINGS</span></div>
            {integrityFindings.length === 0 ? <div className="report-clean-state"><span>✓</span><div><strong>No recorded SHA-256 mismatches</strong><p>This means no mismatch was recorded by the available integrity checks. It does not establish authenticity or prove the media was never altered before ingestion.</p></div></div> : <div className="report-findings-list">{integrityFindings.map((finding, index) => <article key={`${pretty(finding.analysis_job_id)}-${index}`}><strong>{pretty(finding.finding || "Integrity finding")}</strong><span>{pretty(finding.filename || finding.media_asset_id)}</span><p>{pretty(finding.message)}</p><small>Severity: {pretty(finding.severity || "review_required")}</small></article>)}</div>}
          </section>

          <section className="workspace-panel">
            <div className="workspace-panel-header"><div><h2>Methodology & limitations</h2><p>Interpretation boundaries for this report snapshot</p></div><span className="workspace-step">TRANSPARENCY</span></div>
            <div className="report-methodology"><p><strong>SHA-256 integrity:</strong> compares the file digest observed during ingestion with the digest observed during analysis.</p><p><strong>Perceptual similarity:</strong> compares image and sampled video-frame fingerprints using Hamming distance. Lower distance indicates closer fingerprints, not a probability of shared origin.</p>{(report.methodology?.limitations ?? []).map((item, index) => <p key={`${item}-${index}`}>{item}</p>)}</div>
          </section>
        </>}
        <footer className="workspace-footer"><span>VERITYX · EVIDENCE FIRST</span><span>Findings are review leads, not definitive authenticity determinations.</span></footer>
      </div>
    </main>
  );
}
