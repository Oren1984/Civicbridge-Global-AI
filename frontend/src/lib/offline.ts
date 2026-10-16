// Low-connectivity continuity: a per-user outbox of operations replayed exactly once via /api/sync/replay.
//
// Storage: browser localStorage, keyed by user id. It is NOT encrypted. Only drafts the user typed are kept
// (no documents, no case data). Logout removes everything for that user; account switching never exposes
// another user's outbox because keys are per user id.

import { useEffect, useState, useSyncExternalStore } from "react";
import { api } from "./api";

export interface OutboxOp {
  idempotency_key: string;
  op: "upsert_draft" | "delete_draft" | "submit_incident";
  draft_key: string;
  base_version?: number | null;
  kind?: string;
  title?: string;
  payload: Record<string, unknown>;
  created_at: string;
}
export interface Conflict {
  op: OutboxOp;
  server: { version: number; title: string; payload: Record<string, unknown>; updated_at: string };
}
export interface Failed {
  op: OutboxOp;
  message: string;
}

/** 128-bit random key; getRandomValues also works on plain-HTTP LAN origins where randomUUID does not. */
export function randomKey() {
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
}

const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());
const k = (kind: string, uid: string) => `cb.${kind}.${uid}`;

function read<T>(key: string): T[] {
  try {
    return JSON.parse(localStorage.getItem(key) || "[]") as T[];
  } catch {
    return [];
  }
}
function write(key: string, v: unknown[]) {
  try {
    if (v.length) localStorage.setItem(key, JSON.stringify(v));
    else localStorage.removeItem(key);
  } catch {
    /* storage full or blocked: the UI still shows the in-memory error */
  }
  emit();
}

export const outbox = {
  list: (uid: string) => read<OutboxOp>(k("outbox", uid)),
  conflicts: (uid: string) => read<Conflict>(k("conflicts", uid)),
  failed: (uid: string) => read<Failed>(k("failed", uid)),
  add(uid: string, op: Omit<OutboxOp, "idempotency_key" | "created_at">) {
    const full: OutboxOp = { ...op, idempotency_key: randomKey(), created_at: new Date().toISOString() };
    write(k("outbox", uid), [...outbox.list(uid), full]);
    return full;
  },
  dropConflict(uid: string, draftKey: string) {
    write(k("conflicts", uid), outbox.conflicts(uid).filter((c) => c.op.draft_key !== draftKey));
  },
  dropFailed(uid: string, key: string) {
    write(k("failed", uid), outbox.failed(uid).filter((f) => f.op.idempotency_key !== key));
  },
  /** Replay queued operations. Safe to call repeatedly: the server deduplicates by idempotency key. */
  async flush(uid: string): Promise<{ applied: number; conflicts: number; rejected: number }> {
    const ops = outbox.list(uid);
    if (!ops.length) return { applied: 0, conflicts: 0, rejected: 0 };
    const res = await api.post<{ results: { idempotency_key: string; status: string; result: any }[] }>("/api/sync/replay", {
      ops: ops.map(({ created_at: _c, ...o }) => o),
    });
    let applied = 0;
    const conflicts = outbox.conflicts(uid);
    const failed = outbox.failed(uid);
    for (const r of res.results) {
      const op = ops.find((o) => o.idempotency_key === r.idempotency_key);
      if (!op) continue;
      if (r.status === "applied") applied++;
      else if (r.status === "conflict") conflicts.push({ op, server: r.result.server });
      else failed.push({ op, message: r.result?.message || "Rejected by the server" });
    }
    const done = new Set(res.results.map((r) => r.idempotency_key));
    write(k("outbox", uid), outbox.list(uid).filter((o) => !done.has(o.idempotency_key)));
    write(k("conflicts", uid), conflicts);
    write(k("failed", uid), failed);
    return { applied, conflicts: conflicts.length, rejected: failed.length };
  },
};

/** Small per-user reference data (e.g. the municipality list) kept so forms still open offline. Cleared on logout and
 * session expiry together with the rest of `cb.cache.<uid>.*`. Never used for case or document data. */
export const refCache = {
  get<T>(uid: string | undefined, name: string): T | undefined {
    if (!uid) return undefined;
    try {
      const v = localStorage.getItem(`cb.cache.${uid}.${name}`);
      return v ? (JSON.parse(v) as T) : undefined;
    } catch {
      return undefined;
    }
  },
  set(uid: string | undefined, name: string, value: unknown) {
    if (!uid) return;
    try {
      localStorage.setItem(`cb.cache.${uid}.${name}`, JSON.stringify(value));
    } catch {
      /* storage full or blocked */
    }
  },
};

/** Remove locally stored data for a user. includeUnsynced=false keeps unsent drafts after a session expiry so
 * the user can sign in again and send them; logout (true) removes everything. */
export function purgeOfflineData(uid: string, includeUnsynced: boolean) {
  try {
    if (includeUnsynced) {
      ["outbox", "conflicts", "failed"].forEach((kind) => localStorage.removeItem(k(kind, uid)));
    }
    Object.keys(localStorage)
      .filter((key) => key.startsWith(`cb.cache.${uid}`))
      .forEach((key) => localStorage.removeItem(key));
  } catch {
    /* ignore */
  }
  emit();
}

function subscribe(fn: () => void) {
  listeners.add(fn);
  const onStorage = () => fn();
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(fn);
    window.removeEventListener("storage", onStorage);
  };
}

export function useOutbox(uid: string | undefined) {
  const snap = useSyncExternalStore(
    subscribe,
    () => (uid ? `${localStorage.getItem(k("outbox", uid))}|${localStorage.getItem(k("conflicts", uid))}|${localStorage.getItem(k("failed", uid))}` : ""),
  );
  void snap;
  return {
    pending: uid ? outbox.list(uid) : [],
    conflicts: uid ? outbox.conflicts(uid) : [],
    failed: uid ? outbox.failed(uid) : [],
  };
}

export function useOnline() {
  const [online, setOnline] = useState(typeof navigator === "undefined" ? true : navigator.onLine);
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);
  return online;
}
