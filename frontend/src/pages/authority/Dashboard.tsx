import { Link } from "react-router";
import { AlarmClock, ClipboardList, Gavel, Inbox, MessageSquareWarning, Scale, UserCheck } from "lucide-react";
import { useI18n } from "../../lib/i18n";
import { Card, Notice, PageHead, Q, SimulatedBadge, useApi } from "../../components/ui";

export function AuthorityDashboard() {
  const { t } = useI18n();
  const q = useApi<any>(["authority-stats"], "/api/authority/stats");
  return (
    <Q q={q}>
      {(d) => (
        <>
          <PageHead title={t("authority.title")} sub={<>{d.tenant} · <SimulatedBadge /></>} />
          <Notice kind="synthetic">{t("authority.simNote")}</Notice>
          <div className="grid grid-4" style={{ margin: "16px 0" }}>
            <Link className="stat" to="/authority/queue?state=open"><div className="v">{d.open}</div><div className="l"><ClipboardList size={14} aria-hidden /> {t("authority.open")}</div></Link>
            <Link className="stat" to="/authority/queue?assigned=me"><div className="v">{d.assigned_to_me}</div><div className="l"><UserCheck size={14} aria-hidden /> {t("authority.mine")}</div></Link>
            <Link className="stat" to="/authority/queue?assigned=unassigned"><div className="v">{d.unassigned}</div><div className="l"><Inbox size={14} aria-hidden /> {t("authority.unassigned")}</div></Link>
            <Link className="stat" to="/authority/queue?sla=breached"><div className="v">{d.sla_breached}</div><div className="l"><AlarmClock size={14} aria-hidden /> {t("authority.breached")}</div></Link>
            <Link className="stat" to="/authority/queue?state=decision_pending"><div className="v">{d.awaiting_approval}</div><div className="l"><Gavel size={14} aria-hidden /> {t("authority.awaiting")}</div></Link>
            <Link className="stat" to="/authority/queue?kind=appeal"><div className="v">{d.open_appeals}</div><div className="l"><Scale size={14} aria-hidden /> {t("authority.appeals")}</div></Link>
            {d.handles_incidents && (
              <Link className="stat" to="/authority/incidents"><div className="v">{d.open_incidents}</div><div className="l"><MessageSquareWarning size={14} aria-hidden /> {t("authority.incidents")}</div></Link>
            )}
          </div>
          <Card title={t("authority.howTitle")}>
            <ul className="small">
              <li>{t("authority.how1")}</li>
              <li>{t("authority.how2")}</li>
              <li>{t("authority.how3")}</li>
            </ul>
          </Card>
        </>
      )}
    </Q>
  );
}
