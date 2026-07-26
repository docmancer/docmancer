"use client";

import {
  ArrowRight, BrainCircuit, Check, ChevronRight, CircleHelp,
  Cloud, Command, Copy, Database, ExternalLink, Library, LoaderCircle, Moon,
  Search, Settings, ShieldCheck, Sparkles, Sun, X,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, ReactNode, useCallback, useEffect, useState } from "react";
import { apiGet, apiJobMutation, establishSession, type JsonMap } from "@/lib/api";
import { ContextWorkbench } from "./context-workbench";
import { LibraryView } from "./library-view";
import { AgentEditor, SettingsView, SetupFlow } from "./settings-view";

export type ViewKey =
  | "overview" | "context" | "library" | "settings" | "help"
  | "tree" | "ask" | "common" | "delivery" | "timeline" | "agent-context"
  | "inbox" | "memory" | "sources" | "intelligence" | "docs" | "audit"
  | "maintenance" | "sync" | "devices" | "team";

type CanonicalView = "home" | "context" | "library" | "settings" | "help";

const PRIMARY = [
  { key: "home", label: "Home", href: "/", icon: Sparkles },
  { key: "context", label: "Context", href: "/context/", icon: BrainCircuit },
  { key: "library", label: "Library", href: "/library/", icon: Library },
] as const;

function canonical(view: ViewKey): CanonicalView {
  if (["context", "common", "delivery", "timeline", "intelligence"].includes(view)) return "context";
  if (["library", "tree", "inbox", "memory", "sources", "docs"].includes(view)) return "library";
  if (["settings", "audit", "maintenance", "sync", "devices", "team"].includes(view)) return "settings";
  if (view === "help") return "help";
  return "home";
}

export function WorkspaceApp({ initialView }: { initialView: ViewKey }) {
  const view = canonical(initialView);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [dark, setDark] = useState(() => typeof window !== "undefined" && (
    window.localStorage.getItem("docmancer-theme") === "dark"
    || (!window.localStorage.getItem("docmancer-theme") && window.matchMedia("(prefers-color-scheme: dark)").matches)
  ));

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);
  useEffect(() => {
    establishSession().then(() => setReady(true)).catch((reason) => setError(messageOf(reason)));
  }, []);

  const toggleTheme = () => {
    const next = !dark;
    setDark(next);
    window.localStorage.setItem("docmancer-theme", next ? "dark" : "light");
    document.documentElement.classList.toggle("dark", next);
  };

  return <div className="app-shell">
    <aside className="sidebar">
      <Link className="wordmark" href="/">
        <span className="wordmark-orb"><Sparkles size={17}/></span>
        <span>docmancer</span>
        <small>local</small>
      </Link>
      <nav className="primary-nav" aria-label="Primary">
        {PRIMARY.map(({ key, label, href, icon: Icon }) =>
          <Link key={key} href={href} className={view === key ? "nav-link active" : "nav-link"}>
            <Icon size={17}/><span>{label}</span>
          </Link>
        )}
      </nav>
      <div className="sidebar-lower">
      <SidebarCloudCard active={ready}/>
      <div className="sidebar-note">
        <ShieldCheck size={15}/>
        <div><strong>Private by default</strong><span>Everything here runs on 127.0.0.1.</span></div>
      </div>
      </div>
      <div className="secondary-nav">
        <Link href="/settings/" className={view === "settings" ? "nav-link active" : "nav-link"}><Settings size={17}/>Settings</Link>
        <Link href="/help/" className={view === "help" ? "nav-link active" : "nav-link"}><CircleHelp size={17}/>Help</Link>
      </div>
    </aside>
    <main className="main-stage">
      <header className="app-bar">
        <div className="page-path"><span>Docmancer</span><ChevronRight size={14}/><strong>{titleFor(view)}</strong></div>
        <div className="app-actions">
          <span className="local-chip"><span/>Local session</span>
          <button className="icon-btn" onClick={toggleTheme} aria-label="Toggle theme">
            {dark ? <Sun size={16}/> : <Moon size={16}/>}
          </button>
        </div>
      </header>
      {error && <Notice kind="error" onClose={() => setError("")}>{error}</Notice>}
      {!ready && !error ? <Loading label="Opening your local memory"/> : <Page view={view}/>}
    </main>
  </div>;
}

