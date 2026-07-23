"use client";

import { AlertTriangle, Check, ChevronDown, Copy, ExternalLink, Eye, LoaderCircle, Pencil, ShieldCheck, Trash2, X } from "lucide-react";
import { useState } from "react";
import type { JsonMap } from "@/lib/api";
import type { ViewKey } from "./workspace-app";
import { MarkdownContent } from "./markdown-content";

type Mutate = (path: string, body: JsonMap, success: string, method?: string) => Promise<JsonMap | undefined>;

export type InspectorState = {
  item: JsonMap;
  detail: JsonMap;
  loading?: boolean;
  error?: string;
};

export function RecordInspector({
  view,
  state,
  close,
  mutate,
  reload,
}: {
  view: ViewKey;
  state: InspectorState;
  close: () => void;
  mutate: Mutate;
  reload: () => Promise<void>;
}) {
  const value = Object.keys(state.detail).length ? state.detail : state.item;
  const [draft, setDraft] = useState(String(value.markdown ?? value.content ?? value.text ?? value.rendered ?? ""));
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<"view" | "edit">("view");
  const [editorTab, setEditorTab] = useState<"write" | "preview">("write");
  const [confirmTreeTrash, setConfirmTreeTrash] = useState(false);
  const title = recordTitle(value, view);
  const subtitle = recordSubtitle(value, view);

  async function run(operation: () => Promise<unknown>, shouldClose = false) {
    setBusy(true);
    try {
      const result = await operation();
      if (result === undefined) return;
      await reload();
      if (shouldClose) close();
      else setMode("view");
    } finally {
      setBusy(false);
    }
  }

  const identifier = String(value.address ?? value.record_id ?? value.atom_id ?? value.id ?? "");
  const sourceKey = String(value.source_key ?? "");
  const contextKind = String(value.view_kind ?? "");
  const canEditMemory = view === "memory" && Boolean(identifier);
  const canEditContext = view === "context" && contextKind === "context-record" && Boolean(identifier);
  const canEditSource = view === "sources" && Boolean(sourceKey && value.content_hash);
  const canOperateTree = view === "tree" && Boolean(value.address && value.content_hash);

  return <div className="drawer-backdrop" onMouseDown={close}>
    <aside className="drawer" role="dialog" aria-modal="true" aria-label={`Inspect ${title}`} onMouseDown={(event) => event.stopPropagation()}>
      <header className="drawer-header">
        <div><span className="mini-label">{humanise(view)} detail</span><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>
        <button className="icon-button" onClick={close} aria-label="Close inspector"><X size={16}/></button>
      </header>

      <div className="drawer-scroll">{state.loading ? <div className="drawer-loading"><LoaderCircle className="spin"/><span>Loading the current local record</span></div> : state.error ? <div className="drawer-error"><AlertTriangle size={17}/>{state.error}</div> : <>
        {(canEditMemory || canEditContext || canEditSource) && mode === "edit" ? <div className="drawer-editor">
          <div className="editor-toolbar"><span>{canEditSource ? "File contents" : "Markdown content"}</span><div className="segmented"><button className={editorTab === "write" ? "active" : ""} onClick={() => setEditorTab("write")}><Pencil size={13}/>Write</button><button className={editorTab === "preview" ? "active" : ""} onClick={() => setEditorTab("preview")}><Eye size={13}/>Preview</button></div></div>
          {editorTab === "write" ? <textarea aria-label="Markdown editor" autoFocus value={draft} onChange={(event) => setDraft(event.target.value)} /> : <div className="editor-preview"><MarkdownContent value={draft}/></div>}
          <div className="drawer-actions">
            <button className="primary" disabled={busy || !draft.trim()} onClick={() => void run(async () => {
              if (canEditSource) await mutate("/api/v1/source", { source_key: sourceKey, content: draft, expected_hash: value.content_hash }, "Source saved and reindexed.", "PUT");
              else if (canEditContext) await mutate(`/api/v1/context/${encodeURIComponent(identifier)}`, { action: "edit", text: draft }, "Context entry updated.");
              else await mutate(`/api/v1/memory/${encodeURIComponent(identifier)}`, { action: "edit", text: draft }, "Memory atom updated.");
            }, true)}><Check size={14}/>Save changes</button>
            <button className="secondary" onClick={() => setMode("view")}>Cancel</button>
          </div>
        </div> : <>
          {view === "audit" && value.view_kind === "secret-finding" && (
            <AuditFinding value={value}/>
          )}
          {view === "intelligence" && (
            <IntelligenceDetail value={value}/>
          )}
          {view === "tree" && <TreeReadingMetadata value={value}/>}
          {(value.markdown || value.content || value.text || value.rendered) && view !== "audit" && <section className="drawer-section content-section"><div className="section-heading"><h3>{canEditSource ? "Current file" : "Content"}</h3><button className="copy-button" onClick={() => void navigator.clipboard.writeText(String(value.markdown ?? value.content ?? value.text ?? value.rendered ?? ""))}><Copy size={13}/>Copy</button></div><MarkdownContent value={String(value.markdown ?? value.content ?? value.text ?? value.rendered)}/></section>}
          <details className="drawer-details"><summary><span>Technical details</span><ChevronDown size={14}/></summary><div><Metadata value={value}/></div></details>
          {Array.isArray(value.matches) && value.matches.length > 0 && <section className="drawer-section"><h3>Search matches</h3><div className="match-list">{value.matches.map((match, index) => <article key={index}><span>Lines {String((match as JsonMap).line_start ?? "?")} to {String((match as JsonMap).line_end ?? "?")}</span><p>{String((match as JsonMap).text ?? "")}</p></article>)}</div></section>}
        </>}
      </>}</div>

      {!state.loading && !state.error && <footer className="drawer-footer">
        <div className="drawer-actions">
          {(canEditMemory || canEditContext || canEditSource) && mode === "view" && <button className="secondary" onClick={() => setMode("edit")}><Pencil size={14}/>Edit</button>}
          {canOperateTree && <button className="secondary" disabled={busy} onClick={() => void run(() => mutate("/api/v1/tree", { action: "open-editor", address: value.address }, "Opened the canonical file in your editor."))}><ExternalLink size={14}/>Open in editor</button>}
          {canOperateTree && <button className="secondary" disabled={busy} onClick={() => { const path = window.prompt("Move to project-relative path", String(value.path ?? "")); if (path) void run(() => mutate("/api/v1/tree", { action: "move", address: value.address, path, expected_hash: value.content_hash }, "Memory file moved."), true); }}><Pencil size={14}/>Move</button>}
          {canOperateTree && <button className="secondary" disabled={busy} onClick={() => { const path = window.prompt("Duplicate to project-relative path"); if (path) void run(() => mutate("/api/v1/tree", { action: "duplicate", address: value.address, path, expected_hash: value.content_hash }, "Memory file duplicated."), true); }}><Copy size={14}/>Duplicate</button>}
          {view === "memory" && identifier && <button className="secondary" disabled={busy} onClick={() => void run(() => mutate(`/api/v1/memory/${encodeURIComponent(identifier)}`, { action: "promote" }, "Memory promoted into prepared context."))}><ShieldCheck size={14}/>Promote</button>}
          {view === "context" && contextKind === "context-pack" && <><button className="secondary" disabled={busy} onClick={() => void run(() => mutate(`/api/v1/context/${encodeURIComponent(String(value.pack_id))}`, { action: "distill" }, "Context distillation completed."))}>Distill</button><button className="secondary" disabled={busy} onClick={() => void run(() => mutate(`/api/v1/context/${encodeURIComponent(String(value.pack_id))}`, { action: "share" }, "Team proposal created."))}>Share</button></>}
          {view === "context" && contextKind === "context-proposal" && <><button className="primary" disabled={busy} onClick={() => void run(() => mutate(`/api/v1/context/${encodeURIComponent(String(value.proposal_id))}`, { action: "approve" }, "Proposal approved."), true)}>Approve</button><button className="secondary" disabled={busy} onClick={() => void run(() => mutate(`/api/v1/context/${encodeURIComponent(String(value.proposal_id))}`, { action: "reject" }, "Proposal rejected."), true)}>Reject</button></>}
          {view === "intelligence" && Boolean(value.relation_id) && <><button className="primary" disabled={busy} onClick={() => void run(() => mutate(`/api/v1/intelligence/${encodeURIComponent(String(value.relation_id))}`, { action: "resolve", resolution: "keep-both" }, "Both memories retained."), true)}>Keep both</button><button className="secondary" disabled={busy} onClick={() => void run(() => mutate(`/api/v1/intelligence/${encodeURIComponent(String(value.relation_id))}`, { action: "resolve", resolution: "dismiss" }, "Suggestion dismissed."), true)}>Dismiss</button></>}
          {view === "team" && Boolean(value.proposal_id) && <><button className="primary" disabled={busy} onClick={() => void run(() => mutate(`/api/v1/cloud/team/${encodeURIComponent(String(value.proposal_id))}/review`, { decision: "approve" }, "Team proposal approved."), true)}>Approve</button><button className="secondary" disabled={busy} onClick={() => void run(() => mutate(`/api/v1/cloud/team/${encodeURIComponent(String(value.proposal_id))}/review`, { decision: "reject" }, "Team proposal rejected."), true)}>Reject</button></>}
          {view === "docs" && typeof value.source === "string" && value.source.startsWith("http") && <a className="secondary link-control" href={value.source} target="_blank" rel="noreferrer"><ExternalLink size={14}/>Open original</a>}
        </div>
        <div className="drawer-actions">
          {canEditMemory && <button className="danger-outline" disabled={busy} onClick={() => { if (window.confirm(`Forget memory ${identifier}? The source file and index will be updated.`)) void run(() => mutate(`/api/v1/memory/${encodeURIComponent(identifier)}`, { action: "forget", confirmation: identifier }, "Memory forgotten."), true); }}><Trash2 size={14}/>Forget</button>}
          {canEditContext && <button className="danger-outline" disabled={busy} onClick={() => { if (window.confirm("Remove this prepared context entry?")) void run(() => mutate(`/api/v1/context/${encodeURIComponent(identifier)}`, { action: "remove", confirmation: identifier }, "Context entry removed."), true); }}><Trash2 size={14}/>Remove</button>}
          {canEditSource && <button className="danger-outline" disabled={busy} onClick={() => { if (window.confirm(`Delete ${String(value.path)}? This removes the file from disk.`)) void run(() => mutate("/api/v1/source", { source_key: sourceKey, expected_hash: value.content_hash, confirmation: sourceKey }, "Source deleted and index rebuilt.", "DELETE"), true); }}><Trash2 size={14}/>Delete file</button>}
          {canOperateTree && !confirmTreeTrash && <button className="danger-outline" disabled={busy} onClick={() => setConfirmTreeTrash(true)}><Trash2 size={14}/>Trash</button>}
          {view === "devices" && Boolean(value.device_id ?? value.id) && <button className="danger-outline" disabled={busy} onClick={() => { const deviceId = String(value.device_id ?? value.id); if (window.confirm(`Revoke device ${deviceId}? It will no longer be able to sync.`)) void run(() => mutate(`/api/v1/cloud/devices/${encodeURIComponent(deviceId)}/revoke`, { confirmation: deviceId }, "Device revoked."), true); }}><Trash2 size={14}/>Revoke device</button>}
        </div>
      </footer>}
      {canOperateTree && confirmTreeTrash && <section className="destructive-preview" aria-label="Confirm recoverable trash operation"><div><span className="mini-label">Recoverable destructive operation</span><h3>Move this file to trash?</h3><dl><div><dt>Target</dt><dd>{String(value.path ?? value.address)}</dd></div><div><dt>Scope</dt><dd>{String(value.scope ?? "project")}</dd></div><div><dt>Expected hash</dt><dd><code>{String(value.content_hash)}</code></dd></div><div><dt>Consequence</dt><dd>The current path stops resolving. Docmancer keeps a restore token and refuses to overwrite a newer file during restore.</dd></div></dl></div><div className="drawer-actions"><button className="secondary" disabled={busy} onClick={() => setConfirmTreeTrash(false)}>Cancel</button><button className="danger-outline" disabled={busy} onClick={() => void run(() => mutate("/api/v1/tree", { action: "trash", address: value.address, expected_hash: value.content_hash }, "Memory moved to recoverable trash."), true)}><Trash2 size={14}/>Move to trash</button></div></section>}
    </aside>
  </div>;
}

