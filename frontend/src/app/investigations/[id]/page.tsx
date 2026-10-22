"use client";

import { useEffect, useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  checkBackendHealth,
  createAiDetectionJob,
  createIntegrityJob,
  getAnalysisJob,
  searchPublicWebImage,
  uploadMedia,
  listInvestigationMedia,
  deleteInvestigationMedia,
} from "@/lib/verityx-api";
import type { MediaResponse, PublicWebImageSearchResponse } from "@/lib/verityx-api";

type EvidenceState =
  | "Ready"
  | "Uploading"
  | "Uploaded"
  | "Queued"
  | "Completed"
  | "Failed";
type EvidenceItem = {
  id: string;
  file: File;
  state: EvidenceState;
  assetId?: string;
  jobId?: string;
  jobStatus?: string;
  error?: string;
  aiJobId?: string;
  aiJobStatus?: string;
  aiResult?: Record<string, unknown> | null;
  webSearchResult?: PublicWebImageSearchResponse;
  webSearchLoading?: boolean;
};
const MAX_FILE_SIZE = 50 * 1024 * 1024;
const ACCEPTED_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp", ".mp4", ".webm"];

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileKind(file: File) {
  if (file.type.startsWith("image/")) return "IMAGE";
  if (file.type.startsWith("video/")) return "VIDEO";
  return "MEDIA";
}

