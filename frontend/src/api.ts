const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

async function readError(response: Response, path: string): Promise<Error> {
  try {
    const payload = await response.json();
    if (typeof payload.detail === "string") {
      return new Error(`${path}: ${payload.detail}`);
    }
  } catch {
    // Keep the network error focused on the failed request when the body is not JSON.
  }
  return new Error(`${path} failed with ${response.status}`);
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) throw await readError(response, `GET ${path}`);
  return response.json();
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw await readError(response, `POST ${path}`);
  return response.json();
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw await readError(response, `PATCH ${path}`);
  return response.json();
}
