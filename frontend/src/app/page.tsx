"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { checkBackendHealth, createInvestigation as createInvestigationApi, getOperationsSummary, type OperationsSummary } from "@/lib/verityx-api";

type Status = "Complete" | "Processing" | "Queued";
type View = "Overview" | "Investigations" | "Evidence" | "Analysis jobs" | "Reports" | "Settings";
type Investigation = {
  id: string;
  title: string;
  description: string;
  assets: number;
  status: Status;
  updated: string;
  initials: string;
  tone: string;
};

const initialInvestigations: Investigation[] = [
  { id: "VX-0248", title: "Media provenance review", description: "Source verification · Internal review", assets: 18, status: "Complete", updated: "8 min ago", initials: "MP", tone: "lavender" },
  { id: "VX-0247", title: "Video integrity investigation", description: "Frame sampling · Evidence intake", assets: 7, status: "Processing", updated: "21 min ago", initials: "VI", tone: "mint" },
  { id: "VX-0246", title: "Image similarity review", description: "Cross-media comparison · Triage", assets: 11, status: "Queued", updated: "1 hr ago", initials: "IS", tone: "peach" },
  { id: "VX-0245", title: "Archived footage assessment", description: "Metadata review · Closed case", assets: 32, status: "Complete", updated: "Yesterday", initials: "AF", tone: "blue" },
];

const navGroups: { label: string; items: { label: View; icon: string }[] }[] = [
  { label: "WORKSPACE", items: [{ label: "Overview", icon: "grid" }, { label: "Investigations", icon: "folder" }, { label: "Evidence", icon: "layers" }, { label: "Analysis jobs", icon: "activity" }, { label: "Reports", icon: "file" }] },
  { label: "SYSTEM", items: [{ label: "Settings", icon: "settings" }] },
];

function Icon({ name, size = 18 }: { name: string; size?: number }) {
  const paths: Record<string, string> = {
    grid: "M3 3h7v7H3z M14 3h7v7h-7z M14 14h7v7h-7z M3 14h7v7H3z",
    folder: "M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
    layers: "m12 3 9 5-9 5-9-5 9-5z M3 12l9 5 9-5 M3 16l9 5 9-5",
    activity: "M3 12h4l3-8 4 16 3-8h4",
    file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M8 13h8 M8 17h8",
    settings: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-1.7 2.94-.09-.03a1.7 1.7 0 0 0-1.82.48l-.06.06h-3.4l-.03-.09a1.7 1.7 0 0 0-1.34-1.2l-.09-.02-2.94-1.7.03-.09a1.7 1.7 0 0 0-.48-1.82l-.06-.06v-3.4l.09-.03a1.7 1.7 0 0 0 1.2-1.34l.02-.09 1.7-2.94.09.03a1.7 1.7 0 0 0 1.82-.48l.06-.06h3.4l.03.09a1.7 1.7 0 0 0 1.34 1.2l.09.02 2.94 1.7-.03.09a1.7 1.7 0 0 0 .48 1.82l.06.06v3.4z",
    search: "m20 20-4.4-4.4 M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0z",
    bell: "M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9 M10 21h4",
    plus: "M12 5v14 M5 12h14",
    arrow: "M5 12h14 M13 6l6 6-6 6",
    chevron: "m9 18 6-6-6-6",
    more: "M5 12h.01 M12 12h.01 M19 12h.01",
    shield: "M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11z M9 12l2 2 4-4",
    clock: "M12 8v4l3 2 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0z",
    check: "m5 12 4 4L19 6",
    upload: "M12 16V4 M7 9l5-5 5 5 M4 20h16",
    close: "M18 6 6 18 M6 6l12 12",
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] ?? paths.grid} /></svg>;
}

function StatusPill({ status }: { status: Status }) {
  return <span className={`status-pill status-${status.toLowerCase()}`}><span className="status-dot" />{status}</span>;
}

