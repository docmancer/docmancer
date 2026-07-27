"use client";

import {
  ArrowRight, Check, Clock3, Cloud, Copy, Database, FileDiff,
  Radio, RefreshCw, RotateCcw, ShieldCheck, Sparkles,
} from "lucide-react";
import { useEffect, useState } from "react";
import { apiGet, apiJobMutation, apiMutation, apiStartJob, waitForJob, type JsonMap } from "@/lib/api";
import { CommandRow, messageOf, Modal, Notice, objectAt, rows } from "./workspace-app";
import { SetupFlow } from "./settings-view";

type Tab = "overview" | "knowledge" | "delivery" | "history";
type Props = { data: JsonMap; reload: () => Promise<void>; inspect: (item: JsonMap) => Promise<void> };

export function ContextWorkbench({ data, reload }: Props) {
  const [tab, setTab] = useState<Tab>(() => {
    if (typeof window === "undefined") return "overview";
    const selected = new URLSearchParams(window.location.search).get("tab");
    return selected === "overview" || selected === "knowledge" || selected === "delivery" || selected === "history" ? selected : "overview";
  });
  const [common, setCommon] = useState<JsonMap>({});
  const [delivery, setDelivery] = useState<JsonMap>({});
  const [cloud, setCloud] = useState<JsonMap>({});
  const [timeline, setTimeline] = useState<JsonMap>({});
  const [detail, setDetail] = useState<JsonMap | null>(null);
  const [setup, setSetup] = useState<JsonMap | null>(null);
  const [plan, setPlan] = useState<JsonMap | null>(null);
  const [distillation, setDistillation] = useState<JsonMap | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (tab === "knowledge" && !Object.keys(common).length) apiGet("/api/v1/common").then(setCommon).catch((reason) => setError(messageOf(reason)));
    if (tab === "delivery" && !Object.keys(delivery).length) Promise.all([
      apiGet("/api/v1/delivery"),
      apiGet("/api/v1/cloud").catch(() => ({})),
    ]).then(([deliveryData, cloudData]) => { setDelivery(deliveryData); setCloud(cloudData); }).catch((reason) => setError(messageOf(reason)));
    if (tab === "history" && !Object.keys(timeline).length) apiGet("/api/v1/timeline").then(setTimeline).catch((reason) => setError(messageOf(reason)));
  }, [tab, common, delivery, timeline]);

  const current = objectAt(data, "current");
  const topics = rows(current.topics);
  const revisions = rows(data.revisions).reverse();
  const counts = objectAt(data, "counts");
  const atoms = Number(counts.atoms ?? 0);
  const freshness = objectAt(current, "freshness");
  const stale = Array.isArray(freshness.stale_cluster_ids) ? freshness.stale_cluster_ids.length : 0;

  const preview = async () => {
    setBusy("preview"); setError("");
    try { setPlan(await apiMutation("/api/v1/context/refresh", { dry_run: true, provider: "none" })); }
    catch (reason) { setError(messageOf(reason)); } finally { setBusy(""); }
  };
  const build = async () => {
    setBusy("build"); setError("");
    try { await apiJobMutation("/api/v1/context/refresh", { provider: "none" }, () => undefined); await reload(); }
    catch (reason) { setError(messageOf(reason)); } finally { setBusy(""); }
  };
  const distill = async () => {
    if (!distillation) return;
    setBusy("distill-run"); setError("");
    try {
      const job = await apiStartJob("/api/v1/context/refresh", {
        provider: String(distillation.provider),
        model: distillation.model ? String(distillation.model) : undefined,
      });
      setDistillation(null);
      setBusy("");
      void waitForJob(job).then(reload).catch((reason) => setError(messageOf(reason)));
    } catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(""); }
  };
  const openSetup = async () => {
    try { setSetup(await apiGet("/api/v1/agent/setup")); } catch (reason) { setError(messageOf(reason)); }
  };
  const openDistillation = async () => {
    setBusy("distill"); setError("");
    try { setDistillation(await apiGet("/api/v1/context/distillation-preview")); }
    catch (reason) { setError(messageOf(reason)); } finally { setBusy(""); }
  };

  if (!data.available) return <section className="context-empty">
    <div className="empty-illustration"><span/><span/><span/><Sparkles size={22}/></div>
    <span className="eyebrow">{atoms ? "Memory found. Context not built." : "First run"}</span>
    <h2>{atoms ? "Turn scattered memory into shared Context" : "Let Docmancer discover what your agents know"}</h2>
    <p>{atoms
      ? "Preview the consolidation first, then create a revisioned Context that connected agents can carry."
      : "Run setup to index the memory and instructions your coding agents have already written. Then Docmancer can build shared Context."}</p>
    {error && <Notice kind="error">{error}</Notice>}
    {atoms ? <><div className="empty-actions"><button className="primary-btn distill-button" disabled={Boolean(busy)} onClick={openDistillation}><Sparkles size={16}/>Distill memory with AI</button><button className="secondary-btn" disabled={Boolean(busy)} onClick={preview}>Build without AI</button></div></>
      : <div className="empty-actions"><button className="primary-btn" onClick={openSetup}>Run Docmancer setup <ArrowRight size={15}/></button></div>}
    <CommandRow title={atoms ? "CLI equivalent" : "Start from the terminal"} command={atoms ? "docmancer context refresh --dry-run" : "docmancer setup"} note={atoms ? "Preview consolidation without writing a revision." : "Index memory and install detected integrations."}/>
    {plan && <Modal title="Build Context locally without AI" subtitle="No files have been changed." close={() => setPlan(null)}><PlanSummary plan={plan} onBuild={build} close={() => setPlan(null)}/></Modal>}
    {distillation && <DistillationPreview preview={distillation} busy={busy === "distill-run"} run={distill} close={() => setDistillation(null)}/>}
    {setup && <Modal title="Connect Docmancer" subtitle="Index existing memory and install skills for your coding agents." close={() => setSetup(null)}><SetupFlow initial={setup} onComplete={() => { setSetup(null); void reload(); }}/></Modal>}
  </section>;

  const tabs: { id: Tab; label: string; icon: typeof Database }[] = [
    { id: "overview", label: "Overview", icon: Sparkles },
    { id: "knowledge", label: "Knowledge", icon: Database },
    { id: "delivery", label: "Delivery", icon: Radio },
    { id: "history", label: "History", icon: Clock3 },
  ];
  return <div className="context-workbench">
    <div className="context-toolbar"><div className="context-tabs">{tabs.map(({ id, label, icon: Icon }) => <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}><Icon size={15}/>{label}</button>)}</div>{(tab === "overview" || tab === "knowledge") && <button className="primary-btn distill-button" disabled={Boolean(busy)} onClick={openDistillation}><Sparkles size={15}/>Distill memory with AI</button>}</div>
    {error && <Notice kind="error">{error}</Notice>}
    {tab === "overview" && <Overview current={current} topics={topics} revisions={revisions} stale={stale} onPreview={preview} onBuild={build} busy={busy} setDetail={setDetail}/>}
    {tab === "knowledge" && <Knowledge data={common} fallback={topics} setDetail={setDetail}/>}
    {tab === "delivery" && <Delivery data={delivery} cloud={cloud} setDetail={setDetail}/>}
    {tab === "history" && <HistoryView data={timeline} revisions={revisions} reload={reload} setDetail={setDetail}/>}
    {plan && <Modal title="Build Context locally without AI" subtitle="No files have been changed." close={() => setPlan(null)}><PlanSummary plan={plan} onBuild={build} close={() => setPlan(null)}/></Modal>}
    {distillation && <DistillationPreview preview={distillation} busy={busy === "distill-run"} run={distill} close={() => setDistillation(null)}/>}
    {detail && <ContextDetail item={detail} close={() => setDetail(null)}/>}
  </div>;
}

