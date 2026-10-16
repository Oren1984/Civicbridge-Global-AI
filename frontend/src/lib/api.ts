// Minimal API client. Session is an HttpOnly cookie; mutations send the CSRF token from /api/auth/me.

export class ApiError extends Error {
  status: number;
  code: string;
  fields?: { field: string; message: string }[];
  extra: Record<string, unknown>;
  constructor(status: number, code: string, message: string, extra: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.extra = extra;
    this.fields = extra.fields as ApiError["fields"];
  }
  /** True when the request failed because the browser is offline or the server is unreachable. */
  get network() {
    return this.status === 0;
  }
}

let csrfToken: string | null = null;
export function setCsrf(token: string | null) {
  csrfToken = token;
}

type Listener = (e: ApiError) => void;
const authListeners = new Set<Listener>();
/** Subscribe to 401/403-mfa events (session expiry, MFA re-verification). */
export function onAuthProblem(fn: Listener) {
  authListeners.add(fn);
  return () => {
    authListeners.delete(fn);
  };
}

async function parse(res: Response) {
  const type = res.headers.get("content-type") || "";
  if (type.includes("application/json")) return res.json();
  return res.text();
}

export async function request<T = any>(method: string, url: string, body?: unknown, opts: { form?: FormData; raw?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  let payload: BodyInit | undefined;
  if (opts.form) payload = opts.form;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let res: Response;
  try {
    res = await fetch(url, { method, headers, body: payload, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "network", "You appear to be offline or the server is unreachable.");
  }
  if (opts.raw && res.ok) return res as unknown as T;
  const data = await parse(res);
  if (!res.ok) {
    const err = data?.error || {};
    const e = new ApiError(res.status, err.code || `http_${res.status}`, err.message || res.statusText || "Request failed", err);
    if (res.status === 401 || (res.status === 403 && e.code === "mfa_required")) authListeners.forEach((l) => l(e));
    throw e;
  }
  return data as T;
}

export const api = {
  get: <T = any>(url: string) => request<T>("GET", url),
  post: <T = any>(url: string, body?: unknown) => request<T>("POST", url, body ?? {}),
  put: <T = any>(url: string, body?: unknown) => request<T>("PUT", url, body ?? {}),
  patch: <T = any>(url: string, body?: unknown) => request<T>("PATCH", url, body ?? {}),
  del: <T = any>(url: string) => request<T>("DELETE", url),
  upload: <T = any>(url: string, form: FormData) => request<T>("POST", url, undefined, { form }),
};

/** Download an authorized file through the API (keeps the session cookie; no public URLs). */
export async function downloadFile(url: string, filename: string) {
  const res = await request<Response>("GET", url, undefined, { raw: true });
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

/** Fetch an authorized file as an object URL for inline preview. */
export async function objectUrl(url: string): Promise<{ url: string; type: string }> {
  const res = await request<Response>("GET", url, undefined, { raw: true });
  const blob = await res.blob();
  return { url: URL.createObjectURL(blob), type: blob.type };
}

export function qs(params: Record<string, string | number | boolean | undefined | null>) {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}
