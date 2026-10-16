import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { Star } from "lucide-react";
import { api, objectUrl } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useAction } from "../../lib/hooks";
import { useEnum, useI18n } from "../../lib/i18n";
import { Button, Card, Dl, Empty, Field, Modal, Notice, PageHead, Q, StatusBadge, useApi } from "../../components/ui";

function Media({ incidentId, m }: { incidentId: string; m: any }) {
  const { t } = useI18n();
  const en = useEnum();
  const [src, setSrc] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [show, setShow] = useState(false);
  useEffect(() => {
    if (!show || !m.available) return;
    let url: string | null = null;
    objectUrl(`/api/incidents/${incidentId}/media/${m.id}`)
      .then((r) => {
        url = r.url;
        setSrc(r.url);
      })
      .catch((e) => setErr(e.message));
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [show, incidentId, m.id, m.available]);
  return (
    <li>
      <div className="row-between">
        <span><b>{en(m.kind)}</b> <span className="xs muted">· {en(m.role)} · {Math.round(m.size / 1024)} KB</span></span>
        <span className="row"><StatusBadge value={m.scan_status} />{m.available && !show && <Button size="sm" onClick={() => setShow(true)}>{t("common.view")}</Button>}</span>
      </div>
      {m.analysis_note && <div className="xs muted">{m.analysis_note}</div>}
      {m.kind === "audio" && (
        <div className="small" style={{ marginTop: 4 }}>
          {t("incident.transcript")}: <StatusBadge value={m.transcription_status} />
          {m.transcription_text && <blockquote className="seg">{m.transcription_text}</blockquote>}
        </div>
      )}
      {err && <div className="small" style={{ color: "var(--danger)" }}>{err}</div>}
      {src && m.kind === "image" && <img className="preview-img" src={src} alt={t("incident.photoAlt")} />}
      {src && m.kind === "audio" && <audio controls src={src} />}
      {src && m.kind === "document" && <a href={src} target="_blank" rel="noreferrer">{t("common.open")}</a>}
    </li>
  );
}

function ResolveModal({ inc, onClose }: { inc: any; onClose: () => void }) {
  const { t } = useI18n();
  const a = useAction();
  const [note, setNote] = useState("");
  const [file, setFile] = useState<File | null>(null);
  return (
    <Modal title={t("action.resolve")} onClose={onClose}>
      <Field label={t("incident.resolution")} hint={t("validation.min10")}>{(id, h) => <textarea id={id} aria-describedby={h} className="textarea" value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
      <Field label={t("incident.evidence")} hint={t("incident.evidenceHint")}>{(id, h) => <input id={id} aria-describedby={h} type="file" accept="image/jpeg,image/png,application/pdf" onChange={(e) => setFile(e.target.files?.[0] || null)} />}</Field>
      <div className="form-actions">
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" mutates busy={a.busy} disabled={note.trim().length < 10} onClick={async () => {
          const r = await a.run(async () => {
            if (file) {
              const fd = new FormData();
              fd.append("file", file);
              fd.append("role", "resolution_evidence");
              await api.upload(`/api/incidents/${inc.id}/media`, fd);
            }
            return api.post(`/api/incidents/${inc.id}/actions`, { action: "resolve", data: { note } });
          }, { success: t("action.resolve.done"), invalidate: [["incident", inc.id], ["authority-incidents"]] });
          if (r) onClose();
        }}>{t("action.resolve")}</Button>
      </div>
    </Modal>
  );
}

function FeedbackModal({ inc, onClose }: { inc: any; onClose: () => void }) {
  const { t } = useI18n();
  const a = useAction();
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  return (
    <Modal title={t("incident.closeTitle")} onClose={onClose}>
      <fieldset><legend>{t("incident.rating")}</legend>
        <div className="row" role="radiogroup">
          {[1, 2, 3, 4, 5].map((n) => (
            <button key={n} type="button" role="radio" aria-checked={rating === n} aria-label={t("incident.stars", { n })} className="icon-btn" onClick={() => setRating(n)}>
              <Star size={22} fill={n <= rating ? "currentColor" : "none"} aria-hidden />
            </button>
          ))}
        </div>
      </fieldset>
      <Field label={t("incident.comment")}>{(id) => <textarea id={id} className="textarea" value={comment} onChange={(e) => setComment(e.target.value)} />}</Field>
      <div className="form-actions">
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" mutates busy={a.busy} onClick={async () => {
          const r = await a.run(() => api.post(`/api/incidents/${inc.id}/actions`, { action: "close", data: { rating: rating || undefined, comment } }),
            { success: t("action.close.done"), invalidate: [["incident", inc.id], ["incidents"]] });
          if (r) onClose();
        }}>{t("incident.confirmClose")}</Button>
      </div>
    </Modal>
  );
}

