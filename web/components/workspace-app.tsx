"use client";

import {
  Activity, AlertTriangle, Archive, BookOpen, BrainCircuit, ChevronLeft, ChevronRight,
  CircleCheck, Cloud, Command, Database, FileSearch, Fingerprint, Gauge, KeyRound,
  LoaderCircle, Moon, Play, Plus, RefreshCw, Search, Settings, ShieldCheck, Sparkles,
  Sun, Users, WandSparkles, X,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { apiGet, apiMutation, establishSession, type JsonMap } from "@/lib/api";
import { RecordInspector, type InspectorState } from "./record-inspector";

export type ViewKey = "overview" | "context" | "memory" | "sources" | "docs" | "audit" | "intelligence" | "maintenance" | "sync" | "devices" | "team" | "settings";

const NAV = [
  { key: "overview", label: "Overview", icon: Gauge }, { key: "context", label: "Context", icon: Archive },
  { key: "memory", label: "Memory", icon: BrainCircuit }, { key: "sources", label: "Sources", icon: Database },
  { key: "docs", label: "Docs", icon: BookOpen }, { key: "audit", label: "Audit", icon: ShieldCheck },
  { key: "intelligence", label: "Intelligence", icon: Sparkles }, { key: "maintenance", label: "Maintenance", icon: WandSparkles },
  { key: "sync", label: "Personal Sync", icon: Cloud }, { key: "devices", label: "Devices", icon: Fingerprint },
  { key: "team", label: "Team", icon: Users }, { key: "settings", label: "Settings", icon: Settings },
] as const;

const NAV_SECTIONS = [
  { label: "Operate", keys: ["overview", "context", "memory", "sources", "docs"] },
  { label: "Review", keys: ["audit", "intelligence", "maintenance"] },
  { label: "Cloud", keys: ["sync", "devices", "team", "settings"] },
] as const;

const ENDPOINTS: Record<ViewKey, string> = {
  overview: "/api/v1/status", context: "/api/v1/context", memory: "/api/v1/memory",
  sources: "/api/v1/sources", docs: "/api/v1/docs", audit: "/api/v1/audit",
  intelligence: "/api/v1/intelligence?view=review", maintenance: "/api/v1/jobs",
  sync: "/api/v1/cloud", devices: "/api/v1/cloud/devices", team: "/api/v1/cloud/team",
  settings: "/api/v1/capabilities",
};

const VIEW_COPY: Record<ViewKey, { eyebrow: string; title: string; description: string }> = {
  overview: { eyebrow: "Local control room", title: "Your memory, in working order", description: "One private view of index health, context, jobs, and encrypted continuity." },
  context: { eyebrow: "Prepared context", title: "What your agents should carry", description: "Inspect, edit, remove, distill, and share deliberate context packs." },
  memory: { eyebrow: "Memory atoms", title: "Search what your agents already learned", description: "Inspect provenance, edit manual memory, forget obsolete records, or promote an atom into prepared context." },
  sources: { eyebrow: "Source ledger", title: "Inspect the files behind recall", description: "Each row is a distinct indexed file. Open it to read, edit, reindex, or delete it with concurrency protection." },
  docs: { eyebrow: "Documentation index", title: "Keep reference material close", description: "Browse source collections, inspect documents, search sections, and ingest new documentation." },
  audit: { eyebrow: "Local safeguards", title: "See risk before it travels", description: "Inspect masked secret findings and agent hook coverage without uploading source content." },
  intelligence: { eyebrow: "Review queue", title: "Resolve conflict, drift, and noise", description: "Open each suggestion to compare evidence, keep both memories, choose a winner, or dismiss it." },
  maintenance: { eyebrow: "Command runner", title: "Rebuild, consolidate, diagnose, and apply", description: "Run allowlisted Docmancer operations locally and inspect every result or background job." },
  sync: { eyebrow: "Docmancer Pro", title: "Encrypted continuity across machines", description: "Start signed encrypted sync from this device. Local recall and the interface remain free." },
  devices: { eyebrow: "Device trust", title: "Know exactly which machines can sync", description: "Inspect registrations, approve by fingerprint, and revoke explicitly." },
  team: { eyebrow: "Shared standards", title: "Review Team memory locally", description: "Inspect and decide encrypted proposals, invite members, and review local Team state." },
  settings: { eyebrow: "Local configuration", title: "Explicit controls for this machine", description: "Review capabilities and change automatic capture settings without editing configuration files." },
};

type Mutate = (path: string, body: JsonMap, success: string, method?: string) => Promise<JsonMap | undefined>;

export function WorkspaceApp({ initialView }: { initialView: ViewKey }) {
  const [data, setData] = useState<JsonMap>({});
  const [status, setStatus] = useState<JsonMap>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [composer, setComposer] = useState("");
  const [secondary, setSecondary] = useState("");
  const [palette, setPalette] = useState(false);
  const [notice, setNotice] = useState("");
  const [inspector, setInspector] = useState<InspectorState | null>(null);

  const load = useCallback(async (path = ENDPOINTS[initialView]) => {
    setLoading(true); setError("");
    try {
      const viewPromise = initialView === "settings"
        ? Promise.all([apiGet(path), apiGet("/api/v1/settings/capture")]).then(([capabilities, capture]) => ({ ...capabilities, capture }))
        : apiGet(path);
      const [viewData, statusData] = await Promise.all([viewPromise, initialView === "overview" ? Promise.resolve({}) : apiGet("/api/v1/status")]);
      setData(viewData); setStatus(initialView === "overview" ? viewData : statusData);
    } catch (reason) { setError(messageOf(reason)); }
    finally { setLoading(false); }
  }, [initialView]);

  useEffect(() => {
    const stored = window.localStorage.getItem("docmancer-theme");
    const preferred = stored === "dark" || stored === "light" ? stored : window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    document.documentElement.classList.toggle("dark", preferred === "dark");
  }, []);
  useEffect(() => { establishSession().then(() => load()).catch((reason) => { setError(messageOf(reason)); setLoading(false); }); }, [load]);
  useEffect(() => {
    const keyboard = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setPalette((value) => !value); }
      if (event.key === "Escape") { setPalette(false); setInspector(null); }
    };
    window.addEventListener("keydown", keyboard); return () => window.removeEventListener("keydown", keyboard);
  }, []);

  const submitSearch = async (event: FormEvent) => {
    event.preventDefault(); const base = ENDPOINTS[initialView].split("?")[0];
    await load(query.trim() ? `${base}?q=${encodeURIComponent(query.trim())}` : ENDPOINTS[initialView]);
  };

  const mutate: Mutate = async (path, body, success, method = "POST") => {
    setError(""); setNotice("");
    try {
      const result = await apiMutation(path, body, method);
      setComposer(""); setSecondary(""); setNotice(success); await load(); return result;
    } catch (reason) { setError(messageOf(reason)); return undefined; }
  };

  async function inspect(item: JsonMap) {
    const normalized = normalizeItem(item, initialView);
    setInspector({ item: normalized, detail: {}, loading: true });
    try {
      let detail = normalized;
      if (initialView === "sources" && normalized.source_key) detail = await apiGet(`/api/v1/source?key=${encodeURIComponent(String(normalized.source_key))}`);
      else if (initialView === "memory") {
        const identifier = normalized.record_id ?? normalized.atom_id ?? normalized.id;
        if (identifier) detail = await apiGet(`/api/v1/memory/${encodeURIComponent(String(identifier))}`);
      } else if (initialView === "docs" && normalized.source && !normalized.id) {
        detail = await apiGet(`/api/v1/docs/source?source=${encodeURIComponent(String(normalized.source))}`);
      } else if (initialView === "maintenance" && normalized.id) detail = await apiGet(`/api/v1/jobs/${encodeURIComponent(String(normalized.id))}`);
      setInspector({ item: normalized, detail: { ...normalized, ...detail } });
    } catch (reason) { setInspector({ item: normalized, detail: normalized, error: messageOf(reason) }); }
  }

  async function runCommand(command: string) {
    setPalette(false);
    const commands: Record<string, [string, JsonMap, string]> = {
      sync: ["/api/v1/maintenance", { action: "sync" }, "Memory sync queued."],
      doctor: ["/api/v1/maintenance", { action: "doctor" }, "Diagnostics completed."],
      consolidate: ["/api/v1/maintenance", { action: "consolidate" }, "Consolidation queued."],
      cloudSync: ["/api/v1/cloud/sync", {}, "Encrypted sync queued."],
    };
    const spec = commands[command]; if (!spec) return;
    const result = await mutate(...spec);
    if (result) setInspector({ item: { title: commandLabel(command) }, detail: result });
  }

  const counts = objectAt(status, "counts");
  const project = String(objectAt(status, "status").project || "Local project");
  const copy = VIEW_COPY[initialView];
  const toggleTheme = () => { const next = document.documentElement.classList.contains("dark") ? "light" : "dark"; window.localStorage.setItem("docmancer-theme", next); document.documentElement.classList.toggle("dark", next === "dark"); };

  return <div className="shell">
    <aside className="rail">
      <div className="brand"><div className="brand-mark" aria-hidden="true"/><div><strong>docmancer <span>local</span></strong></div></div>
      <nav aria-label="Primary navigation">
        {NAV_SECTIONS.map((section) => (
          <div className="nav-section" key={section.label}>
            <p>{section.label}</p>
            {NAV.filter(({ key }) => (section.keys as readonly string[]).includes(key)).map(({ key, label, icon: Icon }) => (
              <Link key={key} href={key === "overview" ? "/" : `/${key}/`} className={initialView === key ? "nav-item active" : "nav-item"}>
                <Icon size={16} strokeWidth={1.8}/><span>{label}</span>{countFor(key, counts) !== null && <b>{countFor(key, counts)}</b>}
              </Link>
            ))}
          </div>
        ))}
      </nav>
      <div className="rail-footer"><button className="command-button" onClick={() => setPalette(true)}><Command size={14}/>Run or go to <kbd>⌘K</kbd></button><div className="local-proof"><span className="pulse"/>Loopback only <code>127.0.0.1</code></div><a href="https://docmancer.dev/account" target="_blank" rel="noreferrer">Account and billing ↗</a></div>
    </aside>

    <main className="stage">
      <header className="topbar"><div className="project-chip"><strong title={project}>{compactPath(project)}</strong><ChevronRight size={14}/><span>{NAV.find((item) => item.key === initialView)?.label}</span></div><div className="top-actions"><div className="privacy-chip"><ShieldCheck size={14}/>Local session</div><button className="icon-button" onClick={() => load()} aria-label="Refresh"><RefreshCw size={15}/></button><button className="icon-button theme-button" onClick={toggleTheme} aria-label="Toggle color theme"><Sun className="theme-sun" size={15}/><Moon className="theme-moon" size={15}/></button></div></header>
      <section className="hero-panel"><div><span className="eyebrow">{copy.eyebrow}</span><h1>{copy.title}</h1><p>{copy.description}</p></div>{["memory", "context", "sources", "docs", "maintenance"].includes(initialView) && <button className="secondary hero-command" onClick={() => setPalette(true)}><Play size={14}/>Run command</button>}</section>
      {error && <div className="alert error"><X size={16}/><span>{error}</span><button onClick={() => setError("")}>Dismiss</button></div>}
      {notice && <div className="alert success"><ShieldCheck size={16}/><span>{notice}</span><button onClick={() => setNotice("")}>Dismiss</button></div>}
      {loading ? <Loading/> : <ViewContent view={initialView} data={data} counts={counts} query={query} setQuery={setQuery} composer={composer} setComposer={setComposer} secondary={secondary} setSecondary={setSecondary} submitSearch={submitSearch} mutate={mutate} inspect={inspect} load={load}/>}
    </main>

    {palette && <CommandPalette close={() => setPalette(false)} run={runCommand}/>}
    {inspector && <RecordInspector key={`${initialView}:${rowKey(inspector.item, 0)}:${inspector.loading ? "loading" : "ready"}`} view={initialView} state={inspector} close={() => setInspector(null)} mutate={mutate} reload={() => load()}/>}
  </div>;
}

