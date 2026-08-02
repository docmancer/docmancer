"use client";

import {
  ArrowRight, Check, Copy, ExternalLink, LoaderCircle, ShieldCheck, TriangleAlert,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { apiMutation, apiStartJob, watchJob, type JsonMap } from "@/lib/api";
import { messageOf, Modal, Notice } from "./workspace-app";

type Phase =
  | "idle"
  | "starting"
  | "awaiting_authorization"
  | "finishing"
  | "connected"
  | "pending_approval"
  | "failed";

/**
 * Drives device-code login from the browser. The dialog never talks to the
 * hosted API directly: it starts a local job and follows its progress stages.
 */
export function ConnectDialog({ close, onConnected }: { close: () => void; onConnected: () => void }) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [userCode, setUserCode] = useState("");
  const [verificationUri, setVerificationUri] = useState("");
  const [remaining, setRemaining] = useState(0);
  const [error, setError] = useState("");
  const [outcome, setOutcome] = useState<JsonMap>({});
  const [recoveryKey, setRecoveryKey] = useState("");
  const [copied, setCopied] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [baseUrl, setBaseUrl] = useState("");
  const [createRecovery, setCreateRecovery] = useState(true);
  const cancelled = useRef(false);

  useEffect(() => () => { cancelled.current = true; }, []);

  useEffect(() => {
    if (phase !== "awaiting_authorization" || remaining <= 0) return;
    const timer = window.setTimeout(() => setRemaining((value) => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [phase, remaining]);

  const start = async () => {
    setError("");
    setPhase("starting");
    try {
      const job = await apiStartJob("/api/v1/cloud/connect", {
        base_url: baseUrl.trim() || undefined,
        create_recovery: createRecovery,
      });
      const result = await watchJob(job, (stage, data) => {
        if (stage === "device_code") {
          setUserCode(String(data.user_code ?? ""));
          setVerificationUri(String(data.verification_uri ?? ""));
          setRemaining(Number(data.expires_in ?? 300));
          setPhase("awaiting_authorization");
        }
        if (stage === "authorized") setPhase("finishing");
      });
      if (cancelled.current) return;
      setOutcome(result);
      if (result.recovery_key_available) {
        try {
          const once = await apiMutation("/api/v1/cloud/connect/recovery-key", {});
          setRecoveryKey(String(once.recovery_key ?? ""));
        } catch {
          // A missing key is not fatal: the wrapper is still stored locally.
        }
      }
      setPhase(result.state === "pending_approval" ? "pending_approval" : "connected");
      onConnected();
    } catch (reason) {
      if (cancelled.current) return;
      setError(messageOf(reason));
      setPhase("failed");
    }
  };

  const abandon = async () => {
    if (phase === "awaiting_authorization" || phase === "starting") {
      await apiMutation("/api/v1/cloud/connect/cancel", {}).catch(() => undefined);
    }
    close();
  };

  const copyCode = async () => {
    await navigator.clipboard.writeText(userCode).catch(() => undefined);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  return <Modal title="Connect Docmancer Cloud" subtitle="Encryption keys are generated here and never leave this machine." close={abandon}>
    {error && <Notice kind="error">{error}</Notice>}

    {(phase === "idle" || phase === "failed") && <div className="connect-step">
      <p>
        Authorizing this device opens Docmancer in your browser. If you are not signed in
        yet you will sign in with GitHub or Google first, and the code entry form appears
        straight after that.
      </p>
      <label className="recovery-choice">
        <span className="recovery-choice-icon"><ShieldCheck size={18}/></span>
        <span className="recovery-choice-copy">
          <strong>Create a recovery key</strong>
          <small>Restore this workspace after a reset. The key is shown once, so save it somewhere safe.</small>
        </span>
        <input
          type="checkbox"
          checked={createRecovery}
          aria-label="Create a recovery key"
          onChange={(event) => setCreateRecovery(event.target.checked)}
        />
      </label>
      <button className="text-btn advanced-toggle" onClick={() => setAdvanced(!advanced)}>
        {advanced ? "Hide" : "Show"} advanced options
      </button>
      {advanced && <label className="field">
        <span>API base URL</span>
        <input
          value={baseUrl}
          placeholder="https://api.docmancer.dev"
          onChange={(event) => setBaseUrl(event.target.value)}
        />
        <small>Leave blank to use the hosted service. Override this only for staging or self-hosted deployments.</small>
      </label>}
      <div className="form-actions">
        <button className="primary-btn" onClick={start}>
          {phase === "failed" ? "Try again" : "Connect this device"} <ArrowRight size={14}/>
        </button>
        <button className="secondary-btn" onClick={abandon}>Cancel</button>
      </div>
    </div>}

    {phase === "starting" && <div className="connect-step">
      <p><LoaderCircle className="spin" size={15}/> Requesting a device code.</p>
    </div>}

    {phase === "awaiting_authorization" && <div className="connect-step">
      <span className="eyebrow">Step 1 of 2</span>
      <h3>Enter this code in your browser</h3>
      <div className="device-code">
        <code>{userCode}</code>
        <button className="icon-btn" onClick={copyCode} aria-label="Copy code">
          {copied ? <Check size={16}/> : <Copy size={16}/>}
        </button>
      </div>
      <div className="form-actions">
        <a className="primary-btn" href={verificationUri} target="_blank" rel="noreferrer">
          Open Docmancer <ExternalLink size={14}/>
        </a>
        <button className="secondary-btn" onClick={abandon}>Cancel</button>
      </div>
      <p className="muted">
        {remaining > 0
          ? `Waiting for authorization. This code expires in ${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, "0")}.`
          : "This code has expired. Cancel and start again."}
      </p>
    </div>}

    {phase === "finishing" && <div className="connect-step">
      <p><LoaderCircle className="spin" size={15}/> Authorized. Registering this device and preparing the workspace.</p>
    </div>}

    {phase === "pending_approval" && recoveryKey && <div className="connect-step">
      <div className="feature-icon mint"><ShieldCheck size={19}/></div>
      <h3>Save this recovery key before approving the device</h3>
      <p>
        This device is registered, but an existing approved device still needs to confirm
        its fingerprint before encrypted sync can start.
      </p>
      <RecoveryKeyPanel value={recoveryKey} onAcknowledge={() => setRecoveryKey("")}/>
    </div>}

    {phase === "pending_approval" && !recoveryKey && <div className="connect-step">
      <div className="feature-icon mint"><ShieldCheck size={19}/></div>
      <h3>This device is registered and waiting for approval</h3>
      <p>
        Your account already has an approved device, so that device has to confirm this one
        before the workspace key is shared with it. Approve this fingerprint from the other
        machine, then run a sync here.
      </p>
      <div className="device-code"><code>{String(outcome.fingerprint ?? "")}</code></div>
      <div className="form-actions"><button className="primary-btn" onClick={close}>Done</button></div>
    </div>}

    {phase === "connected" && <div className="connect-step">
      <div className="feature-icon mint"><Check size={19}/></div>
      <h3>This device is connected</h3>
      {Boolean(outcome.queue_warning) && <Notice kind="error">{String(outcome.queue_warning)}</Notice>}
      {Boolean(outcome.recovery_upload_error) && <Notice kind="error">
        This recovery key was saved on this machine, but it could not be uploaded: {String(outcome.recovery_upload_error)}.
        Until the upload succeeds, it will not work on a different machine. Retry from Settings once the service is reachable.
      </Notice>}
      {recoveryKey
        ? <RecoveryKeyPanel value={recoveryKey} onAcknowledge={close}/>
        : <div className="form-actions"><button className="primary-btn" onClick={close}>Done</button></div>}
    </div>}
  </Modal>;
}

export function RecoveryKeyPanel({ value, onAcknowledge }: { value: string; onAcknowledge: () => void }) {
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  return <div className="recovery-panel">
    <div className="recovery-warning"><TriangleAlert size={16}/> <strong>Store this recovery key offline now. It is shown once and cannot be retrieved again.</strong></div>
    <div className="device-code">
      <code>{value}</code>
      <button
        className="icon-btn"
        aria-label="Copy recovery key"
        onClick={async () => {
          await navigator.clipboard.writeText(value).catch(() => undefined);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 2000);
        }}
      >{copied ? <Check size={16}/> : <Copy size={16}/>}</button>
    </div>
    <label className="checkbox-row">
      <input type="checkbox" checked={saved} onChange={(event) => setSaved(event.target.checked)}/>
      <span>I have saved this recovery key somewhere safe.</span>
    </label>
    <div className="form-actions">
      <button className="primary-btn" disabled={!saved} onClick={onAcknowledge}>Done</button>
    </div>
  </div>;
}
