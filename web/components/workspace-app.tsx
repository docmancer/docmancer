"use client";

import {
  ArrowRight, BookOpen, BrainCircuit, Check, ChevronDown, ChevronRight, CircleHelp,
  Cloud, Command, Copy, FileText, History, Library, LoaderCircle, Moon,
  PanelLeftClose, PanelLeftOpen, Plus, Settings, ShieldCheck,
  Sparkles, Sun, Trash2, X,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiJobMutation, apiMutation, establishSession, type JsonMap } from "@/lib/api";
import { LibraryView } from "./library-view";
import { MarkdownContent } from "./markdown-content";
import { SharedMemoryWorkbench } from "./shared-memory-workbench";
import { AgentEditor, SettingsView, SetupFlow } from "./settings-view";
import { WizardLogo } from "./wizard-logo";

export type ViewKey =
  | "overview" | "context" | "library" | "settings" | "help"
  | "tree" | "ask" | "common" | "delivery" | "timeline" | "agent-context"
  | "inbox" | "memory" | "sources" | "intelligence" | "docs" | "audit"
  | "maintenance";

type CanonicalView = "home" | "memory" | "library" | "settings" | "help";
type ChatTurn = {
  id: string;
  role: "user" | "assistant";
  content: string;
  evidence?: JsonMap[];
  action?: JsonMap;
  pending?: boolean;
};

const PRIMARY = [
  { key: "home", label: "Home", href: "/", icon: Sparkles },
  { key: "memory", label: "Shared Memory", href: "/memory/", icon: BrainCircuit },
  { key: "library", label: "Library", href: "/library/", icon: Library },
] as const;

const CONNECTION_WARNING_DISMISS_KEY = "docmancer-dismissed-connection-warning";

function canonical(view: ViewKey): CanonicalView {
  if (["context", "common", "delivery", "timeline", "intelligence", "memory", "tree", "inbox"].includes(view)) return "memory";
  if (["library", "sources", "docs"].includes(view)) return "library";
  if (["settings", "audit", "maintenance"].includes(view)) return "settings";
  if (view === "help") return "help";
  return "home";
}