type ViewProps = { view: ViewKey; data: JsonMap; counts: JsonMap; query: string; setQuery: (value: string) => void; composer: string; setComposer: (value: string) => void; secondary: string; setSecondary: (value: string) => void; submitSearch: (event: FormEvent) => Promise<void>; mutate: Mutate; inspect: (item: JsonMap) => Promise<void>; load: (path?: string) => Promise<void>; };

function ViewContent(props: ViewProps) {
  if (props.view === "overview") return <Overview data={props.data} counts={props.counts}/>;
  if (props.view === "maintenance") return <Maintenance {...props}/>;
  if (props.view === "sync") return <SyncView {...props}/>;
  if (props.view === "devices") return <DevicesView {...props}/>;
  if (props.view === "team") return <TeamView {...props}/>;
  if (props.view === "settings") return <SettingsView {...props}/>;
  return <CollectionView {...props}/>;
}

function Overview({ data, counts }: { data: JsonMap; counts: JsonMap }) {
  const cards = [["Memory atoms", displayValue(counts.atoms), "Indexed and attributable"], ["Context entries", displayValue(counts.context), "Prepared for delivery"], ["Sources", displayValue(counts.sources), "Memory, instructions, and rules"], ["Docs", displayValue(counts.docs), "Separate reference index"]];
  return <><div className="metric-grid">{cards.map(([label, value, note]) => <article className="metric" key={label}><span>{label}</span><strong>{value}</strong><p>{note}</p></article>)}</div><div className="split-grid"><Panel title="Local runtime" icon={<Activity size={16}/>}><DefinitionRows value={objectAt(data, "status")}/></Panel><Panel title="Trust boundary" icon={<ShieldCheck size={16}/>}><div className="boundary-map"><div><b>LOCAL</b><span>Plaintext, files, keys, recall</span></div><i>signed ciphertext only</i><div><b>CLOUD</b><span>Routing, entitlements, recovery wrappers</span></div></div></Panel></div></>;
}

