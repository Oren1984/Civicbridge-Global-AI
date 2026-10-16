import { useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useAction } from "../../lib/hooks";
import { LOCALES, useI18n, type Locale } from "../../lib/i18n";
import { Button, Card, Dl, Field, Notice, PageHead, Q, StatusBadge, useApi, useFieldErrors } from "../../components/ui";

const ZONES: string[] = (() => {
  try {
    return (Intl as any).supportedValuesOf?.("timeZone") || [];
  } catch {
    return [];
  }
})();

function Profile() {
  const { me, setMe } = useAuth();
  const { t, setLocale } = useI18n();
  const a = useAction();
  const [f, setF] = useState({ display_name: me!.user.display_name, locale: me!.user.locale, timezone: me!.user.timezone });
  return (
    <Card title={t("account.profile")}>
      <Field label={t("account.name")}>{(id) => <input id={id} className="input" value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} />}</Field>
      <Field label={t("prefs.language")}>
        {(id) => <select id={id} className="select" value={f.locale} onChange={(e) => setF({ ...f, locale: e.target.value as Locale })}>{LOCALES.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}</select>}
      </Field>
      <Field label={t("account.timezone")} hint={t("account.timezoneHint")}>
        {(id, h) => ZONES.length
          ? <select id={id} aria-describedby={h} className="select" value={f.timezone} onChange={(e) => setF({ ...f, timezone: e.target.value })}>{ZONES.map((z) => <option key={z} value={z}>{z}</option>)}</select>
          : <input id={id} aria-describedby={h} className="input" value={f.timezone} onChange={(e) => setF({ ...f, timezone: e.target.value })} />}
      </Field>
      <div className="form-actions">
        <Button variant="primary" mutates busy={a.busy} disabled={f.display_name.trim().length < 2} onClick={async () => {
          const m = await a.run(() => api.patch("/api/auth/profile", f), { success: t("account.saved") });
          if (m) {
            setMe(m as any);
            setLocale(f.locale);
          }
        }}>{t("common.save")}</Button>
      </div>
    </Card>
  );
}

function Password() {
  const { t } = useI18n();
  const a = useAction();
  const fe = useFieldErrors(a.error);
  const [f, setF] = useState({ current_password: "", new_password: "", confirm: "" });
  const mismatch = f.confirm.length > 0 && f.confirm !== f.new_password;
  return (
    <Card title={t("account.password")}>
      <Field label={t("account.currentPassword")}>{(id) => <input id={id} type="password" autoComplete="current-password" className="input" value={f.current_password} onChange={(e) => setF({ ...f, current_password: e.target.value })} />}</Field>
      <Field label={t("account.newPassword")} hint={t("auth.passwordRules")} error={fe("new_password")}>{(id, h) => <input id={id} aria-describedby={h} type="password" autoComplete="new-password" className="input" value={f.new_password} onChange={(e) => setF({ ...f, new_password: e.target.value })} />}</Field>
      <Field label={t("account.confirmPassword")} error={mismatch ? t("account.mismatch") : undefined}>{(id, h) => <input id={id} aria-describedby={h} type="password" autoComplete="new-password" className="input" value={f.confirm} onChange={(e) => setF({ ...f, confirm: e.target.value })} />}</Field>
      <p className="xs muted">{t("account.passwordNote")}</p>
      <div className="form-actions">
        <Button variant="primary" mutates busy={a.busy} disabled={!f.current_password || f.new_password.length < 12 || mismatch} onClick={async () => {
          const r = await a.run(() => api.post("/api/auth/password/change", { current_password: f.current_password, new_password: f.new_password }), { success: t("account.passwordChanged"), invalidate: [["sessions"]] });
          if (r) setF({ current_password: "", new_password: "", confirm: "" });
        }}>{t("account.changePassword")}</Button>
      </div>
    </Card>
  );
}

function Mfa() {
  const { me, setMe } = useAuth();
  const { t } = useI18n();
  const a = useAction();
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  if (me!.user.mfa_enabled)
    return <Card title={t("account.mfa")}><Notice kind="success">{t("account.mfaOn")}</Notice></Card>;
  return (
    <Card title={t("account.mfa")}>
      {me!.mfa_setup_required && <Notice kind="warning">{t("account.mfaRequired")}</Notice>}
      <p className="small">{t("account.mfaBody")}</p>
      {!setup ? (
        <Button variant="primary" mutates busy={a.busy} onClick={async () => { const r = await a.run(() => api.post("/api/auth/mfa/setup")); if (r) setSetup(r as any); }}>{t("account.mfaStart")}</Button>
      ) : (
        <>
          <Dl items={[[t("account.mfaSecret"), <span className="mono wrap-anywhere">{setup.secret}</span>], [t("account.mfaUri"), <span className="mono xs wrap-anywhere">{setup.otpauth_uri}</span>]]} />
          <Field label={t("mfa.code")} hint={t("account.mfaCodeHint")}>
            {(id, h) => <input id={id} aria-describedby={h} className="input" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} style={{ maxWidth: 160 }} />}
          </Field>
          <div className="form-actions">
            <Button variant="primary" mutates busy={a.busy} disabled={code.length !== 6} onClick={async () => {
              const m = await a.run(() => api.post("/api/auth/mfa/enable", { code }), { success: t("account.mfaEnabled") });
              if (m) setMe(m as any);
            }}>{t("account.mfaEnable")}</Button>
          </div>
        </>
      )}
    </Card>
  );
}

function Sessions() {
  const { t, fmtDateTime } = useI18n();
  const a = useAction();
  const q = useApi<any>(["sessions"], "/api/auth/sessions");
  return (
    <Card title={t("account.sessions")}>
      <Q q={q}>
        {(d) => (
          <ul className="list">{d.items.map((s: any) => (
            <li key={s.id} className="row-between">
              <span>
                <span className="small">{s.user_agent || t("account.unknownDevice")}</span>
                {s.current && <span className="badge b-info" style={{ marginInlineStart: 6 }}>{t("account.thisSession")}</span>}
                <div className="xs muted">{t("account.started", { date: fmtDateTime(s.created_at) })} · {t("account.lastSeen", { date: fmtDateTime(s.last_seen_at) })}{s.revoked_reason && ` · ${s.revoked_reason.replace(/_/g, " ")}`}</div>
              </span>
              <span className="row">
                <StatusBadge value={s.active ? "active" : "expired"} />
                {s.active && !s.current && <Button size="sm" variant="danger" mutates busy={a.busy} onClick={() => a.run(() => api.del(`/api/auth/sessions/${s.id}`), { success: t("account.revoked"), invalidate: [["sessions"]] })}>{t("account.revoke")}</Button>}
              </span>
            </li>
          ))}</ul>
        )}
      </Q>
    </Card>
  );
}

export function Account() {
  const { me } = useAuth();
  const { t } = useI18n();
  if (!me) return null;
  return (
    <>
      <PageHead title={t("account.title")} sub={me.user.email} />
      {me.user.synthetic && <Notice kind="synthetic">{t("account.synthetic")}</Notice>}
      <div className="grid grid-2" style={{ marginTop: 16, alignItems: "start" }}>
        <div className="stack"><Profile /><Mfa /></div>
        <div className="stack"><Password /><Sessions /></div>
      </div>
    </>
  );
}
