import { useState } from "react";
import { Link } from "react-router";
import { Megaphone, ShieldCheck } from "lucide-react";
import { api } from "../../lib/api";
import { useAction } from "../../lib/hooks";
import { useEnum, useI18n } from "../../lib/i18n";
import { Button, Card, Empty, Field, Notice, PageHead, Q, StatusBadge, Tabs, useApi } from "../../components/ui";

export function Notices() {
  const { t, fmtDateTime } = useI18n();
  const en = useEnum();
  const a = useAction();
  const q = useApi<any>(["emergency-notices"], "/api/emergency/notices");
  const blank = { title: "", body: "", severity: "advisory", fallback_instructions: "", hours: 48 };
  const [f, setF] = useState(blank);
  const valid = f.title.trim().length >= 5 && f.body.trim().length >= 10;
  return (
    <>
      <PageHead title={t("notices.title")} sub={t("notices.sub")} />
      <Notice kind="warning">{t("notices.notAlerting")}</Notice>
      <div className="grid grid-2" style={{ marginTop: 16, alignItems: "start" }}>
        <Card title={t("notices.issue")}>
          <Field label={t("common.title")} hint={t("validation.min5")}>{(id, h) => <input id={id} aria-describedby={h} className="input" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />}</Field>
          <Field label={t("notices.body")} hint={t("validation.min10")}>{(id, h) => <textarea id={id} aria-describedby={h} className="textarea" value={f.body} onChange={(e) => setF({ ...f, body: e.target.value })} />}</Field>
          <Field label={t("notices.severity")}>
            {(id) => <select id={id} className="select" value={f.severity} onChange={(e) => setF({ ...f, severity: e.target.value })}>
              {["info", "advisory", "warning", "critical"].map((s) => <option key={s} value={s}>{en(s)}</option>)}
            </select>}
          </Field>
          <Field label={t("notices.fallback")} hint={t("notices.fallbackHint")}>{(id, h) => <textarea id={id} aria-describedby={h} className="textarea" value={f.fallback_instructions} onChange={(e) => setF({ ...f, fallback_instructions: e.target.value })} />}</Field>
          <Field label={t("notices.hours")}>{(id) => <input id={id} type="number" min={1} max={720} className="input" value={f.hours} onChange={(e) => setF({ ...f, hours: Number(e.target.value) })} />}</Field>
          <div className="form-actions">
            <Button variant="primary" mutates busy={a.busy} disabled={!valid} onClick={async () => {
              const r = await a.run(() => api.post("/api/emergency/notices", f), { success: t("notices.issued"), invalidate: [["emergency-notices"]] });
              if (r) setF(blank);
            }}><Megaphone size={15} aria-hidden /> {t("notices.issueBtn")}</Button>
          </div>
        </Card>
        <Card title={t("notices.active")}>
          <Q q={q}>
            {(d) => d.items.length === 0 ? <Empty title={t("notices.none")} /> : (
              <ul className="list">{d.items.map((n: any) => (
                <li key={n.id}>
                  <div className="row-between"><b>{n.title}</b><StatusBadge value={n.severity} label={en(n.severity)} /></div>
                  <p className="small" style={{ whiteSpace: "pre-wrap" }}>{n.body}</p>
                  <div className="xs muted">{n.source_label} · {fmtDateTime(n.issued_at)} → {fmtDateTime(n.expires_at)}</div>
                </li>
              ))}</ul>
            )}
          </Q>
        </Card>
      </div>
    </>
  );
}

export function AuthorityConsents() {
  const { t, fmtDate } = useI18n();
  const en = useEnum();
  const q = useApi<any>(["authority-consents"], "/api/consents");
  const [tab, setTab] = useState<"pending" | "active" | "other">("pending");
  return (
    <>
      <PageHead title={t("aconsent.title")} sub={t("aconsent.sub")} />
      <Card>
        <Q q={q}>
          {(d) => {
            const groups = {
              pending: d.items.filter((g: any) => g.status === "pending"),
              active: d.items.filter((g: any) => g.status === "active"),
              other: d.items.filter((g: any) => !["pending", "active"].includes(g.status)),
            };
            const items = groups[tab];
            return (
              <>
                <Tabs label={t("aconsent.title")} value={tab} onChange={setTab} tabs={[
                  { id: "pending", label: t("consent.tab.pending"), count: groups.pending.length },
                  { id: "active", label: t("consent.tab.active"), count: groups.active.length },
                  { id: "other", label: t("consent.tab.history"), count: groups.other.length },
                ]} />
                {items.length === 0 ? <Empty title={t("aconsent.none")} icon={<ShieldCheck size={32} />} /> : (
                  <div className="table-wrap"><table>
                    <thead><tr><th>{t("aconsent.citizen")}</th><th>{t("consent.case")}</th><th>{t("review.recipient")}</th><th>{t("consent.purpose")}</th><th>{t("consent.categories")}</th><th>{t("common.status")}</th><th>{t("consent.validUntilCol")}</th></tr></thead>
                    <tbody>{items.map((g: any) => (
                      <tr key={g.id}>
                        <td>{g.owner}</td>
                        <td>{g.case_reference ? <Link to={`/cases/${g.case_id}`}>{g.case_reference}</Link> : "—"}</td>
                        <td>{g.recipient.name}{g.handoff && <> <span className="badge b-accent">{t("review.handoff")}</span></>}<div className="xs muted">{g.requested_by && t("aconsent.requestedBy", { name: g.requested_by })}</div></td>
                        <td className="small">{g.purpose}</td>
                        <td><div className="chip-row">{g.data_categories.map((c: string) => <span key={c} className="badge">{en(c)}</span>)}</div></td>
                        <td><StatusBadge value={g.status} /></td>
                        <td>{fmtDate(g.valid_until)}</td>
                      </tr>
                    ))}</tbody>
                  </table></div>
                )}
              </>
            );
          }}
        </Q>
        <p className="xs muted" style={{ marginTop: 8 }}>{t("aconsent.note")}</p>
      </Card>
    </>
  );
}
