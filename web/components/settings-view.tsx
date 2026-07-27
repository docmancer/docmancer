"use client";

import {
  ArrowRight, BrainCircuit, Check, ChevronDown, Cloud, Command, ExternalLink, KeyRound,
  LoaderCircle, RefreshCw, Search, ShieldCheck, SlidersHorizontal,
} from "lucide-react";
import { KeyboardEvent, ReactNode, useEffect, useMemo, useState } from "react";
import { apiGet, apiJobMutation, apiMutation, type JsonMap } from "@/lib/api";
import { CommandRow, Loading, messageOf, Notice, PageHeading, rows } from "./workspace-app";
import { ConnectDialog } from "./cloud-connect";
import { WizardLogo } from "./wizard-logo";

export function SettingsView() {
  type Section = "agent" | "model" | "connections" | "cloud" | "safeguards";
  const [section, setSection] = useState<Section>(() => {
    const value = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("section") : "";
    return value === "model" || value === "connections" || value === "cloud" || value === "safeguards" ? value : "agent";
  });
  const items = [
    ["agent", "Docmancer", "Behavior and answer style", BrainCircuit],
    ["model", "Model", "Provider, model, and credential", SlidersHorizontal],
    ["connections", "Agent connections", "Skills and recall hooks", Command],
    ["cloud", "Cloud and billing", "Personal Sync and Team", Cloud],
    ["safeguards", "Privacy and safeguards", "Fixed local protections", ShieldCheck],
  ] as const;
  return <div className="page">
    <PageHeading eyebrow="Simple local configuration" title="Settings" description="Configure one Docmancer agent and one selected model. Advanced controls stay available without dominating the page."/>
    <div className="settings-layout">
      <nav className="settings-nav">{items.map(([id, title, note, Icon]) =>
        <button key={id} className={section === id ? "active" : ""} onClick={() => setSection(id)}>
          <Icon size={16}/><span><strong>{title}</strong><small>{note}</small></span>
        </button>
      )}</nav>
      <section className="settings-content">
        {section === "agent" && <AgentEditor/>}
        {section === "model" && <ModelSettings/>}
        {section === "connections" && <ConnectionSettings/>}
        {section === "cloud" && <CloudSettings/>}
        {section === "safeguards" && <Safeguards/>}
      </section>
    </div>
  </div>;
}

export function AgentEditor({ onSaved }: { onSaved?: () => void }) {
  const [value, setValue] = useState<JsonMap>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    apiGet("/api/v1/agent").then(setValue).catch((reason) => setError(messageOf(reason))).finally(() => setLoading(false));
  }, []);
  const save = async () => {
    setBusy(true); setError("");
    try {
      setValue(await apiMutation("/api/v1/agent", value, "PUT"));
      setNotice("Docmancer's behavior was saved locally.");
      onSaved?.();
    } catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(false); }
  };
  if (loading) return <Loading label="Loading Docmancer"/>;
  return <div className="settings-form">
    <div className="settings-title"><div className="agent-avatar small"><WizardLogo/></div><div><span className="eyebrow">Your memory agent</span><h2>Customize Docmancer</h2><p>Give Docmancer durable guidance for how it should help you.</p></div></div>
    {notice && <Notice>{notice}</Notice>}{error && <Notice kind="error">{error}</Notice>}
    <label><span>Agent name</span><input value="Docmancer" disabled/><small>Docmancer is the single agent in this workspace.</small></label>
    <label><span>Agent instructions</span><textarea rows={8} value={String(value.instructions ?? "")} onChange={(event) => setValue((current) => ({ ...current, instructions: event.target.value }))}/><small>Describe tone, priorities, and how you want memory translated into answers.</small></label>
    <div className="field-grid">
      <label><span>Answer style</span><select value={String(value.output_mode ?? "normal")} onChange={(event) => setValue((current) => ({ ...current, output_mode: event.target.value }))}><option value="concise">Concise</option><option value="normal">Balanced</option><option value="thorough">Thorough</option></select></label>
      <label><span>Reasoning effort</span><select value={String(value.reasoning_effort ?? "medium")} onChange={(event) => setValue((current) => ({ ...current, reasoning_effort: event.target.value }))}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></label>
    </div>
    <details className="advanced-settings"><summary>Advanced model behavior <ChevronDown size={15}/></summary><div className="field-grid">
      <label><span>Max output tokens</span><input type="number" min={256} value={Number(value.max_output_tokens ?? 4096)} onChange={(event) => setValue((current) => ({ ...current, max_output_tokens: Number(event.target.value) }))}/></label>
      <label><span>Context budget</span><input type="number" min={1000} value={Number(value.context_budget ?? 12000)} onChange={(event) => setValue((current) => ({ ...current, context_budget: Number(event.target.value) }))}/></label>
      <label><span>Top P</span><input type="number" min={0} max={1} step={0.05} value={Number(value.top_p ?? 0.95)} onChange={(event) => setValue((current) => ({ ...current, top_p: Number(event.target.value) }))}/></label>
    </div></details>
    <div className="form-actions"><button className="primary-btn" disabled={busy} onClick={save}>{busy && <LoaderCircle className="spin" size={15}/>}Save Docmancer</button></div>
  </div>;
}

