import { keepPreviousData } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { FolderOpen } from "lucide-react";
import { api, qs } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useAction } from "../../lib/hooks";
import { useEnum, useI18n } from "../../lib/i18n";
import { Button, Card, Empty, Field, Modal, PageHead, Pagination, Q, StatusBadge, useApi } from "../../components/ui";

export function CaseList() {
  const { t, fmtDate } = useI18n();
  const en = useEnum();
  const { me } = useAuth();
  const [f, setF] = useState({ q: "", status: "", case_type: "", sort: "-updated_at", page: 1 });
  const [creating, setCreating] = useState(false);
  const url = `/api/cases${qs({ ...f, page_size: 15 })}`;
  const q = useApi<any>(["cases", f], url, { placeholderData: keepPreviousData });
  const citizen = me?.active?.workspace === "citizen";
  const title = citizen ? t("cases.title") : me?.active?.workspace === "professional" ? t("nav.delegatedCases") : t("nav.sharedCases");
  return (
    <>
      <PageHead title={title} sub={citizen ? t("cases.sub") : t("cases.subShared")} actions={citizen && <Button variant="primary" mutates onClick={() => setCreating(true)}>{t("cases.new")}</Button>} />
      <Card>
        <form className="row" role="search" onSubmit={(e) => e.preventDefault()} style={{ marginBottom: 12 }}>
          <label className="sr-only" htmlFor="cq">{t("common.search")}</label>
          <input id="cq" className="input" style={{ maxWidth: 280 }} placeholder={t("cases.searchPh")} value={f.q} onChange={(e) => setF({ ...f, q: e.target.value, page: 1 })} />
          <label className="sr-only" htmlFor="cs">{t("common.status")}</label>
          <select id="cs" className="select" style={{ width: "auto" }} value={f.status} onChange={(e) => setF({ ...f, status: e.target.value, page: 1 })}>
            <option value="">{t("common.allStatuses")}</option><option value="open">{en("open")}</option><option value="closed">{en("closed")}</option><option value="archived">{en("archived")}</option>
          </select>
          <label className="sr-only" htmlFor="ct">{t("common.type")}</label>
          <select id="ct" className="select" style={{ width: "auto" }} value={f.case_type} onChange={(e) => setF({ ...f, case_type: e.target.value, page: 1 })}>
            <option value="">{t("common.allTypes")}</option>{["life_event", "rights", "incident", "general"].map((x) => <option key={x} value={x}>{en(x)}</option>)}
          </select>
          <label className="sr-only" htmlFor="cso">{t("common.sort")}</label>
          <select id="cso" className="select" style={{ width: "auto" }} value={f.sort} onChange={(e) => setF({ ...f, sort: e.target.value })}>
            <option value="-updated_at">{t("sort.recent")}</option><option value="-created_at">{t("sort.newest")}</option><option value="title">{t("sort.title")}</option>
          </select>
        </form>
        <Q q={q}>
          {(d) => d.items.length === 0 ? <Empty title={t("cases.none")} icon={<FolderOpen size={32} />}>{citizen && <Link to="/journeys">{t("journeys.start")}</Link>}</Empty> : (
            <>
              <div className="table-wrap"><table>
                <thead><tr><th>{t("common.reference")}</th><th>{t("common.title")}</th><th>{t("common.type")}</th><th>{t("common.progress")}</th><th>{t("common.status")}</th><th>{t("common.updated")}</th></tr></thead>
                <tbody>{d.items.map((c: any) => (
                  <tr key={c.id}>
                    <td className="mono">{c.reference}</td>
                    <td><Link to={`/cases/${c.id}`}>{c.title}</Link></td>
                    <td>{en(c.case_type)}</td>
                    <td>{c.progress.total ? `${c.progress.done}/${c.progress.total}` : "—"}</td>
                    <td><StatusBadge value={c.status} /></td>
                    <td>{fmtDate(c.updated_at)}</td>
                  </tr>
                ))}</tbody>
              </table></div>
              <Pagination meta={d.meta} onPage={(p) => setF({ ...f, page: p })} />
            </>
          )}
        </Q>
      </Card>
      {creating && <NewCase onClose={() => setCreating(false)} />}
    </>
  );
}

function NewCase({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const a = useAction();
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  return (
    <Modal title={t("cases.new")} onClose={onClose}>
      <Field label={t("common.title")} error={title.length > 0 && title.length < 3 ? t("validation.min3") : undefined}>
        {(id, d) => <input id={id} aria-describedby={d} className="input" value={title} onChange={(e) => setTitle(e.target.value)} />}
      </Field>
      <Field label={t("cases.summary")}>{(id) => <textarea id={id} className="textarea" value={summary} onChange={(e) => setSummary(e.target.value)} />}</Field>
      <div className="form-actions">
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" mutates busy={a.busy} disabled={title.length < 3} onClick={async () => {
          const r = await a.run(() => api.post("/api/cases", { title, summary }), { success: t("cases.created"), invalidate: [["cases"]] });
          if (r) onClose();
        }}>{t("common.create")}</Button>
      </div>
    </Modal>
  );
}