function CollectionView(props: ViewProps) {
  const items = extractItems(props.data, props.view); const searchable = ["memory", "sources", "docs", "intelligence"].includes(props.view);
  const total = Number(props.data.total ?? items.length); const page = Number(props.data.page ?? 1); const pages = Number(props.data.total_pages ?? 1);
  return <div className="workspace-grid"><section className="collection">
    {props.view === "audit" && (
      <AuditSummary data={props.data}/>
    )}
    {props.view === "intelligence" && (
      <IntelligenceSummary data={props.data} load={props.load}/>
    )}
    {searchable && <form className="searchbar" onSubmit={props.submitSearch}><Search size={16}/><input value={props.query} onChange={(event) => props.setQuery(event.target.value)} placeholder={`Search ${props.view}`}/><button>Search</button></form>}
    <div className="collection-head"><span>{items.length === total ? `${total} records` : `${items.length} of ${total}`}</span><span>{pages > 1 ? `Page ${page} of ${pages}` : "Local data"}</span></div>
    <div className="rows">{items.length ? items.map((item, index) => <DataRow key={rowKey(item, index)} item={item} view={props.view} inspect={() => void props.inspect(item)}/>) : <EmptyState view={props.view} subview={String(props.data.view ?? "")}/>}</div>
    <Pagination page={page} pages={pages} total={total} label={props.view} go={(next) => void props.load(collectionPagePath(props.view, next, props.query, String(props.data.view ?? "")))}/>
  </section><aside className="action-panel"><ActionComposer {...props}/></aside></div>;
}

function AuditSummary({ data }: { data: JsonMap }) {
  const report = objectAt(data, "report");
  const count = Number(report.finding_count ?? 0);
  const unique = Number(report.unique_secret_count ?? 0);
  return <div className={count ? "collection-summary risk-summary" : "collection-summary safe-summary"}>
    <div className="summary-icon">{count ? <AlertTriangle size={18}/> : <CircleCheck size={18}/>}</div>
    <div><strong>{count ? `${count} possible secret ${count === 1 ? "occurrence" : "occurrences"}` : "No likely secrets detected"}</strong><p>{count ? `${unique} unique masked value${unique === 1 ? "" : "s"}. Open a finding to see its type, file, line, and safe excerpt.` : "The current indexed memory sources passed the local secret scan."}</p></div>
  </div>;
}

function IntelligenceSummary({ data, load }: { data: JsonMap; load: (path?: string) => Promise<void> }) {
  const active = String(data.view ?? "review");
  const tabs = [["review", "Needs review"], ["recent", "Recent activity"], ["maintenance", "Orphans"], ["history", "Resolved"]];
  return <div className="intelligence-summary">
    <div><Sparkles size={17}/><p><strong>Intelligence is derived from your memory graph.</strong><span>The sidebar number is unresolved conflict suggestions, not all memories analysed. A zero means there is nothing waiting for a decision.</span></p></div>
    <nav className="view-tabs" aria-label="Intelligence views">{tabs.map(([key, label]) => <button key={key} className={active === key ? "active" : ""} onClick={() => void load(`/api/v1/intelligence?view=${key}`)}>{label}</button>)}</nav>
  </div>;
}

