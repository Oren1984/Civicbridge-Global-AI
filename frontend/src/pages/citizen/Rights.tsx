import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { AlertTriangle, BookMarked, CheckCircle2, HelpCircle, Scale, XCircle } from "lucide-react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useAction } from "../../lib/hooks";
import { useEnum, useI18n } from "../../lib/i18n";
import { Button, Card, Empty, Field, Notice, PageHead, Q, StatusBadge, SyntheticBadge, Tabs, useApi } from "../../components/ui";
import { QuestionInput } from "./Journeys";

function Citation({ c }: { c: any }) {
  const { t, fmtDate } = useI18n();
  const src = c.source || c;
  return (
    <blockquote className="card card-tight" style={{ margin: "8px 0", background: "var(--surface-2)" }}>
      <div className="row-between">
        <b><BookMarked size={14} aria-hidden /> {c.ref ? `[${c.ref}] ` : ""}{src.title} <span className="mono xs">{c.anchor}</span></b>
        <span className="row">
          {src.is_placeholder && <span className="badge b-synthetic">{t("rights.placeholder")}</span>}
          {(c.stale || (src.review_date && new Date(src.review_date) < new Date())) && <span className="badge b-warning">{t("rights.stale")}</span>}
        </span>
      </div>
      {c.passage && <p className="small" style={{ margin: "6px 0" }}>{c.passage}</p>}
      <div className="xs muted">{src.publisher} · {src.jurisdiction} · {t("rights.reviewDate", { date: fmtDate(src.review_date) })}{src.effective_from && ` · ${t("rights.effective", { date: fmtDate(src.effective_from) })}`} · {src.url ? <a href={src.url} rel="noreferrer" target="_blank">{t("rights.source")}</a> : t("rights.noUrl")}</div>
    </blockquote>
  );
}

const IND: Record<string, { icon: any; kind: "success" | "warning" | "danger" }> = {
  likely_applicable: { icon: CheckCircle2, kind: "success" },
  likely_not_applicable: { icon: XCircle, kind: "warning" },
  insufficient_information: { icon: HelpCircle, kind: "warning" },
};

function Screening() {
  const { t, locale } = useI18n();
  const en = useEnum();
  const nav = useNavigate();
  const { me } = useAuth();
  const sets = useApi<any>(["rulesets"], "/api/rights/rulesets");
  const history = useApi<any>(["screenings"], "/api/rights/screenings");
  const a = useAction();
  const [code, setCode] = useState("");
  const [answers, setAnswers] = useState<Record<string, any>>({});
  const [res, setRes] = useState<any>(null);
  const rs = sets.data?.items.find((x: any) => x.code === code);
  const citizen = me?.active?.workspace === "citizen";
  return (
    <div className="grid grid-2">
      <Card title={t("rights.screenTitle")}>
        <Q q={sets}>
          {(d) => (
            <>
              <Field label={t("rights.topic")}>{(id) => (
                <select id={id} className="select" value={code} onChange={(e) => { setCode(e.target.value); setAnswers({}); setRes(null); }}>
                  <option value="">{t("common.choose")}</option>
                  {d.items.map((x: any) => <option key={x.code} value={x.code}>{x.jurisdiction} · {x.name}</option>)}
                </select>
              )}</Field>
              {rs?.current_version && (
                <>
                  <div className="chip-row" style={{ marginBottom: 12 }}>
                    <span className="badge">{t("rights.version", { v: rs.current_version.version })}</span>
                    <StatusBadge value={rs.current_version.review_status} />
                    <SyntheticBadge />
                    {rs.consequential && <span className="badge b-warning">{t("rights.consequential")}</span>}
                  </div>
                  <p className="xs muted">{rs.authority} · {t("rights.effective", { date: rs.current_version.effective_from })}</p>
                  {rs.current_version.questions.map((q: any) => <QuestionInput key={q.id} q={q} value={answers[q.id]} onChange={(v) => setAnswers({ ...answers, [q.id]: v })} />)}
                  <Button variant="primary" mutates busy={a.busy} onClick={async () => {
                    const r = await a.run(() => api.post("/api/rights/screen", { rule_set_code: code, answers }), { invalidate: [["screenings"]] });
                    if (r) setRes(r);
                  }}><Scale size={15} aria-hidden /> {t("rights.screen")}</Button>
                </>
              )}
            </>
          )}
        </Q>
      </Card>
      <div>
        {res ? (
          <Card title={t("rights.result")}>
            {(() => { const I = IND[res.indication]; return <Notice kind={I.kind} title={en(res.indication)}>{res.indication_text}</Notice>; })()}
            <Notice kind="synthetic">{res.disclaimer}</Notice>
            <h3>{t("rights.why")}</h3>
            <ul className="explain">
              {res.explanation.map((e: any, i: number) => (
                <li key={i}>{e.result === "met" ? "✓" : e.result === "not_met" ? "✗" : "?"} {e.explain || e.question} <span className="xs muted">({en(e.result)})</span></li>
              ))}
            </ul>
            {res.missing.length > 0 && <Notice kind="warning" title={t("rights.missing")}>{res.missing.map((m: string) => rs?.current_version.questions.find((q: any) => q.id === m)?.label?.[locale] || m).join("; ")}</Notice>}
            {res.uncertainty.length > 0 && (
              <><h3><AlertTriangle size={16} aria-hidden /> {t("rights.uncertainty")}</h3><ul className="small">{res.uncertainty.map((u: any, i: number) => <li key={i}>{u.message}</li>)}</ul></>
            )}
            <h3>{t("rights.sources")}</h3>
            {res.citations.length ? res.citations.map((c: any, i: number) => <Citation key={i} c={c} />) : <p className="muted">{t("rights.noSources")}</p>}
            {res.required_evidence?.length > 0 && <><h3>{t("rights.evidence")}</h3><ul>{res.required_evidence.map((e: any) => <li key={e.key}>{e.label} <span className="xs muted">({en(e.category)})</span></li>)}</ul></>}
            {res.appeal_guidance && <><h3>{t("rights.appeal")}</h3><p className="small">{res.appeal_guidance}</p></>}
            <p className="xs muted">{t("rights.ruleMeta", { rule: res.rule.rule_set, v: res.rule.version, pack: res.rule.pack_version, jur: res.rule.jurisdiction })}</p>
            {citizen && res.requires_human_review && (
              <Button variant="primary" mutates busy={a.busy} onClick={async () => {
                const r = await a.run(() => api.post(`/api/rights/screenings/${res.screening_id}/request-review`, { note: "" }), { success: t("rights.reviewRequested"), invalidate: [["cases"], ["screenings"]] });
                if (r) nav(`/cases/${r.case_id}`);
              }}>{t("rights.requestReview")}</Button>
            )}
          </Card>
        ) : (
          <Card title={t("rights.history")}>
            <Q q={history}>
              {(d) => d.items.length === 0 ? <Empty title={t("rights.noHistory")} /> : (
                <ul className="list">{d.items.map((s: any) => (
                  <li key={s.id} className="row-between">
                    <span>{s.rule_name} <span className="xs muted">v{s.version}</span>{s.case_id && <> · <Link to={`/cases/${s.case_id}`}>{t("rights.reviewCase")}</Link></>}</span>
                    <StatusBadge value={s.indication} />
                  </li>
                ))}</ul>
              )}
            </Q>
          </Card>
        )}
      </div>
    </div>
  );
}

