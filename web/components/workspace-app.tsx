"use client";

import {
  ArrowRight, BookOpen, BrainCircuit, Check, ChevronDown, ChevronRight, CircleHelp,
  Cloud, Command, Copy, History, Library, LoaderCircle, Moon,
  PanelLeftClose, PanelLeftOpen, Plus, Settings, ShieldCheck,
  Sparkles, Sun, Trash2, X,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiJobMutation, apiMutation, establishSession, type JsonMap } from "@/lib/api";
import { ContextWorkbench } from "./context-workbench";
import { LibraryView } from "./library-view";
import { MarkdownContent } from "./markdown-content";
import { AgentEditor, SettingsView, SetupFlow } from "./settings-view";
import { WizardLogo } from "./wizard-logo";

export type ViewKey =
  | "overview" | "context" | "library" | "settings" | "help"
  | "tree" | "ask" | "common" | "delivery" | "timeline" | "agent-context"
  | "inbox" | "memory" | "sources" | "intelligence" | "docs" | "audit"
  | "maintenance" | "sync" | "devices" | "team";

type CanonicalView = "home" | "context" | "library" | "settings" | "help";
type ChatTurn = {
  id: string;
  role: "user" | "assistant";
  content: string;
  evidence?: JsonMap[];
  pending?: boolean;
};

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
        <span className="wordmark-orb"><WizardLogo/></span>
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
    {ready && <BackgroundJobs/>}
  </div>;
}

function BackgroundJobs() {
  const [jobs, setJobs] = useState<JsonMap[]>([]);

  const load = useCallback(async () => {
    const data = await apiGet("/api/v1/jobs");
    const now = Date.now();
    setJobs(rows(data.items).filter((job) => {
      if (job.state === "queued" || job.state === "running") return true;
      const finished = new Date(String(job.finished_at ?? "")).getTime();
      const visibleFor = job.kind === "memory.ask" ? 5_000 : 15_000;
      return Number.isFinite(finished) && now - finished < visibleFor;
    }));
  }, []);

  useEffect(() => {
    let timer = 0;
    const refresh = () => void load().catch(() => undefined);
    const started = () => {
      refresh();
      window.clearInterval(timer);
      timer = window.setInterval(refresh, 1200);
    };
    refresh();
    timer = window.setInterval(refresh, 3000);
    window.addEventListener("docmancer:job-started", started);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("docmancer:job-started", started);
    };
  }, [load]);

  if (!jobs.length) return null;
  const job = jobs[0];
  const labels: Record<string, string> = {
    "context.refresh": "Building your Context",
    "memory.ask": "Answering with your memory",
    "agent.setup": "Connecting coding agents",
    "memory.sync": "Indexing agent memory",
    "memory.consolidate": "Consolidating memory",
    "memory.apply": "Applying memory changes",
    "docs.ingest": "Indexing documentation",
    "cloud.sync": "Syncing encrypted Context",
  };
  const label = labels[String(job.kind ?? "")] ?? "Docmancer is working";
  const completed = job.state === "completed";
  const failed = job.state === "failed";
  const detail = failed
    ? String(job.error ?? "The background task failed.")
    : completed
      ? String(job.kind) === "context.refresh"
        ? "Context is ready. Open the Context page to review it."
        : String(job.kind) === "memory.ask"
          ? "The answer is saved in this conversation."
        : "The background task completed."
      : "Running in the background. You can keep using Docmancer.";
  const title = completed && String(job.kind) === "memory.ask"
    ? "Answer ready"
    : completed
      ? `${label} complete`
      : failed
        ? `${label} failed`
        : label;
  return <aside className="background-jobs" aria-live="polite">
    <span className="job-pulse">{completed ? <Check size={15}/> : failed ? <X size={15}/> : <LoaderCircle className="spin" size={15}/>}</span>
    <div><strong>{title}</strong><span>{detail}</span></div>
    {jobs.length > 1 && <small>+{jobs.length - 1}</small>}
  </aside>;
}

