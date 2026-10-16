import { keepPreviousData } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { MessageSquareWarning } from "lucide-react";
import { qs } from "../../lib/api";
import { useEnum, useI18n } from "../../lib/i18n";
import { Card, Empty, PageHead, Pagination, Q, StatusBadge, useApi } from "../../components/ui";

const STATUSES = ["open", "submitted", "triaged", "assigned", "in_progress", "resolved", "closed", "duplicate"];

export function IncidentQueue() {
  const { t, fmtDate } = useI18n();
  const en = useEnum();
  const muni = useApi<any>(["municipalities"], "/api/incidents/municipalities");
  const [f, setF] = useState({ status: "open", category: "", assigned: "all", q: "", sort: "sla_due_at", page: 1 });
  const set = (k: keyof typeof f, v: string) => setF({ ...f, [k]: v, page: 1 });
  const q = useApi<any>(["authority-incidents", f], `/api/incidents${qs({ ...f, page_size: 20 })}`, { placeholderData: keepPreviousData });
  return (
    <>
      <PageHead title={t("incq.title")} sub={t("incq.sub")} />
      <Card>
        <form className="row" role="search" onSubmit={(e) => e.preventDefault()} style={{ marginBottom: 12 }}>
          <label className="sr-only" htmlFor="iq">{t("common.search")}</label>
          <input id="iq" className="input" style={{ maxWidth: 240 }} placeholder={t("incq.searchPh")} value={f.q} onChange={(e) => set("q", e.target.value)} />
          <label className="sr-only" htmlFor="is">{t("common.status")}</label>
          <select id="is" className="select" style={{ width: "auto" }} value={f.status} onChange={(e) => set("status", e.target.value)}>
            <option value="">{t("common.allStatuses")}</option>
            {STATUSES.map((s) => <option key={s} value={s}>{en(s)}</option>)}
          </select>
          <label className="sr-only" htmlFor="ic">{t("common.category")}</label>
          <select id="ic" className="select" style={{ width: "auto" }} value={f.category} onChange={(e) => set("category", e.target.value)}>
            <option value="">{t("incq.allCategories")}</option>
            {(muni.data?.categories || []).map((c: string) => <option key={c} value={c}>{en(c)}</option>)}
          </select>
          <label className="sr-only" htmlFor="ia">{t("queue.assigned")}</label>
          <select id="ia" className="select" style={{ width: "auto" }} value={f.assigned} onChange={(e) => set("assigned", e.target.value)}>
            <option value="all">{t("queue.anyone")}</option><option value="me">{t("queue.me")}</option><option value="unassigned">{t("queue.unassignedOpt")}</option>
          </select>
          <label className="sr-only" htmlFor="iso">{t("common.sort")}</label>
          <select id="iso" className="select" style={{ width: "auto" }} value={f.sort} onChange={(e) => setF({ ...f, sort: e.target.value })}>
            <option value="sla_due_at">{t("sort.slaDue")}</option><option value="-created_at">{t("sort.newest")}</option><option value="-priority">{t("sort.priority")}</option>
          </select>
        </form>
        <Q q={q}>
          {(d) => d.items.length === 0 ? <Empty title={t("incq.none")} icon={<MessageSquareWarning size={32} />} /> : (
            <>
              <div className="table-wrap"><table>
                <thead><tr><th>{t("common.reference")}</th><th>{t("common.category")}</th><th>{t("incq.location")}</th><th>{t("review.priority")}</th><th>{t("common.status")}</th><th>{t("queue.slaDue")}</th><th>{t("common.created")}</th></tr></thead>
                <tbody>{d.items.map((i: any) => (
                  <tr key={i.id}>
                    <td><Link className="mono" to={`/authority/incidents/${i.id}`}>{i.reference}</Link></td>
                    <td>{en(i.category)}{i.category_source === "rules_suggestion" && <span className="xs muted"> · {t("incq.suggested")}</span>}</td>
                    <td className="small">{i.location_text || (i.lat_approx != null ? `${i.lat_approx}, ${i.lon_approx}` : "—")}</td>
                    <td>{en(i.priority)}</td>
                    <td><StatusBadge value={i.status} /></td>
                    <td>{fmtDate(i.sla_due_at)}{i.sla_breached && <> <span className="badge b-danger">{t("queue.breachedOpt")}</span></>}</td>
                    <td>{fmtDate(i.created_at)}</td>
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