function AuditFinding({ value }: { value: JsonMap }) {
  const occurrences = Array.isArray(value.occurrences) ? value.occurrences.filter(isObject) : [];
  return <section className="audit-finding-detail">
    <div className={`risk-banner severity-${String(value.severity ?? "medium")}`}><AlertTriangle size={18}/><div><span>{String(value.severity ?? "finding")} severity</span><strong>{String(value.type ?? "Possible secret")}</strong><p>The value remains masked. Rotate it if it is real, remove it from the source, then rebuild memory.</p></div></div>
    <div className="occurrence-list"><h3>Found in {occurrences.length} {occurrences.length === 1 ? "location" : "locations"}</h3>{occurrences.map((occurrence, index) => <article key={`${String(occurrence.source_path)}:${String(occurrence.line)}:${index}`}>
      <div className="location-line"><strong>{filename(String(occurrence.source_path ?? "Unknown file"))}</strong><span>Line {String(occurrence.line ?? "?")}</span></div>
      <code className="full-path" title={String(occurrence.source_path ?? "")}>{String(occurrence.source_path ?? "")}</code>
      <pre>{String(occurrence.masked_excerpt ?? "[SECRET]")}</pre>
      <div className="occurrence-meta"><span>{humanise(String(occurrence.agent ?? "local"))}</span><span>{humanise(String(occurrence.scope ?? "memory"))}</span></div>
    </article>)}</div>
    <div className="remediation"><strong>Recommended next step</strong><ol><li>Confirm whether this is a live credential.</li><li>Rotate or revoke it at the provider.</li><li>Delete it from the source file, then run <code>docmancer harvest</code> and <code>docmancer reindex</code>.</li></ol></div>
  </section>;
}

