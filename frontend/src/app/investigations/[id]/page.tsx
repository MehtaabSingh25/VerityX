"use client";

import { useEffect, useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import { useParams, useRouter } from "next/navigation";
import { checkBackendHealth, createIntegrityJob, getAnalysisJob, uploadMedia } from "@/lib/verityx-api";

type EvidenceState = "Ready" | "Uploading" | "Uploaded" | "Queued" | "Completed" | "Failed";
type EvidenceItem = { id: string; file: File; state: EvidenceState; assetId?: string; jobId?: string; jobStatus?: string; error?: string };
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
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [apiOnline, setApiOnline] = useState(false);
  const isRealInvestigation = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(investigationId);

  useEffect(() => {
    if (!isRealInvestigation) return;
    let active = true;
    checkBackendHealth().then((healthy) => { if (active) setApiOnline(healthy); });
    return () => { active = false; };
  }, [investigationId, isRealInvestigation]);

  function addFiles(files: FileList | File[]) {
    if (!isRealInvestigation) {
      setError("This is a sample investigation. Create a real investigation from the dashboard before uploading evidence.");
      return;
    }
    setError("");
    setNotice("");
    const accepted: EvidenceItem[] = [];
    const rejected: string[] = [];
    for (const file of Array.from(files)) {
      const extension = file.name.includes(".") ? `.${file.name.split(".").pop()!.toLowerCase()}` : "";
      if (!ACCEPTED_EXTENSIONS.includes(extension)) {
        rejected.push(`${file.name}: unsupported file extension`);
      } else if (file.size === 0) {
        rejected.push(`${file.name}: file is empty`);
      } else if (file.size > MAX_FILE_SIZE) {
        rejected.push(`${file.name}: exceeds the 50 MiB limit`);
      } else if (items.some((item) => item.file.name === file.name) || accepted.some((item) => item.file.name === file.name)) {
        rejected.push(`${file.name}: already in this local queue`);
      } else {
        accepted.push({ id: `${file.name}-${file.size}-${file.lastModified}`, file, state: "Ready" });
      }
    }
    if (accepted.length) setItems((current) => [...current, ...accepted]);
    if (rejected.length) setError(rejected.join(" · "));
    if (accepted.length) setNotice(`${accepted.length} file${accepted.length === 1 ? "" : "s"} selected. Choose Upload selected to send them to the backend.`);
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
    const pending = items.filter((item) => !item.assetId && item.state !== "Uploading");
    if (!isRealInvestigation || pending.length === 0) return;
    setError("");
    setNotice("");
    for (const item of pending) {
      setItems((current) => current.map((candidate) => candidate.id === item.id ? { ...candidate, state: "Uploading", error: undefined } : candidate));
      try {
        const uploaded = await uploadMedia(investigationId, item.file);
        setItems((current) => current.map((candidate) => candidate.id === item.id ? { ...candidate, state: "Uploaded", assetId: uploaded.id, error: undefined } : candidate));
      } catch (uploadError) {
        const message = uploadError instanceof Error ? uploadError.message : "Upload failed";
        setItems((current) => current.map((candidate) => candidate.id === item.id ? { ...candidate, state: "Failed", error: message } : candidate));
        setError(`${item.file.name}: ${message}`);
      }
    }
    setNotice("Upload attempts finished. Review each file's state before starting analysis.");
  }

  async function queueIntegrityCheck(localId: string) {
    const item = items.find((candidate) => candidate.id === localId);
    if (!item?.assetId) {
      setError("Upload this file successfully before starting its integrity check.");
      return;
    }
    setError("");
    try {
      const job = await createIntegrityJob(investigationId, item.assetId);
      setItems((current) => current.map((candidate) => candidate.id === localId ? { ...candidate, state: job.status === "completed" ? "Completed" : job.status === "failed" ? "Failed" : "Queued", jobId: job.id, jobStatus: job.status, error: job.error_message || undefined } : candidate));
      setNotice(`Integrity check submitted. Job ID: ${job.id}`);
    } catch (jobError) {
      setError(jobError instanceof Error ? jobError.message : "Could not submit analysis job.");
    }
  }

  async function refreshJob(localId: string) {
    const item = items.find((candidate) => candidate.id === localId);
    if (!item?.jobId) return;
    try {
      const job = await getAnalysisJob(investigationId, item.jobId);
      setItems((current) => current.map((candidate) => candidate.id === localId ? { ...candidate, state: job.status === "completed" ? "Completed" : job.status === "failed" ? "Failed" : "Queued", jobStatus: job.status, error: job.error_message || undefined } : candidate));
      setNotice(`Job status: ${job.status}${job.result && typeof job.result.matches === "boolean" ? ` · SHA-256 ${job.result.matches ? "matches" : "does not match"}` : ""}`);
    } catch (jobError) {
      setError(jobError instanceof Error ? jobError.message : "Could not refresh analysis status.");
    }
  }

  const totalBytes = items.reduce((total, item) => total + item.file.size, 0);

  return (
    <main className="workspace-page">
      <header className="workspace-topbar">
        <button className="workspace-back" onClick={() => router.push("/")}>← <span>Back to dashboard</span></button>
        <div className="workspace-topbar-brand"><span className="workspace-brand-mark">V</span><strong>VerityX</strong><span>MEDIA FORENSICS</span></div>
        <span className={`workspace-demo-chip ${apiOnline ? "workspace-api-chip" : ""}`}><i /> {isRealInvestigation ? apiOnline ? "API CONNECTED" : "API CHECKING" : "SAMPLE CASE"}</span>
      </header>

      <div className="workspace-content">
        <div className="workspace-breadcrumb"><button onClick={() => router.push("/")}>Investigations</button><span>/</span><strong>{investigationId}</strong></div>
        <section className="workspace-heading">
          <div><div className="workspace-eyebrow">INVESTIGATION WORKSPACE</div><h1>Evidence intake</h1><p>Review candidate media, stage files for analysis, and preserve an evidence-first workflow.</p></div>
          <div className="workspace-heading-actions"><span className="workspace-case-id">CASE ID <strong>{investigationId}</strong></span><button className="workspace-primary-button" onClick={() => router.push(`/investigations/${encodeURIComponent(investigationId)}/reports`)}>View report & findings</button></div>
        </section>

        {!isRealInvestigation ? <div className="workspace-demo-notice"><span>ⓘ</span><div><strong>Sample investigation</strong><p>This dashboard row is illustrative and is not a database record. Create a new investigation from the dashboard before uploading evidence.</p></div></div> : <div className="workspace-demo-notice workspace-live-notice"><span>✓</span><div><strong>Connected workspace</strong><p>Uploads and integrity-check submissions are sent to the configured FastAPI backend. This page currently lists files selected in this browser session; it does not yet fetch the full stored evidence inventory after refresh.</p></div></div>}
        {notice && <div className="workspace-feedback" role="status">{notice}<button onClick={() => setNotice("")} aria-label="Dismiss">×</button></div>}
        {error && <div className="workspace-error" role="alert">{error}</div>}

        <section className="workspace-stats" aria-label="Evidence queue summary">
          <article><span>FILES IN LOCAL QUEUE</span><strong>{String(items.length).padStart(2, "0")}</strong><small>Selected in this browser session</small></article>
          <article><span>TOTAL SELECTED SIZE</span><strong>{formatBytes(totalBytes)}</strong><small>Maximum 50 MiB per file</small></article>
          <article><span>ANALYSIS STATUS</span><strong>{items.filter((item) => item.state === "Queued").length}</strong><small>Submitted or running jobs</small></article>
        </section>

        <section className="workspace-panel">
          <div className="workspace-panel-header"><div><h2>Add evidence</h2><p>Supported: JPG, PNG, WebP, MP4, and WebM</p></div><span className="workspace-step">STEP 01 / 03</span></div>
          <div className={`evidence-dropzone ${dragging ? "is-dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={handleDrop}>
            <div className="dropzone-icon"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M12 16V4m-5 5 5-5 5 5M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" /></svg></div>
            <h3>Drop evidence files here</h3><p>or browse your computer to select media files</p>
            <button className="workspace-primary-button" disabled={!isRealInvestigation} onClick={() => inputRef.current?.click()}>Choose files</button>
            <input ref={inputRef} className="workspace-file-input" type="file" multiple accept=".jpg,.jpeg,.png,.webp,.mp4,.webm,image/jpeg,image/png,image/webp,video/mp4,video/webm" onChange={handleInputChange} />
            <span className="dropzone-footnote">Maximum 50 MiB per file · Selected files upload only after you click Upload selected</span>
          </div>
        </section>

        <section className="workspace-panel evidence-list-panel">
          <div className="workspace-panel-header"><div><h2>Evidence queue <span className="workspace-count">{items.length}</span></h2><p>Selected files, upload state, and analysis jobs</p></div><div className="workspace-header-actions"><button className="workspace-primary-button" disabled={!isRealInvestigation || !apiOnline || !items.some((item) => !item.assetId && item.state !== "Uploading")} onClick={uploadSelected}>Upload selected</button><button className="workspace-text-button" disabled={!items.length} onClick={() => { setItems([]); setError(""); setNotice("Local selection cleared. Uploaded backend records are not deleted."); }}>Clear selection</button></div></div>
          {items.length === 0 ? <div className="workspace-empty"><div className="workspace-empty-icon">▤</div><strong>No evidence selected yet</strong><p>Add an image or video, upload it, then queue a SHA-256 integrity check.</p></div> : <div className="evidence-table-wrap"><table className="evidence-table"><thead><tr><th>FILE</th><th>TYPE</th><th>SIZE</th><th>STATE</th><th>ACTIONS</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td><div className="workspace-file-cell"><span className={`workspace-file-icon ${fileKind(item.file).toLowerCase()}`}>{fileKind(item.file) === "VIDEO" ? "▶" : "▧"}</span><div><strong>{item.file.name}</strong><small>Modified {new Date(item.file.lastModified).toLocaleDateString()}</small></div></div></td><td>{fileKind(item.file)}</td><td>{formatBytes(item.file.size)}</td><td><span className={`workspace-state state-${item.state.toLowerCase()}`}>{item.jobStatus ? `${item.state} · ${item.jobStatus}` : item.state}</span>{item.error && <small className="workspace-row-error">{item.error}</small>}</td><td><div className="workspace-row-actions">{item.jobId ? <button onClick={() => refreshJob(item.id)}>Refresh status</button> : <button disabled={!item.assetId} onClick={() => queueIntegrityCheck(item.id)}>Queue integrity check</button>}{!item.assetId && <button aria-label={`Remove ${item.file.name}`} onClick={() => setItems((current) => current.filter((candidate) => candidate.id !== item.id))}>Remove</button>}</div></td></tr>)}</tbody></table></div>}
          <div className="workspace-panel-footer"><span><i /> {apiOnline ? "Backend reachable" : "Backend not confirmed"}</span><span>API upload · SHA-256 integrity jobs · polling on demand</span></div>
        </section>
        <footer className="workspace-footer"><span>VERITYX · EVIDENCE FIRST</span><span>Perceptual similarity is a lead for review, not proof of origin.</span></footer>
      </div>
    </main>
  );
}
