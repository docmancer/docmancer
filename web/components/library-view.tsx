"use client";

import {
  BookOpen, Check, Copy, ExternalLink, FileText, FolderOpen, LoaderCircle,
  Plus, Search, Sparkles,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { apiGet, type JsonMap } from "@/lib/api";
import { messageOf, Modal, Notice, PageHeading, rows } from "./workspace-app";

type Tab = "memory" | "evidence" | "docs";
type TabData = {
  items: JsonMap[];
  nextCursor: string | null;
  indexState: string;
  lastIndexedAt: string;
  refreshError: string;
};

const TABS: { id: Tab; label: string; note: string }[] = [
  { id: "memory", label: "Curated memory", note: "Markdown you chose to keep" },
  { id: "evidence", label: "Agent evidence", note: "What coding agents wrote" },
  { id: "docs", label: "Documentation", note: "Separate technical reference" },
];

const EMPTY_DATA: TabData = { items: [], nextCursor: null, indexState: "idle", lastIndexedAt: "", refreshError: "" };

export function LibraryView() {
  const [tab, setTab] = useState<Tab>(() => {
    if (typeof window === "undefined") return "memory";
    const selected = new URLSearchParams(window.location.search).get("tab");
    return selected === "memory" || selected === "evidence" || selected === "docs" ? selected : "memory";
  });
  const [cache, setCache] = useState<Partial<Record<Tab, TabData>>>({});
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState<JsonMap | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [detailQuery, setDetailQuery] = useState("");
  const [detailResults, setDetailResults] = useState<JsonMap[]>([]);
  const [detailSearchBusy, setDetailSearchBusy] = useState(false);
  const request = useRef<AbortController | null>(null);
  const requestNumber = useRef(0);
  const prefetched = useRef(new Map<string, JsonMap>());

  const load = useCallback(async (
    selectedTab: Tab,
    search: string,
    cursor?: string,
  ) => {
    const sequence = ++requestNumber.current;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    if (cursor) setLoadingMore(true);
    else setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ corpus: selectedTab, limit: "30" });
      if (search) params.set("q", search);
      if (cursor) params.set("cursor", cursor);
      const prefetchKey = `${selectedTab}\0${search}\0${cursor ?? ""}`;
      const cachedPage = cursor ? prefetched.current.get(prefetchKey) : undefined;
      const result = cachedPage ?? await apiGet(`/api/v1/library?${params}`, controller.signal);
      if (cachedPage) prefetched.current.delete(prefetchKey);
      if (sequence !== requestNumber.current) return;
      const incoming = rows(result.items);
      setCache((current) => {
        const previous = current[selectedTab] ?? EMPTY_DATA;
        return {
          ...current,
          [selectedTab]: {
            items: cursor ? [...previous.items, ...incoming] : incoming,
            nextCursor: result.next_cursor ? String(result.next_cursor) : null,
            indexState: String(result.index_state ?? "ready"),
            lastIndexedAt: String(result.last_indexed_at ?? ""),
            refreshError: String(result.refresh_error ?? ""),
          },
        };
      });
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(messageOf(reason));
    } finally {
      if (sequence === requestNumber.current) {
        setLoading(false);
        setLoadingMore(false);
      }
    }
  }, []);

  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("tab", tab);
    window.history.replaceState({}, "", url);
    if (!cache[tab]) queueMicrotask(() => void load(tab, activeQuery));
    return () => request.current?.abort();
  }, [tab, activeQuery, cache, load]);

  const current = cache[tab] ?? EMPTY_DATA;
  useEffect(() => {
    if (current.indexState !== "building") return;
    const timer = window.setTimeout(() => void load(tab, activeQuery), 900);
    return () => window.clearTimeout(timer);
  }, [current.indexState, tab, activeQuery, load]);

  useEffect(() => {
    if (!current.nextCursor || current.indexState === "building") return;
    const cursor = current.nextCursor;
    const key = `${tab}\0${activeQuery}\0${cursor}`;
    if (prefetched.current.has(key)) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ corpus: tab, limit: "30", cursor });
    if (activeQuery) params.set("q", activeQuery);
    void apiGet(`/api/v1/library?${params}`, controller.signal)
      .then((result) => prefetched.current.set(key, result))
      .catch((reason) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          prefetched.current.delete(key);
        }
      });
    return () => controller.abort();
  }, [current.nextCursor, current.indexState, tab, activeQuery]);

  const search = (event: FormEvent) => {
    event.preventDefault();
    const cleaned = query.trim();
    setActiveQuery(cleaned);
    void load(tab, cleaned);
  };
  const chooseTab = (next: Tab) => {
    setTab(next);
    setQuery("");
    setActiveQuery("");
  };
  const openDetail = async (item: JsonMap) => {
    setDetailLoading(true);
    setError("");
    try {
      setDetail(await apiGet(`/api/v1/library/${tab}/${encodeURIComponent(String(item.record_id))}`));
    } catch (reason) {
      setError(messageOf(reason));
    } finally {
      setDetailLoading(false);
    }
  };
  const copyDiagnostics = async () => {
    const diagnostics = detail?.diagnostics;
    await navigator.clipboard.writeText(JSON.stringify(diagnostics ?? {}, null, 2));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  };
  const searchReference = async (event: FormEvent) => {
    event.preventDefault();
    if (!detailQuery.trim() || !detail?.origin) return;
    setDetailSearchBusy(true);
    try {
      const params = new URLSearchParams({ q: detailQuery.trim(), source: String(detail.origin), page_size: "8" });
      const result = await apiGet(`/api/v1/docs?${params}`);
      setDetailResults(rows(result.items));
    } catch (reason) { setError(messageOf(reason)); }
    finally { setDetailSearchBusy(false); }
  };

  return <div className="page library-page">
    <PageHeading eyebrow="Sources you can understand" title="Your memory library" description="Curated memory, agent evidence, and documentation stay separate, searchable, and fast."/>
    <div className="segmented-tabs" role="tablist">{TABS.map((item) =>
      <button key={item.id} className={tab === item.id ? "active" : ""} onClick={() => chooseTab(item.id)}>
        <strong>{item.label}</strong><span>{item.note}</span>
      </button>
    )}</div>
    <section className="library-panel">
      <header className="library-toolbar">
        <div>
          <span className="eyebrow">{TABS.find((item) => item.id === tab)?.label}</span>
          <h2>{heading(tab)}</h2>
          {current.indexState === "building" && <span className="background-status"><LoaderCircle className="spin" size={12}/>Updating in the background</span>}
        </div>
        <form onSubmit={search}><Search size={16}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`Search ${tab === "docs" ? "documentation" : "memory"}`}/></form>
      </header>
      {error && <Notice kind="error">{error}</Notice>}
      {current.refreshError && <Notice kind="error">The Library could not refresh its local summary index. Existing items remain available. {current.refreshError}</Notice>}
      {!current.items.length && loading ? <LibrarySkeleton/> : current.items.length ? <>
        <div className="library-list">
          {current.items.map((item) => <button key={String(item.record_id)} onClick={() => void openDetail(item)}>
            <span className={`file-icon ${tab}`}>{tab === "docs" ? <BookOpen size={17}/> : tab === "memory" ? <FileText size={17}/> : <FolderOpen size={17}/>}</span>
            <div><small>{labelFor(item, tab)}</small><strong>{String(item.title ?? "Untitled item")}</strong><p>{String(item.summary ?? "")}</p></div>
            <span className="row-meta">{metadataFor(item, tab)}</span>
          </button>)}
        </div>
        {current.nextCursor && <div className="load-more"><button className="secondary-btn" disabled={loadingMore} onClick={() => void load(tab, activeQuery, current.nextCursor ?? undefined)}>{loadingMore && <LoaderCircle className="spin" size={14}/>}Load more</button></div>}
      </> : <EmptyLibrary tab={tab} building={current.indexState === "building"}/>}
    </section>
    {detailLoading && <div className="corner-progress"><LoaderCircle className="spin" size={14}/>Opening item</div>}
    {detail && <Modal title={String(detail.title ?? "Library item")} subtitle={labelFor(detail, tab)} close={() => { setDetail(null); setDetailQuery(""); setDetailResults([]); }}>
      <div className="detail-content">
        <div className="detail-summary"><Sparkles size={18}/><div><strong>How Docmancer uses this</strong><p>{meaning(detail, tab)}</p></div></div>
        <section><span className="eyebrow">Readable summary</span><p className="readable-copy">{String(detail.summary || "Docmancer has indexed this source, but it does not have a readable summary yet.")}</p></section>
        <div className="human-meta">
          {Boolean(detail.agent) && <span><strong>Agent</strong>{String(detail.agent)}</span>}
          {Boolean(detail.scope_label) && <span><strong>Scope</strong>{String(detail.scope_label)}</span>}
          {tab === "memory" ? <span><strong>Provenance</strong>{String(detail.provenance_label ?? `${Number(detail.source_count ?? 0).toLocaleString()} sources`)}</span> : <span><strong>{tab === "docs" ? "Pages" : "Evidence"}</strong>{Number(tab === "docs" ? detail.page_count : detail.source_count ?? 0).toLocaleString()} item{Number(tab === "docs" ? detail.page_count : detail.source_count ?? 0) === 1 ? "" : "s"}</span>}
        </div>
        {tab === "docs" && <DocumentationDetail detail={detail} query={detailQuery} setQuery={setDetailQuery} results={detailResults} busy={detailSearchBusy} search={searchReference}/>}
        <button className="diagnostic-copy" onClick={copyDiagnostics}>{copied ? <Check size={14}/> : <Copy size={14}/>} {copied ? "Diagnostic information copied" : "Copy diagnostic information"}</button>
      </div>
    </Modal>}
  </div>;
}