function Overview({ current, topics, revisions, stale, onPreview, onBuild, busy, setDetail }: {
  current: JsonMap; topics: JsonMap[]; revisions: JsonMap[]; stale: number;
  onPreview: () => void; onBuild: () => void; busy: string; setDetail: (item: JsonMap) => void;
}) {
  return <div className="context-overview">
    <section className="context-status-card">
      <div className="context-status-head"><span className="context-ready"><Check size={16}/></span><div><span className="eyebrow">Current Context</span><h2>Ready for connected agents</h2><p>Revision {String(current.revision_id ?? "").slice(0, 12)} contains {topics.length} consolidated knowledge topics.</p></div></div>
      <div className="context-metrics"><div><strong>{topics.length}</strong><span>Knowledge topics</span></div><div><strong>{stale || "0"}</strong><span>Need refresh</span></div><div><strong>{revisions.length}</strong><span>Safe revisions</span></div></div>
      <div className="context-actions"><button className="secondary-btn" disabled={Boolean(busy)} onClick={onPreview}>Preview providerless changes</button><button className="secondary-btn" disabled={Boolean(busy)} onClick={onBuild}><RefreshCw size={14}/>Refresh providerless Context</button></div>
    </section>
    <section className="topic-preview"><div className="section-heading"><div><span className="eyebrow">What agents can carry</span><h2>Knowledge in this revision</h2></div><span>{topics.length} topics</span></div>
      {topics.length ? <div className="topic-grid">{topics.slice(0, 6).map((topic, index) => <button key={String(topic.cluster_id ?? index)} onClick={() => setDetail(topic)}><small>{topic.has_readable_summary ? "Readable Context" : "Needs AI distillation"}</small><strong>{String(topic.title ?? `Knowledge topic ${index + 1}`)}</strong><p>{readableSummary(topic)}</p><span>{Number(topic.source_count ?? 0)} sources <ArrowRight size={13}/></span></button>)}</div>
        : <div className="purposeful-empty compact"><h3>This revision has no topics</h3><p>Refresh Context after indexing more agent memory.</p></div>}
    </section>
  </div>;
}

