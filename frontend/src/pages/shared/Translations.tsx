import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { Languages } from "lucide-react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useAction } from "../../lib/hooks";
import { useEnum, useI18n } from "../../lib/i18n";
import { Button, Card, Empty, Field, Notice, PageHead, Q, StatusBadge, useApi } from "../../components/ui";

const DIR: Record<string, "rtl" | "ltr"> = { he: "rtl", en: "ltr", de: "ltr" };

export function Translations() {
  const { t, fmtDateTime } = useI18n();
  const { me } = useAuth();
  const nav = useNavigate();
  const a = useAction();
  const q = useApi<any>(["translations"], "/api/translations");
  const [text, setText] = useState("");
  const [src, setSrc] = useState("de");
  const [tgt, setTgt] = useState("en");
  const citizen = me?.active?.workspace === "citizen";
  return (
    <>
      <PageHead title={t("translate.title")} sub={t("translate.sub")} />
      <Notice kind="warning">{t("translate.notCertified")}</Notice>
      <div className="grid grid-2">
        {citizen && (
          <Card title={t("translate.newText")}>
            <div className="row">
              <Field label={t("translate.source")}>{(id) => <select id={id} className="select" value={src} onChange={(e) => setSrc(e.target.value)}>{["en", "he", "de"].map((l) => <option key={l} value={l}>{t(`lang.${l}`)}</option>)}</select>}</Field>
              <Field label={t("translate.target")}>{(id) => <select id={id} className="select" value={tgt} onChange={(e) => setTgt(e.target.value)}>{["en", "he", "de"].map((l) => <option key={l} value={l}>{t(`lang.${l}`)}</option>)}</select>}</Field>
            </div>
            <Field label={t("translate.text")} hint={t("translate.textHint")}>{(id, d) => <textarea id={id} aria-describedby={d} className="textarea" dir={DIR[src]} value={text} onChange={(e) => setText(e.target.value)} />}</Field>
            <Button variant="primary" mutates busy={a.busy} disabled={!text.trim() || src === tgt} onClick={async () => {
              const r = await a.run(() => api.post("/api/translations", { text, source_lang: src, target_lang: tgt }), { invalidate: [["translations"]] });
              if (r) nav(`/translations/${r.id}`);
            }}><Languages size={15} aria-hidden /> {t("translate.start")}</Button>
            <p className="xs muted" style={{ marginTop: 8 }}>{t("translate.fromWallet")} <Link to="/wallet">{t("nav.wallet")}</Link></p>
          </Card>
        )}
        <Card title={citizen ? t("translate.mine") : t("translate.toReview")}>
          <Q q={q}>
            {(d) => d.items.length === 0 ? <Empty title={t("translate.none")} /> : (
              <ul className="list">{d.items.map((x: any) => (
                <li key={x.id} className="row-between">
                  <span><Link to={`/translations/${x.id}`}>{t(`lang.${x.source_lang}`)} → {t(`lang.${x.target_lang}`)}</Link><br /><span className="xs muted">{fmtDateTime(x.created_at)} · {x.mode}</span></span>
                  <StatusBadge value={x.status} />
                </li>
              ))}</ul>
            )}
          </Q>
        </Card>
      </div>
    </>
  );
}

export function TranslationDetail() {
  const { id = "" } = useParams();
  const { t, fmtDateTime } = useI18n();
  const en = useEnum();
  const a = useAction();
  const q = useApi<any>(["translation", id], `/api/translations/${id}`);
  const [target, setTarget] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => {
    if (q.data) setTarget(q.data.segments.map((s: any) => s.target || "").join("\n"));
  }, [q.data]);
  return (
    <Q q={q}>
      {(tr) => (
        <>
          <PageHead title={t("translate.review")} sub={<>{tr.document_title || t("translate.freeText")} · {t(`lang.${tr.source_lang}`)} → {t(`lang.${tr.target_lang}`)} · <StatusBadge value={tr.status} /></>} />
          <div className="chip-row" style={{ marginBottom: 12 }}>
            <span className="badge b-synthetic">{t("translate.modeLabel", { mode: tr.mode })}</span>
            <span className="badge b-danger">{t("translate.notCertifiedShort")}</span>
            {tr.uncertainty.map((u: string) => <span key={u} className="badge b-warning">{en(u)}</span>)}
          </div>
          {tr.mode.startsWith("mock") && <Notice kind="synthetic">{t("translate.mockNote")}</Notice>}
          {tr.mode === "manual" && <Notice kind="info">{t("translate.manualNote")}</Notice>}
          <Card title={t("translate.sideBySide")}>
            <div className="split" role="table" aria-label={t("translate.sideBySide")}>
              <div role="rowgroup"><h3>{t("translate.original")} ({t(`lang.${tr.source_lang}`)})</h3>
                {tr.segments.map((s: any, i: number) => <div key={i} className="seg" dir={DIR[tr.source_lang]} role="cell">{s.source}</div>)}
              </div>
              <div role="rowgroup"><h3>{t("translate.assisted")} ({t(`lang.${tr.target_lang}`)})</h3>
                {tr.segments.map((s: any, i: number) => (
                  <div key={i} className={`seg ${s.target ? "" : "untranslated"}`} dir={DIR[tr.target_lang]} role="cell">
                    {s.target || <em>{t("translate.untranslated")}</em>}
                    {s.flags?.length > 0 && <div className="xs muted">{s.flags.map((f: string) => en(f)).join(", ")}</div>}
                  </div>
                ))}
              </div>
            </div>
          </Card>
          <Card title={t("translate.humanReview")}>
            <Field label={t("translate.finalText")} hint={t("translate.finalHint")}>{(i, d) => <textarea id={i} aria-describedby={d} className="textarea" dir={DIR[tr.target_lang]} style={{ minHeight: 160 }} value={target} onChange={(e) => setTarget(e.target.value)} />}</Field>
            <Field label={t("translate.note")}>{(i) => <input id={i} className="input" value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
            {tr.reviewed_at && <p className="small muted">{t("translate.reviewedAt", { at: fmtDateTime(tr.reviewed_at) })} {tr.review_note && `— ${tr.review_note}`}</p>}
            <div className="row">
              <Button variant="primary" mutates busy={a.busy} disabled={!target.trim()} onClick={() => a.run(() => api.post(`/api/translations/${id}/review`, { status: "reviewed", target_text: target, note }), { success: t("translate.markedReviewed"), invalidate: [["translation", id], ["translations"]] })}>{t("translate.markReviewed")}</Button>
              <Button mutates onClick={() => a.run(() => api.post(`/api/translations/${id}/review`, { status: "rejected", note }), { success: t("translate.markedRejected"), invalidate: [["translation", id]] })}>{t("translate.reject")}</Button>
            </div>
          </Card>
        </>
      )}
    </Q>
  );
}
