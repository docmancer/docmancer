"use client";

import {
  Activity, AlertTriangle, Archive, BookOpen, BrainCircuit, ChevronLeft, ChevronRight,
  CircleCheck, CircleHelp, Cloud, Command, Database, FileSearch, Fingerprint, Gauge, KeyRound,
  History, LoaderCircle, Moon, Play, Plus, Radio, RefreshCw, Search, Share2, ShieldCheck, Sparkles,
  Sun, Users, WandSparkles, WifiOff, X,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { apiGet, apiMutation, establishSession, type JsonMap } from "@/lib/api";
import { RecordInspector, type InspectorState } from "./record-inspector";
import { InboxWorkbench } from "./inbox-workbench";

export type ViewKey = "overview" | "tree" | "ask" | "common" | "delivery" | "timeline" | "agent-context" | "inbox" | "context" | "memory" | "sources" | "intelligence" | "docs" | "audit" | "maintenance" | "sync" | "devices" | "team" | "help";

const NAV = [
  { key: "overview", label: "Home", icon: Gauge }, { key: "tree", label: "Memory tree", icon: Archive },
  { key: "ask", label: "Ask", icon: Search }, { key: "common", label: "Shared memory", icon: Share2 },
  { key: "delivery", label: "Context delivery", icon: Radio }, { key: "timeline", label: "Decision timeline", icon: History },
  { key: "agent-context", label: "Agent Context", icon: BrainCircuit },
  { key: "inbox", label: "Inbox and import", icon: Database }, { key: "docs", label: "Docs", icon: BookOpen },
  { key: "audit", label: "Audit", icon: ShieldCheck }, { key: "maintenance", label: "Activity", icon: WandSparkles },
  { key: "sync", label: "Personal Sync", icon: Cloud }, { key: "devices", label: "Devices", icon: Fingerprint },
  { key: "team", label: "Team", icon: Users }, { key: "help", label: "Help", icon: CircleHelp },
] as const;

const NAV_SECTIONS = [
  { label: "Local memory", keys: ["overview", "tree", "ask", "common", "delivery", "timeline", "agent-context", "inbox"] },
  { label: "Reference", keys: ["docs", "audit", "maintenance"] },
  { label: "Cloud", keys: ["sync", "devices", "team"] },
  { label: "Learn", keys: ["help"] },
] as const;

const ENDPOINTS: Record<ViewKey, string> = {
  overview: "/api/v1/status", tree: "/api/v1/tree", ask: "/api/v1/tree/root",
  common: "/api/v1/common", delivery: "/api/v1/delivery", timeline: "/api/v1/timeline",
  "agent-context": "/api/v1/tree/root", inbox: "/api/v1/inbox", docs: "/api/v1/docs", audit: "/api/v1/audit",
  context: "/api/v1/context", memory: "/api/v1/memory", sources: "/api/v1/sources", intelligence: "/api/v1/intelligence?view=review", maintenance: "/api/v1/jobs",
  sync: "/api/v1/cloud", devices: "/api/v1/cloud/devices", team: "/api/v1/cloud/team",
  help: "/api/v1/status",
};

const VIEW_COPY: Record<ViewKey, { eyebrow: string; title: string; description: string }> = {
  overview: { eyebrow: "Local 127.0.0.1", title: "Your curated Markdown memory tree", description: "Open durable files, inspect the uncurated inbox, and preview the exact context an agent receives." },
  tree: { eyebrow: "Canonical memory", title: "Browse the files your agents share", description: "Each item is a source-attributed Markdown file with a stable address, hash-guarded writes, relations, backlinks, and citations." },
  ask: { eyebrow: "Context Compiler", title: "Ask your local memory", description: "Get a cited evidence brief from the same compiler used by CLI and MCP. No model is required." },
  common: { eyebrow: "Cross-agent recurrence", title: "See what your agents repeatedly know", description: "Equivalent memory from independent harness sources, with generated integration copies excluded. Recurrence is evidence, not consensus or truth." },
  delivery: { eyebrow: "Activation proof", title: "See how context reaches every agent", description: "Inspect integration modes, hook state, the last successful recall, tree revision, and delivered bundle hash." },
  timeline: { eyebrow: "Decision journal", title: "See what changed and when", description: "Follow canonical Markdown creates, edits, moves, duplicates, trash operations, and restores with actors, sources, lineage, and readable diffs." },
  "agent-context": { eyebrow: "Delivery preview", title: "Preview what one agent receives", description: "Inspect mandatory policy and relevant curated memory within an explicit token budget." },
  inbox: { eyebrow: "Uncurated evidence", title: "Review captured and imported Markdown", description: "Optional imports stay visible here until you turn a complete file into durable memory." },
  context: { eyebrow: "Compatibility route", title: "Agent Context", description: "This route is retained for one release and now points users toward the Context Compiler preview." },
  memory: { eyebrow: "Compatibility route", title: "Ask local memory", description: "This route is retained for one release while the product moves from atom browsing to file-backed memory." },
  sources: { eyebrow: "Compatibility route", title: "Inbox and import", description: "This route is retained for one release while optional imports move into the new workbench." },
  docs: { eyebrow: "Reference library", title: "Keep documentation separate from memory", description: "Browse indexed documentation, search its sections, or add another local path or public documentation site." },
  audit: { eyebrow: "Local safeguards", title: "Find risky content before it travels", description: "See each masked finding with its type, exact file, line, and remediation. Source content stays on this machine." },
  intelligence: { eyebrow: "Compatibility route", title: "Activity", description: "Claims-era Intelligence is retired. Existing URLs remain readable for one release." },
  maintenance: { eyebrow: "Local maintenance", title: "Rebuild, consolidate, diagnose, and apply", description: "Run the small set of allowlisted maintenance operations and inspect their results." },
  sync: { eyebrow: "Optional Pro feature", title: "Encrypted continuity across machines", description: "Sync signed encrypted revisions between devices. Local capture, recall, MCP, and this interface remain free." },
  devices: { eyebrow: "Device trust", title: "Control which machines can sync", description: "Connect Cloud first, then verify pending devices by fingerprint or revoke approved devices explicitly." },
  team: { eyebrow: "Shared context", title: "Publish one reviewed Team file", description: "Generate a privacy-filtered file locally, inspect one complete diff, then approve that file for encrypted publication." },
  help: { eyebrow: "Product guide", title: "Understand the whole memory workflow", description: "Start with the guided path, then use workflows and the glossary whenever a Docmancer term is unclear." },
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
      const viewPromise = apiGet(path);
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
  useEffect(() => {
    const openMemory = (event: Event) => {
      const address = String((event as CustomEvent<{ address?: string }>).detail?.address || "");
      if (!address) return;
      const item = { address, title: address };
      setInspector({ item, detail: {}, loading: true });
      apiGet(`/api/v1/tree/file?address=${encodeURIComponent(address)}`)
        .then((detail) => setInspector({ item, detail: { ...item, ...detail } }))
        .catch((reason) => setInspector({ item, detail: item, error: messageOf(reason) }));
    };
    window.addEventListener("docmancer:open-memory", openMemory);
    return () => window.removeEventListener("docmancer:open-memory", openMemory);
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
      if (initialView === "tree" && normalized.address) detail = await apiGet(`/api/v1/tree/file?address=${encodeURIComponent(String(normalized.address))}`);
      else if (initialView === "docs" && normalized.source && !normalized.id) {
        detail = await apiGet(`/api/v1/docs/source?source=${encodeURIComponent(String(normalized.source))}`);
      } else if (initialView === "maintenance" && normalized.id) detail = await apiGet(`/api/v1/jobs/${encodeURIComponent(String(normalized.id))}`);
      setInspector({ item: normalized, detail: { ...normalized, ...detail } });
    } catch (reason) { setInspector({ item: normalized, detail: normalized, error: messageOf(reason) }); }
  }

  async function runCommand(command: string) {
    setPalette(false);
    const commands: Record<string, [string, JsonMap, string]> = {
      reindex: ["/api/v1/tree", { action: "reindex" }, "Curated tree index rebuilt."],
      sync: ["/api/v1/maintenance", { action: "sync" }, "Memory sync queued."],
      doctor: ["/api/v1/maintenance", { action: "doctor" }, "Diagnostics completed."],
      consolidate: ["/api/v1/maintenance", { action: "consolidate" }, "Consolidation queued."],
      distill: ["/api/v1/context/personal-defaults", { action: "distill" }, "Context proposal created for Personal defaults."],
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
  if (props.view === "ask" || props.view === "agent-context") return <AskView {...props}/>;
  if (props.view === "inbox") return <InboxWorkbench data={props.data} reload={() => props.load()}/>;
  if (props.view === "maintenance") return <Maintenance {...props}/>;
  if (props.view === "sync") return <SyncView {...props}/>;
  if (props.view === "devices") return <DevicesView {...props}/>;
  if (props.view === "team") return <TeamView {...props}/>;
  if (props.view === "help") return <HelpView/>;
  return <CollectionView {...props}/>;
}

function Overview({ data, counts }: { data: JsonMap; counts: JsonMap }) {
  const runtime = objectAt(data, "status");
  const project = String(runtime.project ?? "Current working directory");
  const cards = [["Curated files", displayValue(counts.context), "Canonical Markdown memory"], ["Indexed atoms", displayValue(counts.atoms), "Rebuildable retrieval data"], ["Harvested sources", displayValue(counts.sources), "Read-only evidence"], ["Documentation", displayValue(counts.docs), "Separate reference index"]];
  return <><div className="metric-grid">{cards.map(([label, value, note]) => <article className="metric" key={label}><span>{label}</span><strong>{value}</strong><p>{note}</p></article>)}</div><div className="split-grid"><Panel title="Workspace readiness" icon={<Activity size={16}/>}><dl className="readiness-list"><div><dt>Memory index</dt><dd><strong>{displayValue(counts.atoms)} atoms</strong><span>Ready for local search and recall</span></dd></div><div><dt>Prepared context</dt><dd><strong>{displayValue(counts.context)} durable packs</strong><span>Open Context to inspect what agents carry</span></dd></div><div><dt>Review queue</dt><dd><strong>{displayValue(counts.intelligence)} conflicts</strong><span>Intelligence counts unresolved decisions only</span></dd></div><div><dt>Active project</dt><dd><strong title={project}>{compactPath(project)}</strong><span>All project-scoped actions use this directory</span></dd></div></dl></Panel><Panel title="Trust boundary" icon={<ShieldCheck size={16}/>}><div className="boundary-map"><div><b>LOCAL</b><span>Plaintext memory, files, keys, search, and writes</span></div><i>optional encrypted sync</i><div><b>CLOUD</b><span>Ciphertext transport, devices, recovery, and team membership</span></div></div></Panel></div></>;
}

function AskView(props: ViewProps) {
  const [result, setResult] = useState<JsonMap>({}); const [busy, setBusy] = useState(false); const [tokenBudget, setTokenBudget] = useState(2000);
  const sections = [
    { key: "mandatory_policies", label: "Mandatory policy", title: "Rules that always apply", note: "Highest-precedence instructions retained even when they exceed the requested budget.", items: arrayObjects(result.mandatory_policies) },
    { key: "curated_memory", label: "Curated memory", title: "Approved project context", note: "Canonical Markdown selected from the current project and applicable parent scopes.", items: arrayObjects(result.curated_memory) },
    { key: "relevant_evidence", label: "Agent evidence", title: "Relevant source evidence", note: "Task-relevant memory and instructions refreshed from registered coding agents.", items: arrayObjects(result.relevant_evidence) },
  ];
  const structuredItems = sections.flatMap((section) => section.items);
  const items = structuredItems.length > 0 ? structuredItems : extractItems(result, props.view);
  const run = async () => { if (!props.composer.trim()) return; setBusy(true); try { setResult(await apiMutation("/api/v1/ask", { task: props.composer, agent: props.view === "agent-context" ? (props.secondary || "codex") : "web", token_budget: tokenBudget })); } finally { setBusy(false); } };
  return <div className="workspace-grid"><section className="collection"><div className="composer"><span className="mini-label">Cited local retrieval</span><h2>{props.view === "agent-context" ? "Compile an agent bundle" : "Ask a question"}</h2><label>Task<textarea value={props.composer} onChange={(event) => props.setComposer(event.target.value)} placeholder="How do we deploy this project?"/></label>{props.view === "agent-context" && <label>Agent<select value={props.secondary || "codex"} onChange={(event) => props.setSecondary(event.target.value)}><option value="codex">Codex</option><option value="claude-code">Claude Code</option><option value="cursor">Cursor</option></select></label>}<label>Token budget<input type="number" min={100} max={100000} step={100} value={tokenBudget} onChange={(event) => setTokenBudget(Math.min(100000, Math.max(100, Number(event.target.value) || 100)))}/><small>The compiler always retains mandatory policy, even when it alone exceeds this budget.</small></label><button className="primary" disabled={busy || !props.composer.trim()} onClick={run}>{busy ? <LoaderCircle className="spin" size={15}/> : <Search size={15}/>}Compile context</button></div><div className="collection-head"><span>{items.length} cited items</span><span>{result.token_estimate ? `${result.token_estimate} of ${tokenBudget} estimated tokens` : `Budget ${tokenBudget} tokens`}</span></div>{result.no_answer ? <EmptyState view={props.view}/> : structuredItems.length > 0 ? <div className="ask-sections">{sections.filter((section) => section.items.length > 0).map((section) => <section className="context-level" key={section.key}><header><div><span className="mini-label">{section.label}</span><h2>{section.title}</h2></div><p>{section.note}</p></header><div className="rows">{section.items.map((item, index) => <DataRow key={rowKey(item, index)} item={item} view={props.view} inspect={() => void props.inspect(item)}/>)}</div></section>)}</div> : <div className="rows">{items.map((item, index) => <DataRow key={rowKey(item, index)} item={item} view={props.view} inspect={() => void props.inspect(item)}/>)}</div>}</section><aside className="action-panel"><BoundaryCard/></aside></div>;
}

function CollectionView(props: ViewProps) {
  const items = extractItems(props.data, props.view); const searchable = ["memory", "sources", "docs", "intelligence", "common", "timeline"].includes(props.view);
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
    {items.length ? props.view === "context" ? (
      <ContextRows items={items} inspect={props.inspect}/>
    ) : (
      <div className="rows">{items.map((item, index) => <DataRow key={rowKey(item, index)} item={item} view={props.view} inspect={() => void props.inspect(item)}/>)}</div>
    ) : (
      <EmptyState view={props.view} subview={String(props.data.view ?? "")}/>
    )}
    <Pagination page={page} pages={pages} total={total} label={props.view} go={(next) => void props.load(collectionPagePath(props.view, next, props.query, String(props.data.view ?? "")))}/>
  </section><aside className="action-panel"><ActionComposer {...props}/></aside></div>;
}

function ContextRows({ items, inspect }: { items: JsonMap[]; inspect: (item: JsonMap) => Promise<void> }) {
  const packs = items.filter((item) => item.view_kind === "context-pack");
  const proposals = items.filter((item) => item.view_kind === "context-proposal");
  const records = items.filter((item) => item.view_kind === "context-record");
  return <div className="context-levels">
    {packs.length > 0 && <section className="context-level"><header><div><span className="mini-label">Level 1</span><h2>Context packs</h2></div><p>The four durable destinations compiled for your agents.</p></header><div className="pack-grid">{packs.map((item, index) => <ContextPackCard key={rowKey(item, index)} item={item} inspect={() => void inspect(item)}/>)}</div></section>}
    {proposals.length > 0 && <section className="context-level context-proposals"><header><div><span className="mini-label">Needs a decision</span><h2>Pending review</h2></div><p>Proposed changes stay inactive until you approve or reject them.</p></header><div className="rows">{proposals.map((item, index) => <DataRow key={rowKey(item, index)} item={item} view="context" inspect={() => void inspect(item)}/>)}</div></section>}
    {records.length > 0 && <section className="context-level context-records"><header><div><span className="mini-label">Level 2</span><h2>Approved statements</h2></div><p>Individual revisioned memories referenced by one or more packs.</p></header><div className="rows">{records.map((item, index) => <DataRow key={rowKey(item, index)} item={item} view="context" inspect={() => void inspect(item)}/>)}</div></section>}
  </div>;
}

function ContextPackCard({ item, inspect }: { item: JsonMap; inspect: () => void }) {
  const active = Number(item.records ?? 0); const pending = Number(item.pending ?? 0);
  const name = String(item.name ?? "Context pack");
  return <button className="pack-card" onClick={inspect}><div className="pack-card-top"><span className="pack-icon"><Archive size={15}/></span><ChevronRight size={15}/></div><h3>{name}</h3><p>{contextPackPurpose(name)}</p><div className="pack-stats"><span><strong>{active}</strong> approved</span><span className={pending ? "pending" : ""}><strong>{pending}</strong> pending</span></div><div className="pack-scope"><span>{humanise(String(item.audience_kind ?? "personal"))}</span><span>{humanise(String(item.applicability_kind ?? "global"))}</span></div></button>;
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
  if (props.view === "tree") return <div className="composer"><span className="mini-label">New curated file</span><h2>Create Markdown memory</h2><label>Tree path<input value={props.secondary} onChange={(event) => props.setSecondary(event.target.value)} placeholder="deployment/release.md"/></label><label>Complete Markdown<textarea value={props.composer} onChange={(event) => props.setComposer(event.target.value)} placeholder="# Release process&#10;&#10;Use Railway."/></label><button className="primary" disabled={!props.secondary.trim() || !props.composer.trim()} onClick={() => props.mutate("/api/v1/tree/file", { path: props.secondary, markdown: props.composer }, "Curated memory file created.")}><Plus size={15}/>Create file</button></div>;
  if (props.view === "docs") return <div className="composer"><span className="mini-label">Ingest documentation</span><h2>Add a reference source</h2><p>Use a public documentation URL or a local path. Progress appears under Maintenance.</p><label>URL or path<input value={props.composer} onChange={(event) => props.setComposer(event.target.value)} placeholder="https://docs.example.com"/></label><button className="primary" disabled={!props.composer.trim()} onClick={() => props.mutate("/api/v1/docs/ingest", { target: props.composer }, "Documentation ingestion queued.")}><Plus size={15}/>Start ingestion</button></div>;
  if (props.view === "audit") return <BoundaryCard/>;
  if (props.view === "intelligence") return <div className="composer"><span className="mini-label">Human authority</span><h2>Open a suggestion to decide</h2><p>Each result opens with both sides and its provenance. Nothing changes lifecycle state until you explicitly resolve it.</p></div>;
  return <BoundaryCard/>;
}

function Maintenance(props: ViewProps) {
  const jobs = extractItems(props.data, "maintenance"); const [page, setPage] = useState(1); const paged = clientPage(jobs, page);
  return <div className="workspace-grid"><section className="collection"><div className="tool-grid"><Tool icon={<RefreshCw/>} title="Refresh agent sources" command="Automatic when web or ask opens" text="Check source fingerprints and rebuild only when local agent files changed." action="Refresh now" onClick={() => props.mutate("/api/v1/maintenance", { action: "sync" }, "Agent sources refreshed.")}/><Tool icon={<Sparkles/>} title="Draft consolidation" command="Advanced local operation" text="Prepare a reviewable draft from indexed memory." action="Create draft" onClick={() => props.mutate("/api/v1/maintenance", { action: "consolidate", query: props.composer || null }, "Consolidation queued.")}/><Tool icon={<FileSearch/>} title="Run diagnostics" command="docmancer doctor" text="Inspect Python, index, docs, and project state." action="Run doctor" onClick={async () => { const result = await props.mutate("/api/v1/maintenance", { action: "doctor" }, "Diagnostics completed."); if (result) await props.inspect({ title: "Diagnostics result", ...result }); }}/></div><div className="collection-head"><span>Recent jobs</span><span>{jobs.length}</span></div><div className="rows">{paged.items.length ? paged.items.map((item, index) => <DataRow key={rowKey(item, index)} item={item} view="maintenance" inspect={() => void props.inspect(item)}/>) : <EmptyState view="maintenance"/>}</div><Pagination page={paged.page} pages={paged.pages} total={jobs.length} label="maintenance" go={setPage}/></section><aside className="action-panel"><div className="composer"><span className="mini-label">Consolidate or apply</span><h2>Turn memory into agent context</h2><p>Draft a focused consolidation, or apply the current reviewed memory to an installed agent.</p><label>Optional consolidation focus<textarea value={props.composer} onChange={(event) => props.setComposer(event.target.value)} placeholder="Focus on decisions from this project."/></label><button className="primary" onClick={() => props.mutate("/api/v1/maintenance", { action: "consolidate", query: props.composer || null }, "Consolidation queued.")}><Play size={14}/>Run consolidation</button><label>Apply to<select value={props.secondary || "codex"} onChange={(event) => props.setSecondary(event.target.value)}><option value="codex">Codex</option><option value="claude-code">Claude Code</option><option value="cursor">Cursor</option></select></label><button className="secondary" onClick={() => props.mutate("/api/v1/maintenance", { action: "apply", agent: props.secondary || "codex" }, "Context apply queued.")}><WandSparkles size={14}/>Apply managed context</button></div></aside></div>;
}

function SyncView(props: ViewProps) {
  const configured = Boolean(props.data.configured);
  const mapping = objectAt(props.data, "project_mapping");
  const mappingState = String(mapping.state || "unmapped");
  const recovery = objectAt(props.data, "recovery");
  const [recoveryKey, setRecoveryKey] = useState("");
  return <div className="split-grid">
    <Panel title="Connection" icon={<Cloud size={16}/>}>
      <div className={configured ? "state-banner connected" : "state-banner"}><span>{configured ? "CONNECTED" : "LOCAL ONLY"}</span><strong>{configured ? "Encrypted sync is configured" : "Nothing leaves this machine"}</strong><p>{configured ? `Workspace ${String(props.data.workspace_id ?? "")}` : "Connect from the CLI once, then run sync here."}</p></div>
      {configured ? <button className="primary" onClick={() => props.mutate("/api/v1/cloud/sync", {}, "Encrypted file revisions synced.")}><RefreshCw size={15}/>Push and pull</button> : <code className="command-line">docmancer cloud connect --base-url https://api.docmancer.dev</code>}
    </Panel>
    <Panel title="This project" icon={<KeyRound size={16}/>}>
      <div className={mappingState === "mapped" ? "state-banner connected" : "state-banner"}>
        <span>{mappingState.toUpperCase()}</span>
        <strong>{mappingState === "mapped" ? "Stable project mapping is ready" : mappingState === "ambiguous" ? "More than one checkout matches" : "No local checkout is mapped"}</strong>
        <p>{mappingState === "ambiguous" ? "Docmancer preserves incoming revisions as conflicts until you choose a checkout." : "Only a stable project ID and encrypted content travel. Absolute local paths remain on this device."}</p>
      </div>
      <ul className="check-list"><li>{Number(props.data.pending ?? 0)} encrypted revisions waiting to upload</li><li>{Number(props.data.conflicts ?? 0)} unresolved sync conflicts</li><li>Recovery keys and plaintext files never reach the service</li></ul>
      <div className="composer">
        <span className="mini-label">Recovery</span>
        <p>{recovery.verified ? "This recovery key has been verified on this device." : "Verify the offline recovery key before you need to restore another device."}</p>
        <label>Recovery key<input type="password" value={recoveryKey} onChange={(event) => setRecoveryKey(event.target.value)}/></label>
        <button className="secondary" disabled={!configured || !recoveryKey.trim()} onClick={() => props.mutate("/api/v1/cloud/recovery/verify", { recovery_key: recoveryKey }, "Recovery key verified.")}><KeyRound size={15}/>Verify recovery</button>
      </div>
    </Panel>
  </div>;
}

function DevicesView(props: ViewProps) {
  const devices = Array.isArray(props.data.items) ? props.data.items.filter(isObject) : [];
  const [page, setPage] = useState(1);
  const paged = clientPage(devices, page);
  if (props.data.available === false) return <CloudUnavailable surface="devices" state={String(props.data.state ?? "not_connected")} message={String(props.data.message ?? "Connect this machine before managing device trust.")}/>;
  return <div className="workspace-grid">
    <section className="collection">
      <div className="collection-head"><span>Registered devices</span><span>{devices.length}</span></div>
      <div className="rows">{paged.items.length ? paged.items.map((device, index) => {
        const id = String(device.device_id ?? device.id ?? "");
        const state = String(device.state ?? "unknown");
        return <div className="device-admin-row" key={rowKey(device, index)}>
          <DataRow item={device} view="devices" inspect={() => void props.inspect(device)}/>
          {state !== "revoked" && <button className="danger-link" onClick={() => {
            if (window.confirm("Revoke this device from future encrypted sync?")) {
              void props.mutate(`/api/v1/cloud/devices/${encodeURIComponent(id)}/revoke`, { confirmation: id }, "Device revoked.");
            }
          }}>Revoke</button>}
        </div>;
      }) : <EmptyState view="devices"/>}</div>
      <Pagination page={paged.page} pages={paged.pages} total={devices.length} label="devices" go={setPage}/>
    </section>
    <aside className="action-panel"><div className="composer"><span className="mini-label">Approve registration</span><h2>Verify a pending device</h2><p>Compare the fingerprint on both machines before approving access.</p><label>Device ID<input value={props.secondary} onChange={(event) => props.setSecondary(event.target.value)}/></label><label>Fingerprint<input value={props.composer} onChange={(event) => props.setComposer(event.target.value)}/></label><button className="primary" disabled={!props.secondary || !props.composer} onClick={() => props.mutate(`/api/v1/cloud/devices/${encodeURIComponent(props.secondary)}/approve`, { fingerprint: props.composer }, "Device approved.")}><Fingerprint size={15}/>Verify and approve</button></div></aside>
  </div>;
}

function TeamView(props: ViewProps) {
  const proposals = Array.isArray(props.data.proposals) ? props.data.proposals.filter(isObject) : [];
  const members = Array.isArray(props.data.members) ? props.data.members.filter(isObject) : [];
  const cloudAvailable = props.data.available !== false;
  const [teamFile, setTeamFile] = useState<JsonMap>(objectAt(props.data, "team_file"));
  const [domain, setDomain] = useState("standards");
  const [working, setWorking] = useState(false);
  const [localError, setLocalError] = useState("");
  const excluded = Array.isArray(teamFile.excluded) ? teamFile.excluded.filter(isObject) : [];
  const affectedAgents = Array.isArray(teamFile.affected_agents) ? teamFile.affected_agents.map(String) : [];

  const generate = async (publish: boolean) => {
    setWorking(true); setLocalError("");
    try {
      const result = await apiMutation("/api/v1/cloud/team/file", { domain, apply: publish, approved: publish });
      setTeamFile(result);
    } catch (reason) { setLocalError(messageOf(reason)); }
    finally { setWorking(false); }
  };
  const transition = async (outcome: string) => {
    setWorking(true); setLocalError("");
    try {
      const result = await apiMutation("/api/v1/cloud/team/file", { domain, outcome });
      setTeamFile({...teamFile, ...result});
    } catch (reason) { setLocalError(messageOf(reason)); }
    finally { setWorking(false); }
  };

  return <div className="team-layout">
    <section className="team-file-review">
      <div className="collection-head"><span>Generated Team file</span><span>{String(objectAt(teamFile, "approval").granularity || "complete-file")}</span></div>
      <div className="team-file-controls">
        <label>Shared standards domain<input value={domain} onChange={(event) => setDomain(event.target.value)} placeholder="standards"/></label>
        <button className="secondary" disabled={working || !domain.trim()} onClick={() => void generate(false)}><RefreshCw size={14}/>Regenerate preview</button>
      </div>
      {localError && <div className="alert error"><AlertTriangle size={15}/><span>{localError}</span></div>}
      <div className="privacy-grid">
        <span><strong>{Number(teamFile.selected_count ?? 0)}</strong> eligible files</span>
        <span><strong>{excluded.length}</strong> excluded files</span>
        <span><strong>Local</strong> privacy checks</span>
        <span><strong>{teamFile.published ? "Queued" : teamFile.applied ? "Approved" : "Preview"}</strong> state</span>
      </div>
      <p className="quiet-copy">New engineers receive this generated file through: {affectedAgents.length ? affectedAgents.join(", ") : "no installed agent projection detected yet"}.</p>
      <div className="team-diff">
        <span className="mini-label">Complete plaintext diff, local only</span>
        <pre>{String(teamFile.diff || "No eligible change from the current generated file.")}</pre>
      </div>
      <div className="team-exclusions">
        <h3>Exclusion report</h3>
        {excluded.length ? <ul>{excluded.map((item, index) => <li key={rowKey(item, index)}><strong>{String(item.title || "Untitled")}</strong><span>{String(item.reason || "Excluded by policy")}</span></li>)}</ul> : <p>No files were excluded.</p>}
      </div>
      <div className="whole-file-approval">
        <div><span className="mini-label">One decision</span><h3>Approve this complete file revision</h3><p>This encrypts the generated file locally and queues only ciphertext. There are no per-memory approval controls.</p></div>
        <button className="primary" disabled={working || !cloudAvailable || !String(teamFile.diff || "")} onClick={() => void generate(true)}><ShieldCheck size={15}/>Approve and queue</button>
      </div>
      {Boolean(teamFile.applied) && <div className="team-file-controls">
        <span className="mini-label">File publication outcome</span>
        <button className="secondary" disabled={working || !cloudAvailable} onClick={() => void transition("withdrawn")}>Withdraw</button>
        <button className="secondary" disabled={working || !cloudAvailable} onClick={() => void transition("superseded")}>Supersede</button>
        <button className="secondary" disabled={working || !cloudAvailable} onClick={() => void transition("blocked")}>Block</button>
        <button className="secondary" disabled={working || !cloudAvailable} onClick={() => void transition("restored")}>Restore</button>
      </div>}
      {!cloudAvailable && <div className="state-banner"><span>PREVIEW ONLY</span><strong>Cloud is not connected</strong><p>The complete local preview still works. Connect Cloud only when you are ready to publish encrypted Team files.</p></div>}
    </section>
    <aside className="action-panel">
      <div className="composer"><span className="mini-label">Team administration</span><h2>Invite a member</h2><p>Member and device administration stays hosted. Plaintext file review stays here.</p><label>Email<input type="email" value={props.composer} onChange={(event) => props.setComposer(event.target.value)} placeholder="person@example.com"/></label><label>Role<select value={props.secondary || "member"} onChange={(event) => props.setSecondary(event.target.value)}><option value="member">Member</option><option value="reviewer">Reviewer</option><option value="admin">Administrator</option></select></label><button className="primary" disabled={!cloudAvailable || !props.composer.trim()} onClick={() => props.mutate("/api/v1/cloud/team/invitations", { email: props.composer, role: props.secondary || "member" }, "Invitation created.")}><Users size={15}/>Invite</button><p>{members.length} members, {proposals.length} encrypted file records</p><a className="text-link" href="https://docmancer.dev/account" target="_blank" rel="noreferrer">Manage billing and seats ↗</a></div>
    </aside>
  </div>;
}

function CloudUnavailable({ surface, state, message }: { surface: "devices" | "team"; state: string; message: string }) { const unreachable = state === "unreachable"; const title = unreachable ? "Cloud is unavailable right now" : surface === "devices" ? "Connect Cloud to manage devices" : "Connect Cloud to open a team workspace"; const label = unreachable ? "SERVICE UNAVAILABLE" : state === "authentication" ? "SIGN IN REQUIRED" : state === "entitlement" ? "PLAN REQUIRED" : "NOT CONNECTED"; return <div className="split-grid cloud-unavailable"><Panel title={title} icon={<WifiOff size={16}/>}><div className="state-banner"><span>{label}</span><strong>Your local workspace is still fully available</strong><p>{message}</p></div>{unreachable ? <p className="quiet-copy">No local action is required. Try this page again when the hosted service is available.</p> : <code className="command-line">docmancer cloud connect --base-url https://api.docmancer.dev</code>}</Panel><Panel title="What remains local and free" icon={<ShieldCheck size={16}/>}><ul className="check-list"><li>Read, write, search, and compile curated Markdown</li><li>Harvest and curate evidence locally</li><li>Use the CLI, MCP server, and local web app</li><li>Audit sources and rebuild disposable indexes</li></ul><a className="text-link" href="https://docmancer.dev/account" target="_blank" rel="noreferrer">Create an account or manage billing ↗</a></Panel></div>; }

function HelpView() {
  const [section, setSection] = useState("start");
  const tabs = [["start", "Start here"], ["workflow", "Core workflow"], ["cloud", "Cloud and teams"], ["glossary", "Glossary"]];
  return <div className="help-layout"><nav className="help-tabs" aria-label="Help sections">{tabs.map(([key, label], index) => <button key={key} className={section === key ? "active" : ""} onClick={() => setSection(key)}><span>{String(index + 1).padStart(2, "0")}</span>{label}</button>)}</nav><section className="help-content">
    {section === "start" && <><div className="help-intro"><span className="mini-label">Your current workspace</span><h2>From scattered files to useful shared memory</h2><p>Opening the workbench refreshes changed agent sources automatically. Write durable Markdown here, or ask one question across curated memory and supporting evidence.</p></div><ol className="guide-steps"><GuideStep number="1" title="Ask what is already known" text="Recall project policy, curated memory, and supporting agent evidence in one result." command="docmancer ask &quot;why did we choose Railway?&quot;"/><GuideStep number="2" title="Write durable memory" text="Create a complete Markdown file in the Memory tree. The file remains readable outside Docmancer." command="docmancer write &quot;# Decision&#10;&#10;Use Railway.&quot; --path decisions/hosting.md"/><GuideStep number="3" title="Open files in your editor" text="Every Markdown file view includes an Open in menu for editors installed on this machine." command="docmancer web"/><GuideStep number="4" title="Import only when needed" text="Copy an arbitrary Markdown file or directory into the inbox for whole-file review." command="docmancer import ./notes"/></ol></>}
    {section === "workflow" && <div className="help-sections"><HelpSection title="Automatic source refresh" text="Setup discovers agent sources machine-wide. Opening the workbench or asking a question refreshes only when those sources changed." links={[["Ask Memory", "/ask/"], ["Open Inbox", "/inbox/"]]}/><HelpSection title="Write and recall" text="Complete Markdown files are durable memory. Ask uses the same bounded local recall contract as CLI and MCP." links={[["Open Memory tree", "/tree/"], ["Preview Agent Context", "/agent-context/"]]}/><HelpSection title="Maintain and audit" text="Audit locates masked risks. Recovery operations rebuild disposable local state without changing canonical files." links={[["Open Audit", "/audit/"], ["Run Maintenance", "/maintenance/"]]}/><HelpSection title="Keep Docs separate" text="Library and vendor documentation stays in the Docs surface so documentation results never masquerade as project memory." links={[["Open Docs", "/docs/"]]}/></div>}
    {section === "cloud" && <div className="help-sections"><HelpSection title="What is paid" text="Personal sync, device continuity, recovery, hosted revision history, team membership, and encrypted Team publication are paid services. The local product remains free."/><HelpSection title="What reaches the service" text="Approved devices exchange signed encrypted file envelopes and routing metadata. Plaintext memory, complete diffs, exclusion details, local file paths, private keys, workspace keys, and recovery keys stay local."/><HelpSection title="Connect a device" text="Create or sign in to an account, then connect this machine. Team-file previews remain available locally before Cloud is connected." links={[["Open Personal Sync", "/sync/"], ["Account and billing", "https://docmancer.dev/account"]]}/><HelpSection title="Team files" text="Docmancer selects eligible project memory, filters it locally, and generates one file per standards domain. When approval is enabled, one reviewer approves the complete file revision. No per-memory review queue exists." links={[["Open Team", "/team/"]]}/></div>}
    {section === "glossary" && <dl className="glossary"><GlossaryTerm term="Curated memory" text="One canonical Markdown file with stable identity, sources, revision lineage, and guarded writes."/><GlossaryTerm term="Source" text="An original agent-owned file indexed as read-only evidence."/><GlossaryTerm term="Inbox" text="Optional imported or captured Markdown awaiting whole-file review."/><GlossaryTerm term="Ask" text="The shared bounded recall operation used by CLI, MCP, hooks, and the workbench."/><GlossaryTerm term="Stable address" text="A docmancer://memory identifier that survives file moves and renames."/><GlossaryTerm term="Personal Sync" text="Optional paid encrypted transport and recovery between approved devices."/></dl>}
  </section></div>;
}

function GuideStep({ number, title, text, command }: { number: string; title: string; text: string; command?: string }) { return <li><span>{number}</span><div><h3>{title}</h3><p>{text}</p>{command && <code>{command}</code>}</div></li>; }
function HelpSection({ title, text, links = [] }: { title: string; text: string; links?: string[][] }) { return <article><h2>{title}</h2><p>{text}</p>{links.length > 0 && <div>{links.map(([label, href]) => <Link className="text-link" href={href} key={href}>{label}<ChevronRight size={13}/></Link>)}</div>}</article>; }
function GlossaryTerm({ term, text }: { term: string; text: string }) { return <div><dt>{term}</dt><dd>{text}</dd></div>; }

function BoundaryCard() { return <div className="composer boundary-card"><span className="mini-label">Security boundary</span><h2>Local means local</h2><ul className="check-list"><li>The browser talks only to this loopback process.</li><li>Write operations call narrow, allowlisted Python methods.</li><li>No arbitrary shell command is accepted from the browser.</li><li>Destructive changes require explicit local confirmation.</li></ul></div>; }
function Panel({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) { return <section className="panel"><header>{icon}<h2>{title}</h2></header>{children}</section>; }
function Tool({ icon, title, command, text, action, onClick }: { icon: React.ReactNode; title: string; command: string; text: string; action: string; onClick: () => void }) { return <article className="tool"><div className="tool-icon">{icon}</div><h3>{title}</h3><code>{command}</code><p>{text}</p><button onClick={onClick}>{action}</button></article>; }

function DataRow({ item, view, inspect }: { item: JsonMap; view: ViewKey; inspect: () => void }) {
  const normalized = normalizeItem(item, view); const title = rowTitle(normalized, view); const subtitle = rowSubtitle(normalized, view); const text = rowText(normalized, view); const kicker = rowKicker(normalized, view);
  const badges = rowBadges(normalized, view);
  return <article className={`data-row interactive-row ${view}-row`} onClick={inspect} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); inspect(); } }} role="button" tabIndex={0}>
    <div className="row-body">{kicker && <span className="row-kicker">{kicker}</span>}<div className="row-title-line"><h3>{truncate(title, 120)}</h3>{badges.map((badge) => <span className={`row-badge ${badge.tone}`} key={`${badge.label}:${badge.tone}`}>{badge.label}</span>)}</div>
      {text && text !== title && <p>{truncate(cleanMarkdown(text), view === "context" ? 180 : 220)}</p>}
      {subtitle && <span className="row-subtitle" title={fullRowSubtitle(normalized, view)}>{subtitle}</span>}
    </div>
    <button aria-label={`Open ${truncate(title, 60)}`} onClick={(event) => { event.stopPropagation(); inspect(); }}><ChevronRight size={15}/></button>
  </article>;
}

function EmptyState({ view, subview = "" }: { view: ViewKey; subview?: string }) {
  if (view === "intelligence" && subview === "review") return <div className="empty"><div><CircleCheck size={24}/></div><h3>No conflicts need your review</h3><p>Your memory graph has no unresolved contradiction suggestions. Use Recent activity to inspect what changed this week.</p></div>;
  if (view === "audit") return <div className="empty"><div><CircleCheck size={24}/></div><h3>No audit records</h3><p>No secret findings or hook configurations were returned by the local scan.</p></div>;
  return <div className="empty"><div><Archive size={24}/></div><h3>No {view} items yet</h3><p>Run the relevant local action or change the search to populate this view.</p></div>;
}
function Loading() { return <div className="loading"><LoaderCircle className="spin"/><span>Opening the local index</span></div>; }

function CommandPalette({ close, run }: { close: () => void; run: (command: string) => Promise<void> }) {
  const [filter, setFilter] = useState(""); const needle = filter.toLowerCase();
  const pages = NAV.filter((item) => item.label.toLowerCase().includes(needle));
  const commands = [{ key: "reindex", label: "Rebuild local index", cli: "docmancer reindex", icon: RefreshCw }, { key: "doctor", label: "Run diagnostics", cli: "docmancer status --check", icon: FileSearch }, { key: "cloudSync", label: "Run encrypted sync", cli: "docmancer cloud sync", icon: Cloud }].filter((item) => `${item.label} ${item.cli}`.toLowerCase().includes(needle));
  return <div className="palette-backdrop" onMouseDown={close}><div className="palette command-center" onMouseDown={(event) => event.stopPropagation()}><header><Command size={16}/><input autoFocus value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Search pages and safe local commands"/><kbd>ESC</kbd></header><div className="command-results">{commands.length > 0 && <section><p>Run locally</p>{commands.map(({ key, label, cli, icon: Icon }) => <button key={key} onClick={() => void run(key)}><Icon size={16}/><span><strong>{label}</strong><code>{cli}</code></span><b>Run</b></button>)}</section>}{pages.length > 0 && <section><p>Go to</p>{pages.map(({ key, label, icon: Icon }) => <Link key={key} href={key === "overview" ? "/" : `/${key}/`} onClick={close}><Icon size={16}/><span><strong>{label}</strong><small>Open page</small></span><ChevronRight size={14}/></Link>)}</section>}{!commands.length && !pages.length && <div className="command-empty">No matching page or command.</div>}</div></div></div>;
}

function extractItems(data: JsonMap, view: ViewKey): JsonMap[] {
  if ((view === "ask" || view === "agent-context") && Array.isArray(data.items)) return data.items.filter(isObject);
  if (Array.isArray(data.items)) return data.items.filter(isObject).map((item) => normalizeItem(item, view));
  if (view === "audit") { const report = objectAt(data, "report"); return [...(Array.isArray(report.findings) ? report.findings.filter(isObject) : []), ...(Array.isArray(data.hooks) ? data.hooks.filter(isObject) : [])]; }
  if (view === "team") return [...(Array.isArray(data.proposals) ? data.proposals.filter(isObject) : []), ...(Array.isArray(data.conflicts) ? data.conflicts.filter(isObject) : [])];
  return [];
}
function normalizeItem(item: JsonMap, view: ViewKey): JsonMap { if (view === "sources" && isObject(item.source)) return { ...item.source, matches: item.matches }; return item; }
function arrayObjects(value: unknown): JsonMap[] { return Array.isArray(value) ? value.filter(isObject) : []; }
function rowTitle(item: JsonMap, view: ViewKey): string {
  if (view === "common") return memoryPresentation(item).title;
  if (view === "delivery") return humanise(String(item.agent ?? "Agent"));
  if (view === "timeline") return `${humanise(String(item.operation ?? "change"))}: ${humaniseFilename(String(item.after_path ?? item.before_path ?? item.file_id ?? "memory file"))}`;
  if (view === "sources") { const title = String(item.title ?? ""); if (title && !isGenericSourceTitle(title)) return title; return humaniseFilename(String(item.path ?? "Source file")); }
  if (view === "context" && item.view_kind === "context-pack") return String(item.name ?? "Context pack");
  if (view === "context" && item.view_kind === "context-proposal") return `Review changes for ${String(item.context_name ?? humanise(String(item.pack_id ?? "context")))}`;
  if (view === "context" && item.view_kind === "context-record") return memoryPresentation(item).title;
  if (view === "docs") return String(item.title ?? item.source ?? item.text ?? "Documentation source");
  if (view === "maintenance") return String(item.title ?? item.kind ?? "Local job");
  if (view === "intelligence" && item.intelligence_kind === "recent-source") return intelligenceSourceTitle(item);
  if (view === "intelligence" && item.intelligence_kind === "conflict-group") return String(item.claim_subject ?? item.claim_key ?? "Conflicting memories");
  if (view === "intelligence") return String(item.text ?? item.source_text ?? item.target_text ?? humanise(String(item.intelligence_kind ?? "Intelligence item")));
  if (view === "audit" && item.view_kind === "secret-finding") return String(item.type ?? "Possible secret");
  if (view === "audit" && item.agent) return `${humanise(String(item.agent))} ${String(item.scope ?? "hook")}`;
  if (view === "memory") return memoryPresentation(item).title;
  return String(item.name ?? item.title ?? item.text ?? item.fingerprint ?? item.email ?? item.source ?? item.path ?? item.id ?? `${humanise(view)} record`);
}
function rowSubtitle(item: JsonMap, view: ViewKey): string {
  if (view === "common") return `${Number(item.harness_count ?? 0)} harnesses · ${Number(item.source_count ?? 0)} independent sources · ${scopeLabel(String(item.normalized_scope ?? "local"))}`;
  if (view === "delivery") return `${humanise(String(item.integration_mode ?? "unknown"))} · ${String(item.last_successful_recall ?? "No successful recall observed")}`;
  if (view === "timeline") return `${String(item.timestamp ?? "")} · ${String(item.actor_harness ?? item.actor_surface ?? "unknown")} · revision ${String(item.revision_id ?? "").slice(0, 12)}`;
  if (view === "sources") return `${String(item.kind ?? "source")} · ${String(item.harness ?? "local")} · ${Number(item.atom_count ?? 0)} atoms · ${compactPath(String(item.path ?? ""))}`;
  if (view === "context" && item.view_kind === "context-proposal") return `${Array.isArray(item.operations) ? item.operations.length : 0} proposed changes`;
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
function rowText(item: JsonMap, view: ViewKey): string { if (view === "sources" && Array.isArray(item.matches)) { const match = item.matches.find(isObject); const sample = match ? memoryPresentation(match).summary : ""; return sample || `${item.matches.length} matching atoms. Open to inspect excerpts and edit the full file.`; } if (view === "common") return String(item.text ?? ""); if (view === "delivery") return item.bundle_hash ? `Delivered bundle ${String(item.bundle_hash).slice(0, 16)} from tree revision ${String(item.tree_revision ?? "-")}; ${Number(item.item_count ?? 0)} items.` : "No successful context delivery has been observed for this agent in the active project."; if (view === "timeline") return String(item.diff ?? `${item.operation ?? "Changed"} ${item.after_path ?? item.before_path ?? "memory file"}`); if (view === "memory" || (view === "context" && item.view_kind === "context-record")) return memoryPresentation(item).summary; if (view === "context" && item.view_kind === "context-proposal") return memoryPresentation(item).summary; if (view === "context" && item.view_kind === "context-pack") return contextPackPurpose(String(item.name ?? "Context pack")); if (view === "audit" && item.view_kind === "secret-finding") return String(firstOccurrence(item)?.masked_excerpt ?? "Masked value"); if (view === "audit" && item.path) return item.exists ? `Recall ${item.recall ? "installed" : "not installed"}; capture ${item.capture ? "installed" : "not installed"}.` : "Configuration file not found."; if (view === "intelligence" && Array.isArray(item.samples)) return item.samples.filter(isObject).map((sample) => String(sample.text ?? "")).filter(Boolean).slice(0, 2).join(" · "); if (view === "intelligence" && Array.isArray(item.members)) return item.members.filter(isObject).map((member) => String(member.text ?? member.value ?? "")).filter(Boolean).slice(0, 2).join(" ↔ "); return String(item.text ?? item.rendered ?? item.detail ?? item.summary ?? ""); }
function rowKicker(item: JsonMap, view: ViewKey): string { if (view === "tree") return String(item.path ?? "Curated memory"); if (view === "inbox") return "Uncurated inbox"; if (view === "ask" || view === "agent-context") return String(item.authority ?? "advisory"); return ""; }
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
function commandLabel(command: string): string { return ({ reindex: "Tree reindex", sync: "Legacy memory sync", distill: "Legacy context proposal", doctor: "Diagnostics", consolidate: "Legacy consolidation", cloudSync: "Encrypted sync" } as Record<string, string>)[command] ?? command; }
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
function memoryTitle(item: JsonMap): string { return memoryPresentation(item).title; }
function intelligenceSourceTitle(item: JsonMap): string { const title = String(item.source_title ?? ""); if (title && !["promoted memory", "manual memory", "memory"].includes(title.toLowerCase())) return title; const sample = Array.isArray(item.samples) ? item.samples.find(isObject) : undefined; return sample ? memoryTitle(sample) : humaniseFilename(String(item.source_path ?? "Recent source")); }
function cleanMarkdown(value: string): string { return value.replace(/^#{1,6}\s+/gm, "").replace(/[*_`>#]/g, "").replace(/\[(.*?)\]\([^)]*\)/g, "$1").replace(/\s+/g, " ").trim(); }
function memoryPresentation(item: JsonMap): { title: string; summary: string } {
  const value = cleanMarkdown(String(item.text ?? item.title ?? "Memory atom"));
  const parts = value.split(/:\s+/).map((part) => part.trim()).filter(Boolean);
  const instructionIndex = parts.findIndex((part) => /agent instructions/i.test(part));
  let title = ""; let summary = value;
  if (instructionIndex >= 0) {
    const parent = parts[instructionIndex].replace(/^.*?agent instructions\s*/i, "").trim();
    const candidate = parts[instructionIndex + 1] ?? "";
    const useCandidate = candidate.length > 0 && candidate.length <= 58 && parts.length > instructionIndex + 2;
    title = useCandidate ? candidate : parent;
    summary = parts.slice(instructionIndex + (useCandidate ? 2 : 1)).join(": ");
  } else {
    const withoutBoilerplate = parts.filter((part) => !/^(what.?s in memory|promoted memory|manual memory|memory atom)$/i.test(part));
    const genericHeading = /^(user preferences?|user profile|what.?s in memory|older memory topics)$/i.test(withoutBoilerplate[0] ?? "") || /^what.?s in memory\b/i.test(withoutBoilerplate[0] ?? "");
    title = genericHeading && withoutBoilerplate[1] ? withoutBoilerplate[1] : withoutBoilerplate.length > 1 && withoutBoilerplate[0].length < 48 ? withoutBoilerplate[0] : value.split(/(?<=[.!?])\s+/)[0];
    summary = genericHeading ? withoutBoilerplate.slice(2).join(": ") || withoutBoilerplate[1] || value : withoutBoilerplate.length > 1 ? withoutBoilerplate.slice(1).join(": ") : value;
  }
  title = title.replace(/^(docmancer|claude|codex)\s*[-:]?\s*/i, "").trim() || humaniseFilename(String(item.source_path ?? "Memory atom"));
  if (summary === value && value.toLowerCase().startsWith(title.toLowerCase())) summary = value.slice(title.length).replace(/^:\s*/, "");
  return { title: truncate(title, 92), summary: truncate(summary || value, 260) };
}
function isGenericSourceTitle(value: string): boolean { return ["promoted memory", "manual memory", "memory", "memory atom", "docmancer memory"].includes(value.trim().toLowerCase()); }
function contextPackPurpose(value: string): string { const purposes: Record<string, string> = { "Personal defaults": "Your durable preferences and working rules across every project.", "Current project": "Project-specific decisions and exceptions for this working directory.", "Team standards": "Shared rules that apply across the team and all linked projects.", "Team project": "Shared decisions and exceptions for this linked project." }; return purposes[value] ?? "Approved context compiled for installed agents."; }
function fullRowSubtitle(item: JsonMap, view: ViewKey): string { if (view === "audit" && item.view_kind === "secret-finding") { const first = firstOccurrence(item); return `${String(first?.source_path ?? "")}:${String(first?.line ?? "?")}`; } return String(item.source_path ?? item.path ?? item.source ?? rowSubtitle(item, view)); }
function rowBadges(item: JsonMap, view: ViewKey): Array<{ label: string; tone: string }> {
  if (view === "common") return arrayObjects(item.sources).slice(0, 3).map((source) => ({ label: humanise(String(source.harness ?? "agent")), tone: "accent" }));
  if (view === "delivery") return [{ label: String(item.status ?? "not-observed") === "delivered" ? "Delivered" : "Not observed", tone: String(item.status ?? "") === "delivered" ? "success" : "warning" }, { label: String(item.hook_status ?? "not-installed") === "installed" ? "Hook on" : humanise(String(item.integration_mode ?? "manual")), tone: String(item.hook_status ?? "") === "installed" ? "success" : "neutral" }];
  if (view === "timeline") return [{ label: humanise(String(item.operation ?? "change")), tone: "accent" }, { label: humanise(String(item.actor_harness ?? item.actor_surface ?? "local")), tone: "neutral" }];
  if (view === "audit" && item.view_kind === "secret-finding") return [{ label: String(item.severity ?? "finding"), tone: `severity-${String(item.severity ?? "medium")}` }, { label: `${Number(item.occurrence_count ?? 1)} occurrence${Number(item.occurrence_count ?? 1) === 1 ? "" : "s"}`, tone: "neutral" }];
  if (view === "audit" && item.view_kind === "hook-status") return [{ label: item.recall ? "Recall on" : "Recall off", tone: item.recall ? "success" : "warning" }, { label: item.capture ? "Capture on" : "Capture off", tone: item.capture ? "success" : "neutral" }];
  if (view === "context" && item.view_kind === "context-proposal") return [{ label: "Proposal", tone: "neutral" }, { label: "Pending review", tone: "warning" }];
  if (view === "context") return [{ label: humanise(String(item.view_kind === "context-pack" ? item.audience_kind ?? "pack" : item.memory_type ?? "entry")), tone: "neutral" }, { label: humanise(String(item.applicability_kind ?? "context")), tone: "accent" }];
  if (view === "memory") { const metadata = objectAt(item, "metadata"); return [{ label: humanise(String(item.memory_type ?? metadata.memory_type ?? "memory")), tone: "neutral" }, { label: scopeLabel(String(item.scope ?? metadata.scope ?? "local")), tone: "accent" }]; }
  return [];
}
function scopeLabel(value: string): string { const lower = value.toLowerCase(); if (lower.startsWith("project")) return "Project"; if (lower.startsWith("global")) return "Global"; if (lower.startsWith("team")) return "Team"; if (lower.startsWith("personal")) return "Personal"; return humanise(value.split(":", 1)[0] || "Local"); }