function Pagination({ page, pages, total, label, go }: { page: number; pages: number; total: number; label: string; go: (page: number) => void }) {
  const tokens = paginationTokens(page, pages);
  return <nav className="pagination" aria-label={`${humanise(label)} pages`}>
    <span className="pagination-total">{total} total</span>
    <div className="pagination-controls">
      <button className="page-nav" disabled={page <= 1} onClick={() => go(page - 1)}><ChevronLeft size={14}/>Previous</button>
      <div className="page-numbers">{tokens.map((token, index) => token === "ellipsis" ? <span key={`ellipsis-${index}`} className="page-ellipsis">…</span> : <button key={token} className={token === page ? "page-number active" : "page-number"} aria-current={token === page ? "page" : undefined} onClick={() => go(token)}>{token}</button>)}</div>
      <button className="page-nav" disabled={page >= pages} onClick={() => go(page + 1)}>Next<ChevronRight size={14}/></button>
    </div>
    <span className="pagination-status">Page {page} of {pages}</span>
  </nav>;
}

function ActionComposer(props: ViewProps) {
  if (props.view === "memory") return <Composer title="Add a memory atom" label="A durable, self-contained statement" value={props.composer} setValue={props.setComposer} action="Add locally" onSubmit={() => props.mutate("/api/v1/memory", { text: props.composer, scope_kind: "project" }, "Memory added locally.")}/>;
  if (props.view === "context") return <Composer title="Add prepared context" label="Statement for Personal defaults" value={props.composer} setValue={props.setComposer} action="Add to context" onSubmit={() => props.mutate("/api/v1/context", { text: props.composer, pack_id: "personal-defaults" }, "Context updated.")}/>;
  if (props.view === "sources") return <div className="composer"><span className="mini-label">New file-backed source</span><h2>Create and index a source</h2><p>Use an absolute path or a path relative to the project. Parent directories must already exist.</p><label>Path<input value={props.secondary} onChange={(event) => props.setSecondary(event.target.value)} placeholder="notes/decisions.md"/></label><label>Contents<textarea value={props.composer} onChange={(event) => props.setComposer(event.target.value)} placeholder="# Decisions&#10;&#10;Write the source contents here."/></label><button className="primary" disabled={!props.secondary.trim() || !props.composer.trim()} onClick={() => props.mutate("/api/v1/sources", { path: props.secondary, content: props.composer }, "Source created and indexed.")}><Plus size={15}/>Create source</button></div>;
  if (props.view === "docs") return <div className="composer"><span className="mini-label">Ingest documentation</span><h2>Add a reference source</h2><p>Use a public documentation URL or a local path. Progress appears under Maintenance.</p><label>URL or path<input value={props.composer} onChange={(event) => props.setComposer(event.target.value)} placeholder="https://docs.example.com"/></label><button className="primary" disabled={!props.composer.trim()} onClick={() => props.mutate("/api/v1/docs/ingest", { target: props.composer }, "Documentation ingestion queued.")}><Plus size={15}/>Start ingestion</button></div>;
  if (props.view === "audit") return <BoundaryCard/>;
  if (props.view === "intelligence") return <div className="composer"><span className="mini-label">Human authority</span><h2>Open a suggestion to decide</h2><p>Each result opens with both sides and its provenance. Nothing changes lifecycle state until you explicitly resolve it.</p></div>;
  return <BoundaryCard/>;
}

function Maintenance(props: ViewProps) {
  const jobs = extractItems(props.data, "maintenance"); const [page, setPage] = useState(1); const paged = clientPage(jobs, page);
  return <div className="workspace-grid"><section className="collection"><div className="tool-grid"><Tool icon={<RefreshCw/>} title="Rebuild local memory" command="docmancer memory sync" text="Harvest, redact, merge, index, and finalise local memory." action="Run sync" onClick={() => props.mutate("/api/v1/maintenance", { action: "sync" }, "Memory sync queued.")}/><Tool icon={<Sparkles/>} title="Draft consolidation" command="docmancer memory consolidate" text="Prepare a reviewable draft from indexed memory." action="Create draft" onClick={() => props.mutate("/api/v1/maintenance", { action: "consolidate", query: props.composer || null }, "Consolidation queued.")}/><Tool icon={<FileSearch/>} title="Run diagnostics" command="docmancer doctor" text="Inspect Python, index, docs, and project state." action="Run doctor" onClick={async () => { const result = await props.mutate("/api/v1/maintenance", { action: "doctor" }, "Diagnostics completed."); if (result) await props.inspect({ title: "Diagnostics result", ...result }); }}/></div><div className="collection-head"><span>Recent jobs</span><span>{jobs.length}</span></div><div className="rows">{paged.items.length ? paged.items.map((item, index) => <DataRow key={rowKey(item, index)} item={item} view="maintenance" inspect={() => void props.inspect(item)}/>) : <EmptyState view="maintenance"/>}</div><Pagination page={paged.page} pages={paged.pages} total={jobs.length} label="maintenance" go={setPage}/></section><aside className="action-panel"><div className="composer"><span className="mini-label">Consolidate or apply</span><h2>Turn memory into agent context</h2><p>Draft a focused consolidation, or apply the current reviewed memory to an installed agent.</p><label>Optional consolidation focus<textarea value={props.composer} onChange={(event) => props.setComposer(event.target.value)} placeholder="Focus on decisions from this project."/></label><button className="primary" onClick={() => props.mutate("/api/v1/maintenance", { action: "consolidate", query: props.composer || null }, "Consolidation queued.")}><Play size={14}/>Run consolidation</button><label>Apply to<select value={props.secondary || "codex"} onChange={(event) => props.setSecondary(event.target.value)}><option value="codex">Codex</option><option value="claude-code">Claude Code</option><option value="cursor">Cursor</option></select></label><button className="secondary" onClick={() => props.mutate("/api/v1/maintenance", { action: "apply", agent: props.secondary || "codex" }, "Context apply queued.")}><WandSparkles size={14}/>Apply managed context</button></div></aside></div>;
}

