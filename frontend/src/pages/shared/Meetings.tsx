import { useState } from "react";
import { Link } from "react-router";
import { Video } from "lucide-react";
import { api } from "../../lib/api";
import { useAction } from "../../lib/hooks";
import { useI18n } from "../../lib/i18n";
import { Button, Card, Empty, Field, Modal, Notice, PageHead, Q, StatusBadge, useApi } from "../../components/ui";

function localDefault() {
  const d = new Date(Date.now() + 24 * 3600 * 1000);
  d.setMinutes(0, 0, 0);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:00`;
}

export function ScheduleMeetingModal({ caseId, onClose }: { caseId: string; onClose: () => void }) {
  const { t, timeZone } = useI18n();
  const a = useAction();
  const cands = useApi<any>(["meeting-candidates", caseId], `/api/meetings/candidates?case_id=${caseId}`);
  const [f, setF] = useState({ title: "", starts_at_local: localDefault(), timezone: timeZone, duration_minutes: 30 });
  const [inv, setInv] = useState<Record<string, string>>({});
  const toggle = (c: any) => setInv((x) => {
    const n = { ...x };
    if (n[c.user_id]) delete n[c.user_id];
    else n[c.user_id] = c.role;
    return n;
  });
  return (
    <Modal title={t("meetings.schedule")} onClose={onClose} wide>
      <Field label={t("common.title")} hint={t("validation.min3")}>{(id, h) => <input id={id} aria-describedby={h} className="input" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />}</Field>
      <div className="grid grid-3">
        <Field label={t("meetings.start")}>{(id) => <input id={id} type="datetime-local" className="input" value={f.starts_at_local} onChange={(e) => setF({ ...f, starts_at_local: e.target.value })} />}</Field>
        <Field label={t("account.timezone")} hint={t("meetings.tzHint")}>{(id, h) => <input id={id} aria-describedby={h} className="input" value={f.timezone} onChange={(e) => setF({ ...f, timezone: e.target.value })} />}</Field>
        <Field label={t("meetings.duration")}>
          {(id) => <select id={id} className="select" value={f.duration_minutes} onChange={(e) => setF({ ...f, duration_minutes: Number(e.target.value) })}>{[15, 30, 45, 60, 90].map((m) => <option key={m} value={m}>{t("meetings.minutes", { n: m })}</option>)}</select>}
        </Field>
      </div>
      <fieldset><legend>{t("meetings.invitees")}</legend>
        <Q q={cands}>
          {(d) => d.items.length === 0 ? <p className="small muted">{t("meetings.noCandidates")}</p> : (
            <div className="grid grid-2" style={{ gap: 0 }}>{d.items.map((c: any) => (
              <label key={c.user_id + c.role} className="check"><input type="checkbox" checked={!!inv[c.user_id]} onChange={() => toggle(c)} />
                <span>{c.display_name} <span className="xs muted">· {t(`meetings.role.${c.role}`)} · {c.tenant}</span></span></label>
            ))}</div>
          )}
        </Q>
      </fieldset>
      <Notice kind="info">{t("meetings.eligibility")}</Notice>
      <Notice kind="info">{t("meetings.noRecording")}</Notice>
      <div className="form-actions">
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" mutates busy={a.busy} disabled={f.title.trim().length < 3 || !f.starts_at_local} onClick={async () => {
          const r = await a.run(() => api.post("/api/meetings", { case_id: caseId, ...f, invitees: Object.entries(inv).map(([user_id, role]) => ({ user_id, role })) }),
            { success: t("meetings.scheduled"), invalidate: [["meetings"], ["case", caseId]] });
          if (r) onClose();
        }}>{t("meetings.scheduleBtn")}</Button>
      </div>
    </Modal>
  );
}

export function Meetings() {
  const { t, fmtDateTime, timeZone } = useI18n();
  const q = useApi<any>(["meetings"], "/api/meetings");
  return (
    <>
      <PageHead title={t("meetings.title")} sub={t("meetings.sub")} />
      <Notice kind="info">{t("meetings.scheduleFromCase")}</Notice>
      <div style={{ marginTop: 16 }} />
      <Card>
        <Q q={q}>
          {(d) => d.items.length === 0 ? <Empty title={t("meetings.none")} icon={<Video size={32} />} /> : (
            <div className="table-wrap"><table>
              <thead><tr><th>{t("common.title")}</th><th>{t("meetings.when")}</th><th>{t("meetings.yourRole")}</th><th>{t("common.status")}</th><th /></tr></thead>
              <tbody>{d.items.map((m: any) => (
                <tr key={m.id}>
                  <td><Link to={`/meetings/${m.id}`}>{m.title}</Link>{m.host && <span className="badge" style={{ marginInlineStart: 6 }}>{t("meetings.host")}</span>}</td>
                  <td className="small">
                    {fmtDateTime(m.scheduled_start)} <span className="xs muted">({timeZone})</span>
                    {m.timezone !== timeZone && <div className="xs muted">{fmtDateTime(m.scheduled_start, m.timezone)} ({m.timezone})</div>}
                  </td>
                  <td>{t(`meetings.role.${m.my_role}`)} · <StatusBadge value={m.my_status} /></td>
                  <td><StatusBadge value={m.status} /></td>
                  <td>{m.status !== "ended" && <Link className="btn btn-sm" to={`/meetings/${m.id}`}>{t("meetings.enter")}</Link>}</td>
                </tr>
              ))}</tbody>
            </table></div>
          )}
        </Q>
      </Card>
    </>
  );
}