function IntelligenceDetail({ value }: { value: JsonMap }) {
  const raw = Array.isArray(value.members) ? value.members : Array.isArray(value.samples) ? value.samples : [];
  const entries = raw.filter(isObject);
  if (!entries.length) return null;
  const conflict = value.intelligence_kind === "conflict-group";
  return <section className="drawer-section intelligence-detail"><div className="section-heading"><h3>{conflict ? "Evidence to compare" : "Recent memory samples"}</h3><span>{entries.length} shown</span></div><div className="evidence-list">{entries.map((entry, index) => <article key={String(entry.atom_id ?? entry.node_id ?? index)}><div><span>{humanise(String(entry.memory_type ?? "memory"))}</span>{entry.value ? <strong>{String(entry.value)}</strong> : null}</div><MarkdownContent value={String(entry.text ?? "No text available.")} compact/></article>)}</div></section>;
}

function TreeReadingMetadata({ value }: { value: JsonMap }) {
  const outline = Array.isArray(value.outline) ? value.outline.filter(isObject) : [];
  const relations = Array.isArray(value.relations) ? value.relations.filter(isObject) : [];
  const backlinks = Array.isArray(value.backlinks) ? value.backlinks.filter(isObject) : [];
  const properties: JsonMap = {
    type: value.type,
    scope: value.scope,
    authority: value.authority,
    status: value.status,
    project_id: value.project_id,
    tags: value.tags,
    sources: value.sources,
    revision_id: value.revision_id,
  };
  return <>
    <section className="drawer-section reading-properties">
      <h3>Properties</h3>
      <Metadata value={properties}/>
    </section>
    {outline.length > 0 && <section className="drawer-section reading-links"><h3>Outline</h3><ol>{outline.map((item, index) => <li key={`${String(item.line)}:${index}`}><span style={{ paddingLeft: `${Math.max(0, Number(item.level ?? 1) - 1) * 12}px` }}>{String(item.title ?? "Untitled heading")}</span><code>line {String(item.line ?? "?")}</code></li>)}</ol></section>}
    {relations.length > 0 && <section className="drawer-section reading-links"><h3>Relations</h3><ul>{relations.map((item, index) => <li key={`${String(item.type)}:${String(item.target)}:${index}`}><span>{humanise(String(item.type ?? "links to"))}</span><code>{String(item.target ?? "")}</code></li>)}</ul></section>}
    {backlinks.length > 0 && <section className="drawer-section reading-links"><h3>Backlinks</h3><ul>{backlinks.map((item, index) => <li key={`${String(item.address)}:${index}`}><span>{String(item.title ?? "Memory file")}</span><code>{String(item.address ?? "")}</code></li>)}</ul></section>}
  </>;
}

