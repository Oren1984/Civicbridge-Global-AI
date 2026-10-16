import { useState } from "react";
import { Link, useParams } from "react-router";
import { Bot, Lock } from "lucide-react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useAction } from "../../lib/hooks";
import { useEnum, useI18n } from "../../lib/i18n";
import {
  Button, Card, Dl, Empty, Field, Modal, Notice, PageHead, Q, SimulatedBadge, StatusBadge, useApi, useFieldErrors,
} from "../../components/ui";

const CATEGORIES = ["identity", "civil_status", "employment", "education", "financial", "housing", "health", "other"];
const OUTCOMES = ["approved", "partially_approved", "rejected", "referred"];
/** Actions that need input go through a modal; the rest run directly. */
const WITH_FORM = new Set(["assign", "request_info", "propose_decision", "return_for_rework", "escalate"]);

function ActionModal({ action, d, onClose }: { action: string; d: any; onClose: () => void }) {
  const { t } = useI18n();
  const en = useEnum();
  const { me } = useAuth();
  const a = useAction();
  const fe = useFieldErrors(a.error);
  const sr = d.request;
  const [f, setF] = useState<any>({ user_id: me?.user.id || "", message: "", items: "", due_working_days: 10, outcome: "approved", rationale: "", reason: "", note: "" });
  const [scaffold, setScaffold] = useState<string | null>(null);
  const submit = async () => {
    const data: Record<string, unknown> = { expected_version: sr.version };
    if (action === "assign") data.user_id = f.user_id;
    if (action === "request_info") Object.assign(data, { message: f.message, items: f.items.split("\n").map((s: string) => s.trim()).filter(Boolean), due_working_days: f.due_working_days });
    if (action === "propose_decision") Object.assign(data, { outcome: f.outcome, rationale: f.rationale });
    if (action === "return_for_rework") data.note = f.note;
    if (action === "escalate") data.reason = f.reason;
    const r = await a.run(() => api.post(`/api/authority/requests/${sr.id}/actions`, { action, data }), {
      success: t(`action.${action}.done`), invalidate: [["sr", sr.id], ["queue"], ["authority-stats"]],
    });
    if (r) onClose();
  };
  const draft = async () => {
    const r = await a.run(() => api.post("/api/ai/tools/invoke", { tool: "draft_decision_rationale", args: { service_request_id: sr.id } }));
    const res = r?.result || r;
    if (res?.draft) {
      setScaffold(res.label || null);
      setF((x: any) => ({ ...x, rationale: res.draft }));
    }
  };
  const valid =
    action === "request_info" ? f.message.trim().length >= 10
      : action === "propose_decision" ? f.rationale.trim().length >= 30
        : action === "escalate" ? f.reason.trim().length >= 5
          : true;
  return (
    <Modal title={t(`action.${action}`)} onClose={onClose} wide={action === "propose_decision"}>
      {action === "assign" && (
        <Field label={t("review.assignTo")}>
          {(id) => <select id={id} className="select" value={f.user_id} onChange={(e) => setF({ ...f, user_id: e.target.value })}>
            {d.officers.map((o: any) => <option key={o.user_id} value={o.user_id}>{o.display_name} · {t(`role.${o.role}`)}</option>)}
          </select>}
        </Field>
      )}
      {action === "request_info" && (
        <>
          <Field label={t("review.rfiMessage")} error={fe("message")} hint={t("validation.min10")}>
            {(id, h) => <textarea id={id} aria-describedby={h} className="textarea" value={f.message} onChange={(e) => setF({ ...f, message: e.target.value })} />}
          </Field>
          <Field label={t("review.rfiItems")} hint={t("review.rfiItemsHint")}>
            {(id, h) => <textarea id={id} aria-describedby={h} className="textarea" value={f.items} onChange={(e) => setF({ ...f, items: e.target.value })} />}
          </Field>
          <Field label={t("review.rfiDue")} hint={t("review.rfiDueHint")}>
            {(id, h) => <input id={id} aria-describedby={h} type="number" min={1} max={60} className="input" value={f.due_working_days} onChange={(e) => setF({ ...f, due_working_days: Number(e.target.value) })} />}
          </Field>
        </>
      )}
      {action === "propose_decision" && (
        <>
          <Notice kind="warning">{t("review.decisionNote")}</Notice>
          <Field label={t("review.outcome")}>
            {(id) => <select id={id} className="select" value={f.outcome} onChange={(e) => setF({ ...f, outcome: e.target.value })}>
              {OUTCOMES.map((o) => <option key={o} value={o}>{en(o)}</option>)}
            </select>}
          </Field>
          <Field label={t("review.rationale")} hint={t("review.rationaleHint")} error={fe("rationale")}>
            {(id, h) => <textarea id={id} aria-describedby={h} className="textarea" rows={7} value={f.rationale} onChange={(e) => setF({ ...f, rationale: e.target.value })} />}
          </Field>
          <div className="row">
            <Button size="sm" mutates onClick={draft} busy={a.busy}><Bot size={14} aria-hidden /> {t("review.scaffold")}</Button>
            {scaffold && <span className="xs muted">{scaffold}</span>}
          </div>
        </>
      )}
      {action === "return_for_rework" && (
        <Field label={t("review.reworkNote")}>{(id) => <textarea id={id} className="textarea" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />}</Field>
      )}
      {action === "escalate" && (
        <Field label={t("review.escalateReason")}>{(id) => <textarea id={id} className="textarea" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} />}</Field>
      )}
      <div className="form-actions">
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" mutates busy={a.busy} disabled={!valid} onClick={submit}>{t(`action.${action}`)}</Button>
      </div>
    </Modal>
  );
}

