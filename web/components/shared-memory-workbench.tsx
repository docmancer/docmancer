"use client";

import {
  ArrowRight, Check, ChevronDown, ChevronRight, CircleDot, FileText, LoaderCircle,
  Folder, FolderOpen, Plus, Radio, RefreshCw, Search, ShieldCheck, TriangleAlert, X,
} from "lucide-react";
import { FormEvent, RefObject, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiMutation, type JsonMap } from "@/lib/api";
import { MarkdownContent } from "./markdown-content";
import { messageOf, Modal, Notice, panelMessage, rows } from "./workspace-app";

type Root = JsonMap & { key: string; label: string; files: JsonMap[]; folders: JsonMap[] };

const MEMORY_CACHE_KEY = "docmancer:shared-memory:v1";
const DELIVERY_CACHE_KEY = "docmancer:shared-memory-delivery:v1";
let memorySnapshot: JsonMap | null = null;
let deliverySnapshot: JsonMap[] | null = null;

function readSessionCache(key: string): JsonMap | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(key);
    return raw ? JSON.parse(raw) as JsonMap : null;
  } catch {
    return null;
  }
}

function writeSessionCache(key: string, value: unknown) {
  try {
    window.sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // The in-module snapshot still makes client-side navigation instant.
  }
}

/** Keep a workbench sidebar in view without trapping its own scrolling.
 *
 * A plain `position: sticky; top: 76px` pins a column immediately, which is
 * wrong here: the canonical file tree is routinely taller than the viewport, so
 * pinning it at the top means its lower half is unreachable. Instead the sticky
 * offset is measured from the column itself. Columns that fit the viewport stick
 * under the app bar as usual; taller columns get a negative offset equal to
 * their overhang, so the page scrolls through the whole column first and the
 * column then parks with its last row against the bottom of the viewport.
 */
function useStickyColumn<T extends HTMLElement>(): RefObject<T | null> {
  const ref = useRef<T | null>(null);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const TOP_GAP = 76;
    const BOTTOM_GAP = 18;
    const apply = () => {
      const room = window.innerHeight - TOP_GAP - BOTTOM_GAP;
      const overhang = element.offsetHeight - room;
      element.style.setProperty(
        "--memory-stick-top",
        `${overhang > 0 ? TOP_GAP - overhang : TOP_GAP}px`,
      );
    };
    apply();
    const observer = new ResizeObserver(apply);
    observer.observe(element);
    window.addEventListener("resize", apply);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", apply);
    };
  }, []);
  return ref;
}

function mainReadme(memory: JsonMap): JsonMap | undefined {
  const machine = rows(memory.roots).find((root) => root.key === "machine");
  return rows(machine?.files).find((file) => String(file.path).toLowerCase() === "readme.md");
}

