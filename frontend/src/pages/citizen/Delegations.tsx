import { useState } from "react";
import { Link } from "react-router";
import { HandHeart } from "lucide-react";
import { api } from "../../lib/api";
import { useAction } from "../../lib/hooks";
import { useEnum, useI18n } from "../../lib/i18n";
import { Button, Card, Confirm, Empty, Field, Modal, Notice, PageHead, Q, StatusBadge, useApi } from "../../components/ui";

function NewDelegation({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const en = useEnum();
  const a = useAction();
  const pros = useApi<any>(["professionals"], "/api/delegations/professionals");
  const cases = useApi<any>(["cases", "all"], "/api/cases?page_size=100");
  const [f, setF] = useState<{ who: string; case_id: string; scopes: string[]; document_categories: string[]; purpose: string; valid_days: number }>({
    who: "", case_id: "", scopes: ["view_case"], document_categories: [], purpose: "", valid_days: 14,
  });
  const toggle = (k: "scopes" | "document_categories", v: string) => setF({ ...f, [k]: f[k].includes(v) ? f[k].filter((x) => x !== v) : [...f[k], v] });
  const [user_id, tenant_id] = f.who.split("|");
  return (
    <Modal title={t("deleg.new")} onClose={onClose} wide>
      <Q q={pros}>
        {(d) => (
          <>
            <Field label={t("deleg.professional")}>
              {(id) => <select id={id} className="select" value={f.who} onChange={(e) => setF({ ...f, who: e.target.value })}>
                <option value="">{t("common.choose")}</option>
                {d.items.map((p: any) => <option key={p.user_id + p.tenant_id} value={`${p.user_id}|${p.tenant_id}`}>{p.display_name} — {p.organisation}</option>)}
              </select>}
            </Field>
            <Field label={t("deleg.case")} hint={t("deleg.caseHint")}>
              {(id, h) => <select id={id} aria-describedby={h} className="select" value={f.case_id} onChange={(e) => setF({ ...f, case_id: e.target.value })}>
                <option value="">{t("deleg.allCases")}</option>
                {(cases.data?.items || []).map((c: any) => <option key={c.id} value={c.id}>{c.reference} · {c.title}</option>)}
              </select>}
            </Field>
            <fieldset><legend>{t("deleg.scopes")}</legend>
              <div className="grid grid-2" style={{ gap: 0 }}>
                {d.scopes.map((s: string) => <label key={s} className="check"><input type="checkbox" checked={f.scopes.includes(s)} disabled={s === "view_case"} onChange={() => toggle("scopes", s)} /> <span>{t(`scope.${s}`)}</span></label>)}
              </div>
            </fieldset>
            {f.scopes.includes("view_documents") && (
              <fieldset><legend>{t("deleg.categories")}</legend>
                <div className="grid grid-3" style={{ gap: 0 }}>{d.categories.map((c: string) => <label key={c} className="check"><input type="checkbox" checked={f.document_categories.includes(c)} onChange={() => toggle("document_categories", c)} /> {en(c)}</label>)}</div>
              </fieldset>
            )}
            <Field label={t("consent.purpose")}>{(id) => <input id={id} className="input" value={f.purpose} onChange={(e) => setF({ ...f, purpose: e.target.value })} />}</Field>
            <Field label={t("consent.duration")} hint={t("deleg.durationHint")}>{(id, h) => <input id={id} aria-describedby={h} className="input" type="number" min={1} max={180} value={f.valid_days} onChange={(e) => setF({ ...f, valid_days: Number(e.target.value) })} />}</Field>
            <Notice kind="info">{t("deleg.note")}</Notice>
          </>
        )}
      </Q>
      <div className="form-actions">
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button variant="primary" mutates busy={a.busy} disabled={!f.who || f.purpose.trim().length < 5} onClick={async () => {
          const r = await a.run(() => api.post("/api/delegations", { delegate_user_id: user_id, delegate_tenant_id: tenant_id, case_id: f.case_id || null, scopes: f.scopes,
            document_categories: f.document_categories, purpose: f.purpose, valid_days: f.valid_days }), { success: t("deleg.granted"), invalidate: [["delegations"]] });
          if (r) onClose();
        }}>{t("deleg.grant")}</Button>
      </div>
    </Modal>
  );
}

export function DelegationList({ items, canRevoke }: { items: any[]; canRevoke: boolean }) {
  const { t, fmtDate } = useI18n();
  const a = useAction();
  const [revoke, setRevoke] = useState<any>(null);
  if (!items.length) return <Empty title={t("deleg.none")} icon={<HandHeart size={32} />} />;
  return (
    <>
      <ul className="list">
        {items.map((d) => (
          <li key={d.id}>
            <div className="row-between">
              <div>
                <b>{canRevoke ? d.delegate.display_name : d.principal.display_name}</b> <span className="xs muted">· {d.organisation}</span>
                <div className="small">{d.purpose}</div>
                <div className="chip-row" style={{ marginTop: 4 }}>{d.scopes.map((s: string) => <span key={s} className="badge">{t(`scope.${s}`)}</span>)}</div>
                <div className="xs muted" style={{ marginTop: 4 }}>
                  {d.case_reference ? <>{t("consent.case")}: <Link to={`/cases/${d.case_id}`}>{d.case_reference}</Link></> : t("deleg.allCases")} · {t("consent.validUntil", { date: fmtDate(d.valid_until) })}
                </div>
              </div>
              <div className="row"><StatusBadge value={d.status} />{canRevoke && d.status === "active" && <Button size="sm" variant="danger" mutates onClick={() => setRevoke(d)}>{t("consent.revoke")}</Button>}</div>
            </div>
          </li>
        ))}
      </ul>
      {revoke && <Confirm title={t("deleg.revokeTitle")} danger confirmLabel={t("consent.revoke")} body={<p>{t("deleg.revokeBody", { name: revoke.delegate.display_name })}</p>}
        onCancel={() => setRevoke(null)} onConfirm={async () => { await a.run(() => api.post(`/api/delegations/${revoke.id}/revoke`), { success: t("deleg.revoked"), invalidate: [["delegations"]] }); setRevoke(null); }} />}
    </>
  );
}

export function Delegations() {
  const { t } = useI18n();
  const q = useApi<any>(["delegations"], "/api/delegations");
  const [open, setOpen] = useState(false);
  return (
    <>
      <PageHead title={t("deleg.title")} sub={t("deleg.sub")} actions={<Button variant="primary" mutates onClick={() => setOpen(true)}>{t("deleg.new")}</Button>} />
      <Card><Q q={q}>{(d) => <DelegationList items={d.items} canRevoke />}</Q></Card>
      {open && <NewDelegation onClose={() => setOpen(false)} />}
    </>
  );
}