function ConsentRequestModal({ d, onClose }: { d: any; onClose: () => void }) {
  const { t } = useI18n();
  const en = useEnum();
  const { me } = useAuth();
  const a = useAction();
  const rec = useApi<any>(["recipients"], "/api/consents/recipients");
  const [f, setF] = useState({ recipient: me?.active?.tenant.id || "", purpose: "", cats: [] as string[], valid_days: 30 });
  const handoff = f.recipient && f.recipient !== me?.active?.tenant.id;
  return (
    <Modal title={t("review.requestConsent")} onClose={onClose} wide>
      <Field label={t("review.recipient")} hint={t("review.recipientHint")}>
        {(id, h) => <select id={id} aria-describedby={h} className="select" value={f.recipient} onChange={(e) => setF({ ...f, recipient: e.target.value })}>
          {(rec.data?.items || []).map((r: any) => <option key={r.id} value={r.id}>{r.name} ({en(r.kind)})</option>)}
        </select>}
      </Field>
      {handoff && <Notice kind="info" title={t("review.handoff")}>{t("review.handoffNote")}</Notice>}
      <Field label={t("consent.purpose")} hint={t("validation.min5")}>
        {(id, h) => <input id={id} aria-describedby={h} className="input" value={f.purpose} onChange={(e) => setF({ ...f, purpose: e.target.value })} />}
      </Field>
      <fieldset><legend>{t("consent.categories")}</legend>
        <div className="grid grid-3" style={{ gap: 0 }}>
          {CATEGORIES.map((c) => <label key={c} className="check"><input type="checkbox" checked={f.cats.includes(c)} onChange={() => setF({ ...f, cats: f.cats.includes(c) ? f.cats.filter((x) => x !== c) : [...f.cats, c] })} /> {en(c)}</label>)}
        </div>
      </fieldset>
      <Field label={t("consent.duration")}>
        {(id) => <input id={id} type="number" min={1} max={365} className="input" value={f.valid_days} onChange={(e) => setF({ ...f, valid_days: Number(e.target.value) })} />}
      </Field>
      <div className="form-actions">
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" mutates busy={a.busy} disabled={f.purpose.trim().length < 5 || !f.cats.length} onClick={async () => {
          const r = await a.run(() => api.post("/api/consents/requests", { case_id: d.case.id, recipient_tenant_id: f.recipient || null, purpose: f.purpose, data_categories: f.cats, valid_days: f.valid_days }),
            { success: t("review.consentRequested"), invalidate: [["sr", d.request.id], ["authority-consents"]] });
          if (r) onClose();
        }}>{t("review.sendRequest")}</Button>
      </div>
    </Modal>
  );
}