function SyncView(props: ViewProps) { const configured = Boolean(props.data.configured); return <div className="split-grid"><Panel title="Connection" icon={<Cloud size={16}/>}><div className={configured ? "state-banner connected" : "state-banner"}><span>{configured ? "CONNECTED" : "LOCAL ONLY"}</span><strong>{configured ? "Encrypted sync is configured" : "Nothing leaves this machine"}</strong><p>{configured ? `Workspace ${String(props.data.workspace_id ?? "")}` : "Connect from the CLI once, then run sync here."}</p></div>{configured ? <button className="primary" onClick={() => props.mutate("/api/v1/cloud/sync", {}, "Encrypted sync queued.")}><RefreshCw size={15}/>Push and pull</button> : <code className="command-line">docmancer cloud connect</code>}</Panel><Panel title="What Pro pays for" icon={<KeyRound size={16}/>}><ul className="check-list"><li>Encrypted transport between approved devices</li><li>Managed revision history and recovery wrappers</li><li>Team membership, review events, policy, and retention</li></ul><a className="text-link" href="https://docmancer.dev/account" target="_blank" rel="noreferrer">Plans and billing ↗</a></Panel></div>; }

function DevicesView(props: ViewProps) { const devices = Array.isArray(props.data.items) ? props.data.items.filter(isObject) : []; const [page, setPage] = useState(1); const paged = clientPage(devices, page); return <div className="workspace-grid"><section className="collection"><div className="collection-head"><span>Registered devices</span><span>{devices.length}</span></div><div className="rows">{paged.items.length ? paged.items.map((device, index) => <DataRow key={rowKey(device, index)} item={device} view="devices" inspect={() => void props.inspect(device)}/>) : <EmptyState view="devices"/>}</div><Pagination page={paged.page} pages={paged.pages} total={devices.length} label="devices" go={setPage}/></section><aside className="action-panel"><div className="composer"><span className="mini-label">Approve registration</span><h2>Verify a new device</h2><label>Device ID<input value={props.secondary} onChange={(event) => props.setSecondary(event.target.value)}/></label><label>Fingerprint<input value={props.composer} onChange={(event) => props.setComposer(event.target.value)}/></label><button className="primary" disabled={!props.secondary || !props.composer} onClick={() => props.mutate(`/api/v1/cloud/devices/${encodeURIComponent(props.secondary)}/approve`, { fingerprint: props.composer }, "Device approved.")}><Fingerprint size={15}/>Verify and approve</button></div></aside></div>; }

function TeamView(props: ViewProps) { const proposals = Array.isArray(props.data.proposals) ? props.data.proposals.filter(isObject) : []; const members = Array.isArray(props.data.members) ? props.data.members.filter(isObject) : []; const [proposalPage, setProposalPage] = useState(1); const [memberPage, setMemberPage] = useState(1); const pagedProposals = clientPage(proposals, proposalPage); const pagedMembers = clientPage(members, memberPage); return <div className="workspace-grid"><section className="collection"><div className="collection-head"><span>Encrypted proposals</span><span>{proposals.length}</span></div><div className="rows">{pagedProposals.items.length ? pagedProposals.items.map((item, index) => <DataRow key={rowKey(item, index)} item={item} view="team" inspect={() => void props.inspect(item)}/>) : <EmptyState view="team"/>}</div><Pagination page={pagedProposals.page} pages={pagedProposals.pages} total={proposals.length} label="team proposals" go={setProposalPage}/><div className="collection-head"><span>Members</span><span>{members.length}</span></div><div className="rows">{pagedMembers.items.map((item, index) => <DataRow key={rowKey(item, index)} item={item} view="team" inspect={() => void props.inspect(item)}/>)}</div><Pagination page={pagedMembers.page} pages={pagedMembers.pages} total={members.length} label="team members" go={setMemberPage}/></section><aside className="action-panel"><div className="composer"><span className="mini-label">Team seat</span><h2>Invite a member</h2><label>Email<input type="email" value={props.composer} onChange={(event) => props.setComposer(event.target.value)} placeholder="person@example.com"/></label><label>Role<select value={props.secondary || "member"} onChange={(event) => props.setSecondary(event.target.value)}><option value="member">Member</option><option value="reviewer">Reviewer</option><option value="admin">Administrator</option></select></label><button className="primary" disabled={!props.composer.trim()} onClick={() => props.mutate("/api/v1/cloud/team/invitations", { email: props.composer, role: props.secondary || "member" }, "Invitation created.")}><Users size={15}/>Invite</button><a className="text-link" href="https://docmancer.dev/account" target="_blank" rel="noreferrer">Manage billing and seats ↗</a></div></aside></div>; }

function SettingsView(props: ViewProps) { const enabled = objectAt(objectAt(props.data, "capture"), "enabled"); return <div className="settings-grid"><Panel title="Automatic capture" icon={<Settings size={16}/>}><div className="setting-list">{Object.keys(enabled).length ? Object.entries(enabled).map(([agent, value]) => <label key={agent}><span><strong>{humanise(agent)}</strong><small>Capture durable agent output after a session.</small></span><input type="checkbox" defaultChecked={Boolean(value)} onChange={(event) => { const next = { ...enabled, [agent]: event.target.checked }; void props.mutate("/api/v1/settings/capture", { enabled: next }, "Capture settings saved.", "PUT"); }}/></label>) : <p className="panel-copy">No capture agents are configured yet.</p>}</div></Panel><Panel title="Capabilities" icon={<Command size={16}/>}><DefinitionRows value={objectAt(props.data, "capabilities")}/></Panel><section className="panel settings-boundary"><BoundaryCard/></section></div>; }

