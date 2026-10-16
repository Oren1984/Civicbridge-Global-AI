import { useState } from "react";
import { Lock } from "lucide-react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useAction } from "../../lib/hooks";
import { useEnum, useI18n } from "../../lib/i18n";
import { Button, Card, Empty, Field, Modal, Notice, PageHead, Q, StatusBadge, useApi } from "../../components/ui";

function useIsAdmin() {
  const { me } = useAuth();
  return me?.active?.role === "governance_admin";
}

function AdminNote() {
  const { t } = useI18n();
  return useIsAdmin() ? null : <Notice kind="info">{t("gov.adminOnly")}</Notice>;
}

/* ------------------------------------------------------------------ policies */

function PolicyRow({ p, admin }: { p: any; admin: boolean }) {
  const { t, fmtDateTime } = useI18n();
  const en = useEnum();
  const a = useAction();
  const [v, setV] = useState(String(p.value));
  const isMode = p.key === "ai_mode";
  const changed = v !== String(p.value);
  return (
    <tr>
      <td><span className="mono small">{p.key}</span>{p.locked && <> <span className="badge" title={t("policies.lockedTip")}><Lock size={11} aria-hidden /> {t("policies.locked")}</span></>}</td>
      <td className="small">{p.description}</td>
      <td>
        {p.locked || !admin ? <span className="mono">{isMode ? en(String(p.value)) : String(p.value)}</span> : (
          <div className="row">
            <label className="sr-only" htmlFor={`p-${p.key}`}>{p.key}</label>
            {isMode
              ? <select id={`p-${p.key}`} className="select" style={{ width: "auto" }} value={v} onChange={(e) => setV(e.target.value)}>{["rules", "mock", "ollama"].map((m) => <option key={m} value={m}>{en(m)}</option>)}</select>
              : <input id={`p-${p.key}`} className="input" type="number" style={{ width: 110 }} value={v} onChange={(e) => setV(e.target.value)} />}
            <Button size="sm" mutates busy={a.busy} disabled={!changed} onClick={() => a.run(() => api.put(`/api/governance/policies/${p.key}`, { value: isMode ? v : Number(v) }), { success: t("policies.saved"), invalidate: [["gov", "policies"]] })}>{t("common.save")}</Button>
          </div>
        )}
      </td>
      <td className="xs muted">{p.updated_at ? fmtDateTime(p.updated_at) : t("policies.default")}</td>
    </tr>
  );
}

export function Policies() {
  const { t } = useI18n();
  const admin = useIsAdmin();
  const q = useApi<any>(["gov", "policies"], "/api/governance/policies");
  return (
    <>
      <PageHead title={t("policies.title")} sub={t("policies.sub")} />
      <AdminNote />
      <Card>
        <Q q={q}>
          {(d) => (
            <div className="table-wrap"><table>
              <thead><tr><th>{t("policies.key")}</th><th>{t("policies.description")}</th><th>{t("policies.value")}</th><th>{t("common.updated")}</th></tr></thead>
              <tbody>{d.items.map((p: any) => <PolicyRow key={p.key} p={p} admin={admin} />)}</tbody>
            </table></div>
          )}
        </Q>
      </Card>
    </>
  );
}

/* ------------------------------------------------------------------ risks */

const RISK_BLANK = { title: "", description: "", category: "operational", likelihood: 3, impact: 3, owner: "", status: "open", mitigation: "" };

