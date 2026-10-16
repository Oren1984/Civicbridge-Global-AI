import { keepPreviousData } from "@tanstack/react-query";
import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import { api, qs } from "../../lib/api";
import { useAction } from "../../lib/hooks";
import { useEnum, useI18n } from "../../lib/i18n";
import { Button, Card, Empty, Notice, PageHead, Pagination, Q, StatusBadge, useApi } from "../../components/ui";

export function Audit() {
  const { t, fmtDateTime } = useI18n();
  const en = useEnum();
  const a = useAction();
  const [f, setF] = useState({ action: "", outcome: "", resource_type: "", page: 1 });
  const q = useApi<any>(["gov", "audit", f], `/api/governance/audit${qs({ ...f, page_size: 50 })}`, { placeholderData: keepPreviousData });
  const [verify, setVerify] = useState<any>(null);
  return (
    <>
      <PageHead title={t("audit.title")} sub={t("audit.sub")} actions={
        <Button variant="primary" busy={a.busy} onClick={async () => {
          const r = await a.run(() => api.post("/api/governance/audit/verify"), { invalidate: [["gov", "audit"]] });
          if (r) setVerify(r);
        }}><ShieldCheck size={15} aria-hidden /> {t("audit.verify")}</Button>
      } />
      {verify && (
        <Notice kind={verify.ok ? "success" : "danger"} title={verify.ok ? t("audit.ok") : t("audit.broken")}>
          {verify.ok ? t("audit.okBody", { n: verify.checked }) : t("audit.brokenBody", { seq: verify.broken_at_seq })}
          <div className="xs mono wrap-anywhere">{t("gov.headHash")}: {verify.head}</div>
          <div className="xs" style={{ marginTop: 4 }}>{verify.scope}</div>
        </Notice>
      )}
      <Card>
        <form className="row" role="search" onSubmit={(e) => e.preventDefault()} style={{ marginBottom: 12 }}>
          <label className="sr-only" htmlFor="aa">{t("audit.action")}</label>
          <input id="aa" className="input" style={{ maxWidth: 240 }} placeholder={t("audit.actionPh")} value={f.action} onChange={(e) => setF({ ...f, action: e.target.value, page: 1 })} />
          <label className="sr-only" htmlFor="ao">{t("audit.outcome")}</label>
          <select id="ao" className="select" style={{ width: "auto" }} value={f.outcome} onChange={(e) => setF({ ...f, outcome: e.target.value, page: 1 })}>
            <option value="">{t("audit.anyOutcome")}</option>{["success", "denied", "error"].map((o) => <option key={o} value={o}>{en(o)}</option>)}
          </select>
          <label className="sr-only" htmlFor="ar">{t("audit.resource")}</label>
          <input id="ar" className="input" style={{ maxWidth: 200 }} placeholder={t("audit.resourcePh")} value={f.resource_type} onChange={(e) => setF({ ...f, resource_type: e.target.value, page: 1 })} />
        </form>
        <Q q={q}>
          {(d) => d.items.length === 0 ? <Empty title={t("audit.none")} /> : (
            <>
              <div className="table-wrap"><table>
                <thead><tr><th>#</th><th>{t("audit.when")}</th><th>{t("audit.action")}</th><th>{t("audit.actor")}</th><th>{t("audit.resource")}</th><th>{t("audit.subject")}</th><th>{t("audit.outcome")}</th><th>{t("audit.details")}</th></tr></thead>
                <tbody>{d.items.map((e: any) => (
                  <tr key={e.seq}>
                    <td className="mono">{e.seq}</td>
                    <td className="small">{fmtDateTime(e.at)}</td>
                    <td className="mono small">{e.action}</td>
                    <td className="small">{e.actor_role ? t(`role.${e.actor_role}`) : "—"} <span className="mono xs muted">{e.actor}</span></td>
                    <td className="small">{e.resource_type}</td>
                    <td className="mono xs">{e.subject || "—"}</td>
                    <td><StatusBadge value={e.outcome} /></td>
                    <td className="xs mono wrap-anywhere" style={{ maxWidth: 260 }}>{e.details && Object.keys(e.details).length ? JSON.stringify(e.details) : ""}</td>
                  </tr>
                ))}</tbody>
              </table></div>
              <Pagination meta={d.meta} onPage={(p) => setF({ ...f, page: p })} />
            </>
          )}
        </Q>
        <p className="xs muted" style={{ marginTop: 8 }}>{t("audit.pseudo")}</p>
      </Card>
    </>
  );
}