function DocumentationDetail({ detail, query, setQuery, results, busy, search }: {
  detail: JsonMap; query: string; setQuery: (value: string) => void; results: JsonMap[];
  busy: boolean; search: (event: FormEvent) => void;
}) {
  const formats = Array.isArray(detail.formats) ? detail.formats.map(String) : [];
  const surfaces = Array.isArray(detail.access_surfaces) ? detail.access_surfaces.map(String) : [];
  return <div className="documentation-detail">
    <section><span className="eyebrow">Reference details</span><div className="doc-facts">
      <div><strong>Origin</strong><span>{String(detail.origin_label ?? "Indexed reference")}</span></div>
      <div><strong>Ingested</strong><span>{humanDate(detail.ingested_at)}</span></div>
      <div><strong>Last indexed</strong><span>{humanDate(detail.last_indexed_at ?? detail.ingested_at)}</span></div>
      <div><strong>Refresh state</strong><span>{String(detail.refresh_state ?? "Current").replaceAll("-", " ")}</span></div>
      <div><strong>Coverage</strong><span>{Number(detail.page_count ?? 0).toLocaleString()} pages, {Number(detail.section_count ?? 0).toLocaleString()} sections</span></div>
      <div><strong>Formats</strong><span>{formats.length ? formats.join(", ") : "Markdown"}</span></div>
    </div></section>
    <section><span className="eyebrow">Available from</span><div className="access-list">{surfaces.map((surface) => <span key={surface}><Check size={13}/>{surface}</span>)}</div><p className="context-policy">{String(detail.context_policy ?? "Documentation remains separate from personal memory and Context.")}</p></section>
    <section className="reference-search"><span className="eyebrow">Search this reference</span><form onSubmit={search}><Search size={15}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Ask a technical question about this documentation"/><button className="primary-btn" disabled={busy || !query.trim()}>{busy && <LoaderCircle className="spin" size={14}/>}Search</button></form>
      {results.length > 0 && <div className="reference-results">{results.map((item, index) => <article key={String(item.id ?? index)}><strong>{String(item.metadata && typeof item.metadata === "object" ? (item.metadata as JsonMap).title ?? `Result ${index + 1}` : `Result ${index + 1}`)}</strong><p>{String(item.text ?? "").slice(0, 420)}</p></article>)}</div>}
    </section>
    {String(detail.origin ?? "").startsWith("http") && <a className="text-btn" href={String(detail.origin)} target="_blank" rel="noreferrer">Open original documentation <ExternalLink size={14}/></a>}
  </div>;
}

