import { Link } from "react-router";
import { BarChart3 } from "lucide-react";
import { useI18n, useEnum } from "../../lib/i18n";
import { useAuth } from "../../lib/auth";
import { Card, Notice, Q, SyntheticBadge, useApi } from "../../components/ui";

type Cell = { value: number | null; suppressed: boolean };

export function Cellv({ c, suffix = "", k }: { c?: Cell; suffix?: string; k: number }) {
  const { t } = useI18n();
  if (!c) return <>—</>;
  if (c.suppressed) return <span className="muted" title={t("transparency.suppressedTip", { k })}>{t("transparency.suppressed", { k })}</span>;
  return <>{c.value}{suffix}</>;
}

export function TrendChart({ weeks, k }: { weeks: { week_start: string; new_incidents: Cell }[]; k: number }) {
  const { t, fmtDate } = useI18n();
  const max = Math.max(k, ...weeks.map((w) => w.new_incidents.value || 0));
  return (
    <figure style={{ margin: 0 }}>
      <div className="bar-chart" role="img" aria-label={t("transparency.trendAria")}>
        {weeks.map((w) => (
          <div key={w.week_start} className={`bar ${w.new_incidents.suppressed ? "sup" : ""}`}
            style={{ height: `${w.new_incidents.suppressed ? 12 : Math.max(2, (100 * (w.new_incidents.value || 0)) / max)}%` }}
            title={`${fmtDate(w.week_start)}: ${w.new_incidents.suppressed ? t("transparency.suppressed", { k }) : w.new_incidents.value}`} />
        ))}
      </div>
      <div className="bar-labels" aria-hidden>
        {weeks.map((w) => <span key={w.week_start}>{fmtDate(w.week_start, { month: "short", day: "numeric", dateStyle: undefined })}</span>)}
      </div>
      <figcaption className="xs muted">{t("transparency.trendCaption")}</figcaption>
    </figure>
  );
}

export function TransparencyBody({ data }: { data: any }) {
  const { t, fmtDateTime } = useI18n();
  const en = useEnum();
  const k = data.k_threshold;
  return (
    <>
      <div className="row" style={{ marginBottom: 16 }}>
        <SyntheticBadge />
        <span className={`badge ${data.fresh === false ? "b-warning" : "b-success"}`}>{t("transparency.computed", { at: fmtDateTime(data.computed_at) })}</span>
        <span className="badge b-info">{t("transparency.kRule", { k })}</span>
      </div>
      <Notice kind="info">{data.notice}</Notice>
      {data.authorities.map((a: any) => (
        <Card key={a.tenant.id} title={a.tenant.name}>
          <div className="grid grid-4" style={{ marginBottom: 16 }}>
            <div className="stat"><div className="v"><Cellv c={a.requests.open_backlog} k={k} /></div><div className="l">{t("transparency.openRequests")}</div></div>
            <div className="stat"><div className="v"><Cellv c={a.requests.sla_adherence_pct} k={k} suffix="%" /></div><div className="l">{t("transparency.requestSla")}</div></div>
            <div className="stat"><div className="v"><Cellv c={a.incidents.open_backlog} k={k} /></div><div className="l">{t("transparency.openIncidents")}</div></div>
            <div className="stat"><div className="v"><Cellv c={a.incidents.median_resolution_days} k={k} /></div><div className="l">{t("transparency.medianDays")}</div></div>
            <div className="stat"><div className="v"><Cellv c={a.incidents.sla_adherence_pct} k={k} suffix="%" /></div><div className="l">{t("transparency.incidentSla")}</div></div>
            <div className="stat"><div className="v"><Cellv c={a.incidents.satisfaction_avg} k={k} /></div><div className="l">{t("transparency.satisfaction")}</div></div>
          </div>
          <div className="grid grid-2">
            <div>
              <h3>{t("transparency.trend")}</h3>
              <TrendChart weeks={a.incidents.weekly_trend} k={k} />
            </div>
            <div>
              <h3>{t("transparency.byCategory")}</h3>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>{t("common.category")}</th><th className="right">{t("transparency.reports")}</th></tr></thead>
                  <tbody>
                    {Object.entries(a.incidents.by_category).map(([cat, c]) => (
                      <tr key={cat}><td>{en(cat)}</td><td className="right"><Cellv c={c as Cell} k={k} /></td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <h3 style={{ marginTop: 16 }}>{t("transparency.quality")}</h3>
              <p className="small">
                {t("transparency.withLocation")}: <Cellv c={a.data_quality.incidents_with_location_pct} k={k} suffix="%" /> ·{" "}
                {t("transparency.suggested")}: <Cellv c={a.data_quality.incidents_category_suggested_pct} k={k} suffix="%" />
              </p>
            </div>
          </div>
        </Card>
      ))}
      <Card title={t("transparency.provenance")}>
        <p className="small">
          {t("transparency.provenanceBody", { sources: data.provenance.sources_total, placeholder: data.provenance.sources_placeholder, stale: data.provenance.sources_past_review, rules: data.provenance.rule_versions_past_review })}
        </p>
      </Card>
    </>
  );
}

export function Transparency() {
  const { t } = useI18n();
  const { me } = useAuth();
  const q = useApi(["public-transparency"], "/api/public/transparency");
  const n = useApi<{ items: any[]; disclaimer: string }>(["public-notices"], "/api/public/emergency-notices");
  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <div className="env-banner">{t("env.banner")}</div>
      <header className="header">
        <Link to={me ? "/" : "/login"} className="brand"><BarChart3 size={22} aria-hidden /> CivicBridge · {t("nav.transparency")}</Link>
        <span className="spacer" />
        <Link className="btn btn-sm" to={me ? "/" : "/login"}>{me ? t("common.backToApp") : t("login.submit")}</Link>
      </header>
      <main id="main" className="main" style={{ margin: "0 auto" }}>
        <h1>{t("transparency.title")}</h1>
        <p className="muted">{t("transparency.sub")}</p>
        {n.data?.items?.length ? (
          <Card title={t("emergency.notices")}>
            {n.data.items.map((x) => (
              <Notice key={x.id} kind={x.severity === "critical" || x.severity === "warning" ? "warning" : "info"} title={x.title}>
                {x.body} <span className="xs muted">— {x.source_label}</span>
              </Notice>
            ))}
            <p className="small muted">{n.data.disclaimer}</p>
          </Card>
        ) : null}
        <Q q={q}>{(d) => <TransparencyBody data={d} />}</Q>
      </main>
    </div>
  );
}
