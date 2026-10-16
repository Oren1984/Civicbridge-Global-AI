import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { Bot, Check, Download, FileText, Paperclip, Send, ShieldCheck, Sparkles, Video } from "lucide-react";
import { api, downloadFile } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useAction } from "../../lib/hooks";
import { useEnum, useI18n } from "../../lib/i18n";
import {
  Button, Card, Confirm, Dl, Empty, Field, Modal, Notice, PageHead, Progress, Q, SimulatedBadge, StatusBadge, SyntheticBadge, Tabs, useApi,
} from "../../components/ui";
import { GrantConsentModal } from "../citizen/Consent";
import { ScheduleMeetingModal } from "./Meetings";

const PHASES = ["intake", "evidence", "review", "coordination", "decision", "closure"];

function Stepper({ tasks, requests }: { tasks: any[]; requests: any[] }) {
  const { t } = useI18n();
  const state = PHASES.map((p) => {
    const ts = tasks.filter((x) => x.phase === p);
    const done = ts.length ? ts.every((x) => ["done", "skipped"].includes(x.status)) : null;
    return { p, done, has: ts.length > 0 };
  });
  const decided = requests.some((r) => ["decided", "closed", "appealed"].includes(r.state));
  let current = state.findIndex((s) => s.has && !s.done);
  if (current < 0) current = decided ? 5 : 4;
  return (
    <ol className="stepper" aria-label={t("case.journeyStage")}>
      {state.map((s, i) => (
        <li key={s.p} className={`step ${i < current ? "done" : ""} ${i === current ? "current" : ""}`} aria-current={i === current ? "step" : undefined}>
          {i + 1}. {t(`phase.${s.p}`)}
        </li>
      ))}
    </ol>
  );
}

function AttachEvidence({ caseId, task, ev, requestId, onClose }: { caseId: string; task?: any; ev?: any; requestId?: string; onClose: () => void }) {
  const { t } = useI18n();
  const en = useEnum();
  const { me } = useAuth();
  const a = useAction();
  const owner = me?.active?.workspace === "citizen";
  const docs = useApi<any>(["docs", "attach"], owner ? "/api/documents" : null);
  const [docId, setDocId] = useState("");
  const [key, setKey] = useState(ev?.key || "");
  const items = (docs.data?.items || []).filter((d: any) => !ev?.category || d.category === ev.category);
  return (
    <Modal title={t("evidence.attachTitle")} onClose={onClose}>
      {ev && <p className="muted">{t("evidence.for", { label: ev.label, category: en(ev.category) })}</p>}
      {!owner ? <Notice>{t("evidence.ownerOnly")}</Notice> : (
        <Q q={docs}>
          {() => items.length === 0 ? (
            <Empty title={t("evidence.noDocs")}><Link to="/wallet">{t("wallet.upload")}</Link></Empty>
          ) : (
            <>
              <fieldset><legend>{t("evidence.choose")}</legend>
                {items.map((d: any) => (
                  <label key={d.id} className="check">
                    <input type="radio" name="doc" checked={docId === d.id} onChange={() => setDocId(d.id)} />
                    <span>{d.title} <span className="xs muted">· {en(d.category)}</span> <StatusBadge value={d.versions.at(-1)?.scan_status} /></span>
                  </label>
                ))}
              </fieldset>
              <Field label={t("evidence.key")} hint={t("evidence.keyHint")}>{(id, d) => <input id={id} aria-describedby={d} className="input" value={key} onChange={(e) => setKey(e.target.value)} />}</Field>
            </>
          )}
        </Q>
      )}
      <div className="form-actions">
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" mutates disabled={!docId} busy={a.busy} onClick={async () => {
          const r = await a.run(() => api.post(`/api/cases/${caseId}/evidence`, { document_id: docId, task_id: task?.task_id || task?.id || null, service_request_id: requestId || null, evidence_key: key }), { success: t("evidence.attached"), invalidate: [["case", caseId]] });
          if (r) onClose();
        }}>{t("evidence.attach")}</Button>
      </div>
    </Modal>
  );
}

