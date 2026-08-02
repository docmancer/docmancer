"use client";

import {
  ArrowRight, Cloud, ExternalLink, LoaderCircle, ShieldCheck,
} from "lucide-react";
import { useEffect, useState } from "react";
import { apiGet, apiJobMutation, apiMutation, type JsonMap } from "@/lib/api";
import { AgentGroup, Loading, messageOf, Modal, Notice, rows } from "./workspace-app";
import { ConnectDialog, RecoveryKeyPanel } from "./cloud-connect";

/**
 * One section spine for every connection state. Sections show a state-appropriate
 * body instead of the page swapping wholesale, so a pending device can still see
 * that recovery, team, and data controls exist.
 */
export function CloudSettings() {
  const [status, setStatus] = useState<JsonMap>({});
  const [devices, setDevices] = useState<JsonMap[]>([]);
  const [team, setTeam] = useState<JsonMap>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [replacementRecoveryKey, setReplacementRecoveryKey] = useState("");
  const [recoveryUploadError, setRecoveryUploadError] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [revoking, setRevoking] = useState<JsonMap | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const cloud = await apiGet("/api/v1/cloud");
      setStatus(cloud);
      if (cloud.configured) {
        const [deviceData, teamData] = await Promise.all([apiGet("/api/v1/cloud/devices"), apiGet("/api/v1/cloud/team")]);
        setDevices(rows(deviceData.items));
        setTeam(teamData);
      } else if (cloud.registered) {
        const deviceData = await apiGet("/api/v1/cloud/devices");
        setDevices(rows(deviceData.items));
        setTeam({});
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
  // The local API requires the device id as an explicit confirmation, so revocation
  // is confirmed in the UI first rather than fired from a single click.
  const revoke = (id: string) => run(
    () => apiMutation(`/api/v1/cloud/devices/${encodeURIComponent(id)}/revoke`, { confirmation: id }),
    "Device revoked.",
  ).then(() => setRevoking(null));
  const disconnect = () => run(() => apiMutation("/api/v1/cloud/disconnect", {}), "Cloud session cleared. Local memory was not changed.");
  const createRecoveryKey = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await apiMutation("/api/v1/cloud/recovery-key/create", {});
      setReplacementRecoveryKey(String(result.recovery_key ?? ""));
      setRecoveryUploadError(String(result.upload_error ?? ""));
      await load();
    } catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(false); }
  };

  if (loading) return <Loading label="Loading Cloud status"/>;

  const configured = Boolean(status.configured);
  const registered = Boolean(status.registered);
  const localKeys = (status.local_keys ?? {}) as JsonMap;
  const recovery = (status.recovery ?? {}) as JsonMap;
  const members = rows(team.members);
  const pending = devices.filter((device) => String(device.state ?? "") === "pending");
  const canPush = status.entitlement === "active" || status.entitlement === "trial" || status.entitlement === "grace";
  const currentDevice = devices.find(
    (device) => String(device.device_id ?? device.id ?? "") === String(status.device_id ?? ""),
  );

  // Nothing exists to manage before a device is registered, so the page stays a
  // single decision instead of a spine of empty sections.
  if (!configured && !registered) return <div className="settings-form">
    <div className="settings-title"><div className="feature-icon mint"><Cloud size={19}/></div><div><span className="eyebrow">Optional encrypted continuity</span><h2>Carry shared memory beyond this machine</h2><p>The complete local product stays free. Paid plans cover encrypted sync, recovery, and Team coordination.</p></div></div>
    {error && <Notice kind="error">{error}</Notice>}
    <div className="cloud-plan-grid">
      <article><span className="eyebrow">Personal Sync</span><h3>Keep every approved device current</h3><p>Replicate encrypted revisions, recover after a reset, and keep managed history without uploading plaintext memory.</p></article>
      <article><span className="eyebrow">Team</span><h3>Share one approved memory file</h3><p>Generate and review the complete file locally, then encrypt it before hosted coordination and delivery.</p></article>
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

  return <div className="settings-form">
    <div className="settings-title">
      <div className="feature-icon mint">{configured ? <Cloud size={19}/> : <ShieldCheck size={19}/>}</div>
      <div>
        <span className="eyebrow">{configured ? "Encrypted Cloud connected" : "Device registered"}</span>
        <h2>{configured ? "Sync, devices, recovery, and Team" : "Approval is still required"}</h2>
        <p>Manage the local side of encrypted continuity. Billing and checkout remain on docmancer.dev.</p>
      </div>
    </div>
    {error && <Notice kind="error">{error}</Notice>}
    {notice && <Notice onClose={() => setNotice("")}>{notice}</Notice>}

    <AgentGroup title="Connection" note={configured
      ? "This device holds the workspace key and can encrypt and decrypt revisions."
      : "This device is known to your account, but encrypted sync stays off until a trusted device approves its fingerprint."}>
      <div className="cloud-status-grid">
        <article><strong>{configured ? "Connected" : "Pending"}</strong><span>Connection state</span></article>
        <article><strong>{devices.length}</strong><span>Registered devices</span></article>
        <article><strong>{localKeys.device_identity_available ? "Present" : "Missing"}</strong><span>Local device identity</span></article>
        <article><strong>{localKeys.workspace_key_available ? "Present" : "Unavailable"}</strong><span>Local workspace key</span></article>
      </div>
      {!configured && <Notice kind="error">
        Approve fingerprint {String(currentDevice?.fingerprint ?? "unavailable")} from an existing
        trusted device. Secret key material is never displayed on this settings page.
      </Notice>}
      <div className="form-actions">
        <button className="primary-btn" disabled={busy || (configured && !canPush)} onClick={configured
          ? sync
          : () => run(() => apiJobMutation("/api/v1/cloud/sync", {}, () => undefined), "Approval confirmed and first sync complete.")}>
          {busy && <LoaderCircle className="spin" size={14}/>}{configured ? "Sync now" : "Check approval and sync"}
        </button>
      </div>
    </AgentGroup>

    <AgentGroup title="Plan and billing" note="Checkout, invoices, and plan changes live on docmancer.dev. This shows what the local device was told.">
      <div className="cloud-status-grid">
        <article><strong>{String(status.plan ?? status.entitlement ?? "Connected")}</strong><span>Current plan</span></article>
        <article><strong>{String(status.pending ?? 0)}</strong><span>Queued for upload</span></article>
      </div>
      {!canPush && <Notice kind="error">
        This device is connected, but the subscription is not active, so encrypted revisions
        cannot be uploaded yet. Local memory, recall, and every local command keep working.
      </Notice>}
      <div className="form-actions">
        <a className="secondary-btn" href="https://docmancer.dev/account" target="_blank" rel="noreferrer">Account and billing <ExternalLink size={14}/></a>
      </div>
    </AgentGroup>

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
            {/* Approval wraps the workspace key, so only a device that already holds one can do it. */}
            {state === "pending" && configured && <button className="secondary-btn" disabled={busy} onClick={() => approve(device)}>Approve</button>}
            {state !== "revoked" && id !== String(status.device_id ?? "") && <button className="text-btn" disabled={busy} onClick={() => setRevoking(device)}>Revoke</button>}
          </div>
        </article>;
      })}
      {pending.length > 0 && configured && <p className="muted">{pending.length} device(s) are waiting for approval.</p>}
      {pending.length > 0 && !configured && <p className="muted">
        Approval has to happen on a device that already holds the workspace key. This one does not yet, so it cannot approve itself.
      </p>}
    </AgentGroup>

    <AgentGroup title="Recovery" note="The recovery key restores the workspace key onto a machine. It is created and checked here, and never uploaded in usable form.">
      <p className="muted">
        Keep at least one approved device. A recovery key does not enrol a machine on its own,
        so it cannot by itself get you back into hosted history if every approved device is lost.
      </p>
      <div className="cloud-status-grid">
        <article><strong>{recovery.configured ? "Stored" : "Not created"}</strong><span>Recovery wrapper</span></article>
        <article><strong>{recovery.verified ? "Verified" : "Not verified"}</strong><span>Checked on this device</span></article>
      </div>
      <p className="muted">
        Verification only confirms that the key you saved still unwraps this workspace. It is
        optional, it is recorded on this machine alone, and nothing is blocked if you skip it.
      </p>
      {replacementRecoveryKey && <div className="pending-recovery-panel">
        <h3>{recovery.configured ? "Replacement recovery key" : "Recovery key"}</h3>
        <p className="muted">Save it offline before continuing. It is shown once.</p>
        {recoveryUploadError
          ? <Notice kind="error">
              This key was saved on this machine, but the hosted wrapper was not replaced: {recoveryUploadError}.
              Keep your previous recovery key, because that is still the one another machine would be given.
              Create the key again once the service is reachable.
            </Notice>
          : null}
        <RecoveryKeyPanel value={replacementRecoveryKey} onAcknowledge={() => { setReplacementRecoveryKey(""); setRecoveryUploadError(""); }}/>
      </div>}
      <div className="form-actions">
        <button className="secondary-btn" disabled={busy} onClick={() => setVerifying(true)}>Verify recovery key</button>
        {Boolean(localKeys.workspace_key_available) && !replacementRecoveryKey && <button className="secondary-btn" disabled={busy} onClick={createRecoveryKey}>
          {recovery.configured ? "Replace lost recovery key" : "Create recovery key"}
        </button>}
      </div>
    </AgentGroup>

    <AgentGroup title="Team" note="Members share one approved memory file. Review happens locally before anything is encrypted and sent.">
      <p className="muted">
        Team Sync is not available yet. An invitation cannot be accepted, so this shows the
        state the service already holds rather than an invite control that cannot complete.
      </p>
      {members.length === 0 && <p className="muted">No team members yet.</p>}
      {members.map((member) => <article key={String(member.email ?? member.member_id)} className="cloud-row">
        <div><strong>{String(member.email ?? member.member_id ?? "member")}</strong><small>{String(member.role ?? "member")} · {String(member.state ?? "active")}</small></div>
      </article>)}
      {rows(team.promotions).length > 0 && <p className="muted">{rows(team.promotions).length} proposal(s) are waiting for review.</p>}
      {rows(team.conflicts).length > 0 && <p className="muted">{rows(team.conflicts).length} unresolved conflict(s).</p>}
    </AgentGroup>

    <AgentGroup title="Data and deletion" note="Both actions apply to server-held ciphertext only. The canonical Markdown tree on this machine is never touched.">
      <div className="form-actions">
        <button className="secondary-btn" disabled={busy} onClick={() => run(() => apiMutation("/api/v1/cloud/export", {}), "Encrypted export requested.")}>Request encrypted export</button>
        <button className="text-btn" disabled={busy} onClick={() => run(
          () => apiMutation("/api/v1/cloud/delete", { confirmation: "DELETE" }),
          "Remote deletion scheduled.",
        )}>Schedule remote deletion</button>
      </div>
    </AgentGroup>

    <AgentGroup title="Disconnect" note="Clears the local cloud session and stops encrypted transfer. Local memory is never deleted.">
      <div className="form-actions"><button className="text-btn" disabled={busy} onClick={disconnect}>{configured ? "Disconnect this device" : "Disconnect local link"}</button></div>
    </AgentGroup>

    {revoking && <RevokeDeviceDialog
      device={revoking}
      busy={busy}
      close={() => setRevoking(null)}
      onConfirm={() => void revoke(String(revoking.device_id ?? revoking.id ?? ""))}
    />}

    {verifying && <VerifyRecoveryDialog
      close={() => setVerifying(false)}
      onVerified={() => { setVerifying(false); setNotice("Recovery key verified on this device."); void load(); }}
    />}
  </div>;
}

