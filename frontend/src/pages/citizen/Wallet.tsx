import { useRef, useState } from "react";
import { Link } from "react-router";
import { FileStack, Upload } from "lucide-react";
import { api } from "../../lib/api";
import { useAction } from "../../lib/hooks";
import { useEnum, useI18n } from "../../lib/i18n";
import { Button, Card, Empty, Field, Modal, Notice, PageHead, Q, StatusBadge, useApi } from "../../components/ui";

export const ACCEPT = ".pdf,.png,.jpg,.jpeg,.txt";

export function UploadModal({ onClose, onBehalfOf }: { onClose: () => void; onBehalfOf?: string }) {
  const { t, locale } = useI18n();
  const en = useEnum();
  const a = useAction();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [f, setF] = useState({ title: "", category: "identity", issuer: "", expires_at: "", language: locale });
  const cats = ["identity", "civil_status", "employment", "education", "financial", "housing", "health", "other"];
  const tooBig = file && file.size > 15 * 1024 * 1024;
  return (
    <Modal title={t("wallet.upload")} onClose={onClose}>
      <Field label={t("wallet.file")} hint={t("wallet.fileHint")} error={tooBig ? t("wallet.tooBig") : undefined}>
        {(id, d) => <input id={id} aria-describedby={d} ref={fileRef} className="input" type="file" accept={ACCEPT} onChange={(e) => {
          const fl = e.target.files?.[0] || null;
          setFile(fl);
          if (fl && !f.title) setF({ ...f, title: fl.name.replace(/\.[^.]+$/, "") });
        }} />}
      </Field>
      <Field label={t("common.title")}>{(id) => <input id={id} className="input" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />}</Field>
      <div className="grid grid-2" style={{ gap: 12 }}>
        <Field label={t("common.category")}>{(id) => <select id={id} className="select" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>{cats.map((c) => <option key={c} value={c}>{en(c)}</option>)}</select>}</Field>
        <Field label={t("wallet.language")}>{(id) => <select id={id} className="select" value={f.language} onChange={(e) => setF({ ...f, language: e.target.value as any })}><option value="en">English</option><option value="he">עברית</option><option value="de">Deutsch</option></select>}</Field>
        <Field label={t("wallet.issuer")}>{(id) => <input id={id} className="input" value={f.issuer} onChange={(e) => setF({ ...f, issuer: e.target.value })} />}</Field>
        <Field label={t("wallet.expiry")}>{(id) => <input id={id} className="input" type="date" value={f.expires_at} onChange={(e) => setF({ ...f, expires_at: e.target.value })} />}</Field>
      </div>
      <Notice kind="info">{t("wallet.scanNote")}</Notice>
      <div className="form-actions">
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" mutates busy={a.busy} disabled={!file || !!tooBig || f.title.trim().length < 2} onClick={async () => {
          const form = new FormData();
          form.append("file", file!);
          form.append("title", f.title.trim());
          form.append("category", f.category);
          form.append("issuer", f.issuer);
          form.append("language", f.language);
          if (f.expires_at) form.append("expires_at", `${f.expires_at}T00:00:00+00:00`);
          if (onBehalfOf) form.append("on_behalf_of", onBehalfOf);
          const r = await a.run(() => api.upload("/api/documents", form), { success: t("wallet.uploaded"), invalidate: [["docs"]] });
          if (r) onClose();
        }}><Upload size={15} aria-hidden /> {t("wallet.uploadBtn")}</Button>
      </div>
    </Modal>
  );
}

export function Wallet() {
  const { t, fmtDate } = useI18n();
  const en = useEnum();
  const [cat, setCat] = useState("");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const q = useApi<any>(["docs", cat, search], `/api/documents?category=${cat}&q=${encodeURIComponent(search)}`, {
    refetchInterval: (query) => ((query.state.data as any)?.items?.some((d: any) => d.versions.some((v: any) => v.scan_status === "pending")) ? 3000 : false),
  });
  return (
    <>
      <PageHead title={t("wallet.title")} sub={t("wallet.sub")} actions={<Button variant="primary" mutates onClick={() => setOpen(true)}><Upload size={15} aria-hidden /> {t("wallet.upload")}</Button>} />
      <Notice kind="info">{t("wallet.notIdentity")}</Notice>
      <Card>
        <div className="row" style={{ marginBottom: 12 }}>
          <label className="sr-only" htmlFor="wq">{t("common.search")}</label>
          <input id="wq" className="input" style={{ maxWidth: 260 }} placeholder={t("common.search")} value={search} onChange={(e) => setSearch(e.target.value)} />
          <label className="sr-only" htmlFor="wc">{t("common.category")}</label>
          <select id="wc" className="select" style={{ width: "auto" }} value={cat} onChange={(e) => setCat(e.target.value)}>
            <option value="">{t("common.allCategories")}</option>
            {["identity", "civil_status", "employment", "education", "financial", "housing", "health", "other"].map((c) => <option key={c} value={c}>{en(c)}</option>)}
          </select>
        </div>
        <Q q={q}>
          {(d) => d.items.length === 0 ? <Empty title={t("wallet.none")} icon={<FileStack size={32} />} /> : (
            <div className="table-wrap"><table>
              <thead><tr><th>{t("common.title")}</th><th>{t("common.category")}</th><th>{t("wallet.versions")}</th><th>{t("evidence.scan")}</th><th>{t("wallet.verification")}</th><th>{t("wallet.expiry")}</th></tr></thead>
              <tbody>{d.items.map((doc: any) => {
                const cur = doc.versions.find((v: any) => v.version === doc.current_version) || doc.versions.at(-1);
                const expiring = doc.expires_at && new Date(doc.expires_at).getTime() - Date.now() < 120 * 86400000;
                return (
                  <tr key={doc.id}>
                    <td><Link to={`/wallet/${doc.id}`}>{doc.title}</Link></td>
                    <td>{en(doc.category)}</td><td>{doc.current_version}</td>
                    <td><StatusBadge value={cur?.scan_status} /></td>
                    <td><StatusBadge value={doc.verification_status} /></td>
                    <td>{doc.expires_at ? <span className={expiring ? "badge b-warning" : ""}>{fmtDate(doc.expires_at)}</span> : "—"}</td>
                  </tr>
                );
              })}</tbody>
            </table></div>
          )}
        </Q>
      </Card>
      {open && <UploadModal onClose={() => setOpen(false)} />}
    </>
  );
}
