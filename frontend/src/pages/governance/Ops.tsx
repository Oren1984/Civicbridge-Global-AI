import { keepPreviousData } from "@tanstack/react-query";
import { useState } from "react";
import { api, qs } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useAction } from "../../lib/hooks";
import { useEnum, useI18n } from "../../lib/i18n";
import { Button, Card, Dl, Empty, Notice, PageHead, Pagination, Q, StatusBadge, useApi } from "../../components/ui";
import { TransparencyBody } from "../public/Transparency";

const useIsAdmin = () => useAuth().me?.active?.role === "governance_admin";

/* ------------------------------------------------------------------ integrations */

export function Integrations() {
  const { t, fmtDateTime } = useI18n();
  const en = useEnum();
  const admin = useIsAdmin();
  const { readOnly } = useAuth();
  const a = useAction();
  const q = useApi<any>(["gov", "integrations"], "/api/governance/integrations");
  const inv = [["gov", "integrations"], ["gov", "overview"]];
  return (
    <>
      <PageHead title={t("integ.title")} sub={t("integ.sub")} />
      <Notice kind="synthetic">{t("integ.noLive")}</Notice>
      <Q q={q}>
        {(d) => (
          <>
            <Card title={t("integ.states")} tight>
              <Dl items={Object.entries(d.states).map(([k, v]) => [en(k), String(v)])} />
            </Card>
            <div className="stack" style={{ marginTop: 16 }}>
              {d.items.map((x: any) => (
                <Card key={x.id} title={<h2 style={{ margin: 0 }}>{x.name} <span className="xs muted mono">{x.code}</span></h2>} actions={<><StatusBadge value={x.state} /><StatusBadge value={x.health_status} /></>}>
                  <p className="small">{x.description}</p>
                  <Dl items={[
                    [t("integ.jurisdiction"), x.jurisdiction_code],
                    [t("integ.capabilities"), (x.capabilities || []).join(", ")],
                    [t("integ.lastCheck"), fmtDateTime(x.last_check_at)],
                    [t("integ.lastError"), x.last_error ? <span className="small" style={{ color: "var(--danger)" }}>{x.last_error}</span> : null],
                    [t("integ.limits"), t("integ.limitsVal", { ms: x.timeout_ms, n: x.max_retries })],
                    [t("integ.runs"), Object.entries(x.runs).map(([s, n]) => `${en(s)}: ${n}`).join(" · ") || "—"],
                  ]} />
                  <div className="row" style={{ marginTop: 8 }}>
                    <Button size="sm" busy={a.busy} onClick={() => a.run(() => api.post(`/api/governance/integrations/${x.id}/check`), { success: t("integ.checked"), invalidate: inv })}>{t("integ.check")}</Button>
                    {admin && (
                      <>
                        <Button size="sm" mutates busy={a.busy} onClick={() => a.run(() => api.patch(`/api/governance/integrations/${x.id}`, { enabled: !x.enabled }), { success: t("integ.saved"), invalidate: inv })}>
                          {x.enabled ? t("integ.disable") : t("integ.enable")}
                        </Button>
                        <label className="sr-only" htmlFor={`fi-${x.id}`}>{t("integ.failure")}</label>
                        <select id={`fi-${x.id}`} className="select" style={{ width: "auto" }} value={x.failure_injection} disabled={readOnly}
                          onChange={(e) => a.run(() => api.patch(`/api/governance/integrations/${x.id}`, { failure_injection: e.target.value }), { success: t("integ.saved"), invalidate: inv })}>
                          {["none", "timeout", "error"].map((m) => <option key={m} value={m}>{t("integ.inject", { mode: en(m) })}</option>)}
                        </select>
                      </>
                    )}
                    {!x.enabled && <span className="badge b-warning">{t("integ.disabled")}</span>}
                  </div>
                </Card>
              ))}
            </div>
          </>
        )}
      </Q>
    </>
  );
}

/* ------------------------------------------------------------------ jobs */

