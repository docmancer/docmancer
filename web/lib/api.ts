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

async function decode(response: Response): Promise<JsonMap> {
  const data = (await response.json().catch(() => ({}))) as JsonMap;
  if (!response.ok) {
    const error = data.error as JsonMap | undefined;
    throw new Error(String(error?.message ?? `Request failed with HTTP ${response.status}`));
  }
  return data;
}
