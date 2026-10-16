import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { ShieldCheck } from "lucide-react";
import { api } from "../../lib/api";
import { useAction } from "../../lib/hooks";
import { useEnum, useI18n } from "../../lib/i18n";
import { Button, Card, Confirm, Empty, Field, Modal, Notice, PageHead, Q, StatusBadge, Tabs, useApi } from "../../components/ui";

export interface ConsentPreset {
  recipient_tenant_id?: string;
  case_id?: string;
  purpose?: string;
  data_categories?: string[];
}

export function GrantConsentModal({ onClose, preset = {}, invalidate = [] }: { onClose: () => void; preset?: ConsentPreset; invalidate?: unknown[][] }) {
  const { t } = useI18n();
  const en = useEnum();
  const a = useAction();
  const rec = useApi<any>(["consent-recipients"], "/api/consents/recipients");
  const [f, setF] = useState({ recipient_tenant_id: preset.recipient_tenant_id || "", purpose: preset.purpose || "", data_categories: preset.data_categories || [], valid_days: 30 });
  const toggle = (c: string) => setF({ ...f, data_categories: f.data_categories.includes(c) ? f.data_categories.filter((x) => x !== c) : [...f.data_categories, c] });
  const valid = f.recipient_tenant_id && f.purpose.trim().length >= 5 && f.data_categories.length > 0 && f.valid_days >= 1;
  return (
    <Modal title={t("consent.grantTitle")} onClose={onClose}>
      <Q q={rec}>
        {(d) => (
          <>
            <Field label={t("consent.recipient")}>
              {(id) => (
                <select id={id} className="select" value={f.recipient_tenant_id} onChange={(e) => setF({ ...f, recipient_tenant_id: e.target.value })}>
                  <option value="">{t("common.choose")}</option>
                  {d.items.map((x: any) => <option key={x.id} value={x.id}>{x.name} ({en(x.kind)})</option>)}
                </select>
              )}
            </Field>
            <Field label={t("consent.purpose")} hint={t("consent.purposeHint")}>{(id, h) => <input id={id} aria-describedby={h} className="input" value={f.purpose} onChange={(e) => setF({ ...f, purpose: e.target.value })} />}</Field>
            <fieldset>
              <legend>{t("consent.categories")}</legend>
              <div className="grid grid-3" style={{ gap: 0 }}>
                {d.categories.map((c: string) => <label key={c} className="check"><input type="checkbox" checked={f.data_categories.includes(c)} onChange={() => toggle(c)} /> {en(c)}</label>)}
              </div>
            </fieldset>
            <Field label={t("consent.duration")}>{(id) => <input id={id} className="input" type="number" min={1} max={365} value={f.valid_days} onChange={(e) => setF({ ...f, valid_days: Number(e.target.value) })} />}</Field>
            {preset.case_id && <Notice>{t("consent.caseScoped")}</Notice>}
            <Notice kind="info">{t("consent.revocationNote")}</Notice>
          </>
        )}
      </Q>
      <div className="form-actions">
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" mutates busy={a.busy} disabled={!valid} onClick={async () => {
          const r = await a.run(() => api.post("/api/consents", { ...f, case_id: preset.case_id || null }), { success: t("consent.granted"), invalidate: [["consents"], ...invalidate] });
          if (r) onClose();
        }}>{t("consent.grant")}</Button>
      </div>
    </Modal>
  );
}

function GrantRow({ g, onRevoke, actions }: { g: any; onRevoke?: () => void; actions?: ReactNode }) {
  const { t, fmtDate } = useI18n();
  const en = useEnum();
  return (
    <li>
      <div className="row-between">
        <div>
          <b>{g.recipient.name}</b> {g.handoff && <span className="badge b-accent">{t("consent.handoff")}</span>}
          <div className="small">{g.purpose}</div>
          <div className="chip-row" style={{ marginTop: 4 }}>{g.data_categories.map((c: string) => <span key={c} className="badge">{en(c)}</span>)}</div>
          <div className="xs muted" style={{ marginTop: 4 }}>
            {g.case_reference && <>{t("consent.case")}: <Link to={`/cases/${g.case_id}`}>{g.case_reference}</Link> · </>}
            {g.requested_by && <>{t("consent.requestedBy", { by: g.requested_by })} · </>}
            {t("consent.validUntil", { date: fmtDate(g.valid_until) })}
          </div>
        </div>
        <div className="row"><StatusBadge value={g.status} />{actions}{onRevoke && <Button size="sm" variant="danger" mutates onClick={onRevoke}>{t("consent.revoke")}</Button>}</div>
      </div>
    </li>
  );
}