export function Jobs() {
  const { t, fmtDateTime } = useI18n();
  const en = useEnum();
  const admin = useIsAdmin();
  const a = useAction();
  const [f, setF] = useState({ status: "", page: 1 });
  const q = useApi<any>(["gov", "jobs", f], `/api/governance/jobs${qs({ ...f, page_size: 30 })}`, { placeholderData: keepPreviousData, refetchInterval: 10000 });
  return (
    <>
      <PageHead title={t("jobs.title")} sub={t("jobs.sub")} />
      <Q q={q}>
        {(d) => (
          <>
            <Card title={t("jobs.workers")} tight>
              {d.workers.length === 0 ? <Notice kind="warning">{t("jobs.noWorker")}</Notice> : (
                <ul className="list">{d.workers.map((w: any) => (
                  <li key={w.worker_id} className="row-between"><span className="mono small">{w.worker_id}</span><span className="row"><span className="xs muted">{fmtDateTime(w.seen_at)}</span><StatusBadge value={w.alive ? "healthy" : "down"} /></span></li>
                ))}</ul>
              )}
            </Card>
            <div style={{ marginTop: 16 }} />
            <Card>
              <div className="row" style={{ marginBottom: 12 }}>
                <label className="sr-only" htmlFor="js">{t("common.status")}</label>
                <select id="js" className="select" style={{ width: "auto" }} value={f.status} onChange={(e) => setF({ status: e.target.value, page: 1 })}>
                  <option value="">{t("common.allStatuses")}</option>
                  {["queued", "running", "succeeded", "failed", "dead"].map((s) => <option key={s} value={s}>{en(s)}</option>)}
                </select>
              </div>
              {d.items.length === 0 ? <Empty title={t("jobs.none")} /> : (
                <>
                  <div className="table-wrap"><table>
                    <thead><tr><th>{t("common.type")}</th><th>{t("common.status")}</th><th>{t("jobs.attempts")}</th><th>{t("jobs.runAfter")}</th><th>{t("jobs.finished")}</th><th>{t("integ.lastError")}</th><th /></tr></thead>
                    <tbody>{d.items.map((j: any) => (
                      <tr key={j.id}>
                        <td className="mono small">{j.kind}</td>
                        <td><StatusBadge value={j.status} /></td>
                        <td>{j.attempts}/{j.max_attempts}</td>
                        <td className="small">{fmtDateTime(j.run_after)}</td>
                        <td className="small">{fmtDateTime(j.finished_at)}</td>
                        <td className="xs wrap-anywhere" style={{ maxWidth: 280 }}>{j.last_error || ""}</td>
                        <td>{admin && (j.status === "dead" || j.status === "failed") && (
                          <Button size="sm" mutates busy={a.busy} onClick={() => a.run(() => api.post(`/api/governance/jobs/${j.id}/retry`), { success: t("jobs.requeued"), invalidate: [["gov", "jobs"]] })}>{t("jobs.retry")}</Button>
                        )}</td>
                      </tr>
                    ))}</tbody>
                  </table></div>
                  <Pagination meta={d.meta} onPage={(p) => setF({ ...f, page: p })} />
                </>
              )}
            </Card>
          </>
        )}
      </Q>
    </>
  );
}

/* ------------------------------------------------------------------ data quality */

export function DataQuality() {
  const { t, fmtDate, fmtDateTime } = useI18n();
  const en = useEnum();
  const q = useApi<any>(["gov", "dq"], "/api/governance/data-quality");
  const counts = (o: Record<string, number>) => Object.entries(o).map(([k, v]) => <span key={k} className="badge">{en(k)}: {v}</span>);
  return (
    <>
      <PageHead title={t("dq.title")} sub={t("dq.sub")} />
      <Q q={q}>
        {(d) => (
          <div className="stack">
            <div className="grid grid-4">
              <div className="stat"><div className="v">{d.sources.total}</div><div className="l">{t("dq.sources")}</div></div>
              <div className="stat"><div className="v">{d.sources.placeholder}</div><div className="l">{t("dq.placeholder")}</div></div>
              <div className="stat"><div className="v">{d.sources.past_review}</div><div className="l">{t("dq.pastReview")}</div></div>
              <div className="stat"><div className="v">{d.documents_expiring_90d}</div><div className="l">{t("dq.expiring")}</div></div>
              <div className="stat"><div className="v">{d.overdue_tasks}</div><div className="l">{t("dq.overdue")}</div></div>
            </div>
            <Card title={t("dq.rules")}>
              <div className="table-wrap"><table>
                <thead><tr><th>{t("dq.ruleSet")}</th><th>{t("dq.version")}</th><th>{t("dq.reviewDate")}</th><th>{t("dq.review")}</th><th>{t("dq.verification")}</th></tr></thead>
                <tbody>{d.rule_versions.map((r: any) => (
                  <tr key={`${r.rule_set}-${r.version}`}>
                    <td className="mono small">{r.rule_set}</td><td>{r.version}</td>
                    <td>{fmtDate(r.review_date)} {r.stale && <span className="badge b-warning">{t("dq.stale")}</span>}</td>
                    <td><StatusBadge value={r.review_status} /></td><td><StatusBadge value={r.verification_status} /></td>
                  </tr>
                ))}</tbody>
              </table></div>
            </Card>
            <Card title={t("dq.packs")}>
              <div className="table-wrap"><table>
                <thead><tr><th>{t("dq.pack")}</th><th>{t("dq.version")}</th><th>{t("common.status")}</th><th>{t("dq.checksum")}</th><th>{t("dq.loaded")}</th></tr></thead>
                <tbody>{d.packs.map((p: any) => (
                  <tr key={p.code}><td><b>{p.title}</b> <span className="mono xs muted">{p.code}</span></td><td>{p.version}</td><td><StatusBadge value={p.status} /></td><td className="mono xs wrap-anywhere">{p.checksum?.slice(0, 16)}…</td><td className="small">{fmtDateTime(p.loaded_at)}</td></tr>
                ))}</tbody>
              </table></div>
            </Card>
            <div className="grid grid-3">
              <Card title={t("dq.scan")} tight><div className="chip-row">{counts(d.scan_status)}</div></Card>
              <Card title={t("nav.consent")} tight><div className="chip-row">{counts(d.consents)}</div></Card>
              <Card title={t("nav.delegations")} tight><div className="chip-row">{counts(d.delegations)}</div></Card>
            </div>
          </div>
        )}
      </Q>
    </>
  );
}

