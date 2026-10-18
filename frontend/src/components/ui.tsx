import { useEffect, useId, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, FlaskConical, Info, Inbox, Lock, XCircle } from "lucide-react";
import { useQuery, type UseQueryOptions } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useEnum, useI18n } from "../lib/i18n";

/* ------------------------------------------------------------------ data */

export function useApi<T = any>(key: unknown[], url: string | null, opts: Partial<UseQueryOptions<T, ApiError>> = {}) {
  return useQuery<T, ApiError>({ queryKey: key, queryFn: () => api.get<T>(url as string), enabled: url !== null, ...opts });
}

/* ------------------------------------------------------------------ buttons */

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "danger" | "ghost" | "default";
  size?: "sm" | "md";
  busy?: boolean;
  /** Mutating actions are disabled (with an explanation) for the read-only demo account. */
  mutates?: boolean;
};
export function Button({ variant = "default", size = "md", busy, mutates = false, disabled, children, className = "", title, ...rest }: BtnProps) {
  const { readOnly } = useAuth();
  const { t } = useI18n();
  const ro = mutates && readOnly;
  return (
    <button
      type="button"
      {...rest}
      className={`btn ${variant !== "default" ? `btn-${variant}` : ""} ${size === "sm" ? "btn-sm" : ""} ${className}`}
      disabled={disabled || busy || ro}
      aria-disabled={disabled || busy || ro || undefined}
      title={ro ? t("readonly.disabled") : title}
      aria-busy={busy || undefined}
    >
      {ro && <Lock size={14} aria-hidden />}
      {busy && <span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} aria-hidden />}
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ layout bits */

export function PageHead({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </div>
  );
}

export function Card({ title, actions, children, className = "", tight }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; tight?: boolean }) {
  return (
    <section className={`card ${tight ? "card-tight" : ""} ${className}`}>
      {(title || actions) && (
        <div className="card-head">
          {typeof title === "string" ? <h2>{title}</h2> : title}
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Notice({ kind = "info", children, title }: { kind?: "info" | "warning" | "danger" | "success" | "synthetic"; children: ReactNode; title?: string }) {
  const Icon = { info: Info, warning: AlertTriangle, danger: XCircle, success: CheckCircle2, synthetic: FlaskConical }[kind];
  return (
    <div className={`notice n-${kind}`} role={kind === "danger" ? "alert" : undefined}>
      <Icon size={18} aria-hidden />
      <div>
        {title && <strong>{title}. </strong>}
        {children}
      </div>
    </div>
  );
}

export function Loading({ label }: { label?: string }) {
  const { t } = useI18n();
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden /> {label || t("common.loading")}
    </div>
  );
}

export function Empty({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="empty">
      {icon || <Inbox size={32} aria-hidden />}
      <div>
        <strong>{title}</strong>
      </div>
      {children && <div className="small" style={{ marginTop: 6 }}>{children}</div>}
    </div>
  );
}

export function ErrorBox({ error, retry }: { error: unknown; retry?: () => void }) {
  const { t } = useI18n();
  const e = error as ApiError;
  return (
    <Notice kind="danger" title={e?.network ? t("error.offline") : t("error.title")}>
      {e?.status === 404 ? t("error.notFound") : e?.message || String(error)}
      {retry && (
        <div style={{ marginTop: 8 }}>
          <Button size="sm" onClick={retry}>
            {t("common.retry")}
          </Button>
        </div>
      )}
    </Notice>
  );
}

/** Wraps a query: shows loading / error / content. */
export function Q<T>({ q, children }: { q: { isLoading: boolean; error: unknown; data: T | undefined; refetch: () => void }; children: (d: T) => ReactNode }) {
  if (q.isLoading) return <Loading />;
  // Keep showing data we already have when a background refetch fails (for example while offline).
  if (q.error && q.data === undefined) return <ErrorBox error={q.error} retry={() => q.refetch()} />;
  if (q.data === undefined) return null;
  return <>{children(q.data)}</>;
}

/* ------------------------------------------------------------------ forms */

export function Field({ label, hint, error, children, id }: { label: string; hint?: ReactNode; error?: string; children: (id: string, describedBy?: string) => ReactNode; id?: string }) {
  const auto = useId();
  const fid = id || auto;
  const hintId = hint ? `${fid}-hint` : undefined;
  const errId = error ? `${fid}-err` : undefined;
  return (
    <div className="field">
      <label htmlFor={fid}>{label}</label>
      {children(fid, [hintId, errId].filter(Boolean).join(" ") || undefined)}
      {hint && (
        <span className="hint" id={hintId}>
          {hint}
        </span>
      )}
      {error && (
        <span className="error" id={errId} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

export function useFieldErrors(err: unknown) {
  const e = err as ApiError | null;
  return (name: string) => e?.fields?.find((f) => f.field === name || f.field.endsWith(`.${name}`))?.message;
}

/* ------------------------------------------------------------------ modal + confirm */

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const el = ref.current;
    const focusables = () => Array.from(el?.querySelectorAll<HTMLElement>("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])") || []).filter((x) => !x.hasAttribute("disabled"));
    focusables()[0]?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") {
        const f = focusables();
        if (!f.length) return;
        if (e.shiftKey && document.activeElement === f[0]) {
          e.preventDefault();
          f[f.length - 1].focus();
        } else if (!e.shiftKey && document.activeElement === f[f.length - 1]) {
          e.preventDefault();
          f[0].focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      prev?.focus();
    };
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "modal-wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby={titleId} ref={ref}>
        <div className="row-between" style={{ marginBottom: 12 }}>
          <h2 id={titleId} style={{ margin: 0 }}>
            {title}
          </h2>
          <button className="icon-btn" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Confirm({ title, body, confirmLabel, danger, onConfirm, onCancel, requireText }: {
  title: string; body: ReactNode; confirmLabel: string; danger?: boolean; onConfirm: () => Promise<void> | void; onCancel: () => void; requireText?: string;
}) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [typed, setTyped] = useState("");
  return (
    <Modal title={title} onClose={onCancel}>
      <div className="stack">{body}</div>
      {requireText && (
        <Field label={t("confirm.type", { text: requireText })}>
          {(id) => <input id={id} className="input" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />}
        </Field>
      )}
      <div className="form-actions">
        <Button onClick={onCancel}>{t("common.cancel")}</Button>
        <Button
          variant={danger ? "danger" : "primary"}
          busy={busy}
          mutates
          disabled={!!requireText && typed !== requireText}
          onClick={async () => {
            setBusy(true);
            try {
              await onConfirm();
            } finally {
              setBusy(false);
            }
          }}
        >
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}

/* ------------------------------------------------------------------ badges and labels */

const TONE: Record<string, string> = {
  done: "success", clean: "success", approved: "success", active: "success", resolved: "success", closed: "success", decided: "success",
  accepted: "success", reviewed: "success", healthy: "success", succeeded: "success", completed: "success", admitted: "success", answered: "success",
  likely_applicable: "success", success: "success", ok: "success",
  in_progress: "info", in_review: "info", triage: "info", triaged: "info", assigned: "info", submitted: "info", open: "info", scheduled: "info", queued: "info",
  running: "info", processing: "info", waiting: "warning", pending: "warning", info_requested: "warning", decision_pending: "warning", needs_review: "warning",
  needs_more: "warning", blocked: "warning", degraded: "warning", retrying: "warning", appealed: "warning", insufficient_information: "warning",
  partially_completed: "warning", mitigating: "warning", scan_unavailable: "warning", unknown: "warning",
  rejected: "danger", infected: "danger", revoked: "danger", expired: "danger", removed: "danger", dead: "danger", dead_letter: "danger", down: "danger",
  error: "danger", denied: "danger", withdrawn: "danger", declined: "danger", likely_not_applicable: "danger", breached: "danger", unsupported: "danger",
  mock: "synthetic", sandbox: "synthetic", public_data: "accent", authorized_live: "primary", synthetic_illustrative: "synthetic",
};

export function StatusBadge({ value, label }: { value?: string | null; label?: string }) {
  const en = useEnum();
  if (!value) return null;
  return <span className={`badge b-${TONE[value] || "neutral"}`}>{label || en(value)}</span>;
}

export function SyntheticBadge({ text }: { text?: string }) {
  const { t } = useI18n();
  return (
    <span className="badge b-synthetic" title={t("synthetic.tooltip")}>
      <FlaskConical size={12} aria-hidden /> {text || t("synthetic.badge")}
    </span>
  );
}

/** Version and developer credit, shown at the foot of every screen. */
export function CreditFooter() {
  return <footer className="credit-footer">Version 1.0 | Built and developed by Oren Salami</footer>;
}

export function SimulatedBadge() {
  const { t } = useI18n();
  return <span className="badge b-synthetic" title={t("simulated.tooltip")}>{t("simulated.badge")}</span>;
}

/* ------------------------------------------------------------------ misc */

export function Pagination({ meta, onPage }: { meta?: { page: number; pages: number; total: number }; onPage: (p: number) => void }) {
  const { t } = useI18n();
  if (!meta || meta.pages <= 1) return meta ? <div className="pagination small muted">{t("common.total", { n: meta.total })}</div> : null;
  return (
    <nav className="pagination" aria-label={t("common.pagination")}>
      <span className="small muted">{t("common.pageOf", { page: meta.page, pages: meta.pages, total: meta.total })}</span>
      <Button size="sm" disabled={meta.page <= 1} onClick={() => onPage(meta.page - 1)}>
        {t("common.prev")}
      </Button>
      <Button size="sm" disabled={meta.page >= meta.pages} onClick={() => onPage(meta.page + 1)}>
        {t("common.next")}
      </Button>
    </nav>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange, label }: { tabs: { id: T; label: string; count?: number }[]; value: T; onChange: (v: T) => void; label: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((tb, i) => (
        <button
          key={tb.id}
          ref={(el) => {
            refs.current[i] = el;
          }}
          role="tab"
          className="tab"
          aria-selected={value === tb.id}
          tabIndex={value === tb.id ? 0 : -1}
          onClick={() => onChange(tb.id)}
          onKeyDown={(e) => {
            const dir = document.documentElement.dir === "rtl" ? -1 : 1;
            let n = -1;
            if (e.key === "ArrowRight") n = (i + dir + tabs.length) % tabs.length;
            if (e.key === "ArrowLeft") n = (i - dir + tabs.length) % tabs.length;
            if (n >= 0) {
              onChange(tabs[n].id);
              refs.current[n]?.focus();
            }
          }}
        >
          {tb.label}
          {tb.count !== undefined && <span className="badge" style={{ marginInlineStart: 6 }}>{tb.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Progress({ done, total, label }: { done: number; total: number; label?: string }) {
  const pct = total ? Math.round((100 * done) / total) : 0;
  return (
    <div>
      <div className="row-between small">
        <span>{label}</span>
        <span className="muted">
          {done}/{total} · {pct}%
        </span>
      </div>
      <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={label}>
        <span style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function Dl({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="dl">
      {items.map(([k, v]) => (
        <div key={k} style={{ display: "contents" }}>
          <dt>{k}</dt>
          <dd>{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}