function Checklist({ caseId, detail, progress }: { caseId: string; detail: any; progress: any }) {
  const { t, fmtDate } = useI18n();
  const a = useAction();
  const [attach, setAttach] = useState<{ task: any; ev: any } | null>(null);
  const canEdit = detail.access.level === "owner" || detail.access.scopes.includes("respond_info_requests");
  const procedures = new Set(detail.requests.map((r: any) => r.procedure?.code));
  const groups = progress ? progress.groups : [{ jurisdiction: t("case.tasks"), code: null, items: detail.tasks.map((x: any) => ({ ...x, task_id: x.id, explain: [] })), done: 0, total: detail.tasks.length }];
  const toggle = (item: any) =>
    a.run(() => api.patch(`/api/cases/${caseId}/tasks/${item.task_id}`, { status: item.status === "done" ? "todo" : "done" }), {
      success: item.status === "done" ? t("tasks.reopened") : t("tasks.completed"), invalidate: [["case", caseId], ["progress", caseId]],
    });
  const prepare = (code: string) =>
    a.run(() => api.post(`/api/cases/${caseId}/requests`, { procedure_code: code }), { success: t("requests.prepared"), invalidate: [["case", caseId]] });
  return (
    <>
      {progress && <Notice kind="synthetic">{progress.notice}</Notice>}
      {groups.map((g: any) => (
        <Card key={g.code || "p"} title={<h3 style={{ margin: 0 }}>{g.jurisdiction} {g.code && <span className="badge">{g.code}</span>}</h3>}
          actions={g.timezone && <span className="xs muted">{t("tasks.localTime", { tz: g.timezone })}</span>}>
          <Progress done={g.done} total={g.total} label={t("tasks.progress")} />
          <ul className="list" style={{ marginTop: 8 }}>
            {g.items.map((it: any) => (
              <li key={it.task_id} className="task">
                <button className={`task-status ${it.status === "done" ? "done" : ""}`} aria-label={`${it.title}: ${it.status === "done" ? t("tasks.markTodo") : t("tasks.markDone")}`}
                  aria-pressed={it.status === "done"} disabled={!canEdit} onClick={() => toggle(it)}>
                  {it.status === "done" && <Check size={14} aria-hidden />}
                </button>
                <div>
                  <b style={{ textDecoration: it.status === "done" ? "line-through" : undefined }}>{it.title}</b>
                  {it.deadline_basis && <div className="xs muted">{t("tasks.deadlineBasis")}: {it.deadline_basis}</div>}
                  {it.explain?.length > 0 && (
                    <ul className="explain">{it.explain.map((e: any, i: number) => <li key={i} className={e.code}>• {e.text}</li>)}</ul>
                  )}
                  {it.required_evidence?.length > 0 && it.status !== "done" && canEdit && (
                    <div className="chip-row" style={{ marginTop: 6 }}>
                      {it.required_evidence.map((ev: any) => {
                        const have = it.linked_evidence?.some((l: any) => l.key === ev.key);
                        return have ? <span key={ev.key} className="badge b-success"><Check size={12} aria-hidden /> {ev.label}</span> :
                          <Button key={ev.key} size="sm" mutates onClick={() => setAttach({ task: it, ev })}><Paperclip size={13} aria-hidden /> {ev.label}</Button>;
                      })}
                    </div>
                  )}
                  {it.procedure_code && !procedures.has(it.procedure_code) && canEdit && (
                    <div style={{ marginTop: 6 }}><Button size="sm" mutates onClick={() => prepare(it.procedure_code)}>{t("requests.prepare")}</Button></div>
                  )}
                </div>
                <div className="right">{it.due_at && <span className="badge">{fmtDate(it.due_at)}</span>}</div>
              </li>
            ))}
          </ul>
        </Card>
      ))}
      {attach && <AttachEvidence caseId={caseId} task={attach.task} ev={attach.ev} onClose={() => setAttach(null)} />}
    </>
  );
}

