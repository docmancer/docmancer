"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowRight, Check, LoaderCircle, Lock, Pin, RefreshCw, Sparkles } from "lucide-react";

import { apiGet, apiMutation, type JsonMap } from "@/lib/api";

function rows(value: unknown): JsonMap[] {
  return Array.isArray(value) ? (value as JsonMap[]) : [];
}

function messageOf(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

const SECTION_LABELS: Record<string, string> = {
  about: "About you",
  preferences: "Preferences",
  "working-principles": "Working principles",
  "active-projects": "Active projects",
  "canonical-memory": "About this store",
};

function label(section: string): string {
  return SECTION_LABELS[section] ?? section;
}

/**
 * Right-rail summary. Deliberately shows the pinned count rather than a preview
 * excerpt: the one number a user cannot get anywhere else is how much of this
 * memory is their own words versus the reconciler's.
 */
export function CanonicalCard({ status, onOpen }: { status: JsonMap; onOpen: () => void }) {
  const available = Boolean(status.available);
  const sections = rows(status.sections).filter((row) => row.present);
  const pinned = Number(status.pinned_total ?? 0);

  return <article className="feature-card canonical-card">
    <div className="rail-card-heading">
      <div className="feature-icon blue"><Sparkles size={18}/></div>
      <div><span className="eyebrow">Canonical memory</span><h2>What Docmancer knows</h2></div>
    </div>
    {available
      ? <>
          <div className="connection-summary">
            <span><strong>{sections.length}</strong> sections</span>
            <span className={pinned ? "ready" : ""}>{pinned ? `${pinned} pinned by you` : "Nothing pinned yet"}</span>
          </div>
          <p className="canonical-provenance">Rebuilt automatically ({String(status.provider ?? "deterministic")}).</p>
        </>
      : <p>Not built yet. Run setup, or open this to build it now.</p>}
    <button className="primary-btn wide" onClick={onOpen}>
      {available ? "View and edit" : "Build it"} <ArrowRight size={15}/>
    </button>
  </article>;
}

/**
 * Full-screen editor. The generated zone is rendered read-only on purpose: it is
 * replaced on the next reconcile, so making it look editable would be a lie. The
 * pinned zone is the only writable surface, and every save carries the content
 * hash so a reconcile that lands mid-edit produces a visible conflict rather
 * than a silent overwrite.
 */
export function CanonicalEditor() {
  const [status, setStatus] = useState<JsonMap>({});
  const [active, setActive] = useState("");
  const [section, setSection] = useState<JsonMap | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  const loadStatus = useCallback(async (): Promise<JsonMap> => {
    try {
      const value = await apiGet("/api/v1/canonical");
      setStatus(value);
      return value;
    } catch (reason) {
      setError(messageOf(reason));
      return {};
    }
  }, []);

  const openSection = useCallback(async (key: string) => {
    setBusy("section"); setError(""); setSaved(false);
    try {
      const value = await apiGet(`/api/v1/canonical/${encodeURIComponent(key)}`);
      setSection(value);
      setDraft(String(value.pinned ?? ""));
      setActive(key);
    } catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(""); }
  }, []);

  // One boot flow rather than a status effect plus a "select the first tab"
  // effect: the second one set state synchronously on every status change,
  // which cascades renders and fights the user's own tab selection.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const value = await loadStatus();
      if (cancelled || !value.available) return;
      const first = rows(value.sections).find(
        (row) => row.present && row.section !== "canonical-memory",
      );
      if (first) await openSection(String(first.section));
    })();
    return () => { cancelled = true; };
  }, [loadStatus, openSection]);

  const save = async () => {
    if (!section) return;
    setBusy("save"); setError(""); setSaved(false);
    try {
      await apiMutation(`/api/v1/canonical/${encodeURIComponent(active)}/pin`, {
        pinned: draft,
        expected_hash: String(section.content_hash ?? ""),
      });
      await openSection(active);
      await loadStatus();
      setSaved(true);
    } catch (reason) {
      setError(messageOf(reason));
    } finally { setBusy(""); }
  };

  const rebuild = async (deterministic: boolean) => {
    setBusy("rebuild"); setError(""); setSaved(false);
    try {
      await apiMutation("/api/v1/canonical/refresh", { deterministic });
      await loadStatus();
      if (active) await openSection(active);
    } catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(""); }
  };

  const editable = active && active !== "canonical-memory";
  const dirty = section ? draft !== String(section.pinned ?? "") : false;

  if (!status.available) return <div className="canonical-empty">
    <p>Docmancer has not reconciled a canonical memory on this machine yet. Building it reads the memory your coding agents already wrote locally.</p>
    {error && <p className="canonical-error">{error}</p>}
    <div className="modal-actions">
      <button className="secondary-btn" disabled={Boolean(busy)} onClick={() => void rebuild(true)}>Build locally, no AI</button>
      <button className="primary-btn" disabled={Boolean(busy)} onClick={() => void rebuild(false)}>
        {busy === "rebuild" ? <RefreshCw className="spin" size={14}/> : <Sparkles size={14}/>} Build
      </button>
    </div>
  </div>;

  return <div className="canonical-editor">
    <nav className="canonical-tabs">
      {rows(status.sections).filter((row) => row.present).map((row) => {
        const key = String(row.section);
        const pinnedCount = Number(row.pinned_lines ?? 0);
        return <button key={key} className={key === active ? "active" : ""} onClick={() => void openSection(key)}>
          {label(key)}
          {pinnedCount > 0 && <em><Pin size={11}/>{pinnedCount}</em>}
        </button>;
      })}
    </nav>

    {error && <p className="canonical-error">{error}</p>}

    {section && <div className="canonical-body">
      <section className="canonical-pinned">
        <header>
          <div><Pin size={14}/><strong>Your notes</strong></div>
          <small>Kept exactly as written, through every rebuild.</small>
        </header>
        {editable
          ? <>
              <textarea
                value={draft}
                onChange={(event) => { setDraft(event.target.value); setSaved(false); }}
                rows={7}
                placeholder={"- Never use em dashes in public prose.\n- Always ask before committing."}
                spellCheck={false}
              />
              <div className="canonical-save-row">
                <small>{dirty ? "Unsaved changes" : saved ? <><Check size={12}/> Saved</> : "One note per line."}</small>
                <button className="primary-btn" disabled={!dirty || busy === "save"} onClick={() => void save()}>
                  {busy === "save" ? <LoaderCircle className="spin" size={14}/> : <Check size={14}/>} Save notes
                </button>
              </div>
            </>
          : <p className="canonical-locked"><Lock size={13}/> This section describes the store itself and is regenerated automatically, so it cannot be pinned.</p>}
      </section>

      <section className="canonical-generated">
        <header>
          <div><RefreshCw size={14}/><strong>Reconciled from your agents</strong></div>
          <small>Replaced on the next sync. Edits here would be lost, so it is read-only.</small>
        </header>
        <pre>{String(section.generated ?? "")}</pre>
      </section>
    </div>}

    <footer className="canonical-footer">
      <small>
        {String(status.selected ?? 0)} facts selected, {String(status.withheld ?? 0)} withheld
        {status.generated_at ? ` · last rebuilt ${String(status.generated_at)}` : ""}
        {` · ${String(status.provider ?? "deterministic")}`}
      </small>
      <div>
        <button className="secondary-btn" disabled={Boolean(busy)} onClick={() => void rebuild(true)}>Rebuild without AI</button>
        <button className="secondary-btn" disabled={Boolean(busy)} onClick={() => void rebuild(false)}>
          {busy === "rebuild" ? <RefreshCw className="spin" size={13}/> : <RefreshCw size={13}/>} Rebuild
        </button>
      </div>
    </footer>
  </div>;
}
