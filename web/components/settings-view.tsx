"use client";

import { KeyRound, LoaderCircle, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { apiGet, apiMutation, type JsonMap } from "@/lib/api";

function rows(value: unknown): JsonMap[] {
  return Array.isArray(value)
    ? value.filter((item): item is JsonMap => Boolean(item) && typeof item === "object")
    : [];
}

export function SettingsView() {
  const [providers, setProviders] = useState<JsonMap[]>([]);
  const [defaults, setDefaults] = useState<JsonMap>({});
  const [capture, setCapture] = useState<Record<string, boolean>>({});
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");

  const load = async () => {
    const [providerData, defaultData, captureData] = await Promise.all([
      apiGet("/api/v1/providers"),
      apiGet("/api/v1/settings/ai-defaults"),
      apiGet("/api/v1/settings/capture"),
    ]);
    setProviders(rows(providerData.items));
    setDefaults(defaultData);
    setCapture((captureData.enabled && typeof captureData.enabled === "object" ? captureData.enabled : {}) as Record<string, boolean>);
  };

  useEffect(() => {
    let active = true;
    void Promise.all([
      apiGet("/api/v1/providers"),
      apiGet("/api/v1/settings/ai-defaults"),
      apiGet("/api/v1/settings/capture"),
    ]).then(([providerData, defaultData, captureData]) => {
      if (!active) return;
      setProviders(rows(providerData.items));
      setDefaults(defaultData);
      setCapture((captureData.enabled && typeof captureData.enabled === "object" ? captureData.enabled : {}) as Record<string, boolean>);
    });
    return () => { active = false; };
  }, []);

  const saveKey = async (id: string) => {
    setBusy(id);
    try {
      await apiMutation(`/api/v1/providers/${id}/key`, { key: keys[id] ?? "", validate: false }, "PUT");
      setKeys((value) => ({ ...value, [id]: "" }));
      setNotice("Credential stored in the operating-system keyring.");
      await load();
    } finally {
      setBusy("");
    }
  };

  const test = async (id: string) => {
    setBusy(`test:${id}`);
    try {
      const result = await apiMutation(`/api/v1/providers/${id}/test`, {});
      setNotice(`${String(result.provider ?? id)} is ready with ${String(result.model ?? "the selected model")}.`);
    } finally {
      setBusy("");
    }
  };

  const saveDefaults = async () => {
    setBusy("defaults");
    try {
      await apiMutation("/api/v1/settings/ai-defaults", defaults, "PUT");
      setNotice("AI defaults saved locally.");
      await load();
    } finally {
      setBusy("");
    }
  };

  const saveCapture = async () => {
    setBusy("capture");
    try {
      await apiMutation("/api/v1/settings/capture", { enabled: capture }, "PUT");
      setNotice("Capture settings saved locally.");
    } finally {
      setBusy("");
    }
  };

  return <div className="settings-grid">
    {notice && <div className="alert success"><ShieldCheck size={16}/><span>{notice}</span></div>}
    <section className="collection"><div className="collection-head"><span>Answer providers</span><span>Keys stay in your keyring</span></div><div className="setting-list">{providers.map((provider) => {
      const id = String(provider.id ?? "");
      const needsKey = provider.auth_kind === "api_key";
      return <article className="setting-row" key={id}><div><span className="mini-label">{String(provider.key_state ?? "unknown")}</span><h3>{String(provider.label ?? id)}</h3><p>{String(provider.model ?? "Choose a model")} · {String(provider.structured_output ?? "")}</p>{Boolean(provider.key_hint) && <small>Stored credential {String(provider.key_hint)}</small>}</div><div className="row-actions">{needsKey && <><input type="password" value={keys[id] ?? ""} onChange={(event) => setKeys((value) => ({ ...value, [id]: event.target.value }))} placeholder="Paste key"/><button className="secondary" disabled={busy === id || !(keys[id] ?? "").trim()} onClick={() => saveKey(id)}>{busy === id ? <LoaderCircle className="spin" size={13}/> : <KeyRound size={13}/>}Store</button></>}<button className="secondary" disabled={Boolean(busy)} onClick={() => test(id)}>Test</button></div></article>;
    })}</div></section>

    <section className="collection"><div className="collection-head"><span>Answer defaults</span><span>One preference, three modes</span></div><div className="composer"><label>Default provider<select value={String(defaults.default_llm ?? "openrouter")} onChange={(event) => setDefaults((value) => ({ ...value, default_llm: event.target.value }))}>{providers.filter((provider) => Array.isArray(provider.capabilities) && provider.capabilities.map(String).includes("llm")).map((provider) => <option key={String(provider.id)} value={String(provider.id)}>{String(provider.label)}</option>)}</select></label><label>Output mode<select value={String(defaults.output_mode ?? "normal")} onChange={(event) => setDefaults((value) => ({ ...value, output_mode: event.target.value }))}><option value="concise">Concise</option><option value="normal">Normal</option><option value="thorough">Thorough</option></select></label><label>Preference<textarea value={String(defaults.preference ?? "")} onChange={(event) => setDefaults((value) => ({ ...value, preference: event.target.value }))} placeholder="Prefer direct, full-sentence answers."/></label><button className="primary" disabled={busy === "defaults"} onClick={saveDefaults}>Save answer defaults</button></div></section>

    <section className="collection"><div className="collection-head"><span>Capture</span><span>Local and optional</span></div><div className="setting-list">{Object.entries(capture).map(([agent, enabled]) => <label className="setting-row" key={agent}><div><h3>{agent}</h3><p>Capture eligible local session memory from this harness.</p></div><input type="checkbox" checked={enabled} onChange={(event) => setCapture((value) => ({ ...value, [agent]: event.target.checked }))}/></label>)}</div><button className="primary" disabled={busy === "capture"} onClick={saveCapture}>Save capture settings</button></section>
  </div>;
}