function RiskModal({ risk, onClose }: { risk?: any; onClose: () => void }) {
  const { t } = useI18n();
  const en = useEnum();
  const a = useAction();
  const [f, setF] = useState<any>(risk ? Object.fromEntries(Object.keys(RISK_BLANK).map((k) => [k, risk[k] ?? (RISK_BLANK as any)[k]])) : RISK_BLANK);
  const num = (k: string) => (
    <Field label={t(`risks.${k}`)}>{(id) => <select id={id} className="select" value={f[k]} onChange={(e) => setF({ ...f, [k]: Number(e.target.value) })}>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}</select>}</Field>
  );
  return (
    <Modal title={risk ? t("risks.edit") : t("risks.new")} onClose={onClose} wide>
      <Field label={t("common.title")}>{(id) => <input id={id} className="input" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />}</Field>
      <Field label={t("policies.description")}>{(id) => <textarea id={id} className="textarea" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />}</Field>
      <div className="grid grid-3">
        <Field label={t("common.category")}>{(id) => <select id={id} className="select" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>{["operational", "security", "privacy", "legal", "ai", "vendor"].map((c) => <option key={c} value={c}>{en(c)}</option>)}</select>}</Field>
        {num("likelihood")}
        {num("impact")}
      </div>
      <div className="grid grid-2">
        <Field label={t("risks.owner")}>{(id) => <input id={id} className="input" value={f.owner} onChange={(e) => setF({ ...f, owner: e.target.value })} />}</Field>
        <Field label={t("common.status")}>{(id) => <select id={id} className="select" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>{["open", "mitigating", "accepted", "closed"].map((s) => <option key={s} value={s}>{en(s)}</option>)}</select>}</Field>
      </div>
      <Field label={t("risks.mitigation")}>{(id) => <textarea id={id} className="textarea" value={f.mitigation} onChange={(e) => setF({ ...f, mitigation: e.target.value })} />}</Field>
      <div className="form-actions">
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" mutates busy={a.busy} disabled={f.title.trim().length < 3} onClick={async () => {
          const r = await a.run(() => (risk ? api.put(`/api/governance/risks/${risk.id}`, f) : api.post("/api/governance/risks", f)), { success: t("risks.saved"), invalidate: [["gov", "risks"]] });
          if (r) onClose();
        }}>{t("common.save")}</Button>
      </div>
    </Modal>
  );
}

export function Risks() {
  const { t } = useI18n();
  const en = useEnum();
  const admin = useIsAdmin();
  const q = useApi<any>(["gov", "risks"], "/api/governance/risks");
  const [edit, setEdit] = useState<any>(null);
  return (
    <>
      <PageHead title={t("risks.title")} sub={t("risks.sub")} actions={admin && <Button variant="primary" mutates onClick={() => setEdit({})}>{t("risks.new")}</Button>} />
      <AdminNote />
      <Card>
        <Q q={q}>
          {(d) => d.items.length === 0 ? <Empty title={t("risks.none")} /> : (
            <div className="table-wrap"><table>
              <thead><tr><th>{t("risks.score")}</th><th>{t("common.title")}</th><th>{t("common.category")}</th><th>{t("risks.lxi")}</th><th>{t("risks.owner")}</th><th>{t("common.status")}</th><th /></tr></thead>
              <tbody>{d.items.map((r: any) => (
                <tr key={r.id}>
                  <td><span className={`badge ${r.score >= 15 ? "b-danger" : r.score >= 8 ? "b-warning" : "b-success"}`}>{r.score}</span></td>
                  <td><b>{r.title}</b>{r.mitigation && <div className="xs muted">{r.mitigation}</div>}</td>
                  <td>{en(r.category)}</td>
                  <td>{r.likelihood} × {r.impact}</td>
                  <td className="small">{r.owner || "—"}</td>
                  <td><StatusBadge value={r.status} /></td>
                  <td>{admin && <Button size="sm" mutates onClick={() => setEdit(r)}>{t("common.edit")}</Button>}</td>
                </tr>
              ))}</tbody>
            </table></div>
          )}
        </Q>
      </Card>
      {edit && <RiskModal risk={edit.id ? edit : undefined} onClose={() => setEdit(null)} />}
    </>
  );
}

/* ------------------------------------------------------------------ security / privacy incidents */

const SI_FLOW: Record<string, string[]> = { open: ["triaged"], triaged: ["contained"], contained: ["notified", "closed"], notified: ["closed"] };

function NewSI({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const en = useEnum();
  const a = useAction();
  const [f, setF] = useState({ title: "", kind: "security", severity: "medium", description: "", personal_data_involved: false });
  return (
    <Modal title={t("si.new")} onClose={onClose} wide>
      <Field label={t("common.title")}>{(id) => <input id={id} className="input" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />}</Field>
      <div className="grid grid-2">
        <Field label={t("common.type")}>{(id) => <select id={id} className="select" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{["security", "privacy_breach", "availability", "integrity"].map((k) => <option key={k} value={k}>{en(k)}</option>)}</select>}</Field>
        <Field label={t("si.severity")}>{(id) => <select id={id} className="select" value={f.severity} onChange={(e) => setF({ ...f, severity: e.target.value })}>{["low", "medium", "high", "critical"].map((k) => <option key={k} value={k}>{en(k)}</option>)}</select>}</Field>
      </div>
      <Field label={t("policies.description")}>{(id) => <textarea id={id} className="textarea" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />}</Field>
      <label className="check"><input type="checkbox" checked={f.personal_data_involved} onChange={(e) => setF({ ...f, personal_data_involved: e.target.checked })} /> {t("si.personalData")}</label>
      {f.personal_data_involved && <Notice kind="warning">{t("si.clockNote")}</Notice>}
      <div className="form-actions">
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" mutates busy={a.busy} disabled={f.title.trim().length < 3} onClick={async () => {
          const r = await a.run(() => api.post("/api/governance/security-incidents", f), { success: t("si.opened"), invalidate: [["gov", "si"]] });
          if (r) onClose();
        }}>{t("si.record")}</Button>
      </div>
    </Modal>
  );
}

