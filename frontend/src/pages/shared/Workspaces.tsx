import { Link } from "react-router";
import { Video } from "lucide-react";
import { useEnum, useI18n } from "../../lib/i18n";
import { Card, Empty, Notice, PageHead, Q, StatusBadge, useApi } from "../../components/ui";
import { DelegationList } from "../citizen/Delegations";

function MeetingsCard({ items }: { items: any[] }) {
  const { t, fmtDateTime } = useI18n();
  return (
    <Card title={t("nav.meetings")}>
      {items.length === 0 ? <Empty title={t("meetings.none")} icon={<Video size={32} />} /> : (
        <ul className="list">{items.map((m) => (
          <li key={m.id} className="row-between">
            <span><Link to={`/meetings/${m.id}`}>{m.title}</Link><div className="xs muted">{fmtDateTime(m.scheduled_start, m.timezone)} ({m.timezone})</div></span>
            <StatusBadge value={m.status} />
          </li>
        ))}</ul>
      )}
    </Card>
  );
}

function CaseRows({ items, owner }: { items: any[]; owner?: boolean }) {
  const { t, fmtDate } = useI18n();
  if (!items.length) return <Empty title={t("cases.none")} />;
  return (
    <div className="table-wrap"><table>
      <thead><tr><th>{t("common.reference")}</th><th>{t("common.title")}</th>{owner && <th>{t("aconsent.citizen")}</th>}<th>{t("common.status")}</th><th>{t("common.updated")}</th></tr></thead>
      <tbody>{items.map((c) => (
        <tr key={c.id}><td className="mono">{c.reference}</td><td><Link to={`/cases/${c.id}`}>{c.title}</Link></td>{owner && <td>{c.owner}</td>}<td><StatusBadge value={c.status} /></td><td>{fmtDate(c.updated_at)}</td></tr>
      ))}</tbody>
    </table></div>
  );
}

export function InstitutionOverview() {
  const { t, fmtDate } = useI18n();
  const en = useEnum();
  const q = useApi<any>(["overview", "institution"], "/api/overview/institution");
  return (
    <Q q={q}>
      {(d) => (
        <>
          <PageHead title={t("institution.title")} sub={d.tenant} />
          <Notice kind="info">{t("institution.note")}</Notice>
          <div className="grid grid-2" style={{ marginTop: 16, alignItems: "start" }}>
            <Card title={t("institution.handoffs")}>
              {d.handoffs.length === 0 ? <Empty title={t("institution.noHandoffs")} /> : (
                <ul className="list">{d.handoffs.map((g: any) => (
                  <li key={g.id}>
                    <div className="row-between"><b>{g.owner}</b><StatusBadge value={g.status} /></div>
                    <div className="small">{g.purpose}</div>
                    <div className="chip-row">{g.data_categories.map((c: string) => <span key={c} className="badge">{en(c)}</span>)}</div>
                    <div className="xs muted">
                      {g.requested_by && t("aconsent.requestedBy", { name: g.requested_by })} · {g.case_reference && <Link to={`/cases/${g.case_id}`}>{g.case_reference}</Link>} · {t("consent.validUntil", { date: fmtDate(g.valid_until) })}
                    </div>
                    {g.status === "pending" && <div className="xs" style={{ color: "var(--warning)" }}>{t("institution.awaitingCitizen")}</div>}
                  </li>
                ))}</ul>
              )}
            </Card>
            <MeetingsCard items={d.meetings} />
          </div>
          <div style={{ marginTop: 16 }}><Card title={t("nav.sharedCases")}><CaseRows items={d.cases} /></Card></div>
        </>
      )}
    </Q>
  );
}

export function ProfessionalOverview() {
  const { t, fmtDate } = useI18n();
  const en = useEnum();
  const q = useApi<any>(["overview", "professional"], "/api/overview/professional");
  return (
    <Q q={q}>
      {(d) => (
        <>
          <PageHead title={d.role === "interpreter" ? t("professional.interpreterTitle") : t("professional.title")} sub={d.tenant} />
          <Notice kind="info">{d.role === "interpreter" ? t("professional.interpreterNote") : t("professional.note")}</Notice>
          <div className="grid grid-2" style={{ marginTop: 16, alignItems: "start" }}>
            {d.role !== "interpreter" && <Card title={t("professional.delegations")}><DelegationList items={d.delegations} canRevoke={false} /></Card>}
            <MeetingsCard items={d.meetings} />
            {d.role !== "interpreter" && (
              <Card title={t("professional.translations")}>
                {d.translations.length === 0 ? <Empty title={t("professional.noTranslations")} /> : (
                  <ul className="list">{d.translations.map((x: any) => (
                    <li key={x.id} className="row-between">
                      <Link to={`/translations/${x.id}`}>{t(`lang.${x.source_lang}`)} →{t(`lang.${x.target_lang}`)}</Link>
                      <span className="xs muted">{en(x.mode)} · {fmtDate(x.created_at)}</span>
                    </li>
                  ))}</ul>
                )}
              </Card>
            )}
          </div>
          {d.role !== "interpreter" && <div style={{ marginTop: 16 }}><Card title={t("nav.delegatedCases")}><CaseRows items={d.cases} owner /></Card></div>}
        </>
      )}
    </Q>
  );
}