function Knowledge({ data, fallback, setDetail }: { data: JsonMap; fallback: JsonMap[]; setDetail: (item: JsonMap) => void }) {
  const items = rows(data.items ?? data.records);
  const display = fallback.length ? fallback : items;
  return <section className="context-section"><div className="section-heading"><div><span className="eyebrow">Cross-agent knowledge</span><h2>Patterns your agents repeatedly recorded</h2><p>Recurrence is useful evidence, not automatic consensus or truth.</p></div></div>
    {display.length ? <div className="knowledge-list">{display.map((item, index) => <button key={String(item.id ?? item.cluster_id ?? index)} onClick={() => setDetail(item)}><span className="recurrence">{Number(item.source_count ?? item.member_count ?? (Array.isArray(item.sources) ? item.sources.length : 1))}×</span><div><strong>{String(item.title ?? item.topic_label ?? `Knowledge pattern ${index + 1}`).slice(0, 160)}</strong><p>{readableSummary(item)}</p></div><ArrowRight size={14}/></button>)}</div>
      : <div className="purposeful-empty"><Database size={20}/><h3>No repeated knowledge yet</h3><p>As different agents record related decisions and preferences, Docmancer will show the recurrence here with sources.</p></div>}
  </section>;
}

function Delivery({ data, cloud, setDetail }: { data: JsonMap; cloud: JsonMap; setDetail: (item: JsonMap) => void }) {
  const items = rows(data.items ?? data.agents ?? data.records);
  return <><section className="context-section"><div className="section-heading"><div><span className="eyebrow">Activation proof</span><h2>Which agents can receive Context</h2><p>See skills, recall hooks, and the last successful delivery without reading hook files.</p></div></div>
    {items.length ? <div className="delivery-grid">{items.map((item, index) => {
      const connected = item.integration_state === "connected";
      const state = String(item.integration_state ?? "");
      const status = connected
        ? item.recall_hook ? "Connected with automatic recall" : "Connected through Docmancer skills"
        : state === "stale" ? "Docmancer is installed, but needs an update"
        : state === "partial" ? "Docmancer is only partially installed"
        : state === "manual-step" ? "Waiting for a manual setup step"
        : item.detected ? "Detected, but Docmancer is not installed"
        : "Not detected on this machine";
      const nextStep = item.last_successful_recall
        ? `Last used ${humanDate(item.last_successful_recall)}`
        : connected ? "No successful recall recorded yet"
        : state === "stale" ? "Open Connect Docmancer to update"
        : state === "partial" ? "Open Connect Docmancer to finish setup"
        : state === "manual-step" ? String(item.manual_step ?? "Complete the setup step in the agent")
        : "Open Connect Docmancer to install";
      return <button key={String(item.agent ?? item.id ?? index)} onClick={() => setDetail(item)}><div className="delivery-agent"><span className={connected ? "status-dot good" : "status-dot"}/><strong>{String(item.label ?? item.agent ?? "Agent")}</strong></div><p>{status}</p><small>{nextStep}</small></button>;
    })}</div>
      : <div className="purposeful-empty"><Radio size={20}/><h3>No delivery receipts yet</h3><p>Connect Docmancer to your coding agents, then start a new agent session to generate delivery evidence.</p><code>docmancer setup</code></div>}
  </section><section className="context-section cloud-delivery"><div className="section-heading"><div><span className="eyebrow">Beyond this machine</span><h2>Keep Context continuous</h2><p>Local intelligence remains free. Cloud plans add encrypted continuity and coordination.</p></div></div><div className="cloud-plan-grid">
    <article><Cloud size={18}/><span className="eyebrow">Personal Sync</span><h3>Encrypted continuity across devices</h3><p>{cloud.configured ? "This machine is connected. Manage approved devices and run sync from Settings." : "Recover after a reset and keep approved devices current without uploading plaintext memory."}</p><a className="secondary-btn" href="/settings/?section=cloud">{cloud.configured ? "Manage Sync" : "Connect this device"} <ArrowRight size={14}/></a></article>
    <article><ShieldCheck size={18}/><span className="eyebrow">Team</span><h3>One approved Context file</h3><p>Review the complete file locally, then encrypt it before hosted Team coordination.</p><a className="secondary-btn" href="/settings/?section=cloud">{cloud.configured ? "Manage Team" : "Connect this device"} <ArrowRight size={14}/></a></article>
  </div></section></>;
}