function RequestCard({ caseId, r, detail }: { caseId: string; r: any; detail: any }) {
  const { t, fmtDate, fmtDateTime } = useI18n();
  const en = useEnum();
  const a = useAction();
  const [response, setResponse] = useState("");
  const [grounds, setGrounds] = useState("");
  const [appealOpen, setAppealOpen] = useState(false);
  const [consentOpen, setConsentOpen] = useState(false);
  const [confirmWithdraw, setConfirmWithdraw] = useState(false);
  const [attach, setAttach] = useState(false);
  const act = (action: string, data: any = {}) =>
    a.run(() => api.post(`/api/cases/${caseId}/requests/${r.id}/actions`, { action, data: { ...data, expected_version: r.version } }), {
      success: t(`action.${action}.done`), invalidate: [["case", caseId], ["timeline", caseId]],
    });
  const openInfo = r.information_requests.filter((i: any) => i.status === "open");
  const reqEvidence = detail.evidence.filter((e: any) => e.service_request_id === r.id);
  const owner = detail.access.level === "owner";
  const decided = r.decisions.filter((d: any) => d.status === "approved").at(-1);
  return (
    <Card title={<div><h3 style={{ margin: 0 }}>{r.title}</h3><span className="xs muted mono">{r.reference}</span></div>}
      actions={<><StatusBadge value={r.state} /><SimulatedBadge /></>}>
      <Dl items={[
        [t("requests.authority"), r.authority],
        [t("requests.kind"), en(r.kind)],
        [t("requests.submitted"), fmtDateTime(r.submitted_at)],
        [t("requests.sla"), r.sla_due_at ? <>{fmtDate(r.sla_due_at)} {r.sla_paused_at && <span className="badge b-warning">{t("requests.slaPaused")}</span>} {r.sla_breached && <span className="badge b-danger">{t("requests.slaBreached")}</span>}</> : "—"],
      ]} />
      <hr />
      <h4>{t("requests.evidence")}</h4>
      {reqEvidence.length === 0 ? <p className="small muted">{t("requests.noEvidence")}</p> : (
        <ul className="list">{reqEvidence.map((e: any) => (
          <li key={e.id} className="row-between"><span><FileText size={14} aria-hidden /> {e.document.restricted ? t("evidence.restricted") : e.document.title}</span>
            <span className="row"><StatusBadge value={e.status} />{e.review_note && <span className="xs muted">{e.review_note}</span>}</span></li>
        ))}</ul>
      )}
      {owner && r.state === "draft" && (
        <>
          <Notice kind="info" title={t("requests.beforeSubmit")}>{t("requests.consentHint")}</Notice>
          <div className="row">
            <Button size="sm" mutates onClick={() => setAttach(true)}><Paperclip size={14} aria-hidden /> {t("evidence.attach")}</Button>
            <Button size="sm" mutates onClick={() => setConsentOpen(true)}><ShieldCheck size={14} aria-hidden /> {t("consent.grantFor", { name: r.authority })}</Button>
          </div>
        </>
      )}
      {openInfo.map((i: any) => (
        <Notice key={i.id} kind="warning" title={t("requests.infoRequested")}>
          <p style={{ margin: "4px 0" }}>{i.message}</p>
          {i.items?.length > 0 && <ul>{i.items.map((x: string) => <li key={x}>{x}</li>)}</ul>}
          <p className="xs">{t("common.due", { date: fmtDate(i.due_at) })}</p>
          {r.allowed_actions.includes("respond_info") && (
            <>
              <Field label={t("requests.yourResponse")}>{(id) => <textarea id={id} className="textarea" value={response} onChange={(e) => setResponse(e.target.value)} />}</Field>
              <Button variant="primary" size="sm" mutates busy={a.busy} disabled={response.trim().length < 2} onClick={() => act("respond_info", { response })}>{t("requests.sendResponse")}</Button>
            </>
          )}
        </Notice>
      ))}
      {r.decisions.length > 0 && (
        <>
          <h4>{t("decisions.title")}</h4>
          {r.decisions.map((d: any) => (
            <div key={d.id} className="card card-tight" style={{ background: "var(--surface-2)" }}>
              <div className="row-between"><b>{t("decisions.version", { v: d.version })}: {en(d.outcome)}</b><span className="row"><StatusBadge value={d.status} />{d.is_simulated && <SyntheticBadge text={t("decisions.demo")} />}</span></div>
              <p className="small" style={{ marginTop: 6 }}><b>{t("decisions.rationale")}:</b> {d.rationale}</p>
              <p className="xs muted">{t("decisions.approvedAt", { at: fmtDateTime(d.approved_at) })}{d.appeal_deadline && d.status === "approved" && ` · ${t("decisions.appealUntil", { date: fmtDate(d.appeal_deadline) })}`}</p>
            </div>
          ))}
        </>
      )}
      <div className="row" style={{ marginTop: 12 }}>
        {r.allowed_actions.includes("submit") && <Button variant="primary" mutates busy={a.busy} onClick={() => act("submit")}><Send size={14} aria-hidden /> {t("action.submit")}</Button>}
        {r.allowed_actions.includes("appeal") && decided && <Button mutates onClick={() => setAppealOpen(true)}>{t("action.appeal")}</Button>}
        {r.allowed_actions.includes("withdraw") && <Button variant="ghost" mutates onClick={() => setConfirmWithdraw(true)}>{t("action.withdraw")}</Button>}
      </div>
      {r.state === "draft" && <p className="xs muted" style={{ marginTop: 8 }}>{t("requests.simulatedNote")}</p>}
      {appealOpen && (
        <Modal title={t("appeal.title")} onClose={() => setAppealOpen(false)}>
          <p className="muted">{t("appeal.sub")}</p>
          <Field label={t("appeal.grounds")} hint={t("appeal.hint")} error={grounds.length > 0 && grounds.length < 20 ? t("validation.min20") : undefined}>
            {(id, d) => <textarea id={id} aria-describedby={d} className="textarea" value={grounds} onChange={(e) => setGrounds(e.target.value)} />}
          </Field>
          <div className="form-actions"><Button onClick={() => setAppealOpen(false)}>{t("common.cancel")}</Button>
            <Button variant="primary" mutates busy={a.busy} disabled={grounds.trim().length < 20} onClick={async () => { const x = await act("appeal", { grounds }); if (x) setAppealOpen(false); }}>{t("appeal.file")}</Button></div>
        </Modal>
      )}
      {confirmWithdraw && <Confirm title={t("action.withdraw")} body={<p>{t("requests.withdrawConfirm")}</p>} confirmLabel={t("action.withdraw")} danger onCancel={() => setConfirmWithdraw(false)} onConfirm={async () => { await act("withdraw"); setConfirmWithdraw(false); }} />}
      {consentOpen && <GrantConsentModal onClose={() => setConsentOpen(false)} preset={{ recipient_tenant_id: r.tenant_id, case_id: caseId, purpose: `${r.title} (${r.reference})`, data_categories: [...new Set(reqEvidence.map((e: any) => e.document.category).filter(Boolean))] as string[] }} invalidate={[["case", caseId]]} />}
      {attach && <AttachEvidence caseId={caseId} requestId={r.id} onClose={() => setAttach(false)} />}
    </Card>
  );
}