export function WorkspaceApp({ initialView }: { initialView: ViewKey }) {
  const view = canonical(initialView);
  const [error, setError] = useState("");
  const [dark, setDark] = useState(() => typeof window !== "undefined" && (
    window.localStorage.getItem("docmancer-theme") === "dark"
    || (!window.localStorage.getItem("docmancer-theme") && window.matchMedia("(prefers-color-scheme: dark)").matches)
  ));

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);
  useEffect(() => {
    establishSession().catch((reason) => setError(messageOf(reason)));
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
      <div className="secondary-nav">
        <Link href="/settings/" className={view === "settings" ? "nav-link active" : "nav-link"}><Settings size={17}/>Settings</Link>
        <Link href="/help/" className={view === "help" ? "nav-link active" : "nav-link"}><CircleHelp size={17}/>Help</Link>
      </div>
    </aside>
    <main className="main-stage">
      <header className="app-bar">
        <div className="page-path"><span>Docmancer</span><ChevronRight size={14}/><strong>{titleFor(view)}</strong></div>
        <div className="app-actions">
          <button className="icon-btn" onClick={toggleTheme} aria-label="Toggle theme">
            {dark ? <Sun size={16}/> : <Moon size={16}/>}
          </button>
        </div>
      </header>
      {error && <Notice kind="error" onClose={() => setError("")}>{error}</Notice>}
      <Page view={view}/>
    </main>
    <BackgroundJobs/>
  </div>;
}

/** Decide whether a job still belongs on screen.
 *
 * A completed job is an acknowledgement and can fade on its own. A failed one
 * is the opposite: it is the single outcome the user has to act on, and these
 * jobs are explicitly advertised as safe to walk away from ("Running in the
 * background. You can keep using Docmancer."). Expiring a failure on the same
 * timer as a success meant a memory organisation job that died 27 minutes in showed its
 * error for 15 seconds to an empty chair and then erased it, leaving a page
 * indistinguishable from one where nothing had ever run. Failures now stay
 * until the user dismisses them.
 */
export function jobStillVisible(job: JsonMap, now: number): boolean {
  if (job.state === "queued" || job.state === "running") return true;
  if (job.state === "failed") return true;
  const finished = new Date(String(job.finished_at ?? "")).getTime();
  const visibleFor = job.kind === "memory.ask" ? 5_000 : 15_000;
  return Number.isFinite(finished) && now - finished < visibleFor;
}

function BackgroundJobs() {
  const [jobs, setJobs] = useState<JsonMap[]>([]);
  const [dismissed, setDismissed] = useState<string[]>([]);

  const load = useCallback(async () => {
    const data = await apiGet("/api/v1/jobs");
    const now = Date.now();
    setJobs(rows(data.items).filter((job) => jobStillVisible(job, now)));
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

  const visible = jobs.filter((item) => !dismissed.includes(String(item.id ?? "")));
  if (!visible.length) return null;
  // A failure outranks anything still running: it is the item that needs a
  // decision, and it must not be hidden behind a later job's progress.
  const job = visible.find((item) => item.state === "failed") ?? visible[0];
  const labels: Record<string, string> = {
    "context.refresh": "Organising shared memory",
    "memory.ask": "Answering with your memory",
    "agent.setup": "Connecting coding agents",
    "memory.sync": "Indexing agent memory",
    "memory.consolidate": "Consolidating memory",
    "memory.apply": "Applying memory changes",
    "docs.ingest": "Indexing documentation",
    "cloud.sync": "Syncing encrypted memory",
  };
  const label = labels[String(job.kind ?? "")] ?? "Docmancer is working";
  const completed = job.state === "completed";
  const failed = job.state === "failed";
  const temporaryAsk = String(job.kind) === "memory.ask" && Boolean(objectAt(job, "result").temporary);
  const detail = failed
    ? String(job.error ?? "The background task failed.")
    : completed
      ? String(job.kind) === "context.refresh"
        ? "Shared memory is organised. Open Shared Memory to review the files."
        : String(job.kind) === "memory.ask"
          ? temporaryAsk
            ? "This temporary answer is not saved."
            : "The answer is saved in this conversation."
        : "The background task completed."
      : "Running in the background. You can keep using Docmancer.";
  const title = completed && String(job.kind) === "memory.ask"
    ? temporaryAsk ? "Temporary answer ready" : "Answer ready"
    : completed
      ? `${label} complete`
      : failed
        ? `${label} failed`
        : label;
  return <aside className={`background-jobs${failed ? " failed" : ""}`} aria-live={failed ? "assertive" : "polite"}>
    <span className="job-pulse">{completed ? <Check size={15}/> : failed ? <X size={15}/> : <LoaderCircle className="spin" size={15}/>}</span>
    <div><strong>{title}</strong><span>{detail}</span></div>
    {visible.length > 1 && <small>+{visible.length - 1}</small>}
    {failed && <button
      type="button"
      className="job-dismiss"
      aria-label="Dismiss this failure"
      onClick={() => setDismissed((current) => [...current, String(job.id ?? "")])}
    ><X size={13}/></button>}
  </aside>;
}

function Page({ view }: { view: CanonicalView }) {
  if (view === "home") return <HomeView/>;
  if (view === "memory") return <SharedMemoryPage/>;
  if (view === "library") return <LibraryView/>;
  if (view === "settings") return <SettingsView/>;
  return <HelpView/>;
}

function HomeView() {
  const [setup, setSetup] = useState<JsonMap>({});
  const [setupLoaded, setSetupLoaded] = useState(false);
  const [setupUnavailable, setSetupUnavailable] = useState(false);
  const [cloud, setCloud] = useState<JsonMap>({});
  const [cloudLoaded, setCloudLoaded] = useState(false);
  const [cloudUnavailable, setCloudUnavailable] = useState(false);
  const [conversations, setConversations] = useState<JsonMap[]>([]);
  const [activeConversation, setActiveConversation] = useState("");
  const [conversationToDelete, setConversationToDelete] = useState<JsonMap | null>(null);
  const [temporary, setTemporary] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatTurn[]>([]);
  const [busy, setBusy] = useState("");
  const [modal, setModal] = useState<"agent" | "setup" | "">("");
  const [error, setError] = useState("");
  const [dismissedConnectionWarning, setDismissedConnectionWarning] = useState(() => {
    if (typeof window === "undefined") return "";
    try {
      return window.localStorage.getItem(CONNECTION_WARNING_DISMISS_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const chatThreadRef = useRef<HTMLDivElement>(null);
  const chatScrollRef = useRef<"top" | "bottom">("top");
  const chatTurnId = useRef(0);

  const refreshConversations = useCallback(async () => {
    const data = await apiGet("/api/v1/ask/conversations?limit=60");
    setConversations(rows(data.items));
  }, []);
  const load = useCallback(async () => {
    setSetupLoaded(false);
    setSetupUnavailable(false);
    setCloudLoaded(false);
    setCloudUnavailable(false);
    const [setupResult, conversationResult, cloudResult] = await Promise.allSettled([
        apiGet("/api/v1/agent/setup"),
        apiGet("/api/v1/ask/conversations?limit=60"),
        apiGet("/api/v1/cloud"),
    ]);
    if (setupResult.status === "fulfilled") setSetup(setupResult.value);
    else setSetupUnavailable(true);
    if (conversationResult.status === "fulfilled") setConversations(rows(conversationResult.value.items));
    if (cloudResult.status === "fulfilled") setCloud(cloudResult.value);
    else setCloudUnavailable(true);
    setSetupLoaded(true);
    setCloudLoaded(true);
    const failed = [setupResult, conversationResult].find((result) => result.status === "rejected");
    if (failed?.status === "rejected") setError(messageOf(failed.reason));
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
    setBusy("delete"); setError("");
    try {
      await apiMutation(
        `/api/v1/ask/conversations/${encodeURIComponent(conversationId)}`,
        {},
        "DELETE",
      );
      if (activeConversation === conversationId) newChat();
      setConversationToDelete(null);
      await refreshConversations();
    } catch (reason) {
      setError(messageOf(reason));
    } finally {
      setBusy("");
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
        action: objectAt(result, "action"),
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
  const decideAction = async (turnId: string, action: JsonMap, decision: "apply" | "cancel") => {
    const actionId = String(action.id ?? "");
    if (!actionId || busy) return;
    setBusy(`action:${actionId}`); setError("");
    try {
      const response = await apiMutation(
        `/api/v1/ask/actions/${encodeURIComponent(actionId)}`,
        { decision },
      );
      const resolved = objectAt(response, "action");
      setMessages((current) => current.map((turn) =>
        turn.id === turnId ? { ...turn, action: resolved } : turn
      ));
    } catch (reason) {
      setError(messageOf(reason));
      if (activeConversation) {
        const conversation = await apiGet(
          `/api/v1/ask/conversations/${encodeURIComponent(activeConversation)}`,
        ).catch(() => null);
        if (conversation) setMessages(conversationTurns(conversation));
      }
    } finally {
      setBusy("");
    }
  };

  const integrations = rows(setup.items);
  const connected = integrations.filter((item) => item.integration_state === "connected" && !item.recall_setup_required);
  const updates = integrations.filter((item) => item.action_kind === "automatic" && item.integration_state === "stale");
  const repairs = integrations.filter((item) => item.action_kind === "automatic" && item.integration_state === "partial");
  const automatic = integrations.filter((item) => item.action_kind === "automatic" && item.integration_state === "ready-to-connect");
  const recallSetup = integrations.filter((item) => item.action_kind === "automatic" && item.integration_state === "connected" && item.recall_setup_required);
  const manual = integrations.filter((item) => item.action_kind === "manual" && item.detected);
  const attentionCount = automatic.length + recallSetup.length + updates.length + repairs.length + manual.length;
  const showConnectionBanner = setupLoaded && !setupUnavailable && (attentionCount > 0 || connected.length === 0);
  const activeTitle = temporary
    ? "Temporary chat"
    : String(conversations.find((item) => item.id === activeConversation)?.title ?? "Ask Docmancer");
  const connectionStatus = automatic.length
    ? `${automatic.length} ready to connect`
    : recallSetup.length
      ? `${recallSetup.length} need automatic memory setup`
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
      ? "Finish automatic memory setup"
      : updates.length
        ? "Update integrations"
        : repairs.length
          ? "Repair integrations"
          : manual.length
            ? `Finish ${String(manual[0].label)} setup`
            : "Manage connections";
  const connectionWarningSignature = JSON.stringify(integrations.map((item) => [
    item.id ?? item.key ?? item.label,
    item.integration_state,
    item.action_kind,
    Boolean(item.recall_setup_required),
    Boolean(item.detected),
  ]));
  const connectionWarningVisible = showConnectionBanner
    && connectionWarningSignature !== dismissedConnectionWarning;
  const dismissConnectionWarning = () => {
    setDismissedConnectionWarning(connectionWarningSignature);
    try {
      window.localStorage.setItem(CONNECTION_WARNING_DISMISS_KEY, connectionWarningSignature);
    } catch {
      // The state update above still dismisses the warning for this session.
    }
  };
  const suggestions = [
    { kind: "Ask", prompt: "What decisions have my agents made about this project?" },
    { kind: "Ask", prompt: "What working preferences recur across my agents?" },
    { kind: "Remember", prompt: "Remember that production releases require a smoke test" },
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
                onClick={() => setConversationToDelete(conversation)}
                aria-label={`Delete ${String(conversation.title ?? "conversation")}`}
              ><Trash2 size={13}/></button>
            </div>)}
          </div>
          <button className={temporary ? "temporary-chat active" : "temporary-chat"} onClick={() => newChat(true)}>
            <ShieldCheck size={14}/>
            <span><strong>Temporary chat</strong><small>This chat is not saved</small></span>
          </button>
          <button className="chat-history-close" onClick={() => setHistoryOpen(false)}>
            <PanelLeftClose size={15}/>Close history
          </button>
        </aside>
        {historyOpen && <button className="chat-history-scrim" aria-label="Close conversation history" onClick={() => setHistoryOpen(false)}/>}
        <section className="chat-main">
        <div className="chat-top">
        <header className="chat-header">
          <button className="history-toggle" onClick={() => setHistoryOpen(true)} aria-label="Open conversation history">
            <PanelLeftOpen size={17}/>
          </button>
          <div className="chat-header-copy">
            <h1>{activeConversation || temporary ? activeTitle : "Ask Docmancer"}</h1>
          </div>
          <button className="secondary-btn chat-customize" onClick={() => setModal("agent")} aria-label="Customise Docmancer">
            <Sparkles size={14}/><span>Customise</span>
          </button>
          {(messages.length > 0 || activeConversation || temporary) && <button className="secondary-btn chat-reset" onClick={() => newChat()}><Plus size={14}/>New chat</button>}
        </header>
        {connectionWarningVisible && <div className="connection-banner">
          <span className="connection-banner-icon"><Command size={15}/></span>
          <div><strong>{connectionStatus}</strong><span>Connect your coding agents so they can use the same memory.</span></div>
          <button className="secondary-btn" onClick={() => setModal("setup")} aria-label={connectionAction}><span>{connectionAction}</span><ArrowRight size={14}/></button>
          <button className="connection-banner-dismiss" onClick={dismissConnectionWarning} aria-label="Dismiss agent setup warning" title="Do not show this warning again"><X size={14}/></button>
        </div>}
        </div>
        <div ref={chatThreadRef} className={messages.length ? "chat-thread" : "chat-thread empty"}>
          {!messages.length && <div className="chat-welcome">
            <div className="chat-welcome-mark"><WizardLogo/></div>
            <h2>Ask what your agents already know</h2>
            <p>Ask across their memory, instructions, decisions, and project notes, or request one complete-file memory update for approval. Docmancer keeps the source evidence attached.</p>
            <div className="chat-suggestions">{suggestions.map((suggestion) =>
              <button key={suggestion.prompt} className={suggestion.kind.toLowerCase()} onClick={() => void askQuestion(suggestion.prompt)}>
                {suggestion.kind === "Ask" ? <Sparkles size={14}/> : <FileText size={14}/>}
                <span className="suggestion-copy"><small>{suggestion.kind}</small><span>{suggestion.prompt}</span></span>
                <ArrowRight size={14}/>
              </button>
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
              {turn.role === "assistant" && turn.action && Object.keys(turn.action).length > 0 && <MemoryActionCard
                action={turn.action}
                busy={busy === `action:${String(turn.action.id ?? "")}`}
                decide={(decision) => void decideAction(turn.id, turn.action ?? {}, decision)}
                replan={() => void askQuestion(
                  `Update Shared Memory again for ${String((turn.action as JsonMap).path ?? (turn.action as JsonMap).target ?? "this file")} using its current contents.`
                )}
              />}
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
            placeholder="Ask a question or request a Shared Memory update..."
            rows={2}
          />
          <div className="chat-composer-footer">
            <span><ShieldCheck size={13}/>{temporary ? "Temporary chat, not saved" : "Conversation saved locally"}</span>
            <button className="chat-send" aria-label="Send message" disabled={busy === "ask" || !question.trim()}>
              {busy === "ask" ? <LoaderCircle className="spin" size={17}/> : <ArrowRight size={17}/>}
            </button>
          </div>
        </form>
        <small className="chat-footnote">Enter to send, Shift + Enter for a new line. Memory changes require the action card. Typing yes never applies them.</small>
        </section>
      </article>

      <aside className="home-rail">
      <section className={`home-cloud-card${cloud.configured ? " connected" : ""}${cloudUnavailable ? " unavailable" : ""}`} aria-busy={!cloudLoaded}>
        {!cloudLoaded ? <div className="home-cloud-loading" aria-label="Loading Docmancer Cloud status"><span/><span/><span/></div> : <>
        <div className="cloud-card-intro">
          <span className="cloud-mark"><Cloud size={18}/></span>
          <div>
            <span className="eyebrow">{cloudUnavailable ? "Cloud status unavailable" : cloud.configured ? "Docmancer Cloud connected" : "Optional Docmancer Cloud"}</span>
            <h2>{cloud.configured ? "Your memory goes beyond this machine" : "Take your memory beyond this machine"}</h2>
            <p>{cloudUnavailable ? "Open Cloud settings to check this device." : cloud.configured ? "Personal Sync is connected. Manage encrypted continuity and Team from one place." : "The complete local product stays free. Paid plans add encrypted continuity and coordination."}</p>
          </div>
        </div>
        <div className="cloud-benefits">
          <div><Cloud size={16}/><span><strong>Personal Sync</strong><small>History, devices, and recovery</small></span></div>
          <div><ShieldCheck size={16}/><span><strong>Team</strong><small>Approved shared context</small></span></div>
        </div>
        <a className="cloud-cta" href="/settings/?section=cloud">{cloud.configured ? "Manage Cloud" : cloudUnavailable ? "Open Cloud settings" : "Explore Docmancer Cloud"}<ArrowRight size={15}/></a>
        </>}
      </section>
      </aside>
    </section>
    {modal === "agent" && <Modal title="Customise Docmancer" subtitle="This is the one agent humans interact with in the web UI." close={() => setModal("")}><AgentEditor onSaved={() => { setModal(""); void load(); }}/></Modal>}
    {modal === "setup" && <Modal title="Connect Docmancer" subtitle="Index local memory, install skills, and optionally add recall hooks." close={() => setModal("")}><SetupFlow initial={setup} onComplete={() => { setModal(""); void load(); }}/></Modal>}
    {conversationToDelete && <Modal title="Delete this conversation?" subtitle="This cannot be undone." close={() => { if (!busy) setConversationToDelete(null); }}>
      <div className="delete-conversation-modal">
        <div className="delete-conversation-summary">
          <span><Trash2 size={16}/></span>
          <div><small>Conversation</small><strong>{String(conversationToDelete.title ?? "Untitled conversation")}</strong></div>
        </div>
        <p>All messages in this conversation will be removed from this device. Shared Memory will not be changed.</p>
        <div className="modal-actions">
          <button type="button" className="secondary-btn" onClick={() => setConversationToDelete(null)} disabled={Boolean(busy)}>Cancel</button>
          <button type="button" className="danger-btn" onClick={() => void deleteConversation(String(conversationToDelete.id))} disabled={Boolean(busy)}>{busy === "delete" ? "Deleting…" : "Delete permanently"}</button>
        </div>
      </div>
    </Modal>}
  </div>;
}

function SharedMemoryPage() {
  return <div className="page">
    <PageHeading eyebrow="One local source of truth" title="Shared Memory" description="Inspect the canonical files on this machine, see how they are arranged, and check how each coding agent accesses them."/>
    <SharedMemoryWorkbench/>
  </div>;
}

function HelpView() {
  const commands = [
    ["Start everything", "docmancer setup", "Index existing memory and install detected agent integrations."],
    ["Open shared memory", "docmancer web", "Inspect the canonical filesystem and agent delivery from the local workbench."],
    ["Write durable memory", 'docmancer write "# Release\\n\\nUse the release script." --path decisions/release.md', "Save a project decision into the standard scaffold."],
    ["Ask from a terminal", 'docmancer ask "What do my agents know about deployment?"', "Use the same memory from the CLI."],
    ["Propose a memory update", 'docmancer ask "Remember that releases require a smoke test"', "Review one complete-file proposal, then approve it explicitly."],
  ];
  return <div className="page">
    <PageHeading eyebrow="A short guide" title="Use the web UI. Let agents use the CLI." description="Docmancer gives you a human place to understand memory, while coding agents use skills, hooks, CLI, and MCP behind the scenes."/>
    <div className="help-grid">
      <section className="feature-card help-intro"><BrainCircuit size={25}/><h2>The basic loop</h2><ol><li>Connect your coding agents.</li><li>Index what they already know.</li><li>Ask questions or request one memory update.</li><li>Review and approve complete-file action cards.</li><li>Keep working. Connected agents recall the relevant files automatically.</li></ol></section>
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

export function AgentGroup({ title, note, children }: { title: string; note: string; children: ReactNode }) {
  return <section className="agent-group"><header><div><strong>{title}</strong><p>{note}</p></div></header><div className="agent-choice-grid">{children}</div></section>;
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
    action: objectAt(message, "action"),
    pending: message.status === "pending",
  }));
}

function MemoryActionCard({ action, busy, decide, replan }: {
  action: JsonMap;
  busy: boolean;
  decide: (decision: "apply" | "cancel") => void;
  replan: () => void;
}) {
  const operation = String(action.operation ?? "edit");
  const status = String(action.status ?? "pending");
  const destructive = Boolean(action.destructive);
  const target = String(action.path ?? action.target ?? action.section ?? "Shared Memory");
  const source = String(action.address ?? action.target ?? "");
  const restoreToken = String(action.restore_token ?? "");
  const before = String(action.before_markdown ?? "");
  const after = String(action.after_markdown ?? "");
  const diff = String(action.diff ?? "");
  return <section className={`memory-action-card${destructive ? " destructive" : ""}`} aria-label={`${operation} Shared Memory proposal`}>
    <header>
      <span className="memory-action-icon">{destructive ? <Trash2 size={15}/> : <FileText size={15}/>}</span>
      <div><span className="eyebrow">{String(action.scope ?? "project")} memory</span><strong>{operation[0].toUpperCase() + operation.slice(1)} {target}</strong></div>
      <span className={`memory-action-status ${status}`}>{status}</span>
    </header>
    <p>{String(action.rationale ?? "Review this complete-file change before applying it.")}</p>
    {["move", "duplicate"].includes(operation) && <p className="memory-action-route"><strong>Source:</strong> {source}<br/><strong>Destination:</strong> {target}</p>}
    {operation === "restore" && <p className="memory-action-route"><strong>Original destination:</strong> {target}<br/><strong>Restore token:</strong> {restoreToken}</p>}
    {diff && <details open={status === "pending"}><summary>Complete change</summary><pre>{diff}</pre></details>}
    {after && ["create", "edit", "pin"].includes(operation) && <details><summary>Proposed Markdown</summary><pre>{after}</pre></details>}
    {before && operation === "trash" && <details><summary>Complete file to trash</summary><pre>{before}</pre></details>}
    {status === "pending" && <footer>
      <button className="secondary-btn" disabled={busy} onClick={() => decide("cancel")}>Cancel</button>
      <button className={destructive ? "danger-btn" : "primary-btn"} disabled={busy} onClick={() => decide("apply")}>
        {busy ? <LoaderCircle className="spin" size={14}/> : <Check size={14}/>}
        Apply {operation}
      </button>
    </footer>}
    {status === "conflict" && <footer><button className="primary-btn" onClick={replan}>Prepare a new proposal</button></footer>}
    {status === "applied" && <small className="memory-action-result">Shared Memory updated locally.</small>}
  </section>;
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
function titleFor(view: CanonicalView) { return ({ home: "Home", memory: "Shared Memory", library: "Library", settings: "Settings", help: "Help" } as const)[view]; }