function SidebarCloudCard({ active }: { active: boolean }) {
  const [cloud, setCloud] = useState<JsonMap>({});
  useEffect(() => {
    if (active) void apiGet("/api/v1/cloud").then(setCloud).catch(() => setCloud({}));
  }, [active]);
  return <a className="sidebar-cloud" href="/settings/?section=cloud">
    <Cloud size={15}/><div><strong>{cloud.configured ? "Personal Sync connected" : "Keep Context in sync"}</strong><span>{cloud.configured ? "Manage devices and encrypted sync." : "Connect this device to start."}</span></div><ArrowRight size={13}/>
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
  const [setup, setSetup] = useState<JsonMap>({});
  const [conversations, setConversations] = useState<JsonMap[]>([]);
  const [activeConversation, setActiveConversation] = useState("");
  const [temporary, setTemporary] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatTurn[]>([]);
  const [busy, setBusy] = useState("");
  const [modal, setModal] = useState<"agent" | "setup" | "">("");
  const [error, setError] = useState("");
  const chatThreadRef = useRef<HTMLDivElement>(null);
  const chatScrollRef = useRef<"top" | "bottom">("top");
  const chatTurnId = useRef(0);

  const refreshConversations = useCallback(async () => {
    const data = await apiGet("/api/v1/ask/conversations?limit=60");
    setConversations(rows(data.items));
  }, []);
  const load = useCallback(async () => {
    try {
      const [setupData, conversationData] = await Promise.all([
        apiGet("/api/v1/agent/setup"),
        apiGet("/api/v1/ask/conversations?limit=60"),
      ]);
      setSetup(setupData);
      setConversations(rows(conversationData.items));
    } catch (reason) { setError(messageOf(reason)); }
  }, []);
  useEffect(() => { queueMicrotask(() => void load()); }, [load]);
  useEffect(() => {
    const thread = chatThreadRef.current;
    if (!thread) return;
    thread.scrollTop = chatScrollRef.current === "top" ? 0 : thread.scrollHeight;
    chatScrollRef.current = "bottom";
  }, [messages]);
  useEffect(() => {
    if (!activeConversation || busy || !messages.some((message) => message.pending)) return;
    const timer = window.setInterval(() => {
      void apiGet(`/api/v1/ask/conversations/${encodeURIComponent(activeConversation)}`)
        .then((conversation) => {
          const turns = conversationTurns(conversation);
          setMessages(turns);
          if (!turns.some((turn) => turn.pending)) void refreshConversations();
        })
        .catch(() => undefined);
    }, 1200);
    return () => window.clearInterval(timer);
  }, [activeConversation, busy, messages, refreshConversations]);

  const newChat = (isTemporary = false) => {
    chatScrollRef.current = "top";
    setActiveConversation("");
    setTemporary(isTemporary);
    setMessages([]);
    setQuestion("");
    setError("");
    setHistoryOpen(false);
  };

  const openConversation = async (conversationId: string) => {
    if (busy) return;
    setError("");
    try {
      const conversation = await apiGet(
        `/api/v1/ask/conversations/${encodeURIComponent(conversationId)}`,
      );
      chatScrollRef.current = "top";
      setActiveConversation(conversationId);
      setTemporary(false);
      setMessages(conversationTurns(conversation));
      setHistoryOpen(false);
    } catch (reason) {
      setError(messageOf(reason));
    }
  };
  const deleteConversation = async (conversationId: string) => {
    if (busy) return;
    try {
      await apiMutation(
        `/api/v1/ask/conversations/${encodeURIComponent(conversationId)}`,
        {},
        "DELETE",
      );
      if (activeConversation === conversationId) newChat();
      await refreshConversations();
    } catch (reason) {
      setError(messageOf(reason));
    }
  };

  const askQuestion = async (prompt: string) => {
    const text = prompt.trim();
    if (!text || busy === "ask") return;
    let conversationId = activeConversation;
    if (!temporary && !conversationId) {
      try {
        const created = await apiMutation("/api/v1/ask/conversations", {});
        conversationId = String(created.id ?? "");
        if (!conversationId) throw new Error("Docmancer could not create the conversation.");
        setActiveConversation(conversationId);
      } catch (reason) {
        setError(messageOf(reason));
        return;
      }
    }
    chatTurnId.current += 1;
    chatScrollRef.current = "bottom";
    const turnId = `${chatTurnId.current}`;
    const assistantId = `assistant-${turnId}`;
    setBusy("ask"); setQuestion(""); setError("");
    setMessages((current) => [
      ...current,
      { id: `user-${turnId}`, role: "user", content: text },
      { id: assistantId, role: "assistant", content: "", pending: true },
    ]);
    try {
      const result = await apiJobMutation("/api/v1/ask", {
        task: text,
        mode: "normal",
        conversation_id: conversationId || undefined,
        temporary,
      }, (delta) => {
        setMessages((current) => current.map((turn) =>
          turn.id === assistantId ? { ...turn, content: turn.content + delta } : turn
        ));
      });
      setMessages((current) => current.map((turn) => turn.id === assistantId ? {
        ...turn,
        content: turn.content || answerContent(result),
        evidence: rows(result.evidence ?? result.items ?? result.relevant_evidence),
        pending: false,
      } : turn));
      if (!temporary) await refreshConversations();
    } catch (reason) {
      setError(messageOf(reason));
      setMessages((current) => current.map((turn) =>
        turn.id === assistantId ? { ...turn, content: "I could not complete that search. Try again after checking the message below.", pending: false } : turn
      ));
    }
    finally { setBusy(""); }
  };
  const ask = (event: FormEvent) => {
    event.preventDefault();
    void askQuestion(question);
  };

  const integrations = rows(setup.items);
  const connected = integrations.filter((item) => item.integration_state === "connected" && !item.recall_setup_required);
  const installed = integrations.filter((item) => Boolean(item.connected));
  const updates = integrations.filter((item) => item.action_kind === "automatic" && item.integration_state === "stale");
  const repairs = integrations.filter((item) => item.action_kind === "automatic" && item.integration_state === "partial");
  const automatic = integrations.filter((item) => item.action_kind === "automatic" && item.integration_state === "ready-to-connect");
  const recallSetup = integrations.filter((item) => item.action_kind === "automatic" && item.integration_state === "connected" && item.recall_setup_required);
  const manual = integrations.filter((item) => item.action_kind === "manual");
  const attentionCount = automatic.length + recallSetup.length + updates.length + repairs.length + manual.length;
  const activeTitle = temporary
    ? "Temporary chat"
    : String(conversations.find((item) => item.id === activeConversation)?.title ?? "Ask Docmancer");
  const connectionStatus = automatic.length
    ? `${automatic.length} ready to connect`
    : recallSetup.length
      ? `${recallSetup.length} need automatic recall`
      : updates.length
        ? `${updates.length} update${updates.length === 1 ? "" : "s"} available`
        : repairs.length
          ? `${repairs.length} need repair`
          : manual.length
            ? `${String(manual[0].label)} needs a manual step`
            : connected.length
              ? "All detected agents are ready"
              : "No agent integrations detected";
  const connectionAction = automatic.length
    ? "Connect agents"
    : recallSetup.length
      ? "Finish recall setup"
      : updates.length
        ? "Update integrations"
        : repairs.length
          ? "Repair integrations"
          : manual.length
            ? `Finish ${String(manual[0].label)} setup`
            : "Manage connections";
  const suggestions = [
    "What decisions have my agents made about this project?",
    "What working preferences recur across my agents?",
    "What do my agents know about deployment?",
  ];

  return <div className="page home-page">
    <section className="home-workspace">
      <article className="home-chat">
        <aside className={`chat-history ${historyOpen ? "open" : ""}`} aria-label="Ask history">
          <div className="chat-history-head">
            <span><History size={14}/>Conversations</span>
            <button onClick={() => newChat()} aria-label="Start a new conversation"><Plus size={15}/></button>
          </div>
          <div className="chat-history-list">
            {!conversations.length && <div className="chat-history-empty">
              <span><History size={17}/></span>
              <p>Your saved conversations will appear here.</p>
            </div>}
            {conversations.map((conversation) => <div
              className={activeConversation === conversation.id ? "chat-history-row active" : "chat-history-row"}
              key={String(conversation.id)}
            >
              <button className="chat-history-open" onClick={() => void openConversation(String(conversation.id))}>
                <strong>{String(conversation.title ?? "New conversation")}</strong>
                <small>{compactDate(conversation.updated_at)}</small>
              </button>
              <button
                className="chat-history-delete"
                onClick={() => void deleteConversation(String(conversation.id))}
                aria-label={`Delete ${String(conversation.title ?? "conversation")}`}
              ><Trash2 size={13}/></button>
            </div>)}
          </div>
          <button className={temporary ? "temporary-chat active" : "temporary-chat"} onClick={() => newChat(true)}>
            <ShieldCheck size={14}/>
            <span><strong>Temporary chat</strong><small>Nothing is saved</small></span>
          </button>
          <button className="chat-history-close" onClick={() => setHistoryOpen(false)}>
            <PanelLeftClose size={15}/>Close history
          </button>
        </aside>
        {historyOpen && <button className="chat-history-scrim" aria-label="Close conversation history" onClick={() => setHistoryOpen(false)}/>}
        <section className="chat-main">
        <header className="chat-header">
          <button className="history-toggle" onClick={() => setHistoryOpen(true)} aria-label="Open conversation history">
            <PanelLeftOpen size={17}/>
          </button>
          <div className="agent-avatar small"><WizardLogo/></div>
          <div className="chat-header-copy">
            <span className="eyebrow">Your private memory agent</span>
            <h1>Ask Docmancer</h1>
            <p><span>{temporary ? "Temporary chat" : activeConversation ? "Current conversation" : "New conversation"}</span>{activeConversation || temporary ? activeTitle : "What do your agents know?"}</p>
          </div>
          {(messages.length > 0 || activeConversation || temporary) && <button className="secondary-btn chat-reset" onClick={() => newChat()}><Plus size={14}/>New chat</button>}
        </header>
        <div ref={chatThreadRef} className={messages.length ? "chat-thread" : "chat-thread empty"}>
          {!messages.length && <div className="chat-welcome">
            <div className="chat-welcome-mark"><WizardLogo/></div>
            <h2>What do your agents know?</h2>
            <p>Ask across their memory, instructions, decisions, and project notes. Docmancer keeps the source evidence attached.</p>
            <div className="chat-suggestions">{suggestions.map((suggestion) =>
              <button key={suggestion} onClick={() => void askQuestion(suggestion)}><Sparkles size={14}/><span>{suggestion}</span><ArrowRight size={14}/></button>
            )}</div>
          </div>}
          {messages.map((turn) => <div className={`chat-turn ${turn.role}`} key={turn.id}>
            {turn.role === "assistant" && <span className="chat-avatar"><WizardLogo/></span>}
            <div className="chat-bubble">
              {turn.role === "assistant"
                ? turn.content
                  ? <MarkdownContent value={turn.content} compact/>
                  : <span className="chat-thinking"><i/><i/><i/> Reading your local memory</span>
                : <p>{turn.content}</p>}
              {turn.evidence && turn.evidence.length > 0 && <ChatSources evidence={turn.evidence}/>}
            </div>
          </div>)}
        </div>
        {error && <Notice kind="error" onClose={() => setError("")}>{error}</Notice>}
        <form className="chat-composer" onSubmit={ask}>
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="Ask about a decision, preference, project, or past session..."
            rows={2}
          />
          <div className="chat-composer-footer">
            <span><ShieldCheck size={13}/>{temporary ? "Temporary, not saved" : "Conversation saved locally"}</span>
            <button className="chat-send" aria-label="Send message" disabled={busy === "ask" || !question.trim()}>
              {busy === "ask" ? <LoaderCircle className="spin" size={17}/> : <ArrowRight size={17}/>}
            </button>
          </div>
        </form>
        <small className="chat-footnote">Enter to send, Shift + Enter for a new line. Answers retain source attribution.</small>
        </section>
      </article>

      <aside className="home-rail">
      <article className="feature-card agent-card">
        <div className="rail-card-heading"><div className="feature-icon plum"><Sparkles size={18}/></div><div><span className="eyebrow">Your agent</span><h2>Docmancer</h2></div></div>
        <p>Set its instructions, answer style, and model.</p>
        <button className="agent-customize-btn" onClick={() => setModal("agent")}>Customise Docmancer <ArrowRight size={14}/></button>
      </article>
      <article className="feature-card connect-card">
        <div className="rail-card-heading"><div className="feature-icon mint"><Command size={18}/></div><div><span className="eyebrow">Agent connections</span><h2>Share the same memory</h2></div></div>
        <div className="connection-summary">
          <span><strong>{installed.length}</strong> installed</span>
          <span className={attentionCount ? "attention" : "ready"}>{connectionStatus}</span>
        </div>
        <button className="primary-btn wide" onClick={() => setModal("setup")}>{connectionAction} <ArrowRight size={15}/></button>
      </article>
      <section className="home-cloud-card">
        <div><span className="eyebrow">Optional Docmancer Cloud</span><h2>Carry Context beyond this machine</h2><p>Local intelligence stays free. Pay for encrypted continuity and coordination.</p></div>
        <a href="/settings/?section=cloud"><Cloud size={16}/><span><strong>Personal Sync</strong><small>History, devices, and recovery</small></span><ArrowRight size={14}/></a>
        <a href="/settings/?section=cloud"><ShieldCheck size={16}/><span><strong>Team</strong><small>Approved shared Context</small></span><ArrowRight size={14}/></a>
      </section>
      </aside>
    </section>
    {modal === "agent" && <Modal title="Customise Docmancer" subtitle="This is the one agent humans interact with in the web UI." close={() => setModal("")}><AgentEditor onSaved={() => { setModal(""); void load(); }}/></Modal>}
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

function ChatSources({ evidence }: { evidence: JsonMap[] }) {
  const seen = new Set<string>();
  const sources = evidence.filter((item) => {
    const key = String(item.address ?? item.source_path ?? item.title ?? JSON.stringify(item));
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return <details className="chat-sources">
    <summary>
      <span className="chat-sources-icon"><BookOpen size={14}/></span>
      <span><strong>{sources.length} source{sources.length === 1 ? "" : "s"} used</strong><small>Open provenance</small></span>
      <ChevronDown size={14}/>
    </summary>
    <div className="chat-source-list">
      {sources.map((item, index) => <span key={`${String(item.address ?? item.source_path ?? item.title)}-${index}`}>
        <i>{index + 1}</i>
        <span><strong>{sourceTitle(item, index)}</strong><small>{sourceOrigin(item)}</small></span>
      </span>)}
    </div>
  </details>;
}

export function rows(value: unknown): JsonMap[] {
  return Array.isArray(value) ? value.filter((item): item is JsonMap => Boolean(item) && typeof item === "object") : [];
}
export function objectAt(value: JsonMap, key: string): JsonMap {
  const item = value[key]; return item && typeof item === "object" && !Array.isArray(item) ? item as JsonMap : {};
}
export function messageOf(reason: unknown): string { return reason instanceof Error ? reason.message : String(reason); }
function answerContent(result: JsonMap): string {
  const answer = result.answer;
  if (typeof answer === "string") return answer;
  if (answer && typeof answer === "object" && !Array.isArray(answer)) {
    return String((answer as JsonMap).text ?? "");
  }
  return String(result.text ?? result.answer_unavailable ?? "");
}
function conversationTurns(conversation: JsonMap): ChatTurn[] {
  return rows(conversation.messages).map((message) => ({
    id: String(message.id),
    role: message.role === "user" ? "user" : "assistant",
    content: String(message.content ?? ""),
    evidence: rows(message.evidence),
    pending: message.status === "pending",
  }));
}
function sourceTitle(item: JsonMap, index: number): string {
  const title = String(item.title ?? "").trim();
  if (title) return title;
  const path = String(item.source_path ?? item.address ?? "").replaceAll("\\", "/");
  return path.split("/").filter(Boolean).pop() || `Source ${index + 1}`;
}
function sourceOrigin(item: JsonMap): string {
  const value = String(item.harness ?? item.agent ?? item.authority ?? item.class ?? "").trim();
  if (!value) return "Local memory";
  return value.replaceAll("-", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
function compactDate(value: unknown): string {
  const date = new Date(String(value ?? ""));
  if (Number.isNaN(date.getTime())) return "";
  const today = new Date();
  if (date.toDateString() === today.toDateString()) {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}
function titleFor(view: CanonicalView) { return ({ home: "Home", context: "Context", library: "Library", settings: "Settings", help: "Help" } as const)[view]; }
