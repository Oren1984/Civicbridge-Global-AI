import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { Baby, Briefcase, Building, GraduationCap, Palmtree, Plane } from "lucide-react";
import { api } from "../../lib/api";
import { useAction } from "../../lib/hooks";
import { useEnum, useI18n } from "../../lib/i18n";
import { Button, Card, Empty, Field, Modal, Notice, PageHead, Q, StatusBadge, SyntheticBadge, useApi } from "../../components/ui";

const ICON: Record<string, any> = { relocation: Plane, employment: Briefcase, study: GraduationCap, family: Baby, retirement: Palmtree, business: Building };

export function QuestionInput({ q, value, onChange }: { q: any; value: any; onChange: (v: any) => void }) {
  const { t, locale } = useI18n();
  const label = q.label?.[locale] || q.label?.en || q.id;
  if (q.type === "boolean")
    return (
      <fieldset>
        <legend>{label}</legend>
        <div className="row">
          {[true, false].map((v) => (
            <label key={String(v)} className="check">
              <input type="radio" name={q.id} checked={value === v} onChange={() => onChange(v)} /> {v ? t("common.yes") : t("common.no")}
            </label>
          ))}
        </div>
      </fieldset>
    );
  return (
    <Field label={label}>
      {(id) => <input id={id} className="input" type="number" inputMode="decimal" value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))} />}
    </Field>
  );
}

function StartModal({ tpl, onClose }: { tpl: any; onClose: () => void }) {
  const { t } = useI18n();
  const nav = useNavigate();
  const a = useAction();
  const [answers, setAnswers] = useState<Record<string, any>>({});
  const [date, setDate] = useState(() => new Date(Date.now() + 45 * 86400000).toISOString().slice(0, 10));
  const start = async () => {
    const r = await a.run(() => api.post("/api/life-events", { template_code: tpl.code, target_date: `${date}T12:00:00Z`, answers }), {
      success: t("journeys.started"), invalidate: [["cases"], ["overview"]],
    });
    if (r) nav(`/cases/${r.case_id}`);
  };
  return (
    <Modal title={tpl.name} onClose={onClose}>
      <p className="muted">{tpl.summary}</p>
      <div className="chip-row" style={{ marginBottom: 12 }}>
        {tpl.jurisdictions.map((j: string) => <span key={j} className="badge b-primary">{j}</span>)}
        {Object.entries(tpl.pack_versions).map(([k, v]) => <span key={k} className="badge">{k} pack v{String(v)}</span>)}
        <SyntheticBadge />
      </div>
      <Field label={t("journeys.targetDate")} hint={t("journeys.targetHint")}>
        {(id, d) => <input id={id} aria-describedby={d} className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} />}
      </Field>
      {tpl.questions.map((q: any) => <QuestionInput key={q.id} q={q} value={answers[q.id]} onChange={(v) => setAnswers({ ...answers, [q.id]: v })} />)}
      <Notice kind="synthetic">{t("journeys.disclaimer")}</Notice>
      <div className="form-actions">
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" mutates busy={a.busy} onClick={start} disabled={!date}>{t("journeys.create", { n: tpl.task_count })}</Button>
      </div>
    </Modal>
  );
}

export function Journeys() {
  const { t, fmtDate } = useI18n();
  const en = useEnum();
  const tpls = useApi<any>(["templates"], "/api/life-events/templates");
  const mine = useApi<any>(["cases", "life-events"], "/api/life-events");
  const [sel, setSel] = useState<any>(null);
  return (
    <>
      <PageHead title={t("journeys.title")} sub={t("journeys.sub")} />
      <Card title={t("journeys.mine")}>
        <Q q={mine}>
          {(d) => d.items.length === 0 ? <Empty title={t("journeys.none")} /> : (
            <div className="table-wrap"><table>
              <thead><tr><th>{t("common.type")}</th><th>{t("journeys.template")}</th><th>{t("journeys.targetDate")}</th><th>{t("common.status")}</th></tr></thead>
              <tbody>{d.items.map((e: any) => (
                <tr key={e.id}><td>{en(e.event_type)}</td><td><Link to={`/cases/${e.case_id}`}>{e.template_code}</Link></td><td>{fmtDate(e.target_date)}</td><td><StatusBadge value={e.status} /></td></tr>
              ))}</tbody>
            </table></div>
          )}
        </Q>
      </Card>
      <h2>{t("journeys.available")}</h2>
      <Q q={tpls}>
        {(d) => (
          <div className="grid grid-3">
            {d.items.map((tpl: any) => {
              const Icon = ICON[tpl.life_event_type] || Plane;
              return (
                <Card key={tpl.code} tight>
                  <div className="row" style={{ marginBottom: 8 }}><Icon size={22} aria-hidden /><span className="badge b-accent">{en(tpl.life_event_type)}</span></div>
                  <h3>{tpl.name}</h3>
                  <p className="small muted">{tpl.summary}</p>
                  <div className="chip-row" style={{ marginBottom: 12 }}>{tpl.jurisdictions.map((j: string) => <span key={j} className="badge">{j}</span>)}</div>
                  <Button variant="primary" size="sm" mutates onClick={() => setSel(tpl)}>{t("journeys.start")}</Button>
                </Card>
              );
            })}
          </div>
        )}
      </Q>
      {sel && <StartModal tpl={sel} onClose={() => setSel(null)} />}
    </>
  );
}