function ModelSettings() {
  const [providers, setProviders] = useState<JsonMap[]>([]);
  const [defaults, setDefaults] = useState<JsonMap>({});
  const [models, setModels] = useState<JsonMap[]>([]);
  const [modelState, setModelState] = useState<JsonMap>({});
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const selected = String(defaults.default_llm ?? "openrouter");
  const provider = providers.find((item) => item.id === selected) ?? {};

  const load = async () => {
    const [providerData, defaultData] = await Promise.all([apiGet("/api/v1/providers"), apiGet("/api/v1/settings/ai-defaults")]);
    setProviders(rows(providerData.items).filter((item) => Array.isArray(item.capabilities) && item.capabilities.map(String).includes("llm")));
    setDefaults(defaultData);
  };
  useEffect(() => { queueMicrotask(() => load().catch((reason) => setError(messageOf(reason)))); }, []);
  const loadModels = async (refresh = false) => {
    if (!selected) return;
    if (refresh) setBusy("models");
    try {
      const data = await apiGet(`/api/v1/providers/${selected}/models${refresh ? "?refresh=1" : ""}`);
      setModels(rows(data.items));
      setModelState(data);
    } catch (reason) {
      setModels([]);
      setError(messageOf(reason));
    } finally {
      if (refresh) setBusy("");
    }
  };
  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      apiGet(`/api/v1/providers/${selected}/models`).then((data) => {
        if (cancelled) return;
        setModels(rows(data.items));
        setModelState(data);
      }).catch((reason) => {
        if (cancelled) return;
        setModels([]);
        setError(messageOf(reason));
      });
    });
    return () => { cancelled = true; };
  }, [selected]);

  const modelMap = defaults.models && typeof defaults.models === "object" ? defaults.models as JsonMap : {};
  const activeModel = String(modelMap[selected] ?? provider.model ?? models[0]?.id ?? "");
  const updateProvider = (id: string) => setDefaults((current) => ({ ...current, default_llm: id }));
  const updateModel = (model: string) => setDefaults((current) => ({ ...current, models: { ...(current.models as JsonMap ?? {}), [selected]: model } }));
  const save = async () => {
    setBusy("save");
    try { setDefaults(await apiMutation("/api/v1/settings/ai-defaults", defaults, "PUT")); setNotice("Model settings saved locally."); }
    catch (reason) { setError(messageOf(reason)); } finally { setBusy(""); }
  };
  const saveKey = async () => {
    setBusy("key");
    try { await apiMutation(`/api/v1/providers/${selected}/key`, { key, validate: false }, "PUT"); setKey(""); setNotice("Credential stored in your operating-system keyring."); await load(); }
    catch (reason) { setError(messageOf(reason)); } finally { setBusy(""); }
  };
  const test = async () => {
    setBusy("test");
    try { const result = await apiMutation(`/api/v1/providers/${selected}/test`, {}); setNotice(`${String(provider.label ?? selected)} is ready with ${String(result.model ?? activeModel)}.`); }
    catch (reason) { setError(messageOf(reason)); } finally { setBusy(""); }
  };
  return <div className="settings-form">
    <div className="settings-title"><div className="feature-icon blue"><SlidersHorizontal size={19}/></div><div><span className="eyebrow">One active model</span><h2>Model configuration</h2><p>Select a provider first, then choose one of its models.</p></div></div>
    {notice && <Notice>{notice}</Notice>}{error && <Notice kind="error">{error}</Notice>}
    <label><span>Provider</span><select value={selected} onChange={(event) => updateProvider(event.target.value)}>{providers.map((item) => <option key={String(item.id)} value={String(item.id)}>{String(item.label)}</option>)}</select></label>
    <label><span>Model</span><ModelPicker key={`${selected}:${activeModel}`} models={models} value={activeModel} onChange={updateModel}/><small>{modelState.state === "ready" ? `${models.length.toLocaleString()} generation models loaded from the provider.` : modelState.state === "stale" ? "Showing the last successful catalog while refresh is unavailable." : "Showing safe fallback models. Add a credential to load the provider's current catalog."}</small></label>
    <div className="inline-actions">
      <button className="secondary-btn" disabled={Boolean(busy)} onClick={() => void loadModels(true)}><RefreshCw className={busy === "models" ? "spin" : ""} size={14}/>Refresh model catalog</button>
      {Boolean(modelState.refresh_error) && <span className="inline-warning">{String(modelState.refresh_error)}</span>}
    </div>
    {provider.auth_kind === "api_key" && <div className="credential-box">
      <div><span className="eyebrow">Credential</span><strong>{provider.key_state === "stored" ? "Stored in keyring" : provider.key_state === "from_env" ? "Available from your environment" : "API key required"}</strong><p>{provider.key_hint ? `Current key ${String(provider.key_hint)}` : `Docmancer never writes ${String(provider.key_env_var ?? "provider keys")} into project files.`}</p></div>
      <div className="credential-actions"><input type="password" value={key} onChange={(event) => setKey(event.target.value)} placeholder="Paste a new key"/><button className="secondary-btn" disabled={!key.trim() || Boolean(busy)} onClick={saveKey}><KeyRound size={14}/>Store</button><button className="secondary-btn" disabled={Boolean(busy)} onClick={test}>Test connection</button></div>
    </div>}
    <div className="form-actions"><button className="primary-btn" disabled={Boolean(busy)} onClick={save}>{busy === "save" && <LoaderCircle className="spin" size={15}/>}Save model</button></div>
  </div>;
}