export default function InvestigationWorkspacePage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const investigationId = decodeURIComponent(params.id);
  const inputRef = useRef<HTMLInputElement>(null);
  const [items, setItems] = useState<EvidenceItem[]>([]);
  const [storedMedia, setStoredMedia] = useState<MediaResponse[]>([]);
  const [inventoryLoading, setInventoryLoading] = useState(false);
  const [deletingAssetId, setDeletingAssetId] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [apiOnline, setApiOnline] = useState(false);
  const isRealInvestigation =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      investigationId,
    );

  async function refreshInventory() {
    if (!isRealInvestigation) return;
    setInventoryLoading(true);
    try {
      const media = await listInvestigationMedia(investigationId);
      setStoredMedia(media);
    } catch (inventoryError) {
      setError(
        inventoryError instanceof Error
          ? inventoryError.message
          : "Could not load stored evidence inventory.",
      );
    } finally {
      setInventoryLoading(false);
    }
  }

  async function deleteStoredEvidence(asset: MediaResponse) {
    const label = asset.original_filename || asset.id;
    if (
      !window.confirm(
        `Permanently delete "${label}" and its stored analysis data? This cannot be undone.`,
      )
    ) {
      return;
    }
    setDeletingAssetId(asset.id);
    setError("");
    setNotice("");
    try {
      await deleteInvestigationMedia(investigationId, asset.id);
      setStoredMedia((current) => current.filter((item) => item.id !== asset.id));
      setItems((current) => current.filter((item) => item.assetId !== asset.id));
      setNotice(`Deleted evidence: ${label}`);
    } catch (deleteError) {
      setError(
        deleteError instanceof Error
          ? deleteError.message
          : "Could not delete evidence.",
      );
    } finally {
      setDeletingAssetId(null);
    }
  }

  useEffect(() => {
    if (!isRealInvestigation) return;
    let active = true;
    checkBackendHealth().then(async (healthy) => {
      if (!active) return;
      setApiOnline(healthy);
      if (healthy) {
        try {
          const media = await listInvestigationMedia(investigationId);
          if (active) setStoredMedia(media);
        } catch (inventoryError) {
          if (active) {
            setError(
              inventoryError instanceof Error
                ? inventoryError.message
                : "Could not load stored evidence inventory.",
            );
          }
        }
      }
    });
    return () => {
      active = false;
    };
  }, [investigationId, isRealInvestigation]);

  function addFiles(files: FileList | File[]) {
    if (!isRealInvestigation) {
      setError(
        "This is a sample investigation. Create a real investigation from the dashboard before uploading evidence.",
      );
      return;
    }
    setError("");
    setNotice("");
    const accepted: EvidenceItem[] = [];
    const rejected: string[] = [];
    for (const file of Array.from(files)) {
      const extension = file.name.includes(".")
        ? `.${file.name.split(".").pop()!.toLowerCase()}`
        : "";
      if (!ACCEPTED_EXTENSIONS.includes(extension)) {
        rejected.push(`${file.name}: unsupported file extension`);
      } else if (file.size === 0) {
        rejected.push(`${file.name}: file is empty`);
      } else if (file.size > MAX_FILE_SIZE) {
        rejected.push(`${file.name}: exceeds the 50 MiB limit`);
      } else if (
        items.some((item) => item.file.name === file.name) ||
        accepted.some((item) => item.file.name === file.name)
      ) {
        rejected.push(`${file.name}: already in this local queue`);
      } else {
        accepted.push({
          id: `${file.name}-${file.size}-${file.lastModified}`,
          file,
          state: "Ready",
        });
      }
    }
    if (accepted.length) setItems((current) => [...current, ...accepted]);
    if (rejected.length) setError(rejected.join(" · "));
    if (accepted.length)
      setNotice(
        `${accepted.length} file${accepted.length === 1 ? "" : "s"} selected. Choose Upload selected to send them to the backend.`,
      );
  }

  function handleInputChange(event: ChangeEvent<HTMLInputElement>) {
    if (event.target.files) addFiles(event.target.files);
    event.target.value = "";
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    addFiles(event.dataTransfer.files);
  }

  async function uploadSelected() {
    const pending = items.filter(
      (item) => !item.assetId && item.state !== "Uploading",
    );
    if (!isRealInvestigation || pending.length === 0) return;
    setError("");
    setNotice("");
    for (const item of pending) {
      setItems((current) =>
        current.map((candidate) =>
          candidate.id === item.id
            ? { ...candidate, state: "Uploading", error: undefined }
            : candidate,
        ),
      );
      try {
        const uploaded = await uploadMedia(investigationId, item.file);
        setItems((current) =>
          current.map((candidate) =>
            candidate.id === item.id
              ? {
                  ...candidate,
                  state: "Uploaded",
                  assetId: uploaded.id,
                  error: undefined,
                }
              : candidate,
          ),
        );
      } catch (uploadError) {
        const message =
          uploadError instanceof Error ? uploadError.message : "Upload failed";
        setItems((current) =>
          current.map((candidate) =>
            candidate.id === item.id
              ? { ...candidate, state: "Failed", error: message }
              : candidate,
          ),
        );
        setError(`${item.file.name}: ${message}`);
      }
    }
    await refreshInventory();
    setNotice(
      "Upload attempts finished. Review each file's state before starting analysis.",
    );
  }

  async function queueIntegrityCheck(localId: string) {
    const item = items.find((candidate) => candidate.id === localId);
    if (!item?.assetId) {
      setError(
        "Upload this file successfully before starting its integrity check.",
      );
      return;
    }
    setError("");
    try {
      const job = await createIntegrityJob(investigationId, item.assetId);
      setItems((current) =>
        current.map((candidate) =>
          candidate.id === localId
            ? {
                ...candidate,
                state:
                  job.status === "completed"
                    ? "Completed"
                    : job.status === "failed"
                      ? "Failed"
                      : "Queued",
                jobId: job.id,
                jobStatus: job.status,
                error: job.error_message || undefined,
              }
            : candidate,
        ),
      );
      setNotice(`Integrity check submitted. Job ID: ${job.id}`);
    } catch (jobError) {
      setError(
        jobError instanceof Error
          ? jobError.message
          : "Could not submit analysis job.",
      );
    }
  }

  async function refreshJob(localId: string) {
    const item = items.find((candidate) => candidate.id === localId);
    if (!item?.jobId) return;
    try {
      const job = await getAnalysisJob(investigationId, item.jobId);
      setItems((current) =>
        current.map((candidate) =>
          candidate.id === localId
            ? {
                ...candidate,
                state:
                  job.status === "completed"
                    ? "Completed"
                    : job.status === "failed"
                      ? "Failed"
                      : "Queued",
                jobStatus: job.status,
                error: job.error_message || undefined,
              }
            : candidate,
        ),
      );
      setNotice(
        `Job status: ${job.status}${job.result && typeof job.result.matches === "boolean" ? ` · SHA-256 ${job.result.matches ? "matches" : "does not match"}` : ""}`,
      );
    } catch (jobError) {
      setError(
        jobError instanceof Error
          ? jobError.message
          : "Could not refresh analysis status.",
      );
    }
  }

  async function runAiDetection(localId: string) {
    const item = items.find((candidate) => candidate.id === localId);
    if (!item?.assetId || fileKind(item.file) !== "IMAGE") {
      setError(
        "Upload an image successfully before running AI-image detection.",
      );
      return;
    }
    setError("");
    try {
      const job = await createAiDetectionJob(investigationId, item.assetId);
      setItems((current) =>
        current.map((candidate) =>
          candidate.id === localId
            ? {
                ...candidate,
                aiJobId: job.id,
                aiJobStatus: job.status,
                aiResult: job.result ?? null,
                error: job.error_message || candidate.error,
              }
            : candidate,
        ),
      );
      setNotice(
        `AI-image detection ${job.status}. Use Refresh AI result to retrieve the result when the worker finishes.`,
      );
    } catch (jobError) {
      setError(
        jobError instanceof Error
          ? jobError.message
          : "Could not submit AI-image detection.",
      );
    }
  }

  async function refreshAiDetection(localId: string) {
    const item = items.find((candidate) => candidate.id === localId);
    if (!item?.aiJobId) return;
    setError("");
    try {
      const job = await getAnalysisJob(investigationId, item.aiJobId);
      setItems((current) =>
        current.map((candidate) =>
          candidate.id === localId
            ? {
                ...candidate,
                aiJobStatus: job.status,
                aiResult: job.result ?? null,
                error: job.error_message || undefined,
              }
            : candidate,
        ),
      );
      setNotice(`AI-image detection job: ${job.status}`);
    } catch (jobError) {
      setError(
        jobError instanceof Error
          ? jobError.message
          : "Could not refresh AI-image detection.",
      );
    }
  }

  async function runPublicWebSearch(localId: string) {
    const item = items.find((candidate) => candidate.id === localId);
    if (!item?.assetId || fileKind(item.file) !== "IMAGE") {
      setError("Upload an image successfully before searching the public web.");
      return;
    }
    setError("");
    setItems((current) =>
      current.map((candidate) =>
        candidate.id === localId
          ? { ...candidate, webSearchLoading: true, webSearchResult: undefined }
          : candidate,
      ),
    );
    try {
      const result = await searchPublicWebImage(investigationId, item.assetId);
      setItems((current) =>
        current.map((candidate) =>
          candidate.id === localId
            ? { ...candidate, webSearchLoading: false, webSearchResult: result }
            : candidate,
        ),
      );
      setNotice(
        `Public-web search finished: ${result.result_count ?? 0} matching page(s) returned.`,
      );
    } catch (searchError) {
      const message =
        searchError instanceof Error
          ? searchError.message
          : "Public-web image search failed.";
      setItems((current) =>
        current.map((candidate) =>
          candidate.id === localId
            ? { ...candidate, webSearchLoading: false, error: message }
            : candidate,
        ),
      );
      setError(message);
    }
  }


  return (
    <main className="workspace-page">
      <header className="workspace-topbar">
        <button className="workspace-back" onClick={() => router.push("/")}>
          ← <span>Back to dashboard</span>
        </button>
        <div className="workspace-topbar-brand">
          <span className="workspace-brand-mark">V</span>
          <strong>VerityX</strong>
          <span>MEDIA FORENSICS</span>
        </div>
        <span
          className={`workspace-demo-chip ${apiOnline ? "workspace-api-chip" : ""}`}
        >
          <i />{" "}
          {isRealInvestigation
            ? apiOnline
              ? "API CONNECTED"
              : "API CHECKING"
            : "SAMPLE CASE"}
        </span>
      </header>

      <div className="workspace-content">
        <div className="workspace-breadcrumb">
          <button onClick={() => router.push("/")}>Investigations</button>
          <span>/</span>
          <strong>{investigationId}</strong>
        </div>
        <section className="workspace-heading">
          <div>
            <div className="workspace-eyebrow">INVESTIGATION WORKSPACE</div>
            <h1>Evidence intake</h1>
            <p>
              Review candidate media, stage files for analysis, and preserve an
              evidence-first workflow.
            </p>
          </div>
          <div className="workspace-heading-actions">
            <span className="workspace-case-id">
              CASE ID <strong>{investigationId}</strong>
            </span>
            <button
              className="workspace-primary-button"
              onClick={() =>
                router.push(
                  `/investigations/${encodeURIComponent(investigationId)}/reports`,
                )
              }
            >
              View report & findings
            </button>
          </div>
        </section>

        {!isRealInvestigation ? (
          <div className="workspace-demo-notice">
            <span>ⓘ</span>
            <div>
              <strong>Sample investigation</strong>
              <p>
                This dashboard row is illustrative and is not a database record.
                Create a new investigation from the dashboard before uploading
                evidence.
              </p>
            </div>
          </div>
        ) : (
          <div className="workspace-demo-notice workspace-live-notice">
            <span>✓</span>
            <div>
              <strong>Connected workspace</strong>
              <p>
                Evidence is loaded from persistent backend storage. Deleting an
                item removes its record and associated analysis data.
              </p>
            </div>
          </div>
        )}
        {notice && (
          <div className="workspace-feedback" role="status">
            {notice}
            <button onClick={() => setNotice("")} aria-label="Dismiss">
              ×
            </button>
          </div>
        )}
        {error && (
          <div className="workspace-error" role="alert">
            {error}
          </div>
        )}

        <section
          className="workspace-stats"
          aria-label="Evidence queue summary"
        >
          <article>
            <span>STORED EVIDENCE</span>
            <strong>{String(storedMedia.length).padStart(2, "0")}</strong>
            <small>Persisted in this investigation</small>
          </article>
          <article>
            <span>LOCAL SELECTION</span>
            <strong>{String(items.filter((item) => !item.assetId).length).padStart(2, "0")}</strong>
            <small>Not uploaded yet</small>
          </article>
          <article>
            <span>ANALYSIS STATUS</span>
            <strong>
              {items.filter((item) => item.state === "Queued").length}
            </strong>
            <small>Submitted or running jobs</small>
          </article>
        </section>

        <section className="workspace-panel evidence-list-panel">
          <div className="workspace-panel-header">
            <div>
              <h2>
                Stored evidence{" "}
                <span className="workspace-count">{storedMedia.length}</span>
              </h2>
              <p>Persisted records loaded from the backend</p>
            </div>
            <div className="workspace-header-actions">
              <button
                className="workspace-text-button"
                disabled={!isRealInvestigation || inventoryLoading}
                onClick={refreshInventory}
              >
                {inventoryLoading ? "Refreshing…" : "Refresh inventory"}
              </button>
            </div>
          </div>
          {inventoryLoading && storedMedia.length === 0 ? (
            <div className="workspace-empty">
              <strong>Loading evidence inventory…</strong>
            </div>
          ) : storedMedia.length === 0 ? (
            <div className="workspace-empty">
              <div className="workspace-empty-icon">▤</div>
              <strong>No stored evidence</strong>
              <p>Uploaded files will appear here and remain available after a page refresh.</p>
            </div>
          ) : (
            <div className="evidence-table-wrap">
              <table className="evidence-table">
                <thead>
                  <tr>
                    <th>FILE</th>
                    <th>TYPE</th>
                    <th>SIZE</th>
                    <th>SHA-256</th>
                    <th>UPLOADED</th>
                    <th>ACTIONS</th>
                  </tr>
                </thead>
                <tbody>
                  {storedMedia.map((asset) => (
                    <tr key={asset.id}>
                      <td>
                        <div className="workspace-file-cell">
                          <span
                            className={`workspace-file-icon ${asset.mime_type.startsWith("video/") ? "video" : "image"}`}
                          >
                            {asset.mime_type.startsWith("video/") ? "▶" : "▧"}
                          </span>
                          <div>
                            <strong>{asset.original_filename}</strong>
                            <small>{asset.id}</small>
                          </div>
                        </div>
                      </td>
                      <td>{asset.mime_type.startsWith("video/") ? "VIDEO" : "IMAGE"}</td>
                      <td>{formatBytes(asset.size_bytes)}</td>
                      <td><code title={asset.sha256}>{asset.sha256.slice(0, 12)}…</code></td>
                      <td>{asset.created_at ? new Date(asset.created_at).toLocaleString() : "—"}</td>
                      <td>
                        <div className="workspace-row-actions">
                          <button
                            disabled={deletingAssetId === asset.id}
                            onClick={() => deleteStoredEvidence(asset)}
                          >
                            {deletingAssetId === asset.id ? "Deleting…" : "Delete evidence"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="workspace-panel-footer">
            <span><i /> {apiOnline ? "Backend reachable" : "Backend not confirmed"}</span>
            <span>Permanent deletion requires confirmation</span>
          </div>
        </section>

        <section className="workspace-panel">
          <div className="workspace-panel-header">
            <div>
              <h2>Add evidence</h2>
              <p>Supported: JPG, PNG, WebP, MP4, and WebM</p>
            </div>
            <span className="workspace-step">STEP 01 / 03</span>
          </div>
          <div
            className={`evidence-dropzone ${dragging ? "is-dragging" : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
          >
            <div className="dropzone-icon">
              <svg
                width="26"
                height="26"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 16V4m-5 5 5-5 5 5M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
              </svg>
            </div>
            <h3>Drop evidence files here</h3>
            <p>or browse your computer to select media files</p>
            <button
              className="workspace-primary-button"
              disabled={!isRealInvestigation}
              onClick={() => inputRef.current?.click()}
            >
              Choose files
            </button>
            <input
              ref={inputRef}
              className="workspace-file-input"
              type="file"
              multiple
              accept=".jpg,.jpeg,.png,.webp,.mp4,.webm,image/jpeg,image/png,image/webp,video/mp4,video/webm"
              onChange={handleInputChange}
            />
            <span className="dropzone-footnote">
              Maximum 50 MiB per file · Selected files upload only after you
              click Upload selected
            </span>
          </div>
        </section>

        <section className="workspace-panel evidence-list-panel">
          <div className="workspace-panel-header">
            <div>
              <h2>
                Evidence queue{" "}
                <span className="workspace-count">{items.length}</span>
              </h2>
              <p>Selected files, upload state, and analysis jobs</p>
            </div>
            <div className="workspace-header-actions">
              <button
                className="workspace-primary-button"
                disabled={
                  !isRealInvestigation ||
                  !apiOnline ||
                  !items.some(
                    (item) => !item.assetId && item.state !== "Uploading",
                  )
                }
                onClick={uploadSelected}
              >
                Upload selected
              </button>
              <button
                className="workspace-text-button"
                disabled={!items.length}
                onClick={() => {
                  setItems([]);
                  setError("");
                  setNotice(
                    "Local selection cleared. Uploaded backend records are not deleted.",
                  );
                }}
              >
                Clear selection
              </button>
            </div>
          </div>
          {items.length === 0 ? (
            <div className="workspace-empty">
              <div className="workspace-empty-icon">▤</div>
              <strong>No evidence selected yet</strong>
              <p>
                Add an image or video, upload it, then queue a SHA-256 integrity
                check.
              </p>
            </div>
          ) : (
            <div className="evidence-table-wrap">
              <table className="evidence-table">
                <thead>
                  <tr>
                    <th>FILE</th>
                    <th>TYPE</th>
                    <th>SIZE</th>
                    <th>STATE</th>
                    <th>ACTIONS</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <div className="workspace-file-cell">
                          <span
                            className={`workspace-file-icon ${fileKind(item.file).toLowerCase()}`}
                          >
                            {fileKind(item.file) === "VIDEO" ? "▶" : "▧"}
                          </span>
                          <div>
                            <strong>{item.file.name}</strong>
                            <small>
                              Modified{" "}
                              {new Date(
                                item.file.lastModified,
                              ).toLocaleDateString()}
                            </small>
                          </div>
                        </div>
                      </td>
                      <td>{fileKind(item.file)}</td>
                      <td>{formatBytes(item.file.size)}</td>
                      <td>
                        <span
                          className={`workspace-state state-${item.state.toLowerCase()}`}
                        >
                          {item.jobStatus
                            ? `${item.state} · ${item.jobStatus}`
                            : item.state}
                        </span>
                        {item.error && (
                          <small className="workspace-row-error">
                            {item.error}
                          </small>
                        )}
                      </td>
                      <td>
                        <div className="workspace-row-actions">
                          {item.jobId ? (
                            <button onClick={() => refreshJob(item.id)}>
                              Refresh integrity
                            </button>
                          ) : (
                            <button
                              disabled={!item.assetId}
                              onClick={() => queueIntegrityCheck(item.id)}
                            >
                              Integrity check
                            </button>
                          )}
                          {fileKind(item.file) === "IMAGE" && item.assetId && (
                            <>
                              <button
                                disabled={!apiOnline}
                                onClick={() => runAiDetection(item.id)}
                              >
                                {item.aiJobId ? "Run AI again" : "Detect AI"}
                              </button>
                              {item.aiJobId && (
                                <button
                                  onClick={() => refreshAiDetection(item.id)}
                                >
                                  Refresh AI result
                                </button>
                              )}
                              <button
                                disabled={!apiOnline || item.webSearchLoading}
                                onClick={() => runPublicWebSearch(item.id)}
                              >
                                {item.webSearchLoading
                                  ? "Searching…"
                                  : "Search web"}
                              </button>
                            </>
                          )}
                          {!item.assetId && (
                            <button
                              aria-label={`Remove ${item.file.name}`}
                              onClick={() =>
                                setItems((current) =>
                                  current.filter(
                                    (candidate) => candidate.id !== item.id,
                                  ),
                                )
                              }
                            >
                              Remove
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {items.some((item) => item.aiJobId || item.webSearchResult) && (
            <section
              className="forensic-results"
              aria-label="Forensic analysis results"
            >
              <div className="forensic-results-heading">
                <h3>Forensic results</h3>
                <p>
                  Automated signals are investigative leads, not proof of origin
                  or authenticity.
                </p>
              </div>
              {items
                .filter((item) => item.aiJobId || item.webSearchResult)
                .map((item) => {
                  const aiResult = item.aiResult;
                  const interpretation =
                    aiResult && typeof aiResult.interpretation === "string"
                      ? aiResult.interpretation.replaceAll("_", " ")
                      : "Result not available yet";
                  const aiScore =
                    aiResult && typeof aiResult.ai_score === "number"
                      ? `${Math.round(aiResult.ai_score * 100)}%`
                      : "Not available";
                  return (
                    <article
                      className="forensic-result-card"
                      key={`${item.id}-forensic`}
                    >
                      <div className="forensic-result-title">
                        <strong>{item.file.name}</strong>
                        <span>
                          {item.aiJobStatus
                            ? `AI detection · ${item.aiJobStatus}`
                            : "Public-web search"}
                        </span>
                      </div>
                      {item.aiJobId && (
                        <div className="forensic-result-section">
                          <h4>AI-image detection</h4>
                          <p>
                            <strong>Assessment:</strong> {interpretation}
                          </p>
                          <p>
                            <strong>AI score:</strong> {aiScore}
                          </p>
                          {aiResult &&
                            aiResult.score_is_calibrated_probability ===
                              false && (
                              <p className="forensic-disclaimer">
                                Model score is not a calibrated probability.
                                Review the model&apos;s limitations before
                                drawing conclusions.
                              </p>
                            )}
                        </div>
                      )}
                      {item.webSearchResult && (
                        <div className="forensic-result-section">
                          <h4>
                            Public-web image search ·{" "}
                            {item.webSearchResult.result_count ?? 0} matching
                            pages
                          </h4>
                          {(
                            item.webSearchResult.pages_with_matching_images ??
                            []
                          ).length > 0 ? (
                            <ul>
                              {(
                                item.webSearchResult
                                  .pages_with_matching_images ?? []
                              ).map((match, index) => (
                                <li key={`${match.url}-${index}`}>
                                  <a
                                    href={match.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                  >
                                    {match.page_title || match.url}
                                  </a>
                                  <span>{match.url}</span>
                                </li>
                              ))}
                            </ul>
                          ) : (
                            <p>
                              No matching pages were returned by the provider.
                              This does not prove the image has never appeared
                              online.
                            </p>
                          )}
                          {(
                            item.webSearchResult.visually_similar_image_urls ??
                            []
                          ).length > 0 && (
                            <details>
                              <summary>
                                Visually similar image URLs (
                                {
                                  item.webSearchResult
                                    .visually_similar_image_urls!.length
                                }
                                )
                              </summary>
                              <ul>
                                {item.webSearchResult.visually_similar_image_urls!.map(
                                  (url, index) => (
                                    <li key={`${url}-${index}`}>
                                      <a
                                        href={url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                      >
                                        {url}
                                      </a>
                                    </li>
                                  ),
                                )}
                              </ul>
                            </details>
                          )}
                          {(item.webSearchResult.web_entities ?? []).length >
                            0 && (
                            <p>
                              <strong>Detected web entities:</strong>{" "}
                              {item.webSearchResult
                                .web_entities!.map(
                                  (entity) => entity.description,
                                )
                                .join(", ")}
                            </p>
                          )}
                          {(item.webSearchResult.limitations ?? []).length >
                            0 && (
                            <p className="forensic-disclaimer">
                              {item.webSearchResult.limitations!.join(" ")}
                            </p>
                          )}
                        </div>
                      )}
                    </article>
                  );
                })}
            </section>
          )}
          <div className="workspace-panel-footer">
            <span>
              <i /> {apiOnline ? "Backend reachable" : "Backend not confirmed"}
            </span>
            <span>
              SHA-256 · AI-image detection · provider-indexed web search
            </span>
          </div>
        </section>
        <footer className="workspace-footer">
          <span>VERITYX · EVIDENCE FIRST</span>
          <span>
            Perceptual similarity is a lead for review, not proof of origin.
          </span>
        </footer>
      </div>
    </main>
  );
}