export default function Home() {
  const router = useRouter();
  const [view, setView] = useState<View>("Overview");
  const [investigations, setInvestigations] = useState(initialInvestigations);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"All statuses" | Status>("All statuses");
  const [showCreate, setShowCreate] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [notice, setNotice] = useState("");
  const [apiStatus, setApiStatus] = useState<"checking" | "connected" | "offline">("checking");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const [operations, setOperations] = useState<OperationsSummary | null>(null);
  const [operationsLoading, setOperationsLoading] = useState(false);
  const [operationsError, setOperationsError] = useState("");

  const filteredInvestigations = useMemo(() => investigations.filter((item) => {
    const matchesSearch = `${item.title} ${item.id} ${item.description}`.toLowerCase().includes(search.toLowerCase());
    return matchesSearch && (statusFilter === "All statuses" || item.status === statusFilter);
  }), [investigations, search, statusFilter]);

  // The overview still contains clearly labelled sample metrics, but new investigations
  // are written to the configured FastAPI backend.
  useEffect(() => {
    let active = true;
    checkBackendHealth().then((healthy) => {
      if (active) setApiStatus(healthy ? "connected" : "offline");
    });
    return () => { active = false; };
  }, []);

  const refreshOperations = useCallback(async () => {
    setOperationsLoading(true);
    setOperationsError("");
    try {
      setOperations(await getOperationsSummary());
    } catch (error) {
      setOperationsError(error instanceof Error ? error.message : "Could not load operational summary.");
    } finally {
      setOperationsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (view !== "Settings") return;
    // Defer the request so its state updates run after this effect completes.
    const task = Promise.resolve().then(() => refreshOperations());
    void task;
  }, [view, refreshOperations]);

  async function createInvestigation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const title = newTitle.trim();
    if (!title || creating) return;
    setCreating(true);
    setCreateError("");
    try {
      const created = await createInvestigationApi({ title, description: newDescription.trim() || null });
      const item: Investigation = {
        id: created.id,
        title: created.title,
        description: created.description || "New investigation · Backend record",
        assets: 0,
        status: "Queued",
        updated: "Just now",
        initials: title.split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase()).join(""),
        tone: "blue",
      };
      setInvestigations((current) => [item, ...current]);
      setNewTitle("");
      setNewDescription("");
      setShowCreate(false);
      setView("Investigations");
      setApiStatus("connected");
      setNotice("Investigation created in the backend. Upload evidence from its workspace.");
      router.push(`/investigations/${encodeURIComponent(created.id)}`);
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : "Could not create the investigation.");
    } finally {
      setCreating(false);
    }
  }

  const pageDescriptions: Record<View, string> = {
    Overview: "A clear view of your evidence workflow and investigation activity.",
    Investigations: "Organize cases and track the evidence attached to each investigation.",
    Evidence: "Browse uploaded media and inspect its recorded provenance signals.",
    "Analysis jobs": "Follow background processing and review completed analysis results.",
    Reports: "Review structured findings and the methods used to produce them.",
    Settings: "Configure your workspace connection and review integration status.",
  };

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#overview" onClick={() => setView("Overview")} aria-label="VerityX overview">
          <span className="brand-mark"><Icon name="shield" size={23} /></span>
          <span className="brand-word">verity<span>x</span><small>MEDIA FORENSICS</small></span>
        </a>
        <div className="workspace-switcher">
          <div className="workspace-avatar">VX</div>
          <div className="workspace-copy"><strong>Personal workspace</strong><span>Local environment</span></div>
          <span className="switch-chevron"><Icon name="chevron" size={15} /></span>
        </div>
        <nav className="side-nav" aria-label="Main navigation">
          {navGroups.map((group) => <div className="nav-group" key={group.label}>
            <p className="nav-heading">{group.label}</p>
            {group.items.map((item) => <button key={item.label} className={`nav-item ${view === item.label ? "active" : ""}`} onClick={() => { setView(item.label); setNotice(""); }}>
              <Icon name={item.icon} size={18} /><span>{item.label}</span>{item.label === "Analysis jobs" && <span className="nav-count">3</span>}
            </button>)}
          </div>)}
        </nav>
        <div className="sidebar-bottom">
          <div className="help-card"><div className="help-icon"><Icon name="shield" size={18} /></div><strong>Evidence first.</strong><p>Similarity signals guide review. They do not prove authenticity or manipulation.</p><button onClick={() => { setView("Reports"); setNotice("Reports should preserve methods, source hashes, and uncertainty."); }}>Forensic principles <Icon name="arrow" size={14} /></button></div>
          <div className="profile-row"><div className="profile-avatar">M</div><div className="profile-copy"><strong>Local analyst</strong><span>Development mode</span></div><button className="icon-button profile-more" aria-label="Profile options" onClick={() => setView("Settings")}><Icon name="more" /></button></div>
        </div>
      </aside>

      <section className="main-area">
        <header className="topbar">
          <div className="breadcrumb"><span>Workspace</span><Icon name="chevron" size={14} /><strong>{view}</strong></div>
          <div className="topbar-actions"><span className={`environment-chip ${apiStatus === "connected" ? "api-connected" : ""}`}><span /> {apiStatus === "checking" ? "Checking API" : apiStatus === "connected" ? "API connected" : "API offline"}</span><button className="icon-button notification-button" aria-label="Notifications" onClick={() => setNotice("No live notifications are connected in this dashboard preview.")}><Icon name="bell" size={19} /><i /></button><div className="topbar-divider" /><div className="topbar-avatar">M</div></div>
        </header>

        <div className="content-wrap" id="overview">
          <div className="page-heading">
            <div><div className="eyebrow">THURSDAY, OCTOBER 22, 2026 <span className="eyebrow-line" /></div><h1>{view === "Overview" ? "Investigation overview" : view}</h1><p>{pageDescriptions[view]}</p></div>
            <div className="heading-actions"><button className="button button-secondary" onClick={() => { setNotice("This preview uses sample data. Live refresh will be enabled when the API is connected."); }}><Icon name="clock" size={16} /> Last 7 days <span className="button-caret">⌄</span></button><button className="button button-primary" onClick={() => { setShowCreate(true); setNotice(""); }}><Icon name="plus" size={17} /> New investigation</button></div>
          </div>

          {notice && <div className="notice-banner" role="status"><Icon name="shield" size={17} /><span>{notice}</span><button aria-label="Dismiss message" onClick={() => setNotice("")}><Icon name="close" size={15} /></button></div>}
          <div className="demo-banner"><span className="demo-banner-icon"><Icon name="activity" size={16} /></span><span><strong>{apiStatus === "connected" ? "API connected" : "Dashboard preview"}</strong> — overview counts and existing sample cases are illustrative. New investigations and evidence uploads use the configured backend.</span><button onClick={() => setView("Settings")}>Connection settings <Icon name="arrow" size={14} /></button></div>

          {view === "Overview" && <>
            <section className="metrics-grid" aria-label="Workspace metrics">
              <article className="metric-card"><div className="metric-top"><span className="metric-label">Total investigations</span><span className="metric-icon icon-violet"><Icon name="folder" /></span></div><div className="metric-value">24<span className="metric-trend trend-up">+3</span></div><div className="metric-foot"><span className="tiny-bar violet-bar" /><span>Created in the last 7 days</span></div></article>
              <article className="metric-card"><div className="metric-top"><span className="metric-label">Evidence assets</span><span className="metric-icon icon-blue"><Icon name="layers" /></span></div><div className="metric-value">186<span className="metric-trend trend-up">+12</span></div><div className="metric-foot"><span className="tiny-bar blue-bar" /><span>Across all investigations</span></div></article>
              <article className="metric-card"><div className="metric-top"><span className="metric-label">Jobs processing</span><span className="metric-icon icon-amber"><Icon name="activity" /></span></div><div className="metric-value">3<span className="metric-neutral">active</span></div><div className="metric-foot"><span className="pulse-dot" /><span>Background analysis queue</span></div></article>
              <article className="metric-card"><div className="metric-top"><span className="metric-label">Completed analyses</span><span className="metric-icon icon-green"><Icon name="check" /></span></div><div className="metric-value">142<span className="metric-trend trend-up">+18</span></div><div className="metric-foot"><span className="tiny-bar green-bar" /><span>Successfully completed</span></div></article>
            </section>

            <section className="dashboard-grid">
              <article className="panel investigations-panel">
                <div className="panel-header"><div><h2>Recent investigations</h2><p>Track active cases and evidence intake</p></div><button className="text-button" onClick={() => setView("Investigations")}>View all <Icon name="arrow" size={15} /></button></div>
                <div className="table-toolbar"><label className="search-field"><Icon name="search" size={17} /><input aria-label="Search investigations" placeholder="Search investigations..." value={search} onChange={(event) => setSearch(event.target.value)} /><kbd>⌘ K</kbd></label><select aria-label="Filter by status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as "All statuses" | Status)}><option>All statuses</option><option>Complete</option><option>Processing</option><option>Queued</option></select></div>
                <div className="table-scroll"><table><thead><tr><th>INVESTIGATION</th><th>ASSETS</th><th>STATUS</th><th>LAST UPDATED</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>{filteredInvestigations.length ? filteredInvestigations.slice(0, view === "Overview" ? 4 : undefined).map((item) => <tr key={item.id}><td><div className="case-cell"><div className={`case-avatar ${item.tone}`}>{item.initials}</div><div className="case-copy"><button className="case-open-link" onClick={() => router.push(`/investigations/${encodeURIComponent(item.id)}`)}>{item.title}</button><span>{item.id} <span className="case-dot">·</span> {item.description}</span></div></div></td><td><span className="asset-count">{item.assets.toString().padStart(2, "0")}</span></td><td><StatusPill status={item.status} /></td><td><span className="updated-text">{item.updated}</span></td><td><button className="icon-button row-more" aria-label={`More options for ${item.title}`} onClick={() => setNotice(`${item.title} is sample data. Investigation details will be connected to the API in a later frontend milestone.`)}><Icon name="more" size={18} /></button></td></tr>) : <tr><td colSpan={5} className="empty-state">No investigations match those filters.</td></tr>}</tbody></table></div>
                <div className="panel-footer"><span>Showing <strong>{filteredInvestigations.length}</strong> of <strong>{investigations.length}</strong> sample investigations</span><button className="pagination-button" onClick={() => { setSearch(""); setStatusFilter("All statuses"); }}>Reset filters</button></div>
              </article>

              <article className="panel activity-panel"><div className="panel-header"><div><h2>Recent activity</h2><p>Latest events across your workspace</p></div><button className="icon-button" aria-label="Activity options" onClick={() => setNotice("Activity feed is populated with illustrative events until the API is connected.")}><Icon name="more" /></button></div>
                <div className="activity-list"><div className="activity-item"><div className="activity-icon activity-green"><Icon name="check" size={16} /></div><div className="activity-body"><p><strong>Integrity check completed</strong></p><span>Media provenance review</span><time>8 min ago</time></div></div><div className="activity-item"><div className="activity-icon activity-blue"><Icon name="upload" size={16} /></div><div className="activity-body"><p><strong>New evidence received</strong></p><span>Video integrity investigation</span><time>21 min ago</time></div></div><div className="activity-item"><div className="activity-icon activity-amber"><Icon name="activity" size={16} /></div><div className="activity-body"><p><strong>Analysis job queued</strong></p><span>Image similarity review</span><time>1 hr ago</time></div></div><div className="activity-item"><div className="activity-icon activity-violet"><Icon name="file" size={16} /></div><div className="activity-body"><p><strong>Report generated</strong></p><span>Archived footage assessment</span><time>Yesterday</time></div></div></div>
                <button className="activity-link" onClick={() => setView("Analysis jobs")}>View activity log <Icon name="arrow" size={15} /></button>
              </article>
            </section>

            <section className="bottom-grid"><article className="panel queue-panel"><div className="panel-header"><div><h2>Analysis queue</h2><p>Background tasks by current state</p></div><button className="text-button" onClick={() => setView("Analysis jobs")}>All jobs <Icon name="arrow" size={15} /></button></div><div className="queue-content"><div className="queue-summary"><div className="queue-number">03</div><div><strong>Jobs in progress</strong><span>Workers are processing queued media</span></div></div><div className="queue-track"><span className="queue-complete" /><span className="queue-processing" /><span className="queue-pending" /></div><div className="queue-legend"><span><i className="legend-green" /> Completed <strong>142</strong></span><span><i className="legend-amber" /> Processing <strong>3</strong></span><span><i className="legend-gray" /> Queued <strong>8</strong></span></div></div></article><article className="panel integrity-panel"><div className="panel-header"><div><h2>Evidence integrity</h2><p>Recorded file-hash verification status</p></div><span className="mini-badge">DEMO</span></div><div className="integrity-content"><div className="integrity-ring"><div><strong>98.6<span>%</span></strong><small>match rate</small></div></div><div className="integrity-details"><div><span className="integrity-key"><i className="legend-green" /> Hash matches</span><strong>138</strong></div><div><span className="integrity-key"><i className="legend-amber" /> Needs review</span><strong>2</strong></div><p>Hash matches indicate byte-level consistency with a recorded digest. They do not establish source authenticity.</p></div></div></article></section>
          </>}

          {view === "Settings" ? <section className="operations-layout" aria-label="System status and security settings">
            <article className="panel operations-panel">
              <div className="panel-header"><div><h2>Backend connection</h2><p>Live health check through the same-origin server proxy</p></div><span className={`operations-health ${apiStatus}`}><i />{apiStatus === "checking" ? "Checking" : apiStatus === "connected" ? "Reachable" : "Unreachable"}</span></div>
              <div className="operations-body">
                <div className="operations-info-row"><span>API health endpoint</span><strong>/health</strong></div>
                <div className="operations-info-row"><span>Connection state</span><strong>{apiStatus === "connected" ? "Backend responded successfully" : apiStatus === "offline" ? "Check VERITYX_BACKEND_URL and backend process" : "Checking backend…"}</strong></div>
                <div className="operations-security-note"><Icon name="shield" size={18} /><div><strong>Server-side credentials only</strong><p>Keep VERITYX_API_KEY in frontend/.env.local or the deployment secret store. Never use a NEXT_PUBLIC_ prefix for private credentials.</p></div></div>
                <div className="operations-security-note"><Icon name="key" size={18} /><div><strong>Investigation tokens</strong><p>Scoped tokens are kept in sessionStorage for the current browser session and forwarded through the same-origin proxy. Sign out or close the session when finished on a shared device.</p></div></div>
              </div>
            </article>
            <article className="panel operations-panel">
              <div className="panel-header"><div><h2>Analysis operations</h2><p>Counts from persisted job and lifecycle records</p></div><button className="text-button" onClick={() => void refreshOperations()} disabled={operationsLoading}><Icon name="clock" size={14} /> {operationsLoading ? "Refreshing…" : "Refresh"}</button></div>
              {operationsError ? <div className="operations-message error" role="alert"><strong>Operational summary unavailable</strong><p>{operationsError}</p><button className="button button-secondary" onClick={() => void refreshOperations()}>Try again</button></div> : operationsLoading && !operations ? <div className="operations-message">Loading live operational summary…</div> : operations ? <div className="operations-body">
                <div className="operations-total"><span>Total analysis jobs</span><strong>{operations.total_jobs ?? 0}</strong><small>{operations.generated_at ? `Updated ${new Date(operations.generated_at).toLocaleString()}` : "Live API response"}</small></div>
                <h3>Jobs by status</h3><div className="operations-count-grid">{Object.entries(operations.jobs_by_status ?? {}).length ? Object.entries(operations.jobs_by_status ?? {}).map(([key, value]) => <div className="operations-count" key={key}><span>{key.replaceAll("_", " ")}</span><strong>{value}</strong></div>) : <p className="operations-muted">No job status counts returned.</p>}</div>
                <h3>Jobs by analysis type</h3><div className="operations-count-grid">{Object.entries(operations.jobs_by_analysis_type ?? {}).length ? Object.entries(operations.jobs_by_analysis_type ?? {}).map(([key, value]) => <div className="operations-count" key={key}><span>{key.replaceAll("_", " ")}</span><strong>{value}</strong></div>) : <p className="operations-muted">No analysis type counts returned.</p>}</div>
                <h3>Lifecycle events</h3><div className="operations-count-grid">{Object.entries(operations.lifecycle_events_by_type ?? {}).length ? Object.entries(operations.lifecycle_events_by_type ?? {}).map(([key, value]) => <div className="operations-count" key={key}><span>{key.replaceAll("_", " ")}</span><strong>{value}</strong></div>) : <p className="operations-muted">No lifecycle event counts returned.</p>}</div>
              </div> : <div className="operations-message">No operational summary has been loaded yet.</div>}
            </article>
            <div className="operations-footnote"><Icon name="info" size={15} /><span>This view reflects API response data. It does not directly inspect Redis queue depth or guarantee that a Celery worker is healthy. A reachable API alone does not prove the full processing pipeline is operational.</span></div>
          </section> : view !== "Overview" && <section className="panel section-placeholder"><div className="placeholder-icon"><Icon name={view === "Investigations" ? "folder" : view === "Evidence" ? "layers" : view === "Analysis jobs" ? "activity" : "file"} size={25} /></div><h2>{view} workspace</h2><p>{`This ${view.toLowerCase()} view is scaffolded for the next integration milestone. The current dashboard uses sample data and does not yet read or write these records through FastAPI.`}</p><div className="placeholder-actions"><button className="button button-primary" onClick={() => { setView("Overview"); setNotice(""); }}>Back to overview</button>{view === "Investigations" && <button className="button button-secondary" onClick={() => setShowCreate(true)}><Icon name="plus" size={16} /> New investigation</button>}</div></section>}

          <footer className="app-footer"><span><span className="footer-status-dot" /> VerityX local preview</span><span>Evidence-led analysis <span className="footer-divider">·</span> Results require human review</span><span>v0.1.0</span></footer>
        </div>
      </section>

      {showCreate && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowCreate(false); }}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="create-title"><div className="modal-header"><div><span className="modal-kicker">WORKSPACE</span><h2 id="create-title">New investigation</h2><p>Create a real investigation in the configured VerityX API.</p></div><button className="icon-button" aria-label="Close dialog" onClick={() => setShowCreate(false)}><Icon name="close" /></button></div><form onSubmit={createInvestigation}><label className="form-label" htmlFor="investigation-title">Investigation name <span>*</span></label><input id="investigation-title" className="form-input" autoFocus required maxLength={120} placeholder="e.g. Media provenance review" value={newTitle} onChange={(event) => setNewTitle(event.target.value)} /><label className="form-label" htmlFor="investigation-description">Description <span className="optional-label">OPTIONAL</span></label><textarea id="investigation-description" className="form-input form-textarea" rows={3} maxLength={500} placeholder="Briefly describe the scope of this investigation" value={newDescription} onChange={(event) => setNewDescription(event.target.value)} /><div className="modal-notice"><Icon name="shield" size={17} /><span>The request goes through the server-side API proxy. Keep VERITYX_API_KEY in the server environment, never in a NEXT_PUBLIC variable.</span></div>{createError && <p className="create-error" role="alert">{createError}</p>}<div className="modal-actions"><button type="button" className="button button-secondary" onClick={() => { setShowCreate(false); setCreateError(""); }}>Cancel</button><button type="submit" className="button button-primary" disabled={creating}><Icon name="plus" size={16} /> {creating ? "Creating…" : "Create investigation"}</button></div></form></section></div>}
    </main>
  );
}