function ModelPicker({ models, value, onChange }: { models: JsonMap[]; value: string; onChange: (value: string) => void }) {
  const [query, setQuery] = useState(value);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const filtered = useMemo(() => {
    const needle = open && query === value ? "" : query.trim().toLowerCase();
    const matches = models.filter((item) => String(item.id ?? "").toLowerCase().includes(needle));
    return matches.slice(0, 250);
  }, [models, open, query, value]);
  const choose = (model: string) => {
    setQuery(model); onChange(model); setOpen(false);
  };
  const keyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") { event.preventDefault(); setOpen(true); setActive((value) => Math.min(value + 1, filtered.length - 1)); }
    if (event.key === "ArrowUp") { event.preventDefault(); setActive((value) => Math.max(value - 1, 0)); }
    if (event.key === "Enter") {
      event.preventDefault();
      choose(filtered[active] ? String(filtered[active].id) : query.trim());
    }
    if (event.key === "Escape") setOpen(false);
  };
  return <div className="model-picker">
    <Search size={15}/>
    <input role="combobox" aria-expanded={open} aria-controls="model-options" aria-autocomplete="list" value={query} onFocus={() => setOpen(true)} onChange={(event) => { setQuery(event.target.value); setOpen(true); setActive(0); }} onKeyDown={keyDown} placeholder="Search or enter a model ID"/>
    {open && <div className="model-options" id="model-options" role="listbox">
      {filtered.length ? filtered.map((item, index) => <button type="button" role="option" aria-selected={String(item.id) === value} className={index === active ? "active" : ""} key={String(item.id)} onMouseDown={(event) => event.preventDefault()} onClick={() => choose(String(item.id))}><span>{String(item.label ?? item.id)}</span><small>{String(item.source ?? "provider")}</small></button>)
        : <button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => choose(query.trim())}><span>Use custom model ID</span><small>{query.trim()}</small></button>}
    </div>}
  </div>;
}