function SidebarCloudCard({ active }: { active: boolean }) {
  const [cloud, setCloud] = useState<JsonMap>({});
  useEffect(() => {
    if (active) void apiGet("/api/v1/cloud").then(setCloud).catch(() => setCloud({}));
  }, [active]);
  return <a className="sidebar-cloud" href={cloud.configured ? "/settings/?section=cloud" : "https://docmancer.dev/cloud"} target={cloud.configured ? undefined : "_blank"} rel="noreferrer">
    <Cloud size={15}/><div><strong>{cloud.configured ? "Personal Sync connected" : "Keep Context in sync"}</strong><span>{cloud.configured ? "Manage devices and encrypted sync." : "Encrypted continuity across devices."}</span></div><ArrowRight size={13}/>
  </a>;
}

function Page({ view }: { view: CanonicalView }) {
  if (view === "home") return <HomeView/>;
  if (view === "context") return <ContextPage/>;
  if (view === "library") return <LibraryView/>;
  if (view === "settings") return <SettingsView/>;
  return <HelpView/>;
}

function HomeView() {
  const [status, setStatus] = useState<JsonMap>({});
  const [context, setContext] = useState<JsonMap>({});
  const [setup, setSetup] = useState<JsonMap>({});
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [evidence, setEvidence] = useState<JsonMap[]>([]);
  const [busy, setBusy] = useState("");
  const [modal, setModal] = useState<"agent" | "setup" | "">("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [statusData, contextData, setupData] = await Promise.all([
        apiGet("/api/v1/status"), apiGet("/api/v1/context"), apiGet("/api/v1/agent/setup"),
      ]);
      setStatus(statusData); setContext(contextData); setSetup(setupData);
    } catch (reason) { setError(messageOf(reason)); }
  }, []);
  useEffect(() => { queueMicrotask(() => void load()); }, [load]);

  const ask = async (event: FormEvent) => {
    event.preventDefault();
    if (!question.trim()) return;
    setBusy("ask"); setAnswer(""); setEvidence([]); setError("");
    try {
      const result = await apiJobMutation("/api/v1/ask", { task: question.trim(), mode: "normal" }, (delta) => setAnswer((value) => value + delta));
      setAnswer((value) => value || String(result.answer ?? result.text ?? ""));
      setEvidence(rows(result.evidence ?? result.items));
    } catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(""); }
  };

  const counts = objectAt(status, "counts");
  const integrations = rows(setup.items);
  const connected = integrations.filter((item) => item.integration_state === "connected");
  const automatic = integrations.filter((item) => item.detected && item.action_kind === "automatic");
  const manual = integrations.filter((item) => item.action_kind === "manual");
  const contextAvailable = Boolean(context.available);
  const indexed = Number(counts.atoms ?? 0) > 0;

  return <div className="page home-page">
    <section className="home-hero">
      <div className="agent-presence">
        <div className="agent-avatar"><Sparkles size={28}/></div>
        <div><span className="eyebrow">Your private memory agent</span><h1>What do your agents know?</h1><p>Ask Docmancer across the memory, instructions, and decisions your coding agents have already written.</p></div>
      </div>
      <form className="ask-box" onSubmit={ask}>
        <Search size={20}/>
        <textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask Docmancer about your projects, preferences, or past decisions..." rows={1}/>
        <button className="primary-btn" disabled={busy === "ask" || !question.trim()}>
          {busy === "ask" ? <LoaderCircle className="spin" size={16}/> : <ArrowRight size={16}/>}Ask
        </button>
      </form>
      {error && <Notice kind="error" onClose={() => setError("")}>{error}</Notice>}
      {(answer || busy === "ask") && <article className="answer-card">
        <div className="answer-head"><span><BrainCircuit size={16}/>Docmancer</span><small>{evidence.length ? `${evidence.length} sources` : "Searching local memory"}</small></div>
        <div className="answer-copy">{answer || <span className="thinking">Reading what your agents know...</span>}</div>
        {evidence.length > 0 && <div className="evidence-strip">{evidence.slice(0, 5).map((item, index) =>
          <span key={index}>{String(item.title ?? item.source_path ?? item.address ?? `Source ${index + 1}`)}</span>
        )}</div>}
      </article>}
    </section>

    <section className="home-grid">
      <article className="feature-card agent-card">
        <div className="feature-icon plum"><Sparkles size={19}/></div>
        <span className="eyebrow">One agent, your rules</span>
        <h2>Meet Docmancer</h2>
        <p>Shape how Docmancer answers, how detailed it should be, and which model it uses. Privacy and attribution safeguards stay fixed.</p>
        <button className="text-btn" onClick={() => setModal("agent")}>Customize Docmancer <ArrowRight size={14}/></button>
      </article>
      <article className="feature-card connect-card">
        <div className="feature-icon mint"><Command size={19}/></div>
        <span className="eyebrow">Make memory portable</span>
        <h2>Connect every coding agent</h2>
        <p>Install Docmancer skills and recall hooks so Claude Code, Codex, Cursor, and your other agents can use the same memory.</p>
        <div className="agent-pills">{connected.slice(0, 5).map((item) => <span key={String(item.id)}><Check size={12}/>{String(item.label)}</span>)}</div>
        {automatic.length > 0 && <p className="connection-prompt">{automatic.length} agent{automatic.length === 1 ? " is" : "s are"} ready to connect.</p>}
        {!automatic.length && manual.length > 0 && <p className="connection-prompt">{String(manual[0].label)} needs one manual setup step.</p>}
        {!automatic.length && !manual.length && connected.length > 0 && <p className="connection-complete">All detected agents are connected.</p>}
        <button className="primary-btn wide" onClick={() => setModal("setup")}>{automatic.length ? "Connect Docmancer to my agents" : manual.length ? `Finish ${String(manual[0].label)} setup` : "Manage agent connections"} <ArrowRight size={15}/></button>
      </article>
      <Link href="/context/" className="feature-card status-card">
        <div className="feature-icon blue"><Database size={19}/></div>
        <span className="eyebrow">Shared context</span>
        <h2>{contextAvailable ? "Your Context is ready" : indexed ? "Turn memory into Context" : "Start with your existing memory"}</h2>
        <p>{contextAvailable ? "Inspect the knowledge every connected agent can carry." : indexed ? "Preview and build a consolidated, revisioned Context." : "Run setup to discover and index what your agents already wrote."}</p>
        <div className="status-line"><span className={contextAvailable ? "status-dot good" : "status-dot"}/><strong>{Number(counts.atoms ?? 0).toLocaleString()}</strong> indexed memory atoms</div>
        <span className="text-btn">{contextAvailable ? "Open Context" : "Get started"} <ArrowRight size={14}/></span>
      </Link>
    </section>
    <section className="cloud-promo-strip">
      <div className="cloud-promo-intro"><span className="eyebrow">Optional Docmancer Cloud</span><h2>Local intelligence is free. Continuity is paid.</h2><p>Keep encrypted Context current across devices or coordinate one approved Team file without uploading plaintext memory.</p></div>
      <a href="https://docmancer.dev/cloud" target="_blank" rel="noreferrer"><Cloud size={17}/><span><strong>Personal Sync</strong><small>Encrypted history, devices, and recovery</small></span><ArrowRight size={14}/></a>
      <a href="https://docmancer.dev/teams" target="_blank" rel="noreferrer"><ShieldCheck size={17}/><span><strong>Team</strong><small>Locally approved, encrypted coordination</small></span><ExternalLink size={14}/></a>
    </section>
    {modal === "agent" && <Modal title="Customize Docmancer" subtitle="This is the one agent humans interact with in the web UI." close={() => setModal("")}><AgentEditor onSaved={() => { setModal(""); void load(); }}/></Modal>}
    {modal === "setup" && <Modal title="Connect Docmancer" subtitle="Index local memory, install skills, and optionally add recall hooks." close={() => setModal("")}><SetupFlow initial={setup} onComplete={() => { setModal(""); void load(); }}/></Modal>}
  </div>;
}