function Messages({ caseId, access }: { caseId: string; access: any }) {
  const { t, fmtDateTime, locale } = useI18n();
  const q = useApi<any>(["messages", caseId], `/api/cases/${caseId}/messages`, { refetchInterval: 15000 });
  const a = useAction();
  const [body, setBody] = useState("");
  const [aiDrafted, setAiDrafted] = useState(false);
  const canSend = access.level === "owner" || access.scopes.includes("send_messages");
  const canDraft = access.level === "owner" || access.scopes.includes("draft_messages");
  const draft = async () => {
    const r = await a.run(() => api.post("/api/ai/tools/invoke", { tool: "draft_message", args: { case_id: caseId, intent: "status_question", language: locale } }), { silent: false });
    if (r?.result?.draft) {
      setBody(r.result.draft);
      setAiDrafted(true);
    }
  };
  return (
    <Card title={t("messages.title")}>
      <Q q={q}>
        {(d) => d.items.length === 0 ? <Empty title={t("messages.none")} /> : (
          <ul className="list">{d.items.map((m: any) => (
            <li key={m.id}>
              <div className="row-between"><b>{m.sender_label}</b><span className="xs muted">{fmtDateTime(m.created_at)}</span></div>
              <div style={{ whiteSpace: "pre-wrap" }}>{m.body}</div>
              {m.ai_drafted && <span className="badge b-synthetic"><Bot size={12} aria-hidden /> {t("messages.aiDrafted")}</span>}
            </li>
          ))}</ul>
        )}
      </Q>
      {canSend ? (
        <div style={{ marginTop: 12 }}>
          <Field label={t("messages.compose")}>{(id) => <textarea id={id} className="textarea" value={body} onChange={(e) => { setBody(e.target.value); if (!e.target.value) setAiDrafted(false); }} />}</Field>
          {aiDrafted && <Notice kind="synthetic">{t("messages.draftNotice")}</Notice>}
          <div className="row">
            <Button variant="primary" mutates busy={a.busy} disabled={!body.trim()} onClick={async () => {
              const r = await a.run(() => api.post(`/api/cases/${caseId}/messages`, { body, ai_drafted: aiDrafted }), { success: t("messages.sent"), invalidate: [["messages", caseId], ["timeline", caseId]] });
              if (r) { setBody(""); setAiDrafted(false); }
            }}><Send size={14} aria-hidden /> {t("messages.send")}</Button>
            {canDraft && <Button mutates onClick={draft}><Sparkles size={14} aria-hidden /> {t("messages.draftAi")}</Button>}
          </div>
        </div>
      ) : canDraft ? (
        <div style={{ marginTop: 12 }}>
          <Notice>{t("messages.draftOnly")}</Notice>
          <Button mutates onClick={draft}><Sparkles size={14} aria-hidden /> {t("messages.draftAi")}</Button>
          {body && <pre className="text-preview" style={{ marginTop: 8 }}>{body}</pre>}
        </div>
      ) : <p className="small muted">{t("messages.noScope")}</p>}
    </Card>
  );
}