function HistoryView({ data, revisions, reload, setDetail }: { data: JsonMap; revisions: JsonMap[]; reload: () => Promise<void>; setDetail: (item: JsonMap) => void }) {
  const events = rows(data.items ?? data.records);
  const [busy, setBusy] = useState("");
  const rollback = async (id: string) => { setBusy(id); try { await apiMutation("/api/v1/context/rollback", { revision_id: id }); await reload(); } finally { setBusy(""); } };
  return <section className="context-section"><div className="section-heading"><div><span className="eyebrow">Append-only history</span><h2>How Context and memory changed</h2><p>Readable changes first. Technical identifiers remain available inside each detail view.</p></div></div>
    <div className="history-list">
      {revisions.map((item, index) => { const id = String(item.revision_id ?? ""); return <article key={id}><span className="timeline-dot"/><div><small>{index === 0 ? "Current Context" : "Context revision"}</small><strong>{humanDate(item.generated_at)}</strong><p>{String(item.summary ?? `${Number(item.topic_count ?? 0)} consolidated topics`)}</p></div><div className="row-actions">{index > 0 && <button className="secondary-btn" disabled={busy === id} onClick={() => rollback(id)}><RotateCcw size={13}/>Restore</button>}<button className="secondary-btn" onClick={() => setDetail(item)}><FileDiff size={13}/>Details</button></div></article>; })}
      {events.slice(0, 20).map((item, index) => <button key={String(item.id ?? item.event_id ?? index)} onClick={() => setDetail(item)}><span className="timeline-dot muted"/><div><small>{humanAction(item.action ?? item.event_type)}</small><strong>{eventTitle(item)}</strong><p>{humanDate(item.timestamp ?? item.created_at)}</p></div><ArrowRight size={14}/></button>)}
    </div>
  </section>;
}

function ContextDetail({ item, close }: { item: JsonMap; close: () => void }) {
  const sources = rows(item.sources);
  const copy = async () => navigator.clipboard.writeText(JSON.stringify(item.diagnostics ?? {}, null, 2));
  return <Modal title={String(item.topic_label ?? item.title ?? item.label ?? item.agent ?? "Context detail")} subtitle="Human-readable Context detail" close={close}><div className="detail-content">
    <div className="detail-summary"><ShieldCheck size={18}/><div><strong>What this means</strong><p>{readableSummary(item)}</p></div></div>
    {sources.length > 0 && <section><span className="eyebrow">Where this came from</span><div className="source-cards">{sources.map((source, index) => <article key={`${String(source.title)}-${index}`}><strong>{String(source.title ?? "Memory source")}</strong><span>{String(source.agent ?? "Unknown agent")}</span><small>{String(source.project ?? source.scope ?? "")}</small></article>)}</div></section>}
    {item.has_readable_summary === false && <div className="not-distilled"><Sparkles size={17}/><div><strong>This evidence has not been distilled yet</strong><p>Use the AI distillation preview to see how Docmancer will turn it into a readable explanation.</p></div></div>}
    <button className="diagnostic-copy" onClick={() => void copy()}><Copy size={14}/>Copy diagnostic information</button>
  </div></Modal>;
}

