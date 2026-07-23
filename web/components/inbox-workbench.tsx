"use client";

import { Database, FileDiff, LoaderCircle, Play, Search } from "lucide-react";
import { useState } from "react";
import { apiMutation, type JsonMap } from "@/lib/api";

type Props = {
  data: JsonMap;
  reload: () => Promise<void>;
};

function objects(value: unknown): JsonMap[] {
  return Array.isArray(value) ? value.filter((item): item is JsonMap => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
}

export function InboxWorkbench({ data, reload }: Props) {
  const items = objects(data.items);
  const [source, setSource] = useState("");
  const [inboxId, setInboxId] = useState(String(items[0]?.id ?? ""));
  const [destination, setDestination] = useState("");
  const [result, setResult] = useState<JsonMap>({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function run(path: string, body: JsonMap, mode: string) {
    setBusy(mode); setError("");
    try {
      const response = await apiMutation(path, body);
      setResult(response);
      if (body.apply) await reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally { setBusy(""); }
  }

  return <div className="workspace-grid">
    <section className="collection">
      <div className="collection-head"><span>Uncurated inbox</span><span>{items.length} files</span></div>
      <div className="rows">{items.map((item) => <button className="data-row" key={String(item.id)} onClick={() => setInboxId(String(item.id))}><div><span className="row-kicker">Uncurated evidence</span><strong>{String(item.title ?? item.id)}</strong><p>{String(item.preview ?? "Captured local evidence")}</p></div><span>{inboxId === item.id ? "SELECTED" : "SELECT"}</span></button>)}</div>
      {result.diff ? <article className="composer"><span className="mini-label">Complete-file curation diff</span><h2>{String(result.destination ?? "Preview")}</h2><pre className="command-line">{String(result.diff)}</pre>{result.applied ? <p>Applied to the curated tree.</p> : <p>Preview only. Nothing was written.</p>}</article> : null}
      {Array.isArray(result.results) ? <article className="composer"><span className="mini-label">Harvest result</span><h2>{String(result.count ?? 0)} Markdown files</h2><pre className="command-line">{JSON.stringify(result.results, null, 2)}</pre></article> : null}
      {error ? <div className="alert error">{error}</div> : null}
    </section>
    <aside className="action-panel">
      <div className="composer"><span className="mini-label">Bounded project source</span><h2>Harvest Markdown</h2><p>Choose a file or directory relative to the active project. Preview never writes; apply copies bounded evidence into the inbox.</p><label>Project-relative source<input value={source} onChange={(event) => setSource(event.target.value)} placeholder="notes or docs/decisions.md"/></label><button className="secondary" disabled={!source.trim() || Boolean(busy)} onClick={() => run("/api/v1/harvest", { source, apply: false }, "harvest-preview")}>{busy === "harvest-preview" ? <LoaderCircle className="spin" size={15}/> : <Search size={15}/>}Preview harvest</button><button className="primary" disabled={!source.trim() || Boolean(busy)} onClick={() => run("/api/v1/harvest", { source, apply: true }, "harvest-apply")}>{busy === "harvest-apply" ? <LoaderCircle className="spin" size={15}/> : <Database size={15}/>}Copy to inbox</button></div>
      <div className="composer"><span className="mini-label">Whole-file approval</span><h2>Curate one inbox file</h2><p>Review the entire Markdown diff before applying it. This does not create a per-atom review queue.</p><label>Inbox file<select value={inboxId} onChange={(event) => setInboxId(event.target.value)}><option value="">Select an inbox file</option>{items.map((item) => <option key={String(item.id)} value={String(item.id)}>{String(item.title ?? item.id)}</option>)}</select></label><label>Tree destination<input value={destination} onChange={(event) => setDestination(event.target.value)} placeholder="decisions/release.md"/></label><button className="secondary" disabled={!inboxId || !destination.trim() || Boolean(busy)} onClick={() => run("/api/v1/curate", { inbox_id: inboxId, path: destination, apply: false }, "curate-preview")}>{busy === "curate-preview" ? <LoaderCircle className="spin" size={15}/> : <FileDiff size={15}/>}Preview complete diff</button><button className="primary" disabled={!inboxId || !destination.trim() || !result.diff || Boolean(busy)} onClick={() => run("/api/v1/curate", { inbox_id: inboxId, path: destination, apply: true }, "curate-apply")}>{busy === "curate-apply" ? <LoaderCircle className="spin" size={15}/> : <Play size={15}/>}Apply curated file</button></div>
    </aside>
  </div>;
}