function Timeline({ caseId }: { caseId: string }) {
  const { t, fmtDateTime } = useI18n();
  const q = useApi<any>(["timeline", caseId], `/api/cases/${caseId}/timeline?page_size=100`);
  return (
    <Card title={t("timeline.title")}>
      <Q q={q}>
        {(d) => d.items.length === 0 ? <Empty title={t("timeline.none")} /> : (
          <ol className="timeline">{d.items.map((e: any) => (
            <li key={e.id}>
              <div className="when">{fmtDateTime(e.at)} {e.visibility === "internal" && <span className="badge b-warning">{t("timeline.internal")}</span>}</div>
              <div>{e.summary}</div>
              <div className="who">{e.actor_label}</div>
            </li>
          ))}</ol>
        )}
      </Q>
    </Card>
  );
}

function Assist({ caseId, access }: { caseId: string; access: any }) {
  const { t } = useI18n();
  const a = useAction();
  const [out, setOut] = useState<any>(null);
  const run = async (tool: string) => {
    const r = await a.run(() => api.post("/api/ai/tools/invoke", { tool, args: { case_id: caseId } }));
    if (r) setOut({ tool, ...r.result });
  };
  return (
    <Card title={<h3 style={{ margin: 0 }}><Bot size={16} aria-hidden /> {t("assist.title")}</h3>} tight>
      <p className="small muted">{t("assist.sub")}</p>
      <div className="row">
        <Button size="sm" mutates onClick={() => run("summarize_case")}>{t("assist.summarize")}</Button>
        {access.level !== "authority" && access.level !== "institution" && <Button size="sm" mutates onClick={() => run("suggest_next_steps")}>{t("assist.nextSteps")}</Button>}
      </div>
      {out && (
        <div style={{ marginTop: 12 }}>
          {out.summary && <p>{out.summary}</p>}
          {out.steps && (out.steps.length ? <ul>{out.steps.map((s: any) => <li key={s.task_id}><b>{s.title}</b> <span className="xs muted">— {s.why}</span></li>)}</ul> : <p>{t("assist.noSteps")}</p>)}
          <p className="xs muted">{out.label}</p>
        </div>
      )}
    </Card>
  );
}