function BoundaryCard() { return <div className="composer boundary-card"><span className="mini-label">Security boundary</span><h2>Local means local</h2><ul className="check-list"><li>The browser talks only to this loopback process.</li><li>Write operations call narrow, allowlisted Python methods.</li><li>No arbitrary shell command is accepted from the browser.</li><li>Destructive changes require explicit local confirmation.</li></ul></div>; }
function Panel({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) { return <section className="panel"><header>{icon}<h2>{title}</h2></header>{children}</section>; }
function Composer({ title, label, value, setValue, action, onSubmit }: { title: string; label: string; value: string; setValue: (value: string) => void; action: string; onSubmit: () => void }) { return <div className="composer"><span className="mini-label">Local write</span><h2>{title}</h2><label>{label}<textarea value={value} onChange={(event) => setValue(event.target.value)} placeholder="Write one clear statement…"/></label><button className="primary" disabled={!value.trim()} onClick={onSubmit}><Plus size={15}/>{action}</button></div>; }
function Tool({ icon, title, command, text, action, onClick }: { icon: React.ReactNode; title: string; command: string; text: string; action: string; onClick: () => void }) { return <article className="tool"><div className="tool-icon">{icon}</div><h3>{title}</h3><code>{command}</code><p>{text}</p><button onClick={onClick}>{action}</button></article>; }

function DataRow({ item, view, inspect }: { item: JsonMap; view: ViewKey; inspect: () => void }) {
  const normalized = normalizeItem(item, view); const title = rowTitle(normalized, view); const subtitle = rowSubtitle(normalized, view); const text = rowText(normalized, view);
  const badges = rowBadges(normalized, view);
  return <article className={`data-row interactive-row ${view}-row`} onClick={inspect} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); inspect(); } }} role="button" tabIndex={0}>
    <div className="row-body"><div className="row-title-line"><h3>{truncate(title, 120)}</h3>{badges.map((badge) => <span className={`row-badge ${badge.tone}`} key={`${badge.label}:${badge.tone}`}>{badge.label}</span>)}</div>
      {text && text !== title && <p>{truncate(cleanMarkdown(text), view === "context" ? 180 : 220)}</p>}
      {subtitle && <span className="row-subtitle" title={fullRowSubtitle(normalized, view)}>{subtitle}</span>}
    </div>
    <button aria-label={`Open ${truncate(title, 60)}`} onClick={(event) => { event.stopPropagation(); inspect(); }}><ChevronRight size={15}/></button>
  </article>;
}

function DefinitionRows({ value }: { value: unknown }) { if (!value || typeof value !== "object") return <p className="muted">No local state available.</p>; return <dl className="definitions">{Object.entries(value as JsonMap).slice(0, 12).map(([key, item]) => <div key={key}><dt>{humanise(key)}</dt><dd>{displayValue(item)}</dd></div>)}</dl>; }
function EmptyState({ view, subview = "" }: { view: ViewKey; subview?: string }) {
  if (view === "intelligence" && subview === "review") return <div className="empty"><div><CircleCheck size={24}/></div><h3>No conflicts need your review</h3><p>Your memory graph has no unresolved contradiction suggestions. Use Recent activity to inspect what changed this week.</p></div>;
  if (view === "audit") return <div className="empty"><div><CircleCheck size={24}/></div><h3>No audit records</h3><p>No secret findings or hook configurations were returned by the local scan.</p></div>;
  return <div className="empty"><div><Archive size={24}/></div><h3>No {view} items yet</h3><p>Run the relevant local action or change the search to populate this view.</p></div>;
}
function Loading() { return <div className="loading"><LoaderCircle className="spin"/><span>Opening the local index</span></div>; }

function CommandPalette({ close, run }: { close: () => void; run: (command: string) => Promise<void> }) {
  const [filter, setFilter] = useState(""); const needle = filter.toLowerCase();
  const pages = NAV.filter((item) => item.label.toLowerCase().includes(needle));
  const commands = [{ key: "sync", label: "Sync local memory", cli: "docmancer memory sync", icon: RefreshCw }, { key: "doctor", label: "Run diagnostics", cli: "docmancer doctor", icon: FileSearch }, { key: "consolidate", label: "Draft consolidation", cli: "docmancer memory consolidate", icon: Sparkles }, { key: "cloudSync", label: "Run encrypted sync", cli: "docmancer cloud sync", icon: Cloud }].filter((item) => `${item.label} ${item.cli}`.toLowerCase().includes(needle));
  return <div className="palette-backdrop" onMouseDown={close}><div className="palette command-center" onMouseDown={(event) => event.stopPropagation()}><header><Command size={16}/><input autoFocus value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Search pages and safe local commands"/><kbd>ESC</kbd></header><div className="command-results">{commands.length > 0 && <section><p>Run locally</p>{commands.map(({ key, label, cli, icon: Icon }) => <button key={key} onClick={() => void run(key)}><Icon size={16}/><span><strong>{label}</strong><code>{cli}</code></span><b>Run</b></button>)}</section>}{pages.length > 0 && <section><p>Go to</p>{pages.map(({ key, label, icon: Icon }) => <Link key={key} href={key === "overview" ? "/" : `/${key}/`} onClick={close}><Icon size={16}/><span><strong>{label}</strong><small>Open page</small></span><ChevronRight size={14}/></Link>)}</section>}{!commands.length && !pages.length && <div className="command-empty">No matching page or command.</div>}</div></div></div>;
}

