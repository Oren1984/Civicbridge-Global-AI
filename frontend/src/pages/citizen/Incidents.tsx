import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Camera, MapPin, Mic, Square, Wand2 } from "lucide-react";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useAction } from "../../lib/hooks";
import { outbox, randomKey, refCache, useOnline } from "../../lib/offline";
import { usePrefs } from "../../lib/prefs";
import { useEnum, useI18n } from "../../lib/i18n";
import { Button, Card, Empty, Field, Modal, Notice, PageHead, Pagination, Q, StatusBadge, useApi } from "../../components/ui";

function VoiceRecorder({ onDone }: { onDone: (f: File) => void }) {
  const { t } = useI18n();
  const [rec, setRec] = useState<MediaRecorder | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const chunks = useRef<Blob[]>([]);
  const start = async () => {
    setErr(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream, { mimeType: MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "" });
      chunks.current = [];
      mr.ondataavailable = (e) => chunks.current.push(e.data);
      mr.onstop = () => {
        stream.getTracks().forEach((tr) => tr.stop());
        onDone(new File(chunks.current, "voice-note.webm", { type: "audio/webm" }));
      };
      mr.start();
      setRec(mr);
    } catch {
      setErr(t("incidents.micError"));
    }
  };
  return (
    <div>
      {rec ? <Button onClick={() => { rec.stop(); setRec(null); }}><Square size={14} aria-hidden /> {t("incidents.stopRecording")}</Button>
        : <Button onClick={start}><Mic size={14} aria-hidden /> {t("incidents.recordVoice")}</Button>}
      {err && <div className="small" style={{ color: "var(--danger)" }}>{err}</div>}
    </div>
  );
}

/** Municipalities and categories, cached per user so the report form still opens without a connection. */
function useMunicipalities() {
  const { me } = useAuth();
  const muni = useApi<any>(["municipalities"], "/api/incidents/municipalities", { initialData: () => refCache.get(me?.user.id, "municipalities"), initialDataUpdatedAt: 0 });
  useEffect(() => {
    if (muni.data) refCache.set(me?.user.id, "municipalities", muni.data);
  }, [muni.data, me?.user.id]);
  return muni;
}