export function ConsentCenter() {
  const { t, fmtDateTime } = useI18n();
  const en = useEnum();
  const q = useApi<any>(["consents"], "/api/consents");
  const receipts = useApi<any>(["receipts"], "/api/documents/receipts/all");
  const a = useAction();
  const [tab, setTab] = useState<"active" | "pending" | "history" | "receipts">("active");
  const [grant, setGrant] = useState(false);
  const [revoke, setRevoke] = useState<any>(null);
  const items: any[] = q.data?.items || [];
  const pending = items.filter((g) => g.status === "pending");
  const active = items.filter((g) => g.status === "active");
  const history = items.filter((g) => !["pending", "active"].includes(g.status));
  return (
    <>
      <PageHead title={t("consent.title")} sub={t("consent.sub")} actions={<Button variant="primary" mutates onClick={() => setGrant(true)}><ShieldCheck size={15} aria-hidden /> {t("consent.grantTitle")}</Button>} />
      {pending.length > 0 && <Notice kind="warning">{t("consent.pendingNotice", { n: pending.length })}</Notice>}
      <Tabs label={t("consent.title")} value={tab} onChange={setTab} tabs={[
        { id: "active", label: t("consent.tab.active"), count: active.length },
        { id: "pending", label: t("consent.tab.pending"), count: pending.length },
        { id: "history", label: t("consent.tab.history"), count: history.length },
        { id: "receipts", label: t("consent.tab.receipts") },
      ]} />
      <Card>
        <Q q={q}>
          {() => (
            <>
              {tab === "active" && (active.length ? <ul className="list">{active.map((g) => <GrantRow key={g.id} g={g} onRevoke={() => setRevoke(g)} />)}</ul> : <Empty title={t("consent.noneActive")} />)}
              {tab === "pending" && (pending.length ? (
                <ul className="list">{pending.map((g) => (
                  <GrantRow key={g.id} g={g} actions={<>
                    <Button size="sm" variant="primary" mutates busy={a.busy} onClick={() => a.run(() => api.post(`/api/consents/${g.id}/approve`), { success: t("consent.approved"), invalidate: [["consents"], ["overview"]] })}>{t("consent.approve")}</Button>
                    <Button size="sm" mutates onClick={() => a.run(() => api.post(`/api/consents/${g.id}/decline`), { success: t("consent.declined"), invalidate: [["consents"]] })}>{t("consent.decline")}</Button>
                  </>} />
                ))}</ul>
              ) : <Empty title={t("consent.nonePending")} />)}
              {tab === "history" && (history.length ? <ul className="list">{history.map((g) => <GrantRow key={g.id} g={g} />)}</ul> : <Empty title={t("consent.noneHistory")} />)}
            </>
          )}
        </Q>
        {tab === "receipts" && (
          <Q q={receipts}>
            {(d) => d.items.length === 0 ? <Empty title={t("receipts.none")} /> : (
              <div className="table-wrap"><table>
                <thead><tr><th>{t("receipts.when")}</th><th>{t("common.document")}</th><th>{t("receipts.who")}</th><th>{t("receipts.action")}</th><th>{t("receipts.basis")}</th></tr></thead>
                <tbody>{d.items.map((r: any) => (
                  <tr key={r.id}><td>{fmtDateTime(r.at)}</td><td><Link to={`/wallet/${r.document_id}`}>{r.document_title}</Link></td><td>{r.accessed_by}{r.organisation && <div className="xs muted">{r.organisation}</div>}</td>
                    <td>{en(r.action)}</td><td>{r.consent_grant_id ? t("receipts.consent") : t("receipts.delegation")}</td></tr>
                ))}</tbody>
              </table></div>
            )}
          </Q>
        )}
      </Card>
      {grant && <GrantConsentModal onClose={() => setGrant(false)} />}
      {revoke && (
        <Confirm title={t("consent.revokeTitle")} danger confirmLabel={t("consent.revoke")} onCancel={() => setRevoke(null)}
          body={<><p>{t("consent.revokeBody", { name: revoke.recipient.name })}</p><Notice kind="warning">{t("consent.revokeLimit")}</Notice></>}
          onConfirm={async () => { await a.run(() => api.post(`/api/consents/${revoke.id}/revoke`, { reason: "Revoked by citizen" }), { success: t("consent.revoked"), invalidate: [["consents"]] }); setRevoke(null); }} />
      )}
    </>
  );
}