function Ask() {
  const { t } = useI18n();
  const { me } = useAuth();
  const a = useAction();
  const [question, setQuestion] = useState("");
  const [jur, setJur] = useState<string[]>([]);
  const [mine, setMine] = useState(false);
  const [res, setRes] = useState<any>(null);
  const codes = ["IL", "IL-TA-TLV", "DE", "DE-BE-BER", "US", "US-CA", "US-CA-SF"];
  return (
    <div className="grid grid-2">
      <Card title={t("rights.askTitle")}>
        <p className="small muted">{t("rights.askSub")}</p>
        <Field label={t("rights.question")}>{(id) => <textarea id={id} className="textarea" value={question} onChange={(e) => setQuestion(e.target.value)} />}</Field>
        <fieldset><legend>{t("rights.jurisdictions")}</legend>
          <div className="chip-row">{codes.map((c) => <label key={c} className="check"><input type="checkbox" checked={jur.includes(c)} onChange={() => setJur(jur.includes(c) ? jur.filter((x) => x !== c) : [...jur, c])} /> {c}</label>)}</div>
        </fieldset>
        {me?.active?.workspace === "citizen" && <label className="check"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> {t("rights.includeMine")}</label>}
        <Button variant="primary" mutates busy={a.busy} disabled={question.trim().length < 3} onClick={async () => {
          const r = await a.run(() => api.post("/api/rights/ask", { question, jurisdictions: jur, include_my_documents: mine }));
          if (r) setRes(r);
        }}>{t("rights.ask")}</Button>
      </Card>
      <div>
        {res && (
          <Card title={res.status === "answered" ? t("rights.answer") : t("rights.abstained")}>
            <div className="chip-row" style={{ marginBottom: 8 }}><span className="badge b-synthetic">{t("rights.mode", { mode: res.mode })}</span><span className="badge">{res.retrieval}</span></div>
            {res.status === "answered" ? (
              <>
                <p>{res.answer}</p>
                <p className="xs muted">{res.answer_kind === "extractive_quote" ? t("rights.extractive") : t("rights.generated")}</p>
                {res.warnings.map((w: string, i: number) => <Notice key={i} kind="warning">{w}</Notice>)}
                <h3>{t("rights.sources")}</h3>
                {res.citations.map((c: any) => <Citation key={c.passage_id} c={c} />)}
                <p className="xs muted">{res.disclaimer}</p>
              </>
            ) : (
              <>
                <Notice kind="warning">{res.reason}</Notice>
                {res.candidates?.length > 0 && <><h3>{t("rights.candidates")}</h3>{res.candidates.map((c: any) => <Citation key={c.passage_id} c={{ ...c, passage: c.text }} />)}</>}
              </>
            )}
            {res.personal_document_hits?.length > 0 && (
              <>
                <h3>{t("rights.myDocs")}</h3>
                {res.personal_document_hits.map((h: any) => (
                  <div key={h.document_id + h.chunk} className="card card-tight" style={{ background: "var(--surface-2)" }}>
                    <b><Link to={`/wallet/${h.document_id}`}>{h.document_title}</Link></b>
                    {h.untrusted_instruction_like_text && <Notice kind="warning">{t("rights.injection")}</Notice>}
                    <p className="small" dir="auto">{h.text.slice(0, 300)}</p>
                  </div>
                ))}
              </>
            )}
          </Card>
        )}
      </div>
    </div>
  );
}

export function Rights() {
  const { t } = useI18n();
  const [tab, setTab] = useState<"screen" | "ask">("screen");
  return (
    <>
      <PageHead title={t("rights.title")} sub={t("rights.sub")} />
      <Notice kind="synthetic">{t("rights.disclaimer")}</Notice>
      <Tabs label={t("rights.title")} value={tab} onChange={setTab} tabs={[{ id: "screen", label: t("rights.tabScreen") }, { id: "ask", label: t("rights.tabAsk") }]} />
      {tab === "screen" ? <Screening /> : <Ask />}
    </>
  );
}
