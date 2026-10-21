/** Typed same-origin API client. Never reaches an upstream directly. */

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/** Session-bound CSRF token. Kept in memory only; never localStorage. */
let csrfToken = "";

export function setCsrfToken(token: string | null | undefined): void {
  csrfToken = token ?? "";
}

export function getCsrfToken(): string {
  return csrfToken;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const { headers, ...rest } = init ?? {};
  const method = (init?.method ?? "GET").toUpperCase();
  const merged: Record<string, string> = {
    Accept: "application/json",
    ...(headers as Record<string, string> | undefined)
  };
  if (UNSAFE.has(method) && csrfToken) merged["X-CSRF-Token"] = csrfToken;
  const response = await fetch(path, {
    credentials: "same-origin",
    ...rest,
    headers: merged
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body)
    })
};

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return `${error.status} · ${error.message}`;
  if (error instanceof Error) return error.message;
  return String(error);
}