export function SharedMemoryWorkbench() {
  const [cachedMemory] = useState<JsonMap | null>(
    () => memorySnapshot ?? readSessionCache(MEMORY_CACHE_KEY),
  );
  const [cachedDelivery] = useState<JsonMap[] | null>(() => {
    if (deliverySnapshot !== null) return deliverySnapshot;
    const cached = readSessionCache(DELIVERY_CACHE_KEY);
    return cached ? rows(cached.items) : null;
  });
  const [data, setData] = useState<JsonMap>(cachedMemory ?? {});
  const [delivery, setDelivery] = useState<JsonMap[]>(cachedDelivery ?? []);
  const [selected, setSelected] = useState<JsonMap | null>(null);
  const [openingFile, setOpeningFile] = useState<JsonMap | null>(null);
  const [projection, setProjection] = useState<JsonMap | null>(null);
  const [expanded, setExpanded] = useState<string[]>([
    "machine:profile", "machine:principles", "machine:projects", "machine:shared",
    "project:", "project:decisions", "project:constraints", "project:workflows", "project:lessons",
  ]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(!cachedMemory);
  const [agentLoading, setAgentLoading] = useState(cachedDelivery === null);
  const [backgroundRefresh, setBackgroundRefresh] = useState(false);
  const [libraryRefresh, setLibraryRefresh] = useState(false);
  const [backgroundError, setBackgroundError] = useState("");
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);
  const hasOpenedMainReadme = useRef(false);
  const openingAddress = useRef("");

  const load = useCallback(async () => {
    setError("");
    try {
      const readiness = await apiGet("/api/v1/readiness");
      if (!readiness.ready) {
        if (readiness.error) throw new Error(String(readiness.error));
        if (!cachedMemory) setLoading(true);
        return false;
      }
      void apiGet("/api/v1/shared-memory").then((memory) => {
        memorySnapshot = memory;
        writeSessionCache(MEMORY_CACHE_KEY, memory);
        setData(memory);
        setLoading(false);
        const readme = !hasOpenedMainReadme.current && mainReadme(memory);
        if (readme) {
          hasOpenedMainReadme.current = true;
          void apiGet(`/api/v1/shared-memory/file?address=${encodeURIComponent(String(readme.address))}`)
            .then((file) => setSelected(file))
            .catch((reason) => setError(panelMessage(reason)));
        }
      }).catch((reason) => {
        setLoading(false);
        if (!cachedMemory) setError(panelMessage(reason));
      });
      void apiGet("/api/v1/delivery").then((agents) => {
        const items = rows(agents.items);
        deliverySnapshot = items;
        writeSessionCache(DELIVERY_CACHE_KEY, { items });
        setDelivery(items);
      }).catch(() => undefined).finally(() => setAgentLoading(false));
      const memoryRefresh = (readiness.memory_refresh ?? {}) as JsonMap;
      const libraryIndex = (readiness.library_index ?? {}) as JsonMap;
      setBackgroundRefresh(Boolean(memoryRefresh.running));
      setLibraryRefresh(Boolean(libraryIndex.running));
      setBackgroundError(String(memoryRefresh.error ?? libraryIndex.error ?? ""));
      return true;
    } catch (reason) {
      setLoading(false);
      setError(panelMessage(reason));
      return true;
    }
  }, [cachedMemory]);

  useEffect(() => {
    let cancelled = false;
    let timer = 0;
    const attempt = async () => {
      const done = await load();
      if (!cancelled && !done) timer = window.setTimeout(attempt, 300);
    };
    void attempt();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    const update = async () => {
      try {
        const readiness = await apiGet("/api/v1/readiness");
        if (cancelled) return;
        const memoryRefresh = (readiness.memory_refresh ?? {}) as JsonMap;
        const libraryIndex = (readiness.library_index ?? {}) as JsonMap;
        setBackgroundRefresh(Boolean(memoryRefresh.running));
        setLibraryRefresh(Boolean(libraryIndex.running));
        setBackgroundError(String(memoryRefresh.error ?? libraryIndex.error ?? ""));
      } catch {
        // The main panel owns startup errors. Background status can retry.
      }
    };
    void update();
    const timer = window.setInterval(update, 1200);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const roots = useMemo(
    () => rows(data.roots).map((item) => ({
      ...item,
      key: String(item.key),
      label: String(item.label),
      files: rows(item.files),
      folders: rows(item.folders),
    })) as Root[],
    [data],
  );

  const openFile = useCallback(async (file: JsonMap) => {
    const address = String(file.address);
    setError("");
    openingAddress.current = address;
    setOpeningFile(file);
    try {
      const result = await apiGet(`/api/v1/shared-memory/file?address=${encodeURIComponent(address)}`);
      if (openingAddress.current === address) setSelected(result);
    } catch (reason) {
      if (openingAddress.current === address) setError(panelMessage(reason));
    } finally {
      if (openingAddress.current === address) setOpeningFile(null);
    }
  }, []);

  const inspectAgent = async (agent: JsonMap) => {
    const id = String(agent.agent ?? agent.id ?? "");
    const selection = { ...agent, agent: id, label: agent.label ?? id };
    if (agent.integration_mode !== "managed-projection" || !agent.projection_path) {
      setProjection({ ...selection, available: false });
      return;
    }
    setProjection({ ...selection, loading: true });
    try {
      const result = await apiGet(`/api/v1/agents/${encodeURIComponent(id)}/projection`);
      setProjection({ ...selection, ...result });
    } catch (reason) {
      setProjection({ ...selection, error: messageOf(reason) });
    }
  };

  const mapColumn = useStickyColumn<HTMLDivElement>();
  const agentColumn = useStickyColumn<HTMLDivElement>();

  const toggle = (id: string) => setExpanded((current) =>
    current.includes(id) ? current.filter((item) => item !== id) : [...current, id]
  );

  return <div className="shared-memory-workbench">
    <div className="memory-command-bar">
      <label><Search size={14}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a canonical file"/></label>
      <div className="memory-command-actions">
        <button className="primary-btn" onClick={() => setAdding(true)}><Plus size={14}/>Add memory</button>
      </div>
    </div>

    {(loading || backgroundRefresh || libraryRefresh || backgroundError) && <div className={`memory-activity${backgroundError ? " warning" : ""}`} role="status">
      {backgroundError ? <TriangleAlert size={16}/> : <RefreshCw className="spin" size={16}/>}
      <div>
        <strong>{backgroundError
          ? "Refresh paused. Showing saved memory"
          : loading
            ? "Starting local memory services"
            : backgroundRefresh
              ? "Checking agent memory for changes"
              : "Updating the Library index"}</strong>
        <span>{backgroundError
          ? `Docmancer could not check for newer agent memory. Your saved files are safe and available. Details: ${backgroundError}`
          : loading
            ? "The interface is ready now. Canonical files and agent delivery will appear independently as their local indexes open."
            : "This runs in the background. You can browse files, switch pages, and keep working while Docmancer finishes."}</span>
      </div>
    </div>}

    {error && <Notice kind="error" onClose={() => setError("")}>{error}</Notice>}

    <div className="memory-map-layout">
      <section className="memory-map-panel">
        <div className="memory-side-sticky" ref={mapColumn}>
          <header>
            <div><span className="eyebrow">Canonical files</span><h2>Your shared memory</h2></div>
            <span className="file-total">{roots.reduce((sum, root) => sum + Number(root.count ?? 0), 0)} files</span>
          </header>
          {loading
            ? <MemoryTreeSkeleton/>
            : roots.map((root) => <MemoryRoot
                key={root.key}
                root={root}
                expanded={expanded}
                query={query}
                selected={String(selected?.address ?? "")}
                toggle={toggle}
                openFile={openFile}
              />)}
          {!loading && Number(data.legacy_generated_files ?? 0) > 0 && <div className="legacy-evidence-note">
            <ShieldCheck size={15}/><div><strong>{Number(data.legacy_generated_files).toLocaleString()} generated topic files kept as evidence</strong><span>They remain available to retrieval but are not presented as canonical memory.</span></div>
          </div>}
        </div>
      </section>

      <section className="memory-reading-panel">
        {openingFile ? <FileReaderLoading file={openingFile}/> : selected ? <FileReader file={selected} close={() => setSelected(null)}/> : <div className="memory-reading-empty">
          <span className="file-stack"><FileText size={27}/></span>
          <span className="eyebrow">A filesystem you can inspect</span>
          <h2>Select a memory file</h2>
          <p>Open any file to read its Markdown, provenance, scope, and stable address. This is the same canonical source your agents query.</p>
        </div>}
      </section>

      <aside className="agent-reach-panel">
        <div className="memory-side-sticky" ref={agentColumn}>
        <header><span className="eyebrow">Available to agents</span><h2>Who can use it</h2><p>See whether each agent uses automatic recall, an installed skill, or a managed projection.</p></header>
        {agentLoading ? <AgentSkeleton/> : delivery.length ? <div className="agent-reach-list">{delivery.map((agent, index) => {
          const connected = agent.integration_state === "connected";
          return <button key={String(agent.agent ?? agent.id ?? index)} onClick={() => void inspectAgent(agent)}>
            <span className={`agent-state ${connected ? "connected" : ""}`}>{connected ? <Check size={12}/> : <CircleDot size={12}/>}</span>
            <div><strong>{String(agent.label ?? agent.agent ?? "Agent")}</strong><small>{connected ? agent.recall_hook ? "Automatic recall active" : "Skill available" : agent.detected ? "Ready to connect" : "Not detected"}</small></div>
            <ArrowRight size={13}/>
          </button>;
        })}</div> : <div className="agent-empty"><Radio size={18}/><p>No coding-agent integrations detected yet.</p><code>docmancer setup</code></div>}
        </div>
      </aside>
    </div>

    {adding && <AddMemory close={() => setAdding(false)} saved={() => { setAdding(false); void load(); }}/>}
    {projection && <ProjectionModal value={projection} close={() => setProjection(null)}/>}
  </div>;
}

function MemoryRoot({ root, expanded, query, selected, toggle, openFile }: {
  root: Root; expanded: string[]; query: string; selected: string;
  toggle: (id: string) => void; openFile: (file: JsonMap) => Promise<void>;
}) {
  const rootId = `${root.key}:`;
  const rootOpen = expanded.includes(rootId) || root.key === "machine";
  const needle = query.trim().toLowerCase();
  const visible = root.files.filter((file) => !needle || `${file.path} ${file.title}`.toLowerCase().includes(needle));
  const folders = root.folders.filter((folder) =>
    visible.some((file) => String(file.path).startsWith(`${String(folder.path)}/`))
    || (!needle && !String(folder.parent))
  );
  const rootFiles = visible.filter((file) => !String(file.path).includes("/"));
  return <div className="memory-root">
    <button className="memory-root-row" onClick={() => toggle(rootId)}>
      {rootOpen ? <ChevronDown size={14}/> : <ChevronRight size={14}/>}
      {rootOpen ? <FolderOpen size={16}/> : <Folder size={16}/>}
      <strong>{root.label}</strong><span>{visible.length}</span>
    </button>
    {rootOpen && <div className="memory-root-children">
      {rootFiles.map((file) => <FileRow key={String(file.address)} file={file} selected={selected} openFile={openFile}/>)}
      {folders.filter((folder) => !String(folder.parent)).map((folder) => {
        const path = String(folder.path);
        const id = `${root.key}:${path}`;
        const open = expanded.includes(id) || Boolean(needle);
        const children = visible.filter((file) => String(file.path).startsWith(`${path}/`));
        return <div className="memory-folder" key={id}>
          <button onClick={() => toggle(id)}>{open ? <ChevronDown size={13}/> : <ChevronRight size={13}/>}<Folder size={15}/><strong>{String(folder.name)}</strong><span>{children.length}</span></button>
          {open && <div>{children.map((file) => <FileRow key={String(file.address)} file={file} selected={selected} openFile={openFile} nested/>)}</div>}
        </div>;
      })}
    </div>}
  </div>;
}

function FileRow({ file, selected, openFile, nested = false }: {
  file: JsonMap; selected: string; openFile: (file: JsonMap) => Promise<void>; nested?: boolean;
}) {
  return <button className={`memory-file-row${selected === file.address ? " selected" : ""}${nested ? " nested" : ""}`} onClick={() => void openFile(file)}>
    <FileText size={14}/><span>{String(file.path).split("/").at(-1)}</span>
    <small>{file.curation_origin === "deliberate_write" ? "you" : file.curation_origin ? "generated" : ""}</small>
  </button>;
}

function FileReaderLoading({ file }: { file: JsonMap }) {
  const title = String(file.title ?? file.path).trim() || "memory file";
  return <div className="memory-reading-empty memory-file-loading" role="status" aria-live="polite">
    <span className="file-stack"><LoaderCircle className="spin" size={24}/></span>
    <span className="eyebrow">Opening memory file</span>
    <h2>{title}</h2>
    <p>Loading the Markdown, source details, and stable address.</p>
  </div>;
}

function FileReader({ file, close }: { file: JsonMap; close: () => void }) {
  return <div className="memory-file-reader">
    <header><div><span className="eyebrow">{String(file.root)} memory</span><h2>{String(file.title ?? file.path)}</h2><code>{String(file.path)}</code></div><button className="icon-btn" onClick={close} aria-label="Close file"><X size={15}/></button></header>
    <div className="file-meta-strip">
      <span><strong>Scope</strong>{String(file.scope ?? "unknown")}</span>
      <span><strong>Authority</strong>{String(file.authority ?? "advisory")}</span>
      <span><strong>Sources</strong>{Array.isArray(file.sources) ? file.sources.length || "Generated" : "Generated"}</span>
    </div>
    <article className="memory-markdown"><MarkdownContent value={String(file.markdown ?? "")}/></article>
    <footer><span>Stable address</span><code>{String(file.address)}</code></footer>
  </div>;
}

function AddMemory({ close, saved }: { close: () => void; saved: () => void }) {
  const [kind, setKind] = useState("decisions");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "memory";
    setBusy(true); setError("");
    try {
      await apiMutation("/api/v1/tree/file", {
        path: `${kind}/${slug}.md`,
        markdown: `# ${title.trim()}\n\n${body.trim()}\n`,
        type: kind === "decisions" ? "decision" : kind === "constraints" ? "constraint" : kind === "workflows" ? "workflow" : "fact",
      });
      saved();
    } catch (reason) { setError(panelMessage(reason)); } finally { setBusy(false); }
  };
  return <Modal title="Add project memory" subtitle="Docmancer places it in the standard project scaffold." close={close}><form className="add-memory-form" onSubmit={submit}>
    <label>Kind<select value={kind} onChange={(event) => setKind(event.target.value)}><option value="decisions">Decision</option><option value="constraints">Constraint</option><option value="workflows">Workflow</option><option value="lessons">Lesson</option></select></label>
    <label>Title<input required value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Release process"/></label>
    <label>What should every agent remember?<textarea required value={body} onChange={(event) => setBody(event.target.value)} rows={7} placeholder="Use the release script from the workspace root."/></label>
    {error && <Notice kind="error">{error}</Notice>}
    <div className="modal-actions"><button type="button" className="secondary-btn" onClick={close}>Cancel</button><button className="primary-btn" disabled={busy}>{busy ? "Saving…" : "Save to shared memory"}</button></div>
  </form></Modal>;
}

function ProjectionModal({ value, close }: { value: JsonMap; close: () => void }) {
  const projection = (value.projection && typeof value.projection === "object" ? value.projection : {}) as JsonMap;
  const connected = value.integration_state === "connected";
  const automaticRecall = Boolean(value.recall_hook) || value.integration_mode === "hook";
  const managedProjection = value.integration_mode === "managed-projection";
  const lastDelivery = value.last_successful_recall
    ? new Date(String(value.last_successful_recall)).toLocaleString()
    : "Not observed yet";
  const emptyTitle = automaticRecall
    ? "Automatic recall is active"
    : connected
      ? "Docmancer skill is installed"
      : managedProjection
        ? "Managed projection is unavailable"
        : "Memory delivery is not connected";
  const emptyDescription = automaticRecall
    ? `${String(value.label ?? value.agent)} receives a bounded, task-relevant memory bundle when a session starts or a prompt needs it. It does not use one fixed projection file.`
    : connected
      ? `${String(value.label ?? value.agent)} can query Shared Memory on demand through the installed Docmancer skill. It does not use one fixed projection file.`
      : managedProjection
        ? "Docmancer expected a managed projection file, but it could not be previewed."
        : "Run setup to connect this coding agent to Shared Memory.";
  return <Modal title={`${String(value.label ?? value.agent)} memory delivery`} subtitle="How this agent receives Shared Memory." close={close}>
    {value.loading ? <AgentSkeleton/> : value.error ? <Notice kind="error">{String(value.error)}</Notice> : value.available === false ? <div className="projection-empty">
      <span className={`projection-delivery-icon ${connected ? "connected" : ""}`}>{connected ? <Check size={16}/> : <Radio size={16}/>}</span>
      <span className="eyebrow">Delivery mode</span>
      <h3>{emptyTitle}</h3>
      <p>{emptyDescription}</p>
      {connected && <div className="projection-delivery-facts">
        <span><small>Integration</small><strong>Connected</strong></span>
        <span><small>Last delivery</small><strong>{lastDelivery}</strong></span>
      </div>}
    </div> : <div className="projection-preview">
      <span className="eyebrow">Current managed projection</span>
      <div className="projection-metrics"><span><strong>{Number(projection.token_estimate ?? 0).toLocaleString()}</strong>estimated tokens</span><span><strong>{Number(projection.token_budget ?? 0).toLocaleString()}</strong>token budget</span></div>
      <pre>{String(value.rendered ?? "")}</pre>
    </div>}
  </Modal>;
}

function MemoryTreeSkeleton() {
  return <div className="memory-skeleton" aria-label="Opening canonical files">{[72, 58, 81, 64, 76, 55].map((width, index) => <span key={index} style={{ width: `${width}%` }}/>)}</div>;
}

function AgentSkeleton() {
  return <div className="agent-skeleton">{[1, 2, 3].map((item) => <span key={item}/>)}</div>;
}