function ContextPage() {
  const [data, setData] = useState<JsonMap>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [contextData, statusData] = await Promise.all([apiGet("/api/v1/context"), apiGet("/api/v1/status")]);
      setData({ ...contextData, counts: statusData.counts });
      setError("");
    }
    catch (reason) { setError(messageOf(reason)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { queueMicrotask(() => void load()); }, [load]);
  return <div className="page">
    <PageHeading eyebrow="Portable agent memory" title="Context every agent can carry" description="See the useful knowledge Docmancer has consolidated, where it came from, and whether your agents can receive it."/>
    {error && <Notice kind="error">{error}</Notice>}
    {loading ? <Loading label="Loading Context"/> : <ContextWorkbench data={data} reload={load} inspect={() => Promise.resolve()}/>}
  </div>;
}

function HelpView() {
  const commands = [
    ["Start everything", "docmancer setup", "Index existing memory and install detected agent integrations."],
    ["Preview Context", "docmancer context refresh --dry-run", "See what will be consolidated without writing files."],
    ["Build Context", "docmancer context refresh", "Create the revisioned Context all connected agents can carry."],
    ["Ask from a terminal", 'docmancer ask "What do my agents know about deployment?"', "Use the same memory from the CLI."],
  ];
  return <div className="page">
    <PageHeading eyebrow="A short guide" title="Use the web UI. Let agents use the CLI." description="Docmancer gives you a human place to understand memory, while coding agents use skills, hooks, CLI, and MCP behind the scenes."/>
    <div className="help-grid">
      <section className="feature-card help-intro"><BrainCircuit size={25}/><h2>The basic loop</h2><ol><li>Connect your coding agents.</li><li>Index what they already know.</li><li>Ask Docmancer and inspect shared Context.</li><li>Keep working. Connected agents recall it automatically.</li></ol></section>
      <section className="command-list">{commands.map(([title, command, note]) => <CommandRow key={command} title={title} command={command} note={note}/>)}</section>
    </div>
  </div>;
}