function Metadata({ value }: { value: JsonMap }) {
  const hidden = new Set(["markdown", "content", "text", "rendered", "matches", "atoms", "operations", "metadata_json", "record_ids", "outline", "relations", "backlinks"]);
  const entries = Object.entries(value).filter(([key, item]) => !hidden.has(key) && item !== null && item !== "").slice(0, 24);
  return <dl className="inspector-definitions">{entries.map(([key, item]) => <div key={key}><dt>{humanise(key)}</dt><dd title={displayValue(item)}>{displayValue(item)}</dd></div>)}</dl>;
}

function recordTitle(value: JsonMap, view: ViewKey): string {
  if (view === "sources") return sourceTitle(value);
  if (view === "memory" || (view === "context" && value.view_kind === "context-record")) return semanticTitle(String(value.text ?? value.title ?? "Memory atom"));
  if (view === "context" && value.view_kind === "context-proposal") return `Review changes for ${String(value.context_name ?? humanise(String(value.pack_id ?? "context")))}`;
  if (view === "audit" && value.view_kind === "secret-finding") return String(value.type ?? "Possible secret");
  if (view === "audit" && value.agent) return `${humanise(String(value.agent))} ${String(value.scope ?? "hook")}`;
  if (view === "intelligence" && value.intelligence_kind === "recent-source") { const title = String(value.source_title ?? ""); const sample = Array.isArray(value.samples) ? value.samples.find(isObject) : undefined; return title && !["promoted memory", "manual memory", "memory"].includes(title.toLowerCase()) ? title : String(sample?.text ?? filename(String(value.source_path ?? "Recent source"))).slice(0, 120); }
  if (view === "intelligence" && value.intelligence_kind === "conflict-group") return String(value.claim_subject ?? value.claim_key ?? "Conflicting memories");
  return String(value.name ?? value.title ?? value.text ?? value.source ?? value.kind ?? value.id ?? `${humanise(view)} record`).slice(0, 180);
}

