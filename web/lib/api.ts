export type JsonMap = Record<string, unknown>;

let csrfToken = "";

/* Losing the local service is a whole-app condition, not a per-panel one. Every
 * view that fetches on mount used to catch the same failure and render its own
 * banner, so a single dead server produced a stack of identical notices and
 * dismissing one only revealed the next. Connection failures are now published
 * once here; the app shell renders them, panels skip them, and the state clears
 * itself as soon as any request succeeds. */
export const OFFLINE_MESSAGE =
  "Docmancer cannot reach the local service on this machine. If you stopped it, start it again with docmancer web; this message clears itself once the connection is back.";
export const SESSION_MESSAGE =
  "This browser tab is no longer signed in to the local service. Reopen Docmancer from the terminal to authenticate it again.";

let connectionMessage = "";
const connectionListeners = new Set<(message: string) => void>();

export function currentConnectionMessage(): string {
  return connectionMessage;
}

export function isConnectionMessage(message: string): boolean {
  return message === OFFLINE_MESSAGE || message === SESSION_MESSAGE;
}

export function onConnectionChange(listener: (message: string) => void): () => void {
  connectionListeners.add(listener);
  return () => { connectionListeners.delete(listener); };
}

function publishConnection(message: string) {
  if (message === connectionMessage) return;
  connectionMessage = message;
  connectionListeners.forEach((listener) => listener(message));
}

async function request(path: string, init: RequestInit): Promise<JsonMap> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch (reason) {
    // An aborted request is the caller's own doing and says nothing about the
    // server, so it must not masquerade as a connection failure.
    if (reason instanceof DOMException && reason.name === "AbortError") throw reason;
    publishConnection(OFFLINE_MESSAGE);
    throw new Error(OFFLINE_MESSAGE);
  }
  if (response.status === 401) {
    publishConnection(SESSION_MESSAGE);
    throw new Error(SESSION_MESSAGE);
  }
  const data = await decode(response);
  publishConnection("");
  return data;
}

export async function establishSession(): Promise<void> {
  const data = await request("/api/v1/session", { credentials: "same-origin" });
  csrfToken = String(data.csrf_token ?? "");
}

export async function apiGet(path: string, signal?: AbortSignal): Promise<JsonMap> {
  return request(path, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    signal,
  });
}

export async function apiMutation(
  path: string,
  body: JsonMap,
  method = "POST",
): Promise<JsonMap> {
  return request(path, {
    method,
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Docmancer-CSRF": csrfToken,
    },
    body: JSON.stringify(body),
  });
}

export async function apiJobMutation(
  path: string,
  body: JsonMap,
  onDelta: (delta: string) => void,
): Promise<JsonMap> {
  const job = await apiStartJob(path, body);
  return waitForJob(job, onDelta);
}

export async function apiStartJob(
  path: string,
  body: JsonMap,
): Promise<JsonMap> {
  const job = await apiMutation(path, { ...body, stream: true });
  const jobId = String(job.id ?? "");
  if (!jobId) return job;
  window.dispatchEvent(new CustomEvent("docmancer:job-started", { detail: job }));
  return job;
}

export async function waitForJob(
  job: JsonMap,
  onDelta: (delta: string) => void = () => undefined,
): Promise<JsonMap> {
  const jobId = String(job.id ?? "");
  if (!jobId) return job;
  return new Promise((resolve, reject) => {
    const events = new EventSource(`/api/v1/jobs/${encodeURIComponent(jobId)}/events`);
    events.addEventListener("progress", (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as JsonMap;
      const data = payload.data as JsonMap | undefined;
      if (payload.stage === "answer_delta" && data?.delta) onDelta(String(data.delta));
    });
    events.addEventListener("done", (event) => {
      events.close();
      const payload = JSON.parse((event as MessageEvent).data) as JsonMap;
      if (payload.state === "failed") {
        reject(new Error(String(payload.error ?? "Answer generation failed")));
      } else {
        resolve((payload.result && typeof payload.result === "object" ? payload.result : {}) as JsonMap);
      }
    });
    events.onerror = () => {
      events.close();
      reject(new Error("The local answer stream disconnected."));
    };
  });
}

/** Follow a job and surface every progress stage, not only answer deltas. */
export async function watchJob(
  job: JsonMap,
  onStage: (stage: string, data: JsonMap) => void,
): Promise<JsonMap> {
  const jobId = String(job.id ?? "");
  if (!jobId) return job;
  return new Promise((resolve, reject) => {
    const events = new EventSource(`/api/v1/jobs/${encodeURIComponent(jobId)}/events`);
    events.addEventListener("progress", (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as JsonMap;
      onStage(String(payload.stage ?? ""), (payload.data ?? {}) as JsonMap);
    });
    events.addEventListener("done", (event) => {
      events.close();
      const payload = JSON.parse((event as MessageEvent).data) as JsonMap;
      if (payload.state === "failed") {
        reject(new Error(String(payload.error ?? "The job failed")));
      } else {
        resolve((payload.result && typeof payload.result === "object" ? payload.result : {}) as JsonMap);
      }
    });
    events.onerror = () => {
      events.close();
      reject(new Error("The local job stream disconnected."));
    };
  });
}

async function decode(response: Response): Promise<JsonMap> {
  const data = (await response.json().catch(() => ({}))) as JsonMap;
  if (!response.ok) {
    const error = data.error as JsonMap | undefined;
    throw new Error(String(error?.message ?? `Request failed with HTTP ${response.status}`));
  }
  return data;
}