export function PageHeading({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  return <header className="page-heading"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{action}</header>;
}

export function Modal({ title, subtitle, close, children }: { title: string; subtitle?: string; close: () => void; children: ReactNode }) {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };
    window.addEventListener("keydown", handler); return () => window.removeEventListener("keydown", handler);
  }, [close]);
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}>
    <section className="modal" role="dialog" aria-modal="true" aria-label={title}>
      <header><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div><button className="icon-btn" onClick={close}><X size={18}/></button></header>
      <div className="modal-body">{children}</div>
    </section>
  </div>;
}

export function Notice({ kind = "success", onClose, children }: { kind?: "success" | "error"; onClose?: () => void; children: ReactNode }) {
  return <div className={`notice ${kind}`}><span>{kind === "success" ? <Check size={15}/> : <X size={15}/>}</span><p>{children}</p>{onClose && <button onClick={onClose}>Dismiss</button>}</div>;
}

export function Loading({ label }: { label: string }) {
  return <div className="loading-state"><LoaderCircle className="spin" size={20}/><span>{label}</span></div>;
}

export function CommandRow({ title, command, note }: { title: string; command: string; note: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => { await navigator.clipboard.writeText(command); setCopied(true); window.setTimeout(() => setCopied(false), 1400); };
  return <article className="command-row"><div><strong>{title}</strong><code>{command}</code><p>{note}</p></div><button className="icon-btn" onClick={copy} aria-label={`Copy ${command}`}>{copied ? <Check size={15}/> : <Copy size={15}/>}</button></article>;
}

export function rows(value: unknown): JsonMap[] {
  return Array.isArray(value) ? value.filter((item): item is JsonMap => Boolean(item) && typeof item === "object") : [];
}
export function objectAt(value: JsonMap, key: string): JsonMap {
  const item = value[key]; return item && typeof item === "object" && !Array.isArray(item) ? item as JsonMap : {};
}
export function messageOf(reason: unknown): string { return reason instanceof Error ? reason.message : String(reason); }
function titleFor(view: CanonicalView) { return ({ home: "Home", context: "Context", library: "Library", settings: "Settings", help: "Help" } as const)[view]; }