export function CaseDetail() {
  const { id = "" } = useParams();
  const { t, fmtDateTime } = useI18n();
  const en = useEnum();
  const q = useApi<any>(["case", id], `/api/cases/${id}`);
  const progress = useApi<any>(["progress", id], q.data?.life_event ? `/api/life-events/by-case/${id}/progress` : null);
  const [tab, setTab] = useState<"checklist" | "requests" | "evidence" | "messages" | "timeline" | "meetings">("checklist");
  const [schedule, setSchedule] = useState(false);
  const a = useAction();
  const tabs = useMemo(() => {
    const d = q.data;
    return [
      { id: "checklist" as const, label: t("case.tab.checklist"), count: d?.tasks.length },
      { id: "requests" as const, label: t("case.tab.requests"), count: d?.requests.length },
      { id: "evidence" as const, label: t("case.tab.evidence"), count: d?.evidence.length },
      { id: "messages" as const, label: t("case.tab.messages") },
      { id: "timeline" as const, label: t("case.tab.timeline") },
      { id: "meetings" as const, label: t("case.tab.meetings"), count: d?.meetings.length },
    ];
  }, [q.data, t]);
  return (
    <Q q={q}>
      {(d) => (
        <>
          <PageHead title={d.case.title} sub={<><span className="mono">{d.case.reference}</span> · {en(d.case.case_type)} · <StatusBadge value={d.case.status} /></>}
            actions={<>
              {d.access.level === "owner" && <Button onClick={() => a.run(() => downloadFile(`/api/cases/${id}/export`, `${d.case.reference}.zip`), { success: t("case.exported") })} busy={a.busy}><Download size={15} aria-hidden /> {t("case.export")}</Button>}
              {["owner", "authority", "institution"].includes(d.access.level) && <Button mutates onClick={() => setSchedule(true)}><Video size={15} aria-hidden /> {t("meetings.schedule")}</Button>}
            </>} />
          {d.access.level !== "owner" && <Notice kind="info">{t(`case.accessNote.${d.access.level}`)}</Notice>}
          <Stepper tasks={d.tasks} requests={d.requests} />
          <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1fr)" }}>
            <Tabs label={t("case.sections")} tabs={tabs} value={tab} onChange={setTab} />
            {tab === "checklist" && (
              <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr)", gap: 0 }}>
                <Assist caseId={id} access={d.access} />
                {progress.isLoading ? null : <Checklist caseId={id} detail={d} progress={progress.data} />}
              </div>
            )}
            {tab === "requests" && (d.requests.length === 0 ? <Card><Empty title={t("requests.none")}>{t("requests.noneHint")}</Empty></Card> : d.requests.map((r: any) => <RequestCard key={r.id} caseId={id} r={r} detail={d} />))}
            {tab === "evidence" && (
              <Card title={t("case.tab.evidence")}>
                {d.evidence.length === 0 ? <Empty title={t("evidence.none")} /> : (
                  <div className="table-wrap"><table>
                    <thead><tr><th>{t("common.document")}</th><th>{t("common.category")}</th><th>{t("evidence.key")}</th><th>{t("common.status")}</th><th>{t("evidence.scan")}</th></tr></thead>
                    <tbody>{d.evidence.map((e: any) => (
                      <tr key={e.id}>
                        <td>{e.document.restricted ? <span className="muted">{t("evidence.restricted")}</span> : <Link to={`/wallet/${e.document.id}`}>{e.document.title}</Link>}</td>
                        <td>{en(e.document.category)}</td><td className="mono small">{e.evidence_key || "—"}</td>
                        <td><StatusBadge value={e.status} /></td><td><StatusBadge value={e.document.scan_status} /></td>
                      </tr>
                    ))}</tbody>
                  </table></div>
                )}
                <p className="small muted" style={{ marginTop: 8 }}>{t("evidence.consentNote")}</p>
              </Card>
            )}
            {tab === "messages" && <Messages caseId={id} access={d.access} />}
            {tab === "timeline" && <Timeline caseId={id} />}
            {tab === "meetings" && (
              <Card title={t("case.tab.meetings")}>
                {d.meetings.length === 0 ? <Empty title={t("meetings.none")} /> : (
                  <ul className="list">{d.meetings.map((m: any) => (
                    <li key={m.id} className="row-between"><span><Link to={`/meetings/${m.id}`}>{m.title}</Link><br /><span className="small muted">{fmtDateTime(m.scheduled_start, m.timezone)} ({m.timezone})</span></span><StatusBadge value={m.status} /></li>
                  ))}</ul>
                )}
              </Card>
            )}
          </div>
          <Card title={t("case.participants")} tight>
            <ul className="list">
              <li className="row-between"><span>{t("case.owner")}</span><span className="badge b-primary">{t("case.citizenControlled")}</span></li>
              {d.participants.map((p: any) => (
                <li key={p.id} className="row-between"><span>{p.tenant} <span className="xs muted">· {en(p.role)} · {t("case.via", { via: en(p.granted_via) })}</span></span><StatusBadge value={p.status} /></li>
              ))}
            </ul>
          </Card>
          {schedule && <ScheduleMeetingModal caseId={id} onClose={() => setSchedule(false)} />}
        </>
      )}
    </Q>
  );
}
