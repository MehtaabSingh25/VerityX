"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { createInvestigation as createInvestigationApi, getOperationsSummary, type OperationsSummary } from "@/lib/verityx-api";

type Status = "Open" | "Complete" | "Processing" | "Queued";
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
  const [investigations, setInvestigations] = useState<Investigation[]>([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"All statuses" | Status>("All statuses");
  const [showCreate, setShowCreate] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [notice, setNotice] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const [operations, setOperations] = useState<OperationsSummary | null>(null);
  const [operationsLoading, setOperationsLoading] = useState(false);
  const [operationsError, setOperationsError] = useState("");

  const filteredInvestigations = useMemo(() => investigations.filter((item) => {
    const matchesSearch = `${item.title} ${item.id} ${item.description}`.toLowerCase().includes(search.toLowerCase());
    return matchesSearch && (statusFilter === "All statuses" || item.status === statusFilter);
  }), [investigations, search, statusFilter]);

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
      const backendStatus = (created.status || "open").toLowerCase();
      const item: Investigation = {
        id: created.id,
        title: created.title,
        description: created.description || "",
        assets: 0,
        status: backendStatus === "complete" || backendStatus === "completed"
          ? "Complete"
          : backendStatus === "processing"
            ? "Processing"
            : backendStatus === "queued"
              ? "Queued"
              : "Open",
        updated: created.created_at ? new Date(created.created_at).toLocaleString() : "Just now",
        initials: title.split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase()).join(""),
        tone: "blue",
      };
      setInvestigations((current) => [item, ...current]);
      setNewTitle("");
      setNewDescription("");
      setShowCreate(false);
      setView("Investigations");
      setNotice("Investigation created. Upload evidence from its workspace.");
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
          <div className="topbar-actions"><div className="topbar-avatar" aria-label="Analyst workspace">VX</div></div>
        </header>

        <div className="content-wrap" id="overview">
          <div className="page-heading">
            <div><div className="eyebrow">MEDIA FORENSICS <span className="eyebrow-line" /></div><h1>{view === "Overview" ? "Investigation workspace" : view}</h1><p>{pageDescriptions[view]}</p></div>
            <div className="heading-actions"><button className="button button-primary" onClick={() => { setShowCreate(true); setNotice(""); }}><Icon name="plus" size={17} /> New investigation</button></div>
          </div>

          {notice && <div className="notice-banner" role="status"><Icon name="shield" size={17} /><span>{notice}</span><button aria-label="Dismiss message" onClick={() => setNotice("")}><Icon name="close" size={15} /></button></div>}

          {(view === "Overview" || view === "Investigations") && <section className="panel investigations-panel real-investigations-panel">
            <div className="panel-header"><div><h2>Investigations</h2><p>Cases created in this session. Open a case to manage evidence and run forensic analysis.</p></div><button className="text-button" onClick={() => setShowCreate(true)}><Icon name="plus" size={15} /> New investigation</button></div>
            <div className="table-toolbar"><label className="search-field"><Icon name="search" size={17} /><input aria-label="Search investigations" placeholder="Search investigations…" value={search} onChange={(event) => setSearch(event.target.value)} /><kbd>⌕</kbd></label><select aria-label="Filter by status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as "All statuses" | Status)}><option>All statuses</option><option>Open</option><option>Complete</option><option>Processing</option><option>Queued</option></select></div>
            <div className="table-scroll"><table><thead><tr><th>INVESTIGATION</th><th>EVIDENCE</th><th>STATUS</th><th>CREATED</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>{filteredInvestigations.length ? filteredInvestigations.map((item) => <tr key={item.id}><td><div className="case-cell"><div className="case-avatar blue">{item.initials || "VX"}</div><div className="case-copy"><button className="case-open-link" onClick={() => router.push(`/investigations/${encodeURIComponent(item.id)}`)}>{item.title}</button><span>{item.id}{item.description ? ` · ${item.description}` : ""}</span></div></div></td><td><span className="asset-count">{item.assets.toString().padStart(2, "0")}</span></td><td><StatusPill status={item.status} /></td><td><span className="updated-text">{item.updated}</span></td><td><button className="text-button" onClick={() => router.push(`/investigations/${encodeURIComponent(item.id)}`)}>Open <Icon name="arrow" size={14} /></button></td></tr>) : <tr><td colSpan={5} className="empty-state"><div className="dashboard-empty-state"><span className="dashboard-empty-icon"><Icon name="folder" size={24} /></span><strong>{search || statusFilter !== "All statuses" ? "No matching investigations" : "No investigations yet"}</strong><span>{search || statusFilter !== "All statuses" ? "Try a different search or filter." : "Create a real investigation to start uploading evidence, detecting AI-generated images, and searching public-web image matches."}</span>{!search && statusFilter === "All statuses" && <button className="button button-primary" onClick={() => setShowCreate(true)}><Icon name="plus" size={16} /> Create investigation</button>}</div></td></tr>}</tbody></table></div>
            <div className="panel-footer"><span><strong>{filteredInvestigations.length}</strong> investigation{filteredInvestigations.length === 1 ? "" : "s"} in this session</span><button className="pagination-button" onClick={() => { setSearch(""); setStatusFilter("All statuses"); }}>Reset filters</button></div>
          </section>}

          {view === "Settings" ? <section className="operations-layout" aria-label="System status and security settings">
            <article className="panel operations-panel">
              <div className="panel-header"><div><h2>Workspace security</h2><p>Credential handling and investigation access</p></div></div>
              <div className="operations-body">
                <div className="operations-security-note"><Icon name="shield" size={18} /><div><strong>Server-side credentials only</strong><p>Keep VERITYX_API_KEY in frontend/.env.local or the deployment secret store. Never use a NEXT_PUBLIC_ prefix for private credentials.</p></div></div>
                <div className="operations-security-note"><Icon name="key" size={18} /><div><strong>Investigation tokens</strong><p>Scoped tokens are kept in sessionStorage for the current browser session and forwarded through the same-origin proxy. Sign out or close the session when finished on a shared device.</p></div></div>
              </div>
            </article>
            <article className="panel operations-panel">
              <div className="panel-header"><div><h2>Analysis operations</h2><p>Recorded analysis jobs and lifecycle events</p></div><button className="text-button" onClick={() => void refreshOperations()} disabled={operationsLoading}><Icon name="clock" size={14} /> {operationsLoading ? "Refreshing…" : "Refresh"}</button></div>
              {operationsError ? <div className="operations-message error" role="alert"><strong>Operational summary unavailable</strong><p>{operationsError}</p><button className="button button-secondary" onClick={() => void refreshOperations()}>Try again</button></div> : operationsLoading && !operations ? <div className="operations-message">Loading live operational summary…</div> : operations ? <div className="operations-body">
                <div className="operations-total"><span>Total analysis jobs</span><strong>{operations.total_jobs ?? 0}</strong><small>{operations.generated_at ? `Updated ${new Date(operations.generated_at).toLocaleString()}` : "Latest recorded update"}</small></div>
                <h3>Jobs by status</h3><div className="operations-count-grid">{Object.entries(operations.jobs_by_status ?? {}).length ? Object.entries(operations.jobs_by_status ?? {}).map(([key, value]) => <div className="operations-count" key={key}><span>{key.replaceAll("_", " ")}</span><strong>{value}</strong></div>) : <p className="operations-muted">No job status counts returned.</p>}</div>
                <h3>Jobs by analysis type</h3><div className="operations-count-grid">{Object.entries(operations.jobs_by_analysis_type ?? {}).length ? Object.entries(operations.jobs_by_analysis_type ?? {}).map(([key, value]) => <div className="operations-count" key={key}><span>{key.replaceAll("_", " ")}</span><strong>{value}</strong></div>) : <p className="operations-muted">No analysis type counts returned.</p>}</div>
                <h3>Lifecycle events</h3><div className="operations-count-grid">{Object.entries(operations.lifecycle_events_by_type ?? {}).length ? Object.entries(operations.lifecycle_events_by_type ?? {}).map(([key, value]) => <div className="operations-count" key={key}><span>{key.replaceAll("_", " ")}</span><strong>{value}</strong></div>) : <p className="operations-muted">No lifecycle event counts returned.</p>}</div>
              </div> : <div className="operations-message">No operational summary has been loaded yet.</div>}
            </article>
            <div className="operations-footnote"><Icon name="info" size={15} /><span>Counts reflect recorded analysis jobs and lifecycle events; they do not guarantee that background processing is healthy.</span></div>
          </section> : view !== "Overview" && <section className="panel section-placeholder"><div className="placeholder-icon"><Icon name={view === "Investigations" ? "folder" : view === "Evidence" ? "layers" : view === "Analysis jobs" ? "activity" : "file"} size={25} /></div><h2>{view} workspace</h2><p>{`The ${view.toLowerCase()} view is not connected yet. Use Investigations to create a case and work with persisted evidence and analysis results.`}</p><div className="placeholder-actions"><button className="button button-primary" onClick={() => { setView("Overview"); setNotice(""); }}>Back to overview</button>{view === "Investigations" && <button className="button button-secondary" onClick={() => setShowCreate(true)}><Icon name="plus" size={16} /> New investigation</button>}</div></section>}

          <footer className="app-footer"><span><span className="footer-status-dot" /> VerityX · Evidence first</span><span>Evidence-led analysis <span className="footer-divider">·</span> Results require human review</span><span>v0.1.0</span></footer>
        </div>
      </section>

      {showCreate && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowCreate(false); }}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="create-title"><div className="modal-header"><div><span className="modal-kicker">WORKSPACE</span><h2 id="create-title">New investigation</h2><p>Create an investigation to organize evidence and analysis.</p></div><button className="icon-button" aria-label="Close dialog" onClick={() => setShowCreate(false)}><Icon name="close" /></button></div><form onSubmit={createInvestigation}><label className="form-label" htmlFor="investigation-title">Investigation name <span>*</span></label><input id="investigation-title" className="form-input" autoFocus required maxLength={120} placeholder="e.g. Media provenance review" value={newTitle} onChange={(event) => setNewTitle(event.target.value)} /><label className="form-label" htmlFor="investigation-description">Description <span className="optional-label">OPTIONAL</span></label><textarea id="investigation-description" className="form-input form-textarea" rows={3} maxLength={500} placeholder="Briefly describe the scope of this investigation" value={newDescription} onChange={(event) => setNewDescription(event.target.value)} /><div className="modal-notice"><Icon name="shield" size={17} /><span>Use a clear case name and keep investigation access credentials private.</span></div>{createError && <p className="create-error" role="alert">{createError}</p>}<div className="modal-actions"><button type="button" className="button button-secondary" onClick={() => { setShowCreate(false); setCreateError(""); }}>Cancel</button><button type="submit" className="button button-primary" disabled={creating}><Icon name="plus" size={16} /> {creating ? "Creating…" : "Create investigation"}</button></div></form></section></div>}
    </main>
  );
}
