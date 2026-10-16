import { useState } from "react";
import { CloudUpload, LifeBuoy, WifiOff } from "lucide-react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useAction } from "../../lib/hooks";
import { outbox, useOnline, useOutbox, type Conflict } from "../../lib/offline";
import { usePrefs } from "../../lib/prefs";
import { useEnum, useI18n } from "../../lib/i18n";
import { Button, Card, Empty, Modal, Notice, PageHead, Q, StatusBadge, useApi } from "../../components/ui";
import { ReportForm } from "./Incidents";

function Payload({ p }: { p: Record<string, unknown> }) {
  const text = (p.description || p.body || p.text) as string | undefined;
  return <div className="seg small">{text || JSON.stringify(p, null, 1)}</div>;
}

function ConflictDialog({ c, onClose }: { c: Conflict; onClose: () => void }) {
  const { t, fmtDateTime } = useI18n();
  const { me } = useAuth();
  const a = useAction();
  const uid = me!.user.id;
  return (
    <Modal title={t("continuity.conflictTitle")} onClose={onClose} wide>
      <p className="small">{t("continuity.conflictBody")}</p>
      <div className="split">
        <div><h3>{t("continuity.mine")}</h3><div className="xs muted">{fmtDateTime(c.op.created_at)}</div><Payload p={c.op.payload} /></div>
        <div><h3>{t("continuity.server")}</h3><div className="xs muted">v{c.server.version} · {fmtDateTime(c.server.updated_at)}</div><Payload p={c.server.payload} /></div>
      </div>
      <div className="form-actions">
        <Button onClick={() => { outbox.dropConflict(uid, c.op.draft_key); onClose(); }}>{t("continuity.keepServer")}</Button>
        <Button variant="primary" mutates busy={a.busy} onClick={async () => {
          const r = await a.run(() => api.put(`/api/drafts/${encodeURIComponent(c.op.draft_key)}`, { kind: c.op.kind || "incident_report", title: c.op.title || "", payload: c.op.payload, base_version: c.server.version }),
            { success: t("continuity.keptMine"), invalidate: [["drafts"]] });
          if (r) {
            outbox.dropConflict(uid, c.op.draft_key);
            onClose();
          }
        }}>{t("continuity.keepMine")}</Button>
      </div>
    </Modal>
  );
}

