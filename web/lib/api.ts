export type JsonMap = Record<string, unknown>;

let csrfToken = "";

export async function establishSession(): Promise<void> {
  const response = await fetch("/api/v1/session", { credentials: "same-origin" });
  const data = await decode(response);
  csrfToken = String(data.csrf_token ?? "");
}

export async function apiGet(path: string): Promise<JsonMap> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  return decode(response);
}

export async function apiMutation(
  path: string,
  body: JsonMap,
  method = "POST",
): Promise<JsonMap> {
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Docmancer-CSRF": csrfToken,
    },
    body: JSON.stringify(body),
  });
  return decode(response);
}

export async function apiJobMutation(
  path: string,
  body: JsonMap,
  onDelta: (delta: string) => void,
): Promise<JsonMap> {
  const job = await apiMutation(path, { ...body, stream: true });
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

async function decode(response: Response): Promise<JsonMap> {
  const data = (await response.json().catch(() => ({}))) as JsonMap;
  if (!response.ok) {
    const error = data.error as JsonMap | undefined;
    throw new Error(String(error?.message ?? `Request failed with HTTP ${response.status}`));
  }
  return data;
}