function recordSubtitle(value: JsonMap, view: ViewKey): string {
  if (view === "sources") return String(value.path ?? "");
  return String(value.source_path ?? value.scope ?? value.memory_type ?? value.state ?? "");
}

function sourceTitle(value: JsonMap): string {
  const title = String(value.title ?? "");
  if (title && !["manual memory", "promoted memory", "memory", "memory atom", "docmancer memory"].includes(title.toLowerCase())) return title;
  const name = String(value.path ?? "").split("/").pop() ?? "Source file";
  return name.replace(/-[a-f0-9]{8}(?=\.[^.]+$)/, "").replace(/\.[^.]+$/, "").replaceAll("-", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function semanticTitle(raw: string): string {
  const value = raw.replace(/^#{1,6}\s+/gm, "").replace(/[*_`>#]/g, "").replace(/\s+/g, " ").trim();
  const parts = value.split(/:\s+/).map((part) => part.trim()).filter(Boolean);
  const instructionIndex = parts.findIndex((part) => /agent instructions/i.test(part));
  if (instructionIndex >= 0) {
    const parent = parts[instructionIndex].replace(/^.*?agent instructions\s*/i, "").trim();
    const candidate = parts[instructionIndex + 1] ?? "";
    return (candidate.length > 0 && candidate.length <= 58 && parts.length > instructionIndex + 2 ? candidate : parent) || "Memory atom";
  }
  const meaningful = parts.filter((part) => !/^(promoted memory|manual memory|memory atom)$/i.test(part));
  const genericHeading = /^(user preferences?|user profile|what.?s in memory|older memory topics)$/i.test(meaningful[0] ?? "") || /^what.?s in memory\b/i.test(meaningful[0] ?? "");
  return (genericHeading ? meaningful[1] : meaningful[0] ?? value).slice(0, 120);
}

function humanise(value: string): string { return value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase()); }
function displayValue(value: unknown): string {
  if (value === undefined || value === null || value === "") return "Not set";
  if (Array.isArray(value)) return `${value.length} items`;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
function isObject(value: unknown): value is JsonMap { return Boolean(value) && typeof value === "object" && !Array.isArray(value); }
function filename(value: string): string { return value.split("/").pop() || value; }