export function IncidentDetail() {
  const { id = "" } = useParams();
  const { t, fmtDate, fmtDateTime } = useI18n();
  const en = useEnum();
  const { me } = useAuth();
  const officer = me?.active?.workspace === "authority";
  const a = useAction();
  const q = useApi<any>(["incident", id], `/api/incidents/${id}`);
  const muni = useApi<any>(["municipalities"], officer ? "/api/incidents/municipalities" : null);
  const [modal, setModal] = useState<"resolve" | "close" | null>(null);
  const [tri, setTri] = useState({ category: "", priority: "normal" });
  const [assignee, setAssignee] = useState("");
  const [note, setNote] = useState("");
  const act = (action: string, data: Record<string, unknown> = {}) =>
    a.run(() => api.post(`/api/incidents/${id}/actions`, { action, data }), { success: t(`action.${action}.done`), invalidate: [["incident", id], ["authority-incidents"], ["incidents"]] });
  return (
    <Q q={q}>
      {(d) => {
        const inc = d.incident;
        const can = (x: string) => d.allowed_actions.includes(x);
        return (
          <>
            <PageHead title={`${inc.reference} · ${en(inc.category)}`} sub={<>{inc.municipality} · <StatusBadge value={inc.status} /></>}
              actions={<Link to={officer ? "/authority/incidents" : "/incidents"}>{t("common.back")}</Link>} />
            <div className="grid grid-2" style={{ alignItems: "start" }}>
              <div className="stack">
                <Card title={t("incident.report")}>
                  <p style={{ whiteSpace: "pre-wrap" }}>{inc.description}</p>
                  <Dl items={[
                    [t("common.category"), <>{en(inc.category)} {inc.category_source === "rules_suggestion" && <span className="xs muted">({t("incq.suggested")})</span>}</>],
                    [t("incq.location"), inc.location_text || null],
                    [t("incident.approx"), inc.lat_approx != null ? `${inc.lat_approx}, ${inc.lon_approx} (${t("incident.precision")})` : t("incident.noLocation")],
                    [t("review.priority"), en(inc.priority)],
                    [t("queue.queue"), en(inc.queue)],
                    [t("queue.slaDue"), <>{fmtDate(inc.sla_due_at)} {inc.sla_breached && <span className="badge b-danger">{t("queue.breachedOpt")}</span>}</>],
                    ...(officer ? [[t("queue.assignee"), inc.assignee || t("queue.unassignedOpt")] as [string, string]] : []),
                    [t("common.created"), fmtDateTime(inc.created_at)],
                    ...(inc.feedback_rating ? [[t("incident.rating"), `${inc.feedback_rating}/5${inc.feedback_comment ? ` — ${inc.feedback_comment}` : ""}`] as [string, string]] : []),
                  ]} />
                  {inc.duplicate_of_id && <Notice kind="info">{t("incident.isDuplicate")}</Notice>}
                </Card>
                <Card title={t("incident.media")}>
                  {d.media.length === 0 ? <Empty title={t("incident.noMedia")} /> : <ul className="list">{d.media.map((m: any) => <Media key={m.id} incidentId={id} m={m} />)}</ul>}
                </Card>
                {officer && (
                  <Card title={t("incident.duplicates")}>
                    {(d.duplicates || []).length === 0 ? <Empty title={t("incident.noDuplicates")} /> : (
                      <ul className="list">{d.duplicates.map((x: any) => (
                        <li key={x.incident_id} className="row-between">
                          <span><Link className="mono" to={`/authority/incidents/${x.incident_id}`}>{x.reference}</Link> <span className="xs muted">· {t("incident.score", { s: x.score })} · {x.reasons.join(", ")}</span></span>
                          {can("mark_duplicate") && <Button size="sm" mutates busy={a.busy} onClick={() => act("mark_duplicate", { duplicate_of: x.incident_id })}>{t("action.mark_duplicate")}</Button>}
                        </li>
                      ))}</ul>
                    )}
                    <p className="xs muted">{t("incident.dupNote")}</p>
                  </Card>
                )}
              </div>
              <div className="stack">
                {d.allowed_actions.length > 0 && (
                  <Card title={t("review.actions")}>
                    {officer && can("triage") && (
                      <div className="row" style={{ marginBottom: 8 }}>
                        <label className="sr-only" htmlFor="tc">{t("common.category")}</label>
                        <select id="tc" className="select" style={{ width: "auto" }} value={tri.category || inc.category} onChange={(e) => setTri({ ...tri, category: e.target.value })}>
                          {(muni.data?.categories || [inc.category]).map((c: string) => <option key={c} value={c}>{en(c)}</option>)}
                        </select>
                        <label className="sr-only" htmlFor="tp">{t("review.priority")}</label>
                        <select id="tp" className="select" style={{ width: "auto" }} value={tri.priority} onChange={(e) => setTri({ ...tri, priority: e.target.value })}>
                          {["low", "normal", "high", "urgent"].map((p) => <option key={p} value={p}>{en(p)}</option>)}
                        </select>
                        <Button mutates busy={a.busy} onClick={() => act("triage", { category: tri.category || inc.category, priority: tri.priority, note })}>{t("action.triage")}</Button>
                      </div>
                    )}
                    {officer && can("assign") && (
                      <div className="row" style={{ marginBottom: 8 }}>
                        <label className="sr-only" htmlFor="ias">{t("review.assignTo")}</label>
                        <select id="ias" className="select" style={{ width: "auto" }} value={assignee || me?.user.id} onChange={(e) => setAssignee(e.target.value)}>
                          {(d.officers || []).map((o: any) => <option key={o.user_id} value={o.user_id}>{o.display_name}</option>)}
                        </select>
                        <Button mutates busy={a.busy} onClick={() => act("assign", { user_id: assignee || me?.user.id })}>{t("action.assign")}</Button>
                      </div>
                    )}
                    {(can("start") || can("reopen") || (officer && can("close"))) && (
                      <Field label={t("incident.publicNote")} hint={t("incident.publicNoteHint")}>
                        {(fid, h) => <textarea id={fid} aria-describedby={h} className="textarea" value={note} onChange={(e) => setNote(e.target.value)} />}
                      </Field>
                    )}
                    <div className="row">
                      {can("start") && <Button mutates busy={a.busy} onClick={() => act("start", { note })}>{t("action.start")}</Button>}
                      {can("resolve") && <Button variant="primary" mutates onClick={() => setModal("resolve")}>{t("action.resolve")}</Button>}
                      {can("reopen") && <Button mutates busy={a.busy} onClick={() => act("reopen", { note })}>{t("incident.notFixed")}</Button>}
                      {can("close") && (officer
                        ? <Button mutates busy={a.busy} onClick={() => act("close", { note })}>{t("action.close")}</Button>
                        : <Button variant="primary" mutates onClick={() => setModal("close")}>{t("incident.confirmFixed")}</Button>)}
                    </div>
                  </Card>
                )}
                <Card title={t("incident.updates")}>
                  {d.updates.length === 0 ? <Empty title={t("incident.noUpdates")} /> : (
                    <ol className="timeline">{d.updates.map((u: any) => (
                      <li key={u.id}>
                        <div className="when">{fmtDateTime(u.created_at)} {u.data?.to && <StatusBadge value={u.data.to} />}</div>
                        <div style={{ whiteSpace: "pre-wrap" }}>{u.body}</div>
                        {officer && u.author && <div className="who">{u.author}</div>}
                      </li>
                    ))}</ol>
                  )}
                  {!officer && <p className="xs muted">{t("incident.noStaffNames")}</p>}
                </Card>
              </div>
            </div>
            {modal === "resolve" && <ResolveModal inc={inc} onClose={() => setModal(null)} />}
            {modal === "close" && <FeedbackModal inc={inc} onClose={() => setModal(null)} />}
          </>
        );
      }}
    </Q>
  );
}