function ConnectionSettings() {
  const [plan, setPlan] = useState<JsonMap>({});
  const [loading, setLoading] = useState(true);
  useEffect(() => { apiGet("/api/v1/agent/setup").then(setPlan).finally(() => setLoading(false)); }, []);
  if (loading) return <Loading label="Checking agent connections"/>;
  return <SetupFlow initial={plan}/>;
}

export function SetupFlow({ initial, onComplete }: { initial: JsonMap; onComplete?: () => void }) {
  const items = rows(initial.items);
  const recommended = new Set(Array.isArray(initial.recommended) ? initial.recommended.map(String) : []);
  const recallSetup = items.filter((item) => item.action_kind === "automatic" && item.integration_state === "connected" && item.recall_setup_required);
  const connected = items.filter((item) => item.integration_state === "connected" && !item.recall_setup_required);
  const updates = items.filter((item) => item.action_kind === "automatic" && item.integration_state === "stale");
  const repairs = items.filter((item) => item.action_kind === "automatic" && item.integration_state === "partial");
  const ready = items.filter((item) => item.action_kind === "automatic" && item.integration_state === "ready-to-connect");
  const actionable = [...recallSetup, ...updates, ...repairs, ...ready];
  const manual = items.filter((item) => item.action_kind === "manual");
  const available = items.filter((item) => !connected.includes(item) && !actionable.includes(item) && !manual.includes(item));
  const [selected, setSelected] = useState<Set<string>>(() => new Set(actionable.filter((item) => recommended.has(String(item.id))).map((item) => String(item.id))));
  const [reviewing, setReviewing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const connect = async () => {
    setBusy(true); setError("");
    try {
      const result = await apiJobMutation("/api/v1/agent/setup", { targets: [...selected], capture_hooks: true, confirmed: true }, () => undefined);
      if (result.verified === false) throw new Error("Docmancer finished setup, but one or more integrations could not be verified.");
      setNotice("The selected integrations were installed and verified.");
      window.setTimeout(() => onComplete?.(), 450);
    } catch (reason) { setError(messageOf(reason)); } finally { setBusy(false); }
  };
  const toggle = (id: string) => setSelected((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const hasHookTarget = actionable.some((item) => selected.has(String(item.id)) && item.recall_capable);
  const selectedUpdates = updates.filter((item) => selected.has(String(item.id))).length;
  const selectedRepairs = repairs.filter((item) => selected.has(String(item.id))).length;
  const selectedConnections = ready.filter((item) => selected.has(String(item.id))).length;
  const selectedRecall = recallSetup.filter((item) => selected.has(String(item.id))).length;
  const selectedKinds = [selectedConnections > 0, selectedRepairs > 0, selectedUpdates > 0, selectedRecall > 0].filter(Boolean).length;
  const actionLabel = selectedKinds > 1
    ? `Apply ${selected.size} change${selected.size === 1 ? "" : "s"}`
    : selectedRecall
      ? `Finish ${selectedRecall} automatic memory setup${selectedRecall === 1 ? "" : "s"}`
    : selectedConnections
      ? `Connect ${selected.size} agent${selected.size === 1 ? "" : "s"}`
      : selectedRepairs
      ? `Repair ${selected.size} integration${selected.size === 1 ? "" : "s"}`
      : `Update ${selectedUpdates} integration${selectedUpdates === 1 ? "" : "s"}`;
  if (reviewing) {
    const selectedItems = actionable.filter((item) => selected.has(String(item.id)));
    const recallTargets = selectedItems.filter((item) => item.recall_capable);
    const desktopSelected = selectedItems.some((item) => item.id === "claude-desktop");
    return <div className="settings-form setup-flow setup-confirmation">
      <div className="settings-title"><div className="feature-icon mint"><ShieldCheck size={19}/></div><div><span className="eyebrow">Confirmation required</span><h2>Connect Docmancer everywhere?</h2><p>Review the machine-wide changes before Docmancer writes anything.</p></div></div>
      <div className="setup-confirm-list">
        <article><Check size={16}/><div><strong>Index existing agent memory</strong><p>Discover local memory and instruction files, then rebuild the private local search index.</p></div></article>
        <article><Check size={16}/><div><strong>Install or update {selectedItems.length} integration{selectedItems.length === 1 ? "" : "s"}</strong><p>{selectedItems.map((item) => String(item.label)).join(", ")} will receive Docmancer skills and managed instructions where supported.</p></div></article>
        {recallTargets.length > 0 && <article><Check size={16}/><div><strong>Install automatic recall hooks</strong><p>{recallTargets.map((item) => String(item.label)).join(", ")} will be able to recall relevant local memory at session and prompt boundaries.</p></div></article>}
        <article><Check size={16}/><div><strong>Maintain one laptop-wide canonical memory</strong><p>Docmancer will automatically reconcile important personal context, preferences, projects, and working principles into ~/.docmancer/tree.</p></div></article>
        {desktopSelected && <article><ExternalLink size={16}/><div><strong>Prepare Claude Desktop for manual upload</strong><p>Docmancer will create the skill package and show you where to upload it. The web app cannot complete that final Claude Desktop step.</p></div></article>}
        {recallTargets.length > 0 && <article><ShieldCheck size={16}/><div><strong>Enable automatic session capture</strong><p>Supported agents will save durable local session conclusions and feed them into automatic reconciliation.</p></div></article>}
      </div>
      <Notice>Canonical plaintext stays on this machine. If you configured an AI provider, redacted evidence may be sent to it for synthesis. Existing agent files are updated through bounded Docmancer-managed blocks.</Notice>
      {error && <Notice kind="error">{error}</Notice>}
      <div className="modal-actions setup-confirm-actions"><button className="secondary-btn" disabled={busy} onClick={() => setReviewing(false)}>Back</button><button className="primary-btn" disabled={busy} onClick={connect}>{busy ? <LoaderCircle className="spin" size={15}/> : <Command size={15}/>} Install Docmancer everywhere</button></div>
    </div>;
  }
  return <div className="settings-form setup-flow">
    <div className="settings-title"><div className="feature-icon mint"><Command size={19}/></div><div><span className="eyebrow">CLI for agents</span><h2>Connect your coding agents</h2><p>Detected means the app exists. Connected means Docmancer&apos;s integration is installed and verified.</p></div></div>
    {notice && <Notice>{notice}</Notice>}{error && <Notice kind="error">{error}</Notice>}
    {connected.length > 0 && <AgentGroup title="Connected" note="Docmancer can already be used by these coding agents.">
      {connected.map((item) => <div className="agent-choice connected" key={String(item.id)}>
        <span className="agent-state-icon"><Check size={14}/></span>
        <span><strong>{String(item.label)}</strong><small>{item.recall_hook ? "Connected with automatic recall" : "Integration installed"}</small></span>
        {Boolean(item.last_successful_recall) && <em>Used recently</em>}
      </div>)}
    </AgentGroup>}
    {recallSetup.length > 0 && <AgentGroup title="Finish automatic memory" note="The integration is installed. Setup can add any missing recall and capture hooks.">
      {recallSetup.map((item) => {
        const id = String(item.id);
        return <label className={selected.has(id) ? "agent-choice selected" : "agent-choice"} key={id}>
          <input type="checkbox" checked={selected.has(id)} onChange={() => toggle(id)}/>
          <span><strong>{String(item.label)}</strong><small>Install automatic recall and capture hooks</small></span>{selected.has(id) && <Check size={15}/>}
        </label>;
      })}
    </AgentGroup>}
    {updates.length > 0 && <AgentGroup title="Updates available" note="These agents are connected. Update their Docmancer integration files to the current version.">
      {updates.map((item) => {
        const id = String(item.id);
        return <label className={selected.has(id) ? "agent-choice selected" : "agent-choice"} key={id}>
          <input type="checkbox" checked={selected.has(id)} onChange={() => toggle(id)}/>
          <span><strong>{String(item.label)}</strong><small>{connectionLabel(item)}</small></span>{selected.has(id) && <Check size={15}/>}
        </label>;
      })}
    </AgentGroup>}
    {repairs.length > 0 && <AgentGroup title="Repair installed integrations" note="Docmancer found an incomplete installation and can repair it automatically.">
      {repairs.map((item) => {
        const id = String(item.id);
        return <label className={selected.has(id) ? "agent-choice selected" : "agent-choice"} key={id}>
          <input type="checkbox" checked={selected.has(id)} onChange={() => toggle(id)}/>
          <span><strong>{String(item.label)}</strong><small>{connectionLabel(item)}</small></span>{selected.has(id) && <Check size={15}/>}
        </label>;
      })}
    </AgentGroup>}
    {ready.length > 0 && <AgentGroup title="Ready to connect automatically" note="Docmancer can install these integrations from the browser.">
      {ready.map((item) => {
        const id = String(item.id);
        return <label className={selected.has(id) ? "agent-choice selected" : "agent-choice"} key={id}>
          <input type="checkbox" checked={selected.has(id)} onChange={() => toggle(id)}/>
          <span><strong>{String(item.label)}</strong><small>{connectionLabel(item)}</small></span>{selected.has(id) && <Check size={15}/>}
        </label>;
      })}
    </AgentGroup>}
    {actionable.length > 0 && <div className="agent-group-action"><button className="primary-btn" disabled={busy || selected.size === 0} onClick={() => setReviewing(true)}><Command size={15}/> Review {actionLabel.toLowerCase()}</button></div>}
    {manual.length > 0 && <AgentGroup title="Finish setup manually" note="Docmancer has prepared everything it can. Complete the final step in the coding agent.">
      {manual.map((item) => <article className="manual-agent-step" key={String(item.id)}>
        <span className="agent-state-icon"><ExternalLink size={14}/></span>
        <div><strong>{String(item.label)}</strong><p>{String(item.manual_step ?? "Complete setup in the coding agent.")}</p>{Boolean(item.artifact_ready) && <small>The Docmancer skill package is ready.</small>}</div>
      </article>)}
    </AgentGroup>}
    {available.length > 0 && <details className="available-agents"><summary>Other supported agents <span>{available.length}</span></summary><div className="agent-choice-grid">{available.map((item) => {
      const id = String(item.id);
      return <label className={selected.has(id) ? "agent-choice selected" : "agent-choice"} key={id}>
        <input type="checkbox" checked={selected.has(id)} onChange={() => toggle(id)}/>
        <span><strong>{String(item.label)}</strong><small>Not detected, but available to install</small></span>{selected.has(id) && <Check size={15}/>}
      </label>;
    })}</div></details>}
    {hasHookTarget && <div className="setup-default"><Check size={15}/><span><strong>Automatic memory is included</strong><small>Supported agents capture durable conclusions, share one laptop-wide canonical memory, and recall it at session and prompt boundaries.</small></span></div>}
    {!ready.length && manual.length > 0 && <div className="manual-only-note"><strong>One final step remains</strong><p>Follow the instruction above in the coding agent. There is nothing else for Docmancer to install automatically.</p></div>}
    <details className="advanced-settings terminal-footer"><summary>Prefer the terminal? <ChevronDown size={15}/></summary><div className="command-stack"><CommandRow title="Detected agents" command="docmancer setup" note="Preview, confirm, then install automatic shared memory for every detected integration."/><CommandRow title="Every supported agent" command="docmancer setup --all" note="Preview and install every supported integration, including agents not detected."/></div></details>
  </div>;
}

function AgentGroup({ title, note, children }: { title: string; note: string; children: ReactNode }) {
  return <section className="agent-group"><header><div><strong>{title}</strong><p>{note}</p></div></header><div className="agent-choice-grid">{children}</div></section>;
}

function connectionLabel(item: JsonMap) {
  if (item.integration_state === "stale") return "Installed integration needs an update";
  if (item.integration_state === "partial") return "Partially installed, ready to repair";
  if (item.integration_state === "manual-step") return String(item.manual_step ?? "One manual step remains");
  return "Detected on this machine";
}

function Safeguards() {
  const safeguards = [
    ["Local means local", "The browser talks only to Docmancer on 127.0.0.1."],
    ["Credentials stay out of projects", "Provider keys are stored in the operating-system keyring."],
    ["Sources remain visible", "Answers and Context retain provenance so you can inspect where they came from."],
    ["Risky content is masked", "Secret-like values are masked before they are shown or moved."],
    ["Destructive actions are explicit", "Deletion, rollback, and publication require a deliberate confirmation."],
  ];
  return <div className="settings-form"><div className="settings-title"><div className="feature-icon mint"><ShieldCheck size={19}/></div><div><span className="eyebrow">Fixed protections</span><h2>Privacy and safeguards</h2><p>These protections are part of Docmancer&apos;s trust boundary and cannot be disabled from the agent prompt.</p></div></div><div className="safeguard-list">{safeguards.map(([title, note]) => <article key={title}><span><Check size={14}/></span><div><strong>{title}</strong><p>{note}</p></div></article>)}</div><div className="maintenance-card"><div><RefreshCw size={17}/><div><strong>Something looks stale?</strong><p>Rebuild the local index without changing your source files.</p></div></div><CommandRow title="Refresh local memory" command="docmancer memory sync" note="Re-index changed memory and instruction sources."/></div></div>;
}

function CloudSettings() {
  const [status, setStatus] = useState<JsonMap>({});
  const [devices, setDevices] = useState<JsonMap[]>([]);
  const [team, setTeam] = useState<JsonMap>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const load = async () => {
    setLoading(true);
    try {
      const cloud = await apiGet("/api/v1/cloud");
      setStatus(cloud);
      if (cloud.configured) {
        const [deviceData, teamData] = await Promise.all([apiGet("/api/v1/cloud/devices"), apiGet("/api/v1/cloud/team")]);
        setDevices(rows(deviceData.items));
        setTeam(teamData);
      }
    } catch (reason) { setError(messageOf(reason)); }
    finally { setLoading(false); }
  };
  useEffect(() => { queueMicrotask(() => void load()); }, []);
  const run = async (action: () => Promise<unknown>, message: string) => {
    setBusy(true);
    setError("");
    try { await action(); setNotice(message); await load(); }
    catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(false); }
  };
  const sync = () => run(() => apiJobMutation("/api/v1/cloud/sync", {}, () => undefined), "Sync complete.");
  const approve = (device: JsonMap) => run(
    () => apiMutation(`/api/v1/cloud/devices/${encodeURIComponent(String(device.device_id ?? device.id))}/approve`, {
      fingerprint: String(device.fingerprint ?? ""),
    }),
    "Device approved.",
  );
  const revoke = (device: JsonMap) => run(
    () => apiMutation(`/api/v1/cloud/devices/${encodeURIComponent(String(device.device_id ?? device.id))}/revoke`, {}),
    "Device revoked.",
  );
  const invite = () => run(
    () => apiMutation("/api/v1/cloud/team/invitations", { email: inviteEmail.trim(), role: "member" }),
    `Invitation sent to ${inviteEmail.trim()}.`,
  ).then(() => setInviteEmail(""));
  const disconnect = () => run(() => apiMutation("/api/v1/cloud/disconnect", {}), "Cloud session cleared. Local memory was not changed.");

  if (loading) return <Loading label="Loading Cloud status"/>;

  if (!status.configured) return <div className="settings-form">
    <div className="settings-title"><div className="feature-icon mint"><Cloud size={19}/></div><div><span className="eyebrow">Optional encrypted continuity</span><h2>Carry Context beyond this machine</h2><p>The complete local product stays free. Paid plans cover encrypted sync, recovery, and Team coordination.</p></div></div>
    {error && <Notice kind="error">{error}</Notice>}
    <div className="cloud-plan-grid">
      <article><span className="eyebrow">Personal Sync</span><h3>Keep every approved device current</h3><p>Replicate encrypted revisions, recover after a reset, and keep managed history without uploading plaintext memory.</p></article>
      <article><span className="eyebrow">Team</span><h3>Share one approved Context file</h3><p>Generate and review the complete file locally, then encrypt it before hosted coordination and delivery.</p></article>
    </div>
    <div className="form-actions">
      <button className="primary-btn" onClick={() => setConnecting(true)}>Connect this device <ArrowRight size={14}/></button>
      <a className="secondary-btn" href="https://docmancer.dev/pricing" target="_blank" rel="noreferrer">Compare plans <ExternalLink size={14}/></a>
    </div>
    <p className="muted">
      Connecting is free and does not require a subscription. A plan is only needed before
      encrypted revisions can be uploaded, and the local product is unaffected either way.
    </p>
    {connecting && <ConnectDialog close={() => setConnecting(false)} onConnected={() => void load()}/>}
  </div>;

  const members = rows(team.members);
  const pending = devices.filter((device) => String(device.state ?? "") === "pending");
  const canPush = status.entitlement === "active" || status.entitlement === "trial" || status.entitlement === "grace";
  return <div className="settings-form">
    <div className="settings-title"><div className="feature-icon mint"><Cloud size={19}/></div><div><span className="eyebrow">Encrypted Cloud connected</span><h2>Sync, devices, and Team</h2><p>Manage the local side of encrypted continuity. Billing and checkout remain on docmancer.dev.</p></div></div>
    {error && <Notice kind="error">{error}</Notice>}
    {notice && <Notice onClose={() => setNotice("")}>{notice}</Notice>}
    {!canPush && <Notice kind="error">
      This device is connected, but the subscription is not active, so encrypted revisions
      cannot be uploaded yet. Local memory, recall, and every local command keep working.
    </Notice>}

    <div className="cloud-status-grid">
      <article><strong>{String(status.plan ?? status.entitlement ?? "Connected")}</strong><span>Current plan</span></article>
      <article><strong>{devices.length}</strong><span>Registered devices</span></article>
      <article><strong>{members.length}</strong><span>Team members</span></article>
      <article><strong>{String(status.pending ?? 0)}</strong><span>Queued for upload</span></article>
    </div>
    <div className="form-actions">
      <button className="primary-btn" disabled={busy || !canPush} onClick={sync}>{busy && <LoaderCircle className="spin" size={14}/>}Sync now</button>
      <a className="secondary-btn" href="https://docmancer.dev/account" target="_blank" rel="noreferrer">Account and billing <ExternalLink size={14}/></a>
    </div>

    <AgentGroup title="Devices" note="Approve a new device only after confirming its fingerprint out of band.">
      {devices.length === 0 && <p className="muted">No devices are registered yet.</p>}
      {devices.map((device) => {
        const id = String(device.device_id ?? device.id ?? "");
        const state = String(device.state ?? "pending");
        return <article key={id} className="cloud-row">
          <div>
            <strong>{id === String(status.device_id ?? "") ? "This device" : id}</strong>
            <small>{state} · {String(device.fingerprint ?? "no fingerprint")}</small>
          </div>
          <div className="cloud-row-actions">
            {state === "pending" && <button className="secondary-btn" disabled={busy} onClick={() => approve(device)}>Approve</button>}
            {state !== "revoked" && id !== String(status.device_id ?? "") && <button className="text-btn" disabled={busy} onClick={() => revoke(device)}>Revoke</button>}
          </div>
        </article>;
      })}
      {pending.length > 0 && <p className="muted">{pending.length} device(s) are waiting for approval.</p>}
    </AgentGroup>

    <AgentGroup title="Team" note="Members share one approved Context file. Review happens locally before anything is encrypted and sent.">
      {members.length === 0 && <p className="muted">No team members yet.</p>}
      {members.map((member) => <article key={String(member.email ?? member.member_id)} className="cloud-row">
        <div><strong>{String(member.email ?? member.member_id ?? "member")}</strong><small>{String(member.role ?? "member")} · {String(member.state ?? "active")}</small></div>
      </article>)}
      <div className="form-actions">
        <input
          value={inviteEmail}
          placeholder="teammate@example.com"
          onChange={(event) => setInviteEmail(event.target.value)}
        />
        <button className="secondary-btn" disabled={busy || !inviteEmail.trim()} onClick={invite}>Invite member</button>
      </div>
      {rows(team.promotions).length > 0 && <p className="muted">{rows(team.promotions).length} proposal(s) are waiting for review.</p>}
      {rows(team.conflicts).length > 0 && <p className="muted">{rows(team.conflicts).length} unresolved conflict(s).</p>}
    </AgentGroup>

    <AgentGroup title="Disconnect" note="Clears the local cloud session and stops encrypted transfer. Local memory is never deleted.">
      <div className="form-actions"><button className="text-btn" disabled={busy} onClick={disconnect}>Disconnect this device</button></div>
    </AgentGroup>
  </div>;
}