function AdvanceSI({ si, to, onClose }: { si: any; to: string; onClose: () => void }) {
  const { t } = useI18n();
  const en = useEnum();
  const a = useAction();
  const [note, setNote] = useState("");
  return (
    <Modal title={t("si.advanceTo", { status: en(to) })} onClose={onClose}>
      <Field label={t("si.note")} hint={t("si.noteHint")}>{(id, h) => <textarea id={id} aria-describedby={h} className="textarea" value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
      <div className="form-actions">
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" mutates busy={a.busy} disabled={note.trim().length < 3} onClick={async () => {
          const r = await a.run(() => api.post(`/api/governance/security-incidents/${si.id}/advance`, { status: to, note }), { success: t("si.advanced"), invalidate: [["gov", "si"]] });
          if (r) onClose();
        }}>{t("si.advance")}</Button>
      </div>
    </Modal>
  );
}

export function SecurityIncidents() {
  const { t, fmtDateTime } = useI18n();
  const en = useEnum();
  const admin = useIsAdmin();
  const q = useApi<any>(["gov", "si"], "/api/governance/security-incidents");
  const [creating, setCreating] = useState(false);
  const [adv, setAdv] = useState<{ si: any; to: string } | null>(null);
  return (
    <>
      <PageHead title={t("si.title")} sub={t("si.sub")} actions={admin && <Button variant="primary" mutates onClick={() => setCreating(true)}>{t("si.new")}</Button>} />
      <AdminNote />
      <Q q={q}>
        {(d) => d.items.length === 0 ? <Card><Empty title={t("si.none")} /></Card> : (
          <div className="stack">{d.items.map((s: any) => {
            const overdue = s.notification_due_at && s.status !== "closed" && s.status !== "notified" && new Date(s.notification_due_at) < new Date();
            return (
              <Card key={s.id} title={<h2 style={{ margin: 0 }}>{s.title}</h2>} actions={<><StatusBadge value={s.severity} label={en(s.severity)} /><StatusBadge value={s.status} /></>}>
                <div className="small">{en(s.kind)} · {t("si.detected", { date: fmtDateTime(s.detected_at) })}</div>
                {s.description && <p className="small">{s.description}</p>}
                {s.personal_data_involved && (
                  <Notice kind={overdue ? "danger" : "warning"} title={t("si.personalData")}>
                    {t("si.notifyBy", { date: fmtDateTime(s.notification_due_at) })}{overdue && ` — ${t("si.overdue")}`}
                  </Notice>
                )}
                <ol className="timeline" style={{ marginTop: 8 }}>{(s.timeline || []).map((e: any, i: number) => (
                  <li key={i}><div className="when">{fmtDateTime(e.at)} <StatusBadge value={e.status} /></div><div className="small">{e.note}</div></li>
                ))}</ol>
                {admin && (SI_FLOW[s.status] || []).length > 0 && (
                  <div className="row">{SI_FLOW[s.status].map((to) => (
                    <Button key={to} size="sm" mutates disabled={to === "closed" && s.personal_data_involved && s.status !== "notified"} title={to === "closed" && s.personal_data_involved && s.status !== "notified" ? t("si.needNotify") : undefined}
                      onClick={() => setAdv({ si: s, to })}>{t("si.moveTo", { status: en(to) })}</Button>
                  ))}</div>
                )}
              </Card>
            );
          })}</div>
        )}
      </Q>
      {creating && <NewSI onClose={() => setCreating(false)} />}
      {adv && <AdvanceSI si={adv.si} to={adv.to} onClose={() => setAdv(null)} />}
    </>
  );
}