export function Continuity() {
  const { t, fmtDateTime } = useI18n();
  const en = useEnum();
  const { me, readOnly } = useAuth();
  const { toast } = usePrefs();
  const online = useOnline();
  const uid = me?.user.id;
  const { pending, conflicts, failed } = useOutbox(uid);
  const notices = useApi<any>(["emergency-notices"], "/api/emergency/notices");
  const drafts = useApi<any>(["drafts"], "/api/drafts");
  const a = useAction();
  const [conflict, setConflict] = useState<Conflict | null>(null);
  const [resume, setResume] = useState<any>(null);
  const sync = () => a.run(async () => {
    const r = await outbox.flush(uid!);
    toast(t("continuity.syncResult", { applied: r.applied, conflicts: r.conflicts, rejected: r.rejected }), r.conflicts || r.rejected ? "info" : "success");
    return r;
  }, { invalidate: [["drafts"], ["incidents"]] });
  return (
    <>
      <PageHead title={t("continuity.title")} sub={t("continuity.sub")} />
      {!online && <Notice kind="warning" title={t("offline.offline")}><WifiOff size={14} aria-hidden /> {t("continuity.offlineNote")}</Notice>}
      <div className="grid grid-2" style={{ marginTop: 16, alignItems: "start" }}>
        <div className="stack">
          <Card title={t("continuity.notices")}>
            <Q q={notices}>
              {(d) => (
                <>
                  <Notice kind="danger">{d.disclaimer}</Notice>
                  {d.items.length === 0 ? <Empty title={t("notices.none")} /> : (
                    <ul className="list">{d.items.map((n: any) => (
                      <li key={n.id}>
                        <div className="row-between"><b>{n.title}</b><StatusBadge value={n.severity} label={en(n.severity)} /></div>
                        <p className="small" style={{ whiteSpace: "pre-wrap" }}>{n.body}</p>
                        {n.fallback_instructions && <Notice kind="info" title={t("continuity.fallback")}>{n.fallback_instructions}</Notice>}
                        <div className="xs muted">{n.source_label} · {n.jurisdiction_name} · {fmtDateTime(n.issued_at)}</div>
                      </li>
                    ))}</ul>
                  )}
                </>
              )}
            </Q>
          </Card>
          <Card title={<h2 style={{ margin: 0 }}><LifeBuoy size={18} aria-hidden /> {t("continuity.howTitle")}</h2>}>
            <ul className="small">
              <li>{t("continuity.how1")}</li>
              <li>{t("continuity.how2")}</li>
              <li>{t("continuity.how3")}</li>
              <li>{t("continuity.how4")}</li>
            </ul>
          </Card>
        </div>
        <div className="stack">
          <Card title={t("continuity.outbox")} actions={<Button size="sm" variant="primary" disabled={!online || !pending.length || readOnly} busy={a.busy} onClick={sync}><CloudUpload size={14} aria-hidden /> {t("continuity.syncNow")}</Button>}>
            <Notice kind="warning">{t("continuity.storageNote")}</Notice>
            {pending.length === 0 ? <Empty title={t("continuity.outboxEmpty")} /> : (
              <ul className="list">{pending.map((o) => (
                <li key={o.idempotency_key}>
                  <div className="row-between"><b>{t(`continuity.op.${o.op}`)}</b><span className="xs muted">{fmtDateTime(o.created_at)}</span></div>
                  <Payload p={o.payload} />
                </li>
              ))}</ul>
            )}
          </Card>
          {conflicts.length > 0 && (
            <Card title={t("continuity.conflicts")}>
              <ul className="list">{conflicts.map((c) => (
                <li key={c.op.draft_key} className="row-between">
                  <span>{c.op.title || c.op.draft_key}</span>
                  <Button size="sm" variant="primary" onClick={() => setConflict(c)}>{t("continuity.resolve")}</Button>
                </li>
              ))}</ul>
            </Card>
          )}
          {failed.length > 0 && (
            <Card title={t("continuity.failed")}>
              <ul className="list">{failed.map((f) => (
                <li key={f.op.idempotency_key}>
                  <div className="row-between"><b>{t(`continuity.op.${f.op.op}`)}</b><Button size="sm" onClick={() => outbox.dropFailed(uid!, f.op.idempotency_key)}>{t("continuity.dismiss")}</Button></div>
                  <div className="small" style={{ color: "var(--danger)" }}>{f.message}</div>
                  <Payload p={f.op.payload} />
                </li>
              ))}</ul>
            </Card>
          )}
          <Card title={t("continuity.serverDrafts")}>
            <Q q={drafts}>
              {(d) => d.items.length === 0 ? <Empty title={t("continuity.noDrafts")} /> : (
                <ul className="list">{d.items.map((x: any) => (
                  <li key={x.id}>
                    <div className="row-between">
                      <span><b>{x.title || en(x.kind)}</b> <span className="xs muted">· {en(x.kind)} · v{x.version} · {fmtDateTime(x.updated_at)}</span></span>
                      <span className="row">
                        {x.kind === "incident_report" && <Button size="sm" mutates onClick={() => setResume(x)}>{t("continuity.resume")}</Button>}
                        <Button size="sm" variant="danger" mutates busy={a.busy} onClick={() => a.run(() => api.del(`/api/drafts/${encodeURIComponent(x.draft_key)}`), { success: t("continuity.draftDeleted"), invalidate: [["drafts"]] })}>{t("common.delete")}</Button>
                      </span>
                    </div>
                  </li>
                ))}</ul>
              )}
            </Q>
          </Card>
        </div>
      </div>
      {conflict && <ConflictDialog c={conflict} onClose={() => setConflict(null)} />}
      {resume && <ReportForm draft={resume} onClose={() => setResume(null)} />}
    </>
  );
}