function RevokeDeviceDialog({ device, busy, close, onConfirm }: { device: JsonMap; busy: boolean; close: () => void; onConfirm: () => void }) {
  const id = String(device.device_id ?? device.id ?? "");
  return <Modal title="Revoke this device?" subtitle="Revocation blocks future sync immediately. It cannot erase keys or plaintext the device already holds." close={close}>
    <div className="cloud-row">
      <div><strong>{id}</strong><small>{String(device.state ?? "pending")} · {String(device.fingerprint ?? "no fingerprint")}</small></div>
    </div>
    <p className="muted">
      If this is your last approved device, connect and approve a replacement first. Without an
      approved device there is no way back into the encrypted history, and a recovery key alone
      cannot restore access.
    </p>
    <div className="form-actions">
      <button className="primary-btn" disabled={busy} onClick={onConfirm}>{busy && <LoaderCircle className="spin" size={14}/>}Revoke device</button>
      <button className="text-btn" disabled={busy} onClick={close}>Keep device</button>
    </div>
  </Modal>;
}

function VerifyRecoveryDialog({ close, onVerified }: { close: () => void; onVerified: () => void }) {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const verify = async () => {
    setBusy(true);
    setError("");
    try {
      await apiMutation("/api/v1/cloud/recovery/verify", { recovery_key: key.trim() });
      onVerified();
    } catch (reason) { setError(messageOf(reason)); }
    finally { setBusy(false); }
  };
  return <Modal title="Verify recovery key" subtitle="Confirms the key you saved still unwraps this workspace. Nothing is uploaded and nothing is blocked if you skip this." close={close}>
    {error && <Notice kind="error">{error}</Notice>}
    <label className="field">
      <span>Recovery key</span>
      <input type="password" value={key} autoComplete="off" placeholder="Paste the key you stored offline" onChange={(event) => setKey(event.target.value)}/>
    </label>
    <div className="form-actions">
      <button className="primary-btn" disabled={busy || !key.trim()} onClick={verify}>{busy && <LoaderCircle className="spin" size={14}/>}Verify</button>
      <button className="text-btn" disabled={busy} onClick={close}>Cancel</button>
    </div>
  </Modal>;
}