function PlanSummary({ plan, onBuild, close }: { plan: JsonMap; onBuild: () => void; close: () => void }) {
  const result = plan.result && typeof plan.result === "object" ? plan.result as JsonMap : plan;
  const metrics = [
    ["Evidence records", Number(result.input_sources ?? 0)],
    ["Topics", Number(result.clusters ?? 0)],
    ["Changed topics", Number(rows(result.cluster_plan).length)],
    ["Provider calls", 0],
  ];
  return <div className="plan-summary local-plan"><div className="local-plan-intro"><span className="local-plan-icon"><Database size={19}/></span><div><span className="eyebrow">Deterministic local build</span><h3>Organise evidence without sending it to an LLM</h3><p>Docmancer will cluster related memory, preserve source attribution, and create a safe revision. The wording stays close to the underlying evidence rather than being rewritten for a human reader.</p></div></div><div className="preview-metrics">{metrics.map(([label, value]) => <div key={String(label)}><strong>{Number(value).toLocaleString()}</strong><span>{label}</span></div>)}</div><div className="plan-assurance"><ShieldCheck size={16}/><div><strong>Attribution and rollback stay available</strong><p>This creates a new revision. Your source files are not replaced.</p></div></div><div className="modal-actions"><button className="secondary-btn" onClick={close}>Cancel</button><button className="primary-btn" onClick={onBuild}>Build local Context <ArrowRight size={14}/></button></div></div>;
}

function DistillationPreview({ preview, busy, run, close }: { preview: JsonMap; busy: boolean; run: () => void; close: () => void }) {
  const outputs = Array.isArray(preview.outputs) ? preview.outputs.map(String) : [];
  return <Modal title="Distill memory with AI" subtitle="Review scope and provider before starting." close={close}><div className="distillation-preview">
    <div className="distill-orb"><Sparkles size={22}/></div>
    <span className="eyebrow">Readable, source-attributed Context</span>
    <h3>Turn agent evidence into a brief you can use</h3>
    <p>Docmancer will process {Number(preview.atoms ?? 0).toLocaleString()} memory atoms across {Number(preview.sources ?? 0).toLocaleString()} sources using <strong>{String(preview.provider_label ?? preview.provider ?? "your provider")}</strong>{preview.model ? ` and ${String(preview.model)}` : ""}.</p>
    <div className="preview-metrics"><div><strong>{Number(preview.clusters ?? 0).toLocaleString()}</strong><span>Topics</span></div><div><strong>{Number(preview.estimated_provider_calls ?? 0).toLocaleString()}</strong><span>Provider calls</span></div><div><strong>{Number(preview.estimated_input_tokens ?? 0).toLocaleString()}</strong><span>Input tokens</span></div><div><strong>${Number(preview.estimated_cost_usd ?? 0).toFixed(4)}</strong><span>Planning estimate</span></div></div>
    <div className="distill-output-grid">{outputs.map((output) => <span key={output}><Check size={14}/>{output}</span>)}</div>
    <div className="plan-assurance"><ShieldCheck size={16}/><div><strong>Private by design</strong><p>{String(preview.privacy_note ?? "Only topic evidence is sent to your selected provider. Credentials stay in the operating-system keyring.")}</p></div></div>
    <div className="modal-actions"><button className="secondary-btn" onClick={close}>Close</button>{preview.available ? <button className="primary-btn" disabled={busy} onClick={run}>{busy ? <RefreshCw className="spin" size={14}/> : <Sparkles size={14}/>}Start distillation</button> : <a className="primary-btn" href="/settings/?section=model">Configure provider <ArrowRight size={14}/></a>}</div>
  </div></Modal>;
}

function readableSummary(item: JsonMap) {
  const summary = String(item.summary ?? item.explanation ?? "").trim();
  if (!summary && item.integration_state) {
    if (item.integration_state === "connected") return item.recall_hook
      ? "Docmancer is installed and automatic Context recall is active."
      : "Docmancer is installed. This agent can use the shared memory through its skill and CLI.";
    return item.detected
      ? "The coding agent is installed, but its Docmancer integration has not been installed yet."
      : "This integration is supported but the coding agent was not detected on this machine.";
  }
  return summary || "Docmancer has the source evidence, but this item has not been distilled into a readable explanation yet.";
}
function eventTitle(item: JsonMap) {
  if (item.title || item.file_name) return String(item.title ?? item.file_name);
  const path = String(item.path ?? "");
  return path ? path.split("/").filter(Boolean).at(-1) ?? "Local memory updated" : "Local memory updated";
}
function humanAction(value: unknown) {
  const action = String(value ?? "Memory change").replaceAll("_", " ");
  return action.charAt(0).toUpperCase() + action.slice(1);
}
function humanDate(value: unknown) {
  if (!value) return "Date unavailable";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
