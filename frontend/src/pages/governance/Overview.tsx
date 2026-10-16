import { Link } from "react-router";
import { AlertOctagon, FileWarning, ScrollText, Siren } from "lucide-react";
import { useEnum, useI18n } from "../../lib/i18n";
import { Card, Dl, Notice, PageHead, Q, StatusBadge, useApi } from "../../components/ui";

export function GovernanceOverview() {
  const { t, fmtDateTime } = useI18n();
  const en = useEnum();
  const q = useApi<any>(["gov", "overview"], "/api/governance/overview");
  const ops = useApi<any>(["gov", "operations"], "/api/governance/operations");
  return (
    <>
      <PageHead title={t("gov.title")} sub={t("gov.sub")} />
      <Notice kind="info">{t("gov.noContent")}</Notice>
      <Q q={q}>
        {(d) => (
          <>
            <div className="grid grid-4" style={{ margin: "16px 0" }}>
              <Link className="stat" to="/governance/incidents"><div className="v">{d.open_security_incidents}</div><div className="l"><Siren size={14} aria-hidden /> {t("gov.openIncidents")}</div></Link>
              <Link className="stat" to="/governance/risks"><div className="v">{d.open_risks}</div><div className="l"><AlertOctagon size={14} aria-hidden /> {t("gov.openRisks")}</div></Link>
              <Link className="stat" to="/governance/quality"><div className="v">{d.rule_versions_past_review}</div><div className="l"><ScrollText size={14} aria-hidden /> {t("gov.staleRules")}</div></Link>
              <Link className="stat" to="/governance/quality"><div className="v">{d.quarantined_files}</div><div className="l"><FileWarning size={14} aria-hidden /> {t("gov.quarantined")}</div></Link>
            </div>
            <div className="grid grid-2" style={{ alignItems: "start" }}>
              <Card title={t("gov.audit")}>
                <Dl items={[
                  [t("gov.events"), String(d.audit.events)],
                  [t("gov.lastEvent"), fmtDateTime(d.audit.last_at)],
                  [t("gov.headHash"), <span className="mono wrap-anywhere xs">{d.audit.head_hash}</span>],
                ]} />
                <Link to="/governance/audit">{t("gov.openAudit")}</Link>
              </Card>
              <Card title={t("gov.platform")}>
                <Dl items={[
                  [t("gov.tenants"), String(d.tenants)],
                  [t("gov.aiMode"), en(d.ai_mode)],
                  ...Object.entries(d.memberships_by_workspace).map(([ws, n]) => [t(`workspace.${ws}`), String(n)] as [string, string]),
                ]} />
              </Card>
              <Card title={t("nav.integrations")}>
                <ul className="list">{d.adapters.map((x: any) => (
                  <li key={x.code} className="row-between"><span>{x.name} <span className="xs muted mono">{x.code}</span></span><span className="row"><StatusBadge value={x.state} /><StatusBadge value={x.health_status} /></span></li>
                ))}</ul>
              </Card>
              <Card title={t("gov.services")}>
                <Q q={ops}>
                  {(o) => (
                    <ul className="list">
                      {(["storage", "scanner", "video"] as const).map((k) => (
                        <li key={k} className="row-between">
                          <span><b>{t(`gov.svc.${k}`)}</b><div className="xs muted">{o[k].detail}{o[k].version ? ` · ${o[k].version}` : ""}</div></span>
                          <StatusBadge value={o[k].ok ? "healthy" : "down"} />
                        </li>
                      ))}
                    </ul>
                  )}
                </Q>
                <div className="chip-row" style={{ marginTop: 8 }}>
                  {Object.entries(d.jobs).map(([s, n]) => <span key={s} className="badge">{en(s)}: {String(n)}</span>)}
                </div>
              </Card>
            </div>
          </>
        )}
      </Q>
    </>
  );
}