function EvidenceReview({ items, srId }: { items: any[]; srId: string }) {
  const { t } = useI18n();
  const en = useEnum();
  const a = useAction();
  const [notes, setNotes] = useState<Record<string, string>>({});
  if (!items.length) return <Empty title={t("review.noEvidence")} />;
  const review = (id: string, status: string) =>
    a.run(() => api.post(`/api/authority/evidence/${id}/review`, { status, note: notes[id] || "" }), { success: t("review.evidenceReviewed"), invalidate: [["sr", srId]] });
  return (
    <ul className="list">
      {items.map((e) => (
        <li key={e.id}>
          <div className="row-between">
            <div>
              {e.document.restricted ? (
                <span><Lock size={14} aria-hidden /> <b>{en(e.document.category)}</b> <span className="small muted">— {e.document.note}</span></span>
              ) : (
                <><Link to={`/wallet/${e.document.id}`}><b>{e.document.title}</b></Link> <span className="xs muted">· {en(e.document.category)} · v{e.document.current_version}</span> <StatusBadge value={e.document.scan_status} /></>
              )}
              {e.evidence_key && <div className="xs muted">{t("review.evidenceFor", { key: e.evidence_key })}</div>}
              {e.review_note && <div className="small">{e.review_note}</div>}
            </div>
            <StatusBadge value={e.status} />
          </div>
          {!e.document.restricted && e.service_request_id && (
            <div className="row" style={{ marginTop: 8 }}>
              <label className="sr-only" htmlFor={`n-${e.id}`}>{t("review.note")}</label>
              <input id={`n-${e.id}`} className="input" style={{ maxWidth: 320 }} placeholder={t("review.notePh")} value={notes[e.id] || ""} onChange={(ev) => setNotes({ ...notes, [e.id]: ev.target.value })} />
              <Button size="sm" mutates busy={a.busy} onClick={() => review(e.id, "accepted")}>{t("review.accept")}</Button>
              <Button size="sm" mutates busy={a.busy} disabled={(notes[e.id] || "").length < 5} onClick={() => review(e.id, "needs_more")}>{t("review.needsMore")}</Button>
              <Button size="sm" variant="danger" mutates busy={a.busy} disabled={(notes[e.id] || "").length < 5} onClick={() => review(e.id, "rejected")}>{t("review.reject")}</Button>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

export function RequestReview() {
  const { id = "" } = useParams();
  const { t, fmtDate, fmtDateTime } = useI18n();
  const en = useEnum();
  const a = useAction();
  const q = useApi<any>(["sr", id], `/api/authority/requests/${id}`);
  const [modal, setModal] = useState<string | null>(null);
  const [consentOpen, setConsentOpen] = useState(false);
  const [msg, setMsg] = useState("");
  return (
    <Q q={q}>
      {(d) => {
        const sr = d.request;
        return (
          <>
            <PageHead
              title={`${sr.reference} · ${sr.title}`}
              sub={<>{t("review.applicant")}: <b>{d.case.applicant}</b> · <Link to={`/cases/${d.case.id}`}>{d.case.reference}</Link> · <StatusBadge value={sr.state} /> <SimulatedBadge /></>}
            />
            <Notice kind="synthetic">{d.notice}</Notice>
            <div className="grid grid-2" style={{ marginTop: 16, alignItems: "start" }}>
              <div className="stack">
                <Card title={t("review.details")}>
                  <Dl items={[
                    [t("common.type"), en(sr.kind)],
                    [t("review.procedure"), sr.procedure ? `${sr.procedure.name} (${sr.procedure.code})` : null],
                    [t("queue.queue"), en(sr.queue)],
                    [t("review.priority"), en(sr.priority)],
                    [t("review.submitted"), fmtDateTime(sr.submitted_at)],
                    [t("queue.slaDue"), <>{sr.sla_paused_at ? <span className="badge b-warning">{t("queue.paused")}</span> : fmtDate(sr.sla_due_at)} {sr.sla_breached && <span className="badge b-danger">{t("queue.breachedOpt")}</span>}</>],
                    [t("queue.assignee"), sr.assignee || t("queue.unassignedOpt")],
                    [t("review.escalation"), sr.escalation_level ? String(sr.escalation_level) : "—"],
                    ...(sr.parent_reference ? [[t("review.appealOf"), sr.parent_reference] as [string, string]] : []),
                  ]} />
                  {sr.payload && Object.keys(sr.payload).length > 0 && (
                    <details style={{ marginTop: 8 }}><summary className="small">{t("review.payload")}</summary>
                      <Dl items={Object.entries(sr.payload).filter(([k]) => k !== "queue").map(([k, v]) => [k.replace(/_/g, " "), typeof v === "object" ? JSON.stringify(v) : String(v)])} />
                    </details>
                  )}
                </Card>
                <Card title={t("review.evidence")}>
                  <EvidenceReview items={d.evidence.filter((e: any) => e.service_request_id === sr.id)} srId={sr.id} />
                  {d.evidence.some((e: any) => e.service_request_id !== sr.id) && (
                    <details style={{ marginTop: 8 }}>
                      <summary className="small">{t("review.otherEvidence", { n: d.evidence.filter((e: any) => e.service_request_id !== sr.id).length })}</summary>
                      <EvidenceReview items={d.evidence.filter((e: any) => e.service_request_id !== sr.id)} srId={sr.id} />
                    </details>
                  )}
                </Card>
                <Card title={t("review.infoRequests")}>
                  {d.information_requests.length === 0 ? <Empty title={t("review.noInfo")} /> : (
                    <ul className="list">{d.information_requests.map((i: any) => (
                      <li key={i.id}>
                        <div className="row-between"><b>{i.message}</b><StatusBadge value={i.status} /></div>
                        {i.items?.length > 0 && <ul className="small">{i.items.map((x: string) => <li key={x}>{x}</li>)}</ul>}
                        <div className="xs muted">{t("review.dueOn", { date: fmtDate(i.due_at) })}</div>
                        {i.response && <Notice kind="success" title={t("review.response")}>{i.response}</Notice>}
                      </li>
                    ))}</ul>
                  )}
                </Card>
                <Card title={t("review.decisions")}>
                  {d.decisions.length === 0 ? <Empty title={t("review.noDecisions")} /> : (
                    <ul className="list">{d.decisions.map((x: any) => (
                      <li key={x.id}>
                        <div className="row-between"><b>v{x.version} · {en(x.outcome)}</b><span className="row"><StatusBadge value={x.status} />{x.is_simulated && <SimulatedBadge />}</span></div>
                        <p className="small" style={{ whiteSpace: "pre-wrap" }}>{x.rationale}</p>
                        <div className="xs muted">
                          {t("review.proposedBy", { name: x.proposed_by })}{x.proposed_by_me && ` (${t("review.you")})`}
                          {x.approved_by && <> · {t("review.approvedBy", { name: x.approved_by, date: fmtDate(x.approved_at) })}</>}
                          {x.appeal_deadline && <> · {t("review.appealUntil", { date: fmtDate(x.appeal_deadline) })}</>}
                        </div>
                        {x.status === "proposed" && x.proposed_by_me && <div className="xs" style={{ color: "var(--warning)" }}>{t("review.fourEyes")}</div>}
                      </li>
                    ))}</ul>
                  )}
                </Card>
              </div>
              <div className="stack">
                <Card title={t("review.actions")}>
                  {d.allowed_actions.length === 0 ? <p className="small muted">{t("review.noActions")}</p> : (
                    <div className="row">
                      {d.allowed_actions.map((act: string) => (
                        <Button key={act} mutates busy={a.busy} variant={act === "approve_decision" || act === "propose_decision" ? "primary" : "default"}
                          onClick={() => WITH_FORM.has(act) ? setModal(act) : a.run(() => api.post(`/api/authority/requests/${sr.id}/actions`, { action: act, data: { expected_version: sr.version } }),
                            { success: t(`action.${act}.done`), invalidate: [["sr", sr.id], ["queue"], ["authority-stats"]] })}>
                          {t(`action.${act}`)}
                        </Button>
                      ))}
                    </div>
                  )}
                  <p className="xs muted" style={{ marginTop: 8 }}>{t("review.actionsNote")}</p>
                </Card>
                <Card title={t("review.consents")} actions={<Button size="sm" mutates onClick={() => setConsentOpen(true)}>{t("review.requestConsent")}</Button>}>
                  {d.consents.length === 0 ? <Empty title={t("review.noConsents")} /> : (
                    <ul className="list">{d.consents.map((g: any) => (
                      <li key={g.id}>
                        <div className="row-between"><span><b>{g.recipient.name}</b>{g.handoff && <> <span className="badge b-accent">{t("review.handoff")}</span></>}</span><StatusBadge value={g.status} /></div>
                        <div className="small">{g.purpose}</div>
                        <div className="chip-row">{g.data_categories.map((c: string) => <span key={c} className="badge">{en(c)}</span>)}</div>
                        <div className="xs muted">{t("consent.validUntil", { date: fmtDate(g.valid_until) })}</div>
                      </li>
                    ))}</ul>
                  )}
                </Card>
                <Card title={t("messages.title")}>
                  {d.messages.length === 0 ? <Empty title={t("messages.none")} /> : (
                    <ul className="list">{d.messages.map((m: any) => (
                      <li key={m.id}><div className="xs muted">{m.sender_label} · {fmtDateTime(m.created_at)}{m.ai_drafted && ` · ${t("messages.aiDrafted")}`}</div><div style={{ whiteSpace: "pre-wrap" }}>{m.body}</div></li>
                    ))}</ul>
                  )}
                  <Field label={t("messages.new")}>{(fid) => <textarea id={fid} className="textarea" value={msg} onChange={(e) => setMsg(e.target.value)} />}</Field>
                  <div className="form-actions">
                    <Button variant="primary" mutates busy={a.busy} disabled={msg.trim().length < 2} onClick={async () => {
                      const r = await a.run(() => api.post(`/api/cases/${d.case.id}/messages`, { body: msg }), { success: t("messages.sent"), invalidate: [["sr", sr.id]] });
                      if (r) setMsg("");
                    }}>{t("messages.send")}</Button>
                  </div>
                </Card>
                <Card title={t("timeline.title")}>
                  <ol className="timeline">{d.timeline.map((e: any) => (
                    <li key={e.id}>
                      <div className="when">{fmtDateTime(e.at)} {e.visibility !== "all" && <span className="badge b-warning">{t("timeline.internal")}</span>}</div>
                      <div>{e.summary}</div>
                      <div className="who">{e.actor_label}</div>
                    </li>
                  ))}</ol>
                </Card>
              </div>
            </div>
            {modal && <ActionModal action={modal} d={d} onClose={() => setModal(null)} />}
            {consentOpen && <ConsentRequestModal d={d} onClose={() => setConsentOpen(false)} />}
          </>
        );
      }}
    </Q>
  );
}