function extractItems(data: JsonMap, view: ViewKey): JsonMap[] {
  if (Array.isArray(data.items)) return data.items.filter(isObject).map((item) => normalizeItem(item, view));
  if (view === "audit") { const report = objectAt(data, "report"); return [...(Array.isArray(report.findings) ? report.findings.filter(isObject) : []), ...(Array.isArray(data.hooks) ? data.hooks.filter(isObject) : [])]; }
  if (view === "team") return [...(Array.isArray(data.proposals) ? data.proposals.filter(isObject) : []), ...(Array.isArray(data.conflicts) ? data.conflicts.filter(isObject) : [])];
  return [];
}
function normalizeItem(item: JsonMap, view: ViewKey): JsonMap { if (view === "sources" && isObject(item.source)) return { ...item.source, matches: item.matches }; return item; }
function rowTitle(item: JsonMap, view: ViewKey): string {
  if (view === "sources") { const title = String(item.title ?? ""); if (title && title.toLowerCase() !== "manual memory") return title; return humaniseFilename(String(item.path ?? "Source file")); }
  if (view === "context" && item.view_kind === "context-pack") return String(item.name ?? "Context pack");
  if (view === "context" && item.view_kind === "context-record") return humaniseFilename(String(item.source_path ?? item.pack_name ?? "Context entry"));
  if (view === "docs") return String(item.title ?? item.source ?? item.text ?? "Documentation source");
  if (view === "maintenance") return String(item.title ?? item.kind ?? "Local job");
  if (view === "intelligence" && item.intelligence_kind === "recent-source") return intelligenceSourceTitle(item);
  if (view === "intelligence" && item.intelligence_kind === "conflict-group") return String(item.claim_subject ?? item.claim_key ?? "Conflicting memories");
  if (view === "intelligence") return String(item.text ?? item.source_text ?? item.target_text ?? humanise(String(item.intelligence_kind ?? "Intelligence item")));
  if (view === "audit" && item.view_kind === "secret-finding") return String(item.type ?? "Possible secret");
  if (view === "audit" && item.agent) return `${humanise(String(item.agent))} ${String(item.scope ?? "hook")}`;
  if (view === "memory") return memoryTitle(item);
  return String(item.name ?? item.title ?? item.text ?? item.fingerprint ?? item.email ?? item.source ?? item.path ?? item.id ?? `${humanise(view)} record`);
}
function rowSubtitle(item: JsonMap, view: ViewKey): string {
  if (view === "sources") return `${String(item.kind ?? "source")} · ${String(item.harness ?? "local")} · ${Number(item.atom_count ?? 0)} atoms · ${compactPath(String(item.path ?? ""))}`;
  if (view === "context") return compactPath(String(item.source_path ?? ""));
  if (view === "memory") return compactPath(String(item.source_path ?? item.source ?? ""));
  if (view === "audit" && item.view_kind === "secret-finding") { const first = firstOccurrence(item); return first ? `${compactPath(String(first.source_path ?? ""))}:${String(first.line ?? "?")}` : "Location unavailable"; }
  if (view === "audit" && item.view_kind === "hook-status") return compactPath(String(item.path ?? ""));
  if (view === "docs") return item.sections ? `${String(item.sections)} sections · ${String(item.pages ?? 0)} pages` : String(item.source ?? item.metadata ?? "Indexed documentation");
  if (view === "maintenance") return `${String(item.state ?? "unknown")} · ${String(item.created_at ?? "")}`;
  if (view === "intelligence" && item.intelligence_kind === "recent-source") return `${humanise(String(item.harness ?? "local"))} · ${scopeLabel(String(item.scope ?? "local"))} · ${Number(item.atom_count ?? 0)} atoms · ${String(item.activity_at ?? "")}`;
  if (view === "intelligence") return `${humanise(String(item.intelligence_kind ?? "analysis"))} · ${scopeLabel(String(item.scope ?? item.source_scope ?? "local"))}`;
  return String(item.source_path ?? item.scope ?? item.memory_type ?? item.kind ?? item.state ?? item.updated_at ?? "Local record");
}
function rowText(item: JsonMap, view: ViewKey): string { if (view === "sources" && Array.isArray(item.matches)) return `${item.matches.length} matching atoms. Open to inspect excerpts and edit the full file.`; if (view === "audit" && item.view_kind === "secret-finding") return String(firstOccurrence(item)?.masked_excerpt ?? "Masked value"); if (view === "audit" && item.path) return item.exists ? `Recall ${item.recall ? "installed" : "not installed"}; capture ${item.capture ? "installed" : "not installed"}.` : "Configuration file not found."; if (view === "intelligence" && Array.isArray(item.samples)) return item.samples.filter(isObject).map((sample) => String(sample.text ?? "")).filter(Boolean).slice(0, 2).join(" · "); if (view === "intelligence" && Array.isArray(item.members)) return item.members.filter(isObject).map((member) => String(member.text ?? member.value ?? "")).filter(Boolean).slice(0, 2).join(" ↔ "); return String(item.text ?? item.rendered ?? item.detail ?? item.summary ?? ""); }
function isObject(value: unknown): value is JsonMap { return Boolean(value) && typeof value === "object" && !Array.isArray(value); }
function objectAt(value: unknown, key: string): JsonMap { if (!isObject(value)) return {}; const nested = value[key]; return isObject(nested) ? nested : {}; }
function rowKey(item: JsonMap, index: number): string { const value = normalizeItem(item, "sources"); return String(value.id ?? value.record_id ?? value.atom_id ?? value.source_key ?? value.source ?? value.path ?? index); }
function compactPath(value: string): string { const parts = value.split("/").filter(Boolean); return parts.length > 2 ? `…/${parts.slice(-2).join("/")}` : value; }
function humanise(value: string): string { return value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase()); }
function humaniseFilename(value: string): string { const name = value.split("/").pop() ?? value; return name.replace(/-[a-f0-9]{8}(?=\.[^.]+$)/, "").replace(/\.[^.]+$/, "").replaceAll("-", " ").replace(/^./, (letter) => letter.toUpperCase()); }
function truncate(value: string, limit: number): string { return value.length > limit ? `${value.slice(0, limit - 1)}…` : value; }
function displayValue(value: unknown): string { if (value === null || value === undefined || value === "") return "Not set"; if (typeof value === "object") return Array.isArray(value) ? `${value.length} items` : `${Object.keys(value as JsonMap).length} fields`; return String(value); }
function messageOf(reason: unknown): string { return reason instanceof Error ? reason.message : "The local operation failed."; }
function countFor(key: string, counts: JsonMap): string | null { const map: Record<string, string> = { context: "context", memory: "atoms", sources: "sources", docs: "docs", intelligence: "intelligence" }; const countKey = map[key]; return countKey && counts[countKey] !== undefined ? String(counts[countKey]) : null; }
function commandLabel(command: string): string { return ({ sync: "Memory sync", doctor: "Diagnostics", consolidate: "Consolidation", cloudSync: "Encrypted sync" } as Record<string, string>)[command] ?? command; }
function collectionPagePath(view: ViewKey, page: number, query: string, activeView = ""): string { const [base, existing = ""] = ENDPOINTS[view].split("?"); const params = new URLSearchParams(existing); params.set("page", String(page)); if (activeView) params.set("view", activeView); if (query.trim()) params.set("q", query.trim()); return `${base}?${params.toString()}`; }

