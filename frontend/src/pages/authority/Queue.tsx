import { keepPreviousData } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { ClipboardList } from "lucide-react";
import { qs } from "../../lib/api";
import { useEnum, useI18n } from "../../lib/i18n";
import { Card, Empty, PageHead, Pagination, Q, StatusBadge, useApi } from "../../components/ui";

const STATES = ["open", "submitted", "triage", "in_review", "info_requested", "decision_pending", "decided", "closed", "appealed", "withdrawn"];

export function Queue() {
  const { t, fmtDate } = useI18n();
  const en = useEnum();
  const [params] = useSearchParams();
  const [f, setF] = useState({
    state: params.get("state") || "open", queue: "", assigned: params.get("assigned") || "all", sla: params.get("sla") || "",
    kind: params.get("kind") || "", q: "", sort: "sla_due_at", page: 1,
  });
  const set = (k: keyof typeof f, v: string) => setF({ ...f, [k]: v, page: 1 });
  const q = useApi<any>(["queue", f], `/api/authority/queue${qs({ ...f, page_size: 20 })}`, { placeholderData: keepPreviousData });
  return (
    <>
      <PageHead title={t("queue.title")} sub={t("queue.sub")} />
      <Card>
        <form className="row" role="search" onSubmit={(e) => e.preventDefault()} style={{ marginBottom: 12 }}>
          <label className="sr-only" htmlFor="qq">{t("common.search")}</label>
          <input id="qq" className="input" style={{ maxWidth: 240 }} placeholder={t("queue.searchPh")} value={f.q} onChange={(e) => set("q", e.target.value)} />
          <label className="sr-only" htmlFor="qs">{t("common.status")}</label>
          <select id="qs" className="select" style={{ width: "auto" }} value={f.state} onChange={(e) => set("state", e.target.value)}>
            <option value="">{t("common.allStatuses")}</option>
            {STATES.map((s) => <option key={s} value={s}>{en(s)}</option>)}
          </select>
          <label className="sr-only" htmlFor="qqu">{t("queue.queue")}</label>
          <select id="qqu" className="select" style={{ width: "auto" }} value={f.queue} onChange={(e) => set("queue", e.target.value)}>
            <option value="">{t("queue.allQueues")}</option>
            {(q.data?.queues || []).map((x: any) => <option key={x.queue} value={x.queue}>{en(x.queue)} ({x.open})</option>)}
          </select>
          <label className="sr-only" htmlFor="qa">{t("queue.assigned")}</label>
          <select id="qa" className="select" style={{ width: "auto" }} value={f.assigned} onChange={(e) => set("assigned", e.target.value)}>
            <option value="all">{t("queue.anyone")}</option><option value="me">{t("queue.me")}</option><option value="unassigned">{t("queue.unassignedOpt")}</option>
          </select>
          <label className="sr-only" htmlFor="qsl">SLA</label>
          <select id="qsl" className="select" style={{ width: "auto" }} value={f.sla} onChange={(e) => set("sla", e.target.value)}>
            <option value="">{t("queue.anySla")}</option><option value="due_soon">{t("queue.dueSoon")}</option><option value="breached">{t("queue.breachedOpt")}</option>
          </select>
          <label className="sr-only" htmlFor="qk">{t("common.type")}</label>
          <select id="qk" className="select" style={{ width: "auto" }} value={f.kind} onChange={(e) => set("kind", e.target.value)}>
            <option value="">{t("common.allTypes")}</option><option value="application">{en("application")}</option><option value="appeal">{en("appeal")}</option>
          </select>
          <label className="sr-only" htmlFor="qso">{t("common.sort")}</label>
          <select id="qso" className="select" style={{ width: "auto" }} value={f.sort} onChange={(e) => setF({ ...f, sort: e.target.value })}>
            <option value="sla_due_at">{t("sort.slaDue")}</option><option value="-submitted_at">{t("sort.newest")}</option>
            <option value="submitted_at">{t("sort.oldest")}</option><option value="-priority">{t("sort.priority")}</option>
          </select>
        </form>
        <Q q={q}>
          {(d) => d.items.length === 0 ? <Empty title={t("queue.none")} icon={<ClipboardList size={32} />} /> : (
            <>
              <div className="table-wrap"><table>
                <thead><tr>
                  <th>{t("common.reference")}</th><th>{t("common.title")}</th><th>{t("queue.applicant")}</th><th>{t("common.status")}</th>
                  <th>{t("queue.queue")}</th><th>{t("queue.assignee")}</th><th>{t("queue.slaDue")}</th>
                </tr></thead>
                <tbody>{d.items.map((r: any) => (
                  <tr key={r.id}>
                    <td><Link className="mono" to={`/authority/requests/${r.id}`}>{r.reference}</Link>{r.kind === "appeal" && <> <span className="badge b-warning">{en("appeal")}</span></>}</td>
                    <td>{r.title}</td>
                    <td>{r.applicant}</td>
                    <td><StatusBadge value={r.state} /></td>
                    <td>{en(r.queue)}</td>
                    <td>{r.assignee || <span className="muted">{t("queue.unassignedOpt")}</span>}</td>
                    <td>
                      {r.sla_paused_at ? <span className="badge b-warning">{t("queue.paused")}</span> : fmtDate(r.sla_due_at)}
                      {r.sla_breached && <> <span className="badge b-danger">{t("queue.breachedOpt")}</span></>}
                    </td>
                  </tr>
                ))}</tbody>
              </table></div>
              <Pagination meta={d.meta} onPage={(p) => setF({ ...f, page: p })} />
            </>
          )}
        </Q>
      </Card>
    </>
  );
}
