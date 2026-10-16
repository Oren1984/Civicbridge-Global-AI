import { Link } from "react-router";
import { AlarmClock, FileWarning, Inbox, Map, MessageSquareWarning, ShieldCheck, Video } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useEnum, useI18n } from "../../lib/i18n";
import { Card, Empty, Notice, PageHead, Progress, Q, StatusBadge, useApi } from "../../components/ui";

export function CitizenOverview() {
  const { t, fmtDate, fmtDateTime } = useI18n();
  const en = useEnum();
  const { me } = useAuth();
  const q = useApi<any>(["overview", "citizen"], "/api/overview/citizen");
  return (
    <>
      <PageHead title={t("overview.hello", { name: me?.user.display_name.split(" ")[0] })} sub={t("overview.sub")}
        actions={<><Link className="btn btn-primary" to="/journeys">{t("journeys.start")}</Link><Link className="btn" to="/incidents?new=1">{t("incidents.report")}</Link></>} />
      <Q q={q}>
        {(d) => (
          <>
            {d.emergency_notices.map((n: any) => (
              <Notice key={n.id} kind={n.severity === "critical" || n.severity === "warning" ? "warning" : "info"} title={n.title}>
                <span className="xs">{n.source_label}</span> · <Link to="/continuity">{t("common.details")}</Link>
              </Notice>
            ))}
            <div className="grid grid-4" style={{ marginBottom: 16 }}>
              <Link className="stat" to="/cases"><div className="v">{d.deadlines.length}</div><div className="l"><AlarmClock size={14} aria-hidden /> {t("overview.deadlines")}</div></Link>
              <Link className="stat" to="/cases"><div className="v">{d.information_requests.length}</div><div className="l"><Inbox size={14} aria-hidden /> {t("overview.infoRequests")}</div></Link>
              <Link className="stat" to="/consent"><div className="v">{d.pending_consent_requests}</div><div className="l"><ShieldCheck size={14} aria-hidden /> {t("overview.consentRequests")}</div></Link>
              <Link className="stat" to="/notifications"><div className="v">{d.unread_notifications}</div><div className="l">{t("overview.unread")}</div></Link>
            </div>
            <div className="grid grid-2">
              <Card title={t("overview.actionNeeded")}>
                {d.information_requests.length === 0 && d.deadlines.length === 0 ? (
                  <Empty title={t("overview.nothingDue")} />
                ) : (
                  <ul className="list">
                    {d.information_requests.map((i: any) => (
                      <li key={i.id}>
                        <div className="row-between">
                          <Link to={`/cases/${i.case_id}`}><b>{t("overview.authorityAsks", { ref: i.request_reference })}</b></Link>
                          <span className="badge b-warning">{t("common.due", { date: fmtDate(i.due_at) })}</span>
                        </div>
                        <div className="small muted">{i.message}</div>
                      </li>
                    ))}
                    {d.deadlines.map((x: any) => (
                      <li key={x.task_id} className="row-between">
                        <Link to={`/cases/${x.case_id}`}>{x.title}</Link>
                        <span className={`badge ${x.overdue ? "b-danger" : "b-info"}`}>{x.overdue ? t("common.overdue") : t("common.due", { date: fmtDate(x.due_at) })}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
              <Card title={t("overview.journeys")} actions={<Link to="/journeys" className="small">{t("common.all")}</Link>}>
                {d.journeys.length === 0 ? (
                  <Empty title={t("journeys.none")} icon={<Map size={32} />}><Link to="/journeys">{t("journeys.start")}</Link></Empty>
                ) : (
                  <ul className="list">
                    {d.journeys.map((j: any) => (
                      <li key={j.case_id}>
                        <Link to={`/cases/${j.case_id}`}><b>{j.title}</b></Link> <span className="xs muted">{j.reference}</span>
                        <Progress done={j.done} total={j.total} label={t("overview.targetDate", { date: fmtDate(j.target_date) })} />
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
              <Card title={t("overview.meetings")} actions={<Link to="/meetings" className="small">{t("common.all")}</Link>}>
                {d.meetings.length === 0 ? <Empty title={t("meetings.none")} icon={<Video size={32} />} /> : (
                  <ul className="list">
                    {d.meetings.map((m: any) => (
                      <li key={m.id} className="row-between">
                        <span><Link to={`/meetings/${m.id}`}>{m.title}</Link><br /><span className="small muted">{fmtDateTime(m.scheduled_start)}</span></span>
                        <StatusBadge value={m.status} />
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
              <Card title={t("overview.documents")} actions={<Link to="/wallet" className="small">{t("nav.wallet")}</Link>}>
                {d.expiring_documents.length === 0 ? <Empty title={t("overview.noExpiring")} icon={<FileWarning size={32} />} /> : (
                  <ul className="list">
                    {d.expiring_documents.map((x: any) => (
                      <li key={x.id} className="row-between"><Link to={`/wallet/${x.id}`}>{x.title}</Link><span className="badge b-warning">{t("wallet.expires", { date: fmtDate(x.expires_at) })}</span></li>
                    ))}
                  </ul>
                )}
              </Card>
              <Card title={t("overview.incidents")} actions={<Link to="/incidents" className="small">{t("common.all")}</Link>}>
                {d.incidents.length === 0 ? <Empty title={t("incidents.none")} icon={<MessageSquareWarning size={32} />} /> : (
                  <ul className="list">
                    {d.incidents.map((x: any) => (
                      <li key={x.id} className="row-between"><Link to={`/incidents/${x.id}`}>{x.reference} · {en(x.category)}</Link><StatusBadge value={x.status} /></li>
                    ))}
                  </ul>
                )}
              </Card>
            </div>
          </>
        )}
      </Q>
    </>
  );
}
