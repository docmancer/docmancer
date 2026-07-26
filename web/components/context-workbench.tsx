"use client";

import { ArchiveRestore, FileDiff, RefreshCw, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { apiGet, apiMutation, type JsonMap } from "@/lib/api";

type Props = {
  data: JsonMap;
  reload: () => Promise<void>;
  inspect: (item: JsonMap) => Promise<void>;
};

function rows(value: unknown): JsonMap[] {
  return Array.isArray(value)
    ? value.filter((item): item is JsonMap => Boolean(item) && typeof item === "object")
    : [];
}

export function ContextWorkbench({ data, reload, inspect }: Props) {
  const current = (data.current && typeof data.current === "object" ? data.current : {}) as JsonMap;
  const revisions = rows(data.revisions).reverse();
  const topics = rows(current.topics);
  const excluded = rows(current.excluded);
  const freshness = (current.freshness && typeof current.freshness === "object" ? current.freshness : {}) as JsonMap;
  const stale = new Set(rows(freshness.stale_cluster_ids).map(String));
  const [busy, setBusy] = useState("");
  const [plan, setPlan] = useState<JsonMap | null>(null);
  const [diff, setDiff] = useState<JsonMap | null>(null);
  const generatedStates = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const topic of topics) {
      const state = String(topic.ownership_state ?? (topic.synthesized ? "generated-synthesized" : "generated-providerless"));
      counts[state] = (counts[state] ?? 0) + 1;
    }
    return counts;
  }, [topics]);

  const dryRun = async () => {
    setBusy("plan");
    try {
      setPlan(await apiMutation("/api/v1/context/refresh", { dry_run: true, provider: "none" }));
    } finally {
      setBusy("");
    }
  };

  const refresh = async () => {
    setBusy("refresh");
    try {
      await apiMutation("/api/v1/context/refresh", { provider: "none" });
      await reload();
    } finally {
      setBusy("");
    }
  };

  const compare = async (revisionId: string) => {
    setDiff(await apiGet(`/api/v1/context/diff?a=${encodeURIComponent(revisionId)}`));
  };

  const rollback = async (revisionId: string) => {
    setBusy(revisionId);
    try {
      await apiMutation("/api/v1/context/rollback", { revision_id: revisionId });
      await reload();
    } finally {
      setBusy("");
    }
  };

  if (!data.available) {
    return <section className="collection">
      <div className="empty"><ShieldCheck size={24}/><h2>No Context revision yet</h2><p>Preview the loss-safety report first, then build a deterministic providerless revision.</p></div>
      <div className="tool-grid">
        <button className="secondary" disabled={Boolean(busy)} onClick={dryRun}>Preview dry run</button>
        <button className="primary" disabled={Boolean(busy)} onClick={refresh}><RefreshCw size={14}/>Build Context</button>
      </div>
      {plan && <pre className="command-line">{JSON.stringify(plan, null, 2)}</pre>}
    </section>;
  }

  return <div className="workspace-grid">
    <section className="collection">
      <div className="metric-grid">
        <article className="metric"><span>Current revision</span><strong>{String(current.revision_id ?? "").slice(0, 12)}</strong><p>{topics.length} topic clusters</p></article>
        <article className="metric"><span>Freshness</span><strong>{stale.size ? `${stale.size} stale` : "Current"}</strong><p>Only affected clusters rebuild</p></article>
        <article className="metric"><span>Exclusions</span><strong>{excluded.reduce((sum, item) => sum + Number(item.count ?? 0), 0)}</strong><p>Reasons and counts, never hidden content</p></article>
        <article className="metric"><span>History</span><strong>{revisions.length}</strong><p>Rollback always appends</p></article>
      </div>

      <div className="collection-head"><span>Generated topics</span><span>{Object.entries(generatedStates).map(([key, value]) => `${value} ${key}`).join(", ")}</span></div>
      <div className="rows">{topics.map((topic) => {
        const clusterId = String(topic.cluster_id ?? "");
        const sourceCount = Array.isArray(topic.source_addresses)
          ? topic.source_addresses.length
          : Number(topic.member_count ?? 0);
        return <button className="data-row" key={clusterId} onClick={() => inspect(topic)}>
          <div><span className="mini-label">{topic.synthesized ? "Synthesized" : "Providerless"}{stale.has(clusterId) ? " · stale" : ""}</span><h3>{String(topic.topic_label ?? clusterId)}</h3><p>{String(topic.artifact_path ?? "")}</p></div>
          <span>{sourceCount} sources</span>
        </button>;
      })}</div>

      <div className="collection-head"><span>Revision history</span><span>Append-only</span></div>
      <div className="rows">{revisions.map((revision, index) => {
        const id = String(revision.revision_id ?? "");
        const currentId = id === current.revision_id;
        return <article className="data-row" key={id}>
          <div><span className="mini-label">{currentId ? "Current" : `Revision ${revisions.length - index}`}</span><h3>{id.slice(0, 16)}</h3><p>{String(revision.generated_at ?? "")}</p></div>
          {!currentId && <div className="row-actions"><button className="secondary" onClick={() => compare(id)}><FileDiff size={13}/>Diff</button><button className="secondary" disabled={busy === id} onClick={() => rollback(id)}><ArchiveRestore size={13}/>Rollback</button></div>}
        </article>;
      })}</div>
    </section>

    <aside className="action-panel">
      <div className="composer"><span className="mini-label">Safe refresh</span><h2>Rebuild consolidated Context</h2><p>Dry run reports every collapse and holdback before any generated file changes.</p><button className="secondary" disabled={Boolean(busy)} onClick={dryRun}>Preview dry run</button><button className="primary" disabled={Boolean(busy)} onClick={refresh}><RefreshCw size={14}/>Refresh providerless</button></div>
      {plan && <pre className="command-line">{JSON.stringify(plan, null, 2)}</pre>}
      {diff && <pre className="command-line">{JSON.stringify(diff, null, 2)}</pre>}
      {excluded.length > 0 && <div className="composer"><span className="mini-label">Excluded</span>{excluded.map((item, index) => <p key={index}>{String(item.reason ?? "excluded")}: {Number(item.count ?? 0)}</p>)}</div>}
    </aside>
  </div>;
}