/* ------------------------------------------------------------------ reporting */

export function Reporting() {
  const { t } = useI18n();
  const en = useEnum();
  const q = useApi<any>(["gov", "analytics"], "/api/governance/analytics");
  const co = useApi<any>(["gov", "consent-oversight"], "/api/governance/consent-oversight");
  return (
    <>
      <PageHead title={t("reporting.title")} sub={t("reporting.sub")} />
      <Q q={q}>{(d) => <TransparencyBody data={d} />}</Q>
      <div style={{ marginTop: 16 }} />
      <Card title={t("reporting.consent")}>
        <Q q={co}>
          {(d) => d.items.length === 0 ? <Empty title={t("reporting.noConsent")} /> : (
            <>
              <div className="table-wrap"><table>
                <thead><tr><th>{t("review.recipient")}</th><th>{t("common.status")}</th><th>{t("reporting.count")}</th></tr></thead>
                <tbody>{d.items.map((r: any, i: number) => (
                  <tr key={i}><td>{r.recipient}</td><td>{en(r.status)}</td><td>{r.suppressed ? <span className="muted">{t("transparency.suppressed", { k: d.k_threshold })}</span> : r.count}</td></tr>
                ))}</tbody>
              </table></div>
              <p className="xs muted">{t("reporting.suppressionNote", { k: d.k_threshold })}</p>
            </>
          )}
        </Q>
      </Card>
    </>
  );
}

/* ------------------------------------------------------------------ AI oversight */

export function AIOversight() {
  const { t, fmtDateTime } = useI18n();
  const en = useEnum();
  const q = useApi<any>(["gov", "ai"], "/api/governance/ai");
  const st = useApi<any>(["ai-status"], "/api/ai/status");
  return (
    <>
      <PageHead title={t("aio.title")} sub={t("aio.sub")} />
      <Q q={q}>
        {(d) => (
          <div className="stack">
            <Notice kind="info">{d.note}</Notice>
            {st.data && (
              <Card title={t("aio.config")}>
                <Dl items={[
                  [t("gov.aiMode"), <>{en(st.data.mode)} <span className="xs muted">— {st.data.modes?.[st.data.mode]}</span></>],
                  [t("aio.retrieval"), st.data.retrieval],
                  [t("aio.never"), <ul className="small" style={{ margin: 0 }}>{Object.entries(st.data.never_automated || {}).map(([k, why]) => <li key={k}><b>{k.replace(/_/g, " ")}</b> — {String(why)}</li>)}</ul>],
                ]} />
              </Card>
            )}
            <Card title={t("aio.byTool")}>
              {d.by_tool.length === 0 ? <Empty title={t("aio.none")} /> : (
                <div className="table-wrap"><table>
                  <thead><tr><th>{t("aio.tool")}</th><th>{t("common.status")}</th><th>{t("reporting.count")}</th></tr></thead>
                  <tbody>{d.by_tool.map((r: any) => <tr key={`${r.tool}-${r.status}`}><td className="mono small">{r.tool}</td><td><StatusBadge value={r.status} /></td><td>{r.count}</td></tr>)}</tbody>
                </table></div>
              )}
            </Card>
            <Card title={t("aio.exceptions")}>
              {d.recent_exceptions.length === 0 ? <Empty title={t("aio.noExceptions")} /> : (
                <div className="table-wrap"><table>
                  <thead><tr><th>{t("audit.when")}</th><th>{t("aio.tool")}</th><th>{t("common.status")}</th><th>{t("aio.reason")}</th><th>{t("aio.mode")}</th></tr></thead>
                  <tbody>{d.recent_exceptions.map((c: any) => (
                    <tr key={c.id}><td className="small">{fmtDateTime(c.created_at)}</td><td className="mono small">{c.tool}</td><td><StatusBadge value={c.status} /></td><td className="small">{c.reason}</td><td>{en(c.mode)}</td></tr>
                  ))}</tbody>
                </table></div>
              )}
            </Card>
          </div>
        )}
      </Q>
    </>
  );
}
