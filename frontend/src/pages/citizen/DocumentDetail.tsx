import { useEffect, useRef, useState, type MouseEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { Download, Eye, EyeOff, Languages, Scissors, Trash2, Upload } from "lucide-react";
import { api, downloadFile, objectUrl } from "../../lib/api";
import { useAction } from "../../lib/hooks";
import { useEnum, useI18n } from "../../lib/i18n";
import { Button, Card, Confirm, Dl, Field, Modal, Notice, PageHead, Q, StatusBadge, useApi } from "../../components/ui";
import { ACCEPT } from "./Wallet";

function Preview({ docId, v }: { docId: string; v: any }) {
  const { t } = useI18n();
  const [src, setSrc] = useState<{ url: string; type: string; text?: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    let made: string | null = null;
    objectUrl(`/api/documents/${docId}/versions/${v.version}/preview`)
      .then(async (r) => {
        made = r.url;
        if (r.type.startsWith("text/")) {
          const text = await (await fetch(r.url)).text();
          if (alive) setSrc({ ...r, text });
        } else if (alive) setSrc(r);
      })
      .catch((e) => alive && setErr(e.message));
    return () => {
      alive = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [docId, v.version]);
  if (err) return <Notice kind="warning">{err}</Notice>;
  if (!src) return <p className="muted">{t("common.loading")}</p>;
  if (src.text !== undefined) return <pre className="text-preview" dir="auto">{src.text}</pre>;
  if (src.type.startsWith("image/")) return <img className="preview-img" src={src.url} alt={t("doc.previewAlt")} />;
  // PDF only (the server allowlists and magic-checks it); Chrome's viewer cannot run inside a sandboxed frame.
  return <iframe className="preview-frame" title={t("doc.preview")} src={src.url} />;
}

function RedactModal({ doc, v, onClose }: { doc: any; v: any; onClose: () => void }) {
  const { t } = useI18n();
  const a = useAction();
  const [terms, setTerms] = useState("");
  const [regions, setRegions] = useState<number[][]>([]);
  const [img, setImg] = useState<string | null>(null);
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null);
  const [manual, setManual] = useState({ x: 0, y: 0, w: 30, h: 10 });
  const box = useRef<HTMLDivElement>(null);
  const isImage = v.mime.startsWith("image/");
  useEffect(() => {
    if (!isImage) return;
    let u: string | null = null;
    objectUrl(`/api/documents/${doc.id}/versions/${v.version}/preview`).then((r) => { u = r.url; setImg(r.url); });
    return () => { if (u) URL.revokeObjectURL(u); };
  }, [doc.id, v.version, isImage]);
  const pos = (e: MouseEvent) => {
    const r = box.current!.getBoundingClientRect();
    return { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) };
  };
  return (
    <Modal title={t("redact.title")} onClose={onClose} wide>
      <Notice kind="info">{isImage ? t("redact.imageNote") : v.mime === "application/pdf" ? t("redact.pdfNote") : t("redact.textNote")}</Notice>
      {isImage ? (
        <>
          <p className="small muted">{t("redact.drag")}</p>
          <div ref={box} style={{ position: "relative", display: "inline-block", cursor: "crosshair", userSelect: "none", maxWidth: "100%" }}
            onMouseDown={(e) => setDrag(pos(e))}
            onMouseUp={(e) => {
              if (!drag) return;
              const p = pos(e);
              const r = [Math.min(drag.x, p.x), Math.min(drag.y, p.y), Math.abs(p.x - drag.x), Math.abs(p.y - drag.y)];
              if (r[2] > 0.01 && r[3] > 0.01) setRegions([...regions, r]);
              setDrag(null);
            }}>
            {img && <img src={img} alt={t("doc.previewAlt")} style={{ maxWidth: "100%", display: "block" }} draggable={false} />}
            {regions.map((r, i) => <div key={i} style={{ position: "absolute", left: `${r[0] * 100}%`, top: `${r[1] * 100}%`, width: `${r[2] * 100}%`, height: `${r[3] * 100}%`, background: "#000" }} />)}
          </div>
          <fieldset style={{ marginTop: 12 }}><legend>{t("redact.manual")}</legend>
            <div className="row">
              {(["x", "y", "w", "h"] as const).map((k) => (
                <label key={k} className="small">{k.toUpperCase()} %<input className="input" style={{ width: 80 }} type="number" min={0} max={100} value={manual[k]} onChange={(e) => setManual({ ...manual, [k]: Number(e.target.value) })} /></label>
              ))}
              <Button size="sm" onClick={() => setRegions([...regions, [manual.x / 100, manual.y / 100, manual.w / 100, manual.h / 100]])}>{t("redact.addRegion")}</Button>
              {regions.length > 0 && <Button size="sm" variant="ghost" onClick={() => setRegions([])}>{t("redact.clear")}</Button>}
            </div>
          </fieldset>
        </>
      ) : (
        <Field label={t("redact.terms")} hint={t("redact.termsHint")}>{(id, d) => <textarea id={id} aria-describedby={d} className="textarea" value={terms} onChange={(e) => setTerms(e.target.value)} />}</Field>
      )}
      <div className="form-actions">
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" mutates busy={a.busy} disabled={isImage ? !regions.length : !terms.trim()} onClick={async () => {
          const r = await a.run(() => api.post(`/api/documents/${doc.id}/redact`, { version: v.version, terms: terms.split("\n").map((s) => s.trim()).filter(Boolean), regions }), { success: t("redact.done"), invalidate: [["doc", doc.id], ["docs"]] });
          if (r) onClose();
        }}><Scissors size={15} aria-hidden /> {t("redact.create")}</Button>
      </div>
    </Modal>
  );
}