function paginationTokens(page: number, pages: number): Array<number | "ellipsis"> {
  if (pages <= 7) return Array.from({ length: pages }, (_, index) => index + 1);
  const visible = new Set([1, pages, page - 1, page, page + 1].filter((value) => value >= 1 && value <= pages));
  if (page <= 3) [2, 3, 4].forEach((value) => visible.add(value));
  if (page >= pages - 2) [pages - 3, pages - 2, pages - 1].forEach((value) => visible.add(value));
  const ordered = [...visible].sort((left, right) => left - right);
  const result: Array<number | "ellipsis"> = [];
  ordered.forEach((value, index) => { if (index && value - ordered[index - 1] > 1) result.push("ellipsis"); result.push(value); });
  return result;
}
function clientPage(items: JsonMap[], requestedPage: number, size = 20): { items: JsonMap[]; page: number; pages: number } { const pages = Math.max(1, Math.ceil(items.length / size)); const page = Math.min(Math.max(1, requestedPage), pages); return { items: items.slice((page - 1) * size, page * size), page, pages }; }

function firstOccurrence(item: JsonMap): JsonMap | undefined { return Array.isArray(item.occurrences) ? item.occurrences.find(isObject) : undefined; }
function memoryTitle(item: JsonMap): string { const value = cleanMarkdown(String(item.text ?? item.title ?? "Memory atom")); const sections = value.split(":").map((part) => part.trim()).filter(Boolean); const semantic = sections.length > 1 ? sections.slice(0, 2).join(": ") : value.split(/(?<=[.!?])\s+/)[0]; return truncate(semantic || "Memory atom", 76); }
function intelligenceSourceTitle(item: JsonMap): string { const title = String(item.source_title ?? ""); if (title && !["promoted memory", "manual memory", "memory"].includes(title.toLowerCase())) return title; const sample = Array.isArray(item.samples) ? item.samples.find(isObject) : undefined; return sample ? memoryTitle(sample) : humaniseFilename(String(item.source_path ?? "Recent source")); }
function cleanMarkdown(value: string): string { return value.replace(/^#{1,6}\s+/gm, "").replace(/[*_`>#]/g, "").replace(/\[(.*?)\]\([^)]*\)/g, "$1").replace(/\s+/g, " ").trim(); }
function fullRowSubtitle(item: JsonMap, view: ViewKey): string { if (view === "audit" && item.view_kind === "secret-finding") { const first = firstOccurrence(item); return `${String(first?.source_path ?? "")}:${String(first?.line ?? "?")}`; } return String(item.source_path ?? item.path ?? item.source ?? rowSubtitle(item, view)); }
function rowBadges(item: JsonMap, view: ViewKey): Array<{ label: string; tone: string }> {
  if (view === "audit" && item.view_kind === "secret-finding") return [{ label: String(item.severity ?? "finding"), tone: `severity-${String(item.severity ?? "medium")}` }, { label: `${Number(item.occurrence_count ?? 1)} occurrence${Number(item.occurrence_count ?? 1) === 1 ? "" : "s"}`, tone: "neutral" }];
  if (view === "audit" && item.view_kind === "hook-status") return [{ label: item.recall ? "Recall on" : "Recall off", tone: item.recall ? "success" : "warning" }, { label: item.capture ? "Capture on" : "Capture off", tone: item.capture ? "success" : "neutral" }];
  if (view === "context") return [{ label: humanise(String(item.view_kind === "context-pack" ? item.audience_kind ?? "pack" : item.memory_type ?? "entry")), tone: "neutral" }, { label: humanise(String(item.view_kind === "context-proposal" ? "pending review" : item.applicability_kind ?? "context")), tone: item.view_kind === "context-proposal" ? "warning" : "accent" }];
  if (view === "memory") { const metadata = objectAt(item, "metadata"); return [{ label: humanise(String(item.memory_type ?? metadata.memory_type ?? "memory")), tone: "neutral" }, { label: scopeLabel(String(item.scope ?? metadata.scope ?? "local")), tone: "accent" }]; }
  return [];
}
function scopeLabel(value: string): string { const lower = value.toLowerCase(); if (lower.startsWith("project")) return "Project"; if (lower.startsWith("global")) return "Global"; if (lower.startsWith("team")) return "Team"; if (lower.startsWith("personal")) return "Personal"; return humanise(value.split(":", 1)[0] || "Local"); }