export function ReportForm({ onClose, draft }: { onClose: () => void; draft?: any }) {
  const { t } = useI18n();
  const en = useEnum();
  const { me } = useAuth();
  const { toast } = usePrefs();
  const online = useOnline();
  const nav = useNavigate();
  const a = useAction();
  const muni = useMunicipalities();
  const [f, setF] = useState<any>(draft?.payload || { tenant_id: "", description: "", category: "", location_text: "", lat: null, lon: null });
  const [draftKey] = useState<string>(draft?.draft_key || `incident-${randomKey().slice(0, 12)}`);
  const [files, setFiles] = useState<File[]>([]);
  const [suggest, setSuggest] = useState<any>(null);
  const [locErr, setLocErr] = useState<string | null>(null);
  useEffect(() => {
    if (!f.tenant_id && muni.data?.items?.length) setF((x: any) => ({ ...x, tenant_id: muni.data.items[0].id }));
  }, [muni.data, f.tenant_id]);
  const locate = () => {
    setLocErr(null);
    navigator.geolocation?.getCurrentPosition(
      // Minimised on the device too: only ~110 m precision ever leaves the browser.
      (p) => setF({ ...f, lat: Math.round(p.coords.latitude * 1000) / 1000, lon: Math.round(p.coords.longitude * 1000) / 1000 }),
      () => setLocErr(t("incidents.locError")),
      { enableHighAccuracy: false, timeout: 8000 },
    );
  };
  const queueOffline = () => {
    if (!me) return;
    outbox.add(me.user.id, { op: "upsert_draft", draft_key: draftKey, kind: "incident_report", title: f.description.slice(0, 60), payload: f });
    outbox.add(me.user.id, { op: "submit_incident", draft_key: draftKey, payload: f });
    toast(t("incidents.queued"), "info");
    onClose();
  };
  const submit = async () => {
    if (!online) return queueOffline();
    try {
      const inc = await api.post("/api/incidents", { ...f, category: f.category || null, draft_key: draftKey });
      for (const file of files) {
        const form = new FormData();
        form.append("file", file);
        await api.upload(`/api/incidents/${inc.id}/media`, form);
      }
      toast(t("incidents.submitted", { ref: inc.reference }));
      onClose();
      nav(`/incidents/${inc.id}`);
    } catch (e) {
      if (e instanceof ApiError && e.network) return queueOffline();
      toast((e as ApiError).message, "error");
    }
  };
  const valid = f.tenant_id && f.description.trim().length >= 10;
  return (
    <Modal title={t("incidents.report")} onClose={onClose} wide>
      {!online && <Notice kind="warning">{t("incidents.offlineNote")}</Notice>}
      <Notice kind="info">{t("incidents.notEmergency")}</Notice>
      <Q q={muni}>
        {(d) => (
          <>
            <Field label={t("incidents.municipality")}>{(id) => <select id={id} className="select" value={f.tenant_id} onChange={(e) => setF({ ...f, tenant_id: e.target.value })}>{d.items.map((m: any) => <option key={m.id} value={m.id}>{m.name}</option>)}</select>}</Field>
            <Field label={t("incidents.description")} hint={t("incidents.descHint")} error={f.description && f.description.trim().length < 10 ? t("validation.min10") : undefined}>
              {(id, h) => <textarea id={id} aria-describedby={h} className="textarea" dir="auto" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />}
            </Field>
            <div className="row" style={{ alignItems: "flex-end" }}>
              <div style={{ flex: 1, minWidth: 200 }}>
                <Field label={t("common.category")} hint={t("incidents.catHint")}>{(id, h) => <select id={id} aria-describedby={h} className="select" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>
                  <option value="">{t("incidents.autoCategory")}</option>{d.categories.map((c: string) => <option key={c} value={c}>{en(c)}</option>)}</select>}</Field>
              </div>
              <Button disabled={f.description.length < 3 || !online} onClick={async () => {
                const r = await a.run(() => api.post("/api/incidents/classify", { description: f.description }), { silent: true });
                if (r) setSuggest(r);
              }} style={{ marginBottom: 16 }}><Wand2 size={14} aria-hidden /> {t("incidents.suggest")}</Button>
            </div>
            {suggest && (
              <Notice kind="synthetic">
                {suggest.category === "other" ? suggest.label : <>{t("incidents.suggested", { cat: en(suggest.category) })} — {suggest.label} <Button size="sm" onClick={() => setF({ ...f, category: suggest.category })}>{t("incidents.useSuggestion")}</Button></>}
              </Notice>
            )}
            <fieldset><legend>{t("incidents.location")}</legend>
              <p className="xs muted">{t("incidents.locNote")}</p>
              <div className="row">
                <Button size="sm" onClick={locate}><MapPin size={14} aria-hidden /> {t("incidents.useLocation")}</Button>
                {f.lat != null && <span className="badge b-info">{f.lat}, {f.lon} (≈110 m)</span>}
                {f.lat != null && <Button size="sm" variant="ghost" onClick={() => setF({ ...f, lat: null, lon: null })}>{t("common.remove")}</Button>}
              </div>
              {locErr && <p className="small" style={{ color: "var(--danger)" }}>{locErr}</p>}
              <Field label={t("incidents.landmark")}>{(id) => <input id={id} className="input" value={f.location_text} onChange={(e) => setF({ ...f, location_text: e.target.value })} />}</Field>
            </fieldset>
            <fieldset><legend>{t("incidents.attachments")}</legend>
              {!online ? <p className="small muted">{t("incidents.mediaOnline")}</p> : (
                <>
                  <div className="row">
                    <label className="btn btn-sm"><Camera size={14} aria-hidden /> {t("incidents.addPhoto")}
                      <input type="file" accept="image/png,image/jpeg" hidden onChange={(e) => e.target.files?.[0] && setFiles([...files, e.target.files[0]])} />
                    </label>
                    <label className="btn btn-sm">{t("incidents.addAudio")}<input type="file" accept="audio/*" hidden onChange={(e) => e.target.files?.[0] && setFiles([...files, e.target.files[0]])} /></label>
                    <VoiceRecorder onDone={(fl) => setFiles([...files, fl])} />
                  </div>
                  {files.length > 0 && <ul className="small">{files.map((fl, i) => <li key={i}>{fl.name} ({Math.round(fl.size / 1024)} KB) <button className="btn btn-sm btn-ghost" onClick={() => setFiles(files.filter((_, j) => j !== i))}>{t("common.remove")}</button></li>)}</ul>}
                  <p className="xs muted">{t("incidents.mediaNote")}</p>
                </>
              )}
            </fieldset>
          </>
        )}
      </Q>
      <div className="form-actions">
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        {me && <Button mutates onClick={() => { outbox.add(me.user.id, { op: "upsert_draft", draft_key: draftKey, kind: "incident_report", title: f.description.slice(0, 60), payload: f }); toast(t("incidents.draftSaved"), "info"); if (online) outbox.flush(me.user.id).catch(() => undefined); onClose(); }}>{t("incidents.saveDraft")}</Button>}
        <Button variant="primary" mutates disabled={!valid} onClick={submit}>{online ? t("incidents.submit") : t("incidents.queue")}</Button>
      </div>
    </Modal>
  );
}

export function Incidents() {
  const { t, fmtDate } = useI18n();
  const en = useEnum();
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState(1);
  useMunicipalities();
  const q = useApi<any>(["incidents", page], `/api/incidents?page=${page}&page_size=15`);
  const open = params.get("new") === "1";
  return (
    <>
      <PageHead title={t("incidents.title")} sub={t("incidents.sub")} actions={<Button variant="primary" mutates onClick={() => setParams({ new: "1" })}>{t("incidents.report")}</Button>} />
      <Card>
        <Q q={q}>
          {(d) => d.items.length === 0 ? <Empty title={t("incidents.none")} /> : (
            <>
              <div className="table-wrap"><table>
                <thead><tr><th>{t("common.reference")}</th><th>{t("common.category")}</th><th>{t("incidents.municipality")}</th><th>{t("common.status")}</th><th>{t("common.created")}</th></tr></thead>
                <tbody>{d.items.map((i: any) => (
                  <tr key={i.id}><td><Link to={`/incidents/${i.id}`} className="mono">{i.reference}</Link></td><td>{en(i.category)}</td><td>{i.municipality}</td><td><StatusBadge value={i.status} /></td><td>{fmtDate(i.created_at)}</td></tr>
                ))}</tbody>
              </table></div>
              <Pagination meta={d.meta} onPage={setPage} />
            </>
          )}
        </Q>
      </Card>
      {open && <ReportForm onClose={() => setParams({})} />}
    </>
  );
}