function TranslateModal({ doc, v, onClose }: { doc: any; v: any; onClose: () => void }) {
  const { t } = useI18n();
  const nav = useNavigate();
  const a = useAction();
  const [target, setTarget] = useState(doc.language === "en" ? "de" : "en");
  return (
    <Modal title={t("translate.fromDoc")} onClose={onClose}>
      <p className="muted">{t("translate.fromDocSub", { lang: doc.language })}</p>
      <Field label={t("translate.target")}>{(id) => <select id={id} className="select" value={target} onChange={(e) => setTarget(e.target.value)}>
        {["en", "he", "de"].filter((l) => l !== doc.language).map((l) => <option key={l} value={l}>{t(`lang.${l}`)}</option>)}
      </select>}</Field>
      <Notice kind="warning">{t("translate.notCertified")}</Notice>
      <div className="form-actions">
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" mutates busy={a.busy} onClick={async () => {
          const r = await a.run(() => api.post("/api/translations", { document_id: doc.id, version: v.version, source_lang: doc.language, target_lang: target }), { invalidate: [["translations"]] });
          if (r) nav(`/translations/${r.id}`);
        }}><Languages size={15} aria-hidden /> {t("translate.start")}</Button>
      </div>
    </Modal>
  );
}

export function DocumentDetail() {
  const { id = "" } = useParams();
  const { t, fmtDate, fmtDateTime } = useI18n();
  const en = useEnum();
  const nav = useNavigate();
  const a = useAction();
  const q = useApi<any>(["doc", id], `/api/documents/${id}`, {
    refetchInterval: (query) => ((query.state.data as any)?.versions?.some((v: any) => v.scan_status === "pending") ? 3000 : false),
  });
  const [preview, setPreview] = useState<number | null>(null);
  const [redact, setRedact] = useState<any>(null);
  const [translate, setTranslate] = useState<any>(null);
  const [del, setDel] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  return (
    <Q q={q}>
      {(doc) => {
        const owner = doc.access_via === "owner";
        const cur = doc.versions.find((v: any) => v.version === doc.current_version);
        return (
          <>
            <PageHead title={doc.title} sub={<>{en(doc.category)} · <StatusBadge value={doc.verification_status} /> · {t("doc.accessVia", { via: en(doc.access_via) })}</>}
              actions={owner && <>
                <input ref={fileRef} type="file" accept={ACCEPT} hidden onChange={async (e) => {
                  const f = e.target.files?.[0];
                  if (!f) return;
                  const form = new FormData();
                  form.append("file", f);
                  await a.run(() => api.upload(`/api/documents/${id}/versions`, form), { success: t("doc.versionAdded"), invalidate: [["doc", id]] });
                  e.target.value = "";
                }} />
                <Button mutates onClick={() => fileRef.current?.click()}><Upload size={15} aria-hidden /> {t("doc.newVersion")}</Button>
                <Button variant="danger" mutates onClick={() => setDel(true)}><Trash2 size={15} aria-hidden /> {t("common.delete")}</Button>
              </>} />
            {!owner && <Notice kind="info">{t("doc.sharedNotice")}</Notice>}
            <div className="grid grid-2">
              <Card title={t("doc.details")}>
                <Dl items={[[t("wallet.issuer"), doc.issuer || "—"], [t("wallet.language"), t(`lang.${doc.language}`)], [t("doc.issued"), fmtDate(doc.issued_at)],
                  [t("wallet.expiry"), fmtDate(doc.expires_at)], [t("doc.created"), fmtDateTime(doc.created_at)], [t("doc.retention"), doc.retention_until ? fmtDate(doc.retention_until) : t("doc.retentionDefault")]]} />
                {doc.evidence_links?.length > 0 && <><hr /><h3>{t("doc.usedIn")}</h3><ul>{doc.evidence_links.map((l: any) => <li key={l.id}><Link to={`/cases/${l.case_id}`}>{t("doc.caseEvidence", { key: l.evidence_key || "—" })}</Link> <StatusBadge value={l.status} /></li>)}</ul></>}
                {owner && <div className="row" style={{ marginTop: 12 }}><Link to={`/wallet/${id}#receipts`} className="small" onClick={() => document.getElementById("receipts")?.scrollIntoView()}>{t("doc.receipts")}</Link></div>}
              </Card>
              <Card title={t("doc.versionsTitle")}>
                <ul className="list">
                  {[...doc.versions].reverse().map((v: any) => (
                    <li key={v.id}>
                      <div className="row-between">
                        <span><b>v{v.version}</b> <span className="mono small">{v.filename}</span> {v.kind === "redacted_derivative" && <span className="badge b-accent">{t("doc.redacted")}</span>}</span>
                        <StatusBadge value={v.scan_status} />
                      </div>
                      <div className="xs muted">{fmtDateTime(v.created_at)} · {(v.size / 1024).toFixed(1)} KB · sha256 {v.sha256.slice(0, 12)}…</div>
                      {v.note && <div className="xs">{v.note}</div>}
                      {v.scan_status !== "clean" && <div className="xs" style={{ color: "var(--warning)" }}>{v.scan_detail || t(`scan.${v.scan_status}`)}</div>}
                      <div className="row" style={{ marginTop: 6 }}>
                        <Button size="sm" disabled={!v.available} onClick={() => setPreview(preview === v.version ? null : v.version)}>{preview === v.version ? <EyeOff size={14} aria-hidden /> : <Eye size={14} aria-hidden />} {t("doc.preview")}</Button>
                        <Button size="sm" disabled={!v.available} onClick={() => a.run(() => downloadFile(`/api/documents/${id}/versions/${v.version}/download`, v.filename))}><Download size={14} aria-hidden /> {t("doc.download")}</Button>
                        {owner && v.available && v.kind === "original" && <Button size="sm" mutates onClick={() => setRedact(v)}><Scissors size={14} aria-hidden /> {t("redact.title")}</Button>}
                        {owner && v.available && v.version === doc.current_version && <Button size="sm" mutates onClick={() => setTranslate(v)}><Languages size={14} aria-hidden /> {t("translate.short")}</Button>}
                      </div>
                    </li>
                  ))}
                </ul>
              </Card>
            </div>
            {preview !== null && <Card title={t("doc.previewOf", { v: preview })}><Notice>{t("doc.previewSafe")}</Notice><Preview docId={id} v={doc.versions.find((x: any) => x.version === preview)} /></Card>}
            {cur?.available && doc.extracted_text_preview !== null && (
              <Card title={t("doc.extracted")}>
                {doc.extracted_text_preview ? <pre className="text-preview" dir="auto">{doc.extracted_text_preview}</pre> : <p className="muted">{t("doc.noText")}</p>}
              </Card>
            )}
            {owner && <Receipts id={id} />}
            {redact && <RedactModal doc={doc} v={redact} onClose={() => setRedact(null)} />}
            {translate && <TranslateModal doc={doc} v={translate} onClose={() => setTranslate(null)} />}
            {del && <Confirm title={t("doc.deleteTitle")} danger requireText="DELETE" confirmLabel={t("common.delete")} body={<p>{t("doc.deleteBody")}</p>}
              onCancel={() => setDel(false)} onConfirm={async () => { const r = await a.run(() => api.del(`/api/documents/${id}`), { success: t("doc.deleted"), invalidate: [["docs"]] }); if (r) nav("/wallet"); }} />}
          </>
        );
      }}
    </Q>
  );
}

function Receipts({ id }: { id: string }) {
  const { t, fmtDateTime } = useI18n();
  const en = useEnum();
  const q = useApi<any>(["receipts", id], `/api/documents/${id}/receipts`);
  return (
    <Card title={t("doc.receipts")}>
      <span id="receipts" />
      <Q q={q}>{(d) => d.items.length === 0 ? <p className="muted">{t("receipts.none")}</p> : (
        <div className="table-wrap"><table><thead><tr><th>{t("receipts.when")}</th><th>{t("receipts.who")}</th><th>{t("receipts.action")}</th><th>{t("receipts.basis")}</th></tr></thead>
          <tbody>{d.items.map((r: any) => <tr key={r.id}><td>{fmtDateTime(r.at)}</td><td>{r.accessed_by}<div className="xs muted">{r.organisation}</div></td><td>{en(r.action)}</td><td>{r.consent_grant_id ? t("receipts.consent") : t("receipts.delegation")}</td></tr>)}</tbody></table></div>
      )}</Q>
    </Card>
  );
}