function LibrarySkeleton() {
  return <div className="library-skeleton" aria-label="Loading Library">{Array.from({ length: 6 }, (_, index) =>
    <div key={index}><span/><div><i/><i/></div></div>
  )}</div>;
}

function EmptyLibrary({ tab, building }: { tab: Tab; building: boolean }) {
  if (building) return <div className="purposeful-empty compact"><LoaderCircle className="spin" size={20}/><h3>Preparing your Library</h3><p>You can keep using Docmancer while the local summary index is built in the background.</p></div>;
  const copy = tab === "memory"
    ? ["No curated memory yet", "Create durable memory from the useful evidence Docmancer discovers.", "docmancer setup"]
    : tab === "evidence"
      ? ["No agent evidence indexed", "Connect your coding agents and index what they have already written.", "docmancer setup"]
      : ["No documentation indexed", "Add public or local documentation without mixing it into personal memory.", "docmancer ingest <url-or-path>"];
  return <div className="purposeful-empty"><div><Plus size={20}/></div><h3>{copy[0]}</h3><p>{copy[1]}</p><code>{copy[2]}</code></div>;
}

function heading(tab: Tab) {
  if (tab === "memory") return "Memory you chose to keep";
  if (tab === "evidence") return "What your agents have already written";
  return "Technical reference, kept separate";
}
function labelFor(item: JsonMap, tab: Tab) {
  return String(item.kind ?? (tab === "memory" ? "Curated memory" : tab === "docs" ? "Documentation" : "Agent evidence")).replaceAll("-", " ");
}
function metadataFor(item: JsonMap, tab: Tab) {
  if (tab === "docs") return `${Number(item.section_count ?? 0).toLocaleString()} sections`;
  if (item.agent) return String(item.agent).replaceAll("-", " ");
  if (item.updated_at) return new Date(String(item.updated_at)).toLocaleDateString();
  return "";
}
function meaning(item: JsonMap, tab: Tab) {
  if (tab === "memory") return "Docmancer treats this as durable guidance that connected coding agents can recall in future sessions.";
  if (tab === "docs") return "Docmancer searches this technical reference when you or a connected coding agent asks for documentation. It remains separate from personal memory.";
  return `This is source evidence${item.agent ? ` from ${String(item.agent)}` : ""}. Docmancer keeps it attributable instead of treating repeated text as automatically true.`;
}
function humanDate(value: unknown) {
  if (!value) return "Not available";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString(undefined, { dateStyle: "medium" });
}
