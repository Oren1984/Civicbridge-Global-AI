import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { api, ApiError } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { Button, Field, Notice } from "../../components/ui";
import { AuthFrame } from "./Login";

function useSubmit() {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const run = async (fn: () => Promise<{ message?: string } | unknown>, okMsg: string) => {
    setBusy(true);
    setErr(null);
    try {
      const r = (await fn()) as { message?: string };
      setDone(r?.message || okMsg);
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  };
  return { busy, err, done, run };
}

export function ForgotPassword() {
  const { t } = useI18n();
  const [email, setEmail] = useState("");
  const s = useSubmit();
  return (
    <AuthFrame>
      <h1 style={{ fontSize: "1.5rem" }}>{t("recovery.forgotTitle")}</h1>
      <p className="muted">{t("recovery.forgotSub")}</p>
      {s.done ? (
        <Notice kind="success">
          {s.done} {t("recovery.mailpit")} <a href="http://localhost:8095" target="_blank" rel="noreferrer">localhost:8095</a>
        </Notice>
      ) : (
        <form onSubmit={(e: FormEvent) => { e.preventDefault(); s.run(() => api.post("/api/auth/password/forgot", { email }), t("recovery.sent")); }}>
          {s.err && <Notice kind="danger">{s.err.message}</Notice>}
          <Field label={t("login.email")}>{(id) => <input id={id} className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />}</Field>
          <Button type="submit" variant="primary" busy={s.busy} disabled={!email}>{t("recovery.send")}</Button>
        </form>
      )}
      <p className="small" style={{ marginTop: 16 }}><Link to="/login">{t("recovery.back")}</Link></p>
    </AuthFrame>
  );
}

export function ResetPassword() {
  const { t } = useI18n();
  const [params] = useSearchParams();
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const s = useSubmit();
  const mismatch = pw2.length > 0 && pw !== pw2;
  return (
    <AuthFrame>
      <h1 style={{ fontSize: "1.5rem" }}>{t("recovery.resetTitle")}</h1>
      {s.done ? (
        <Notice kind="success">{t("recovery.resetDone")} <Link to="/login">{t("login.submit")}</Link></Notice>
      ) : (
        <form onSubmit={(e: FormEvent) => { e.preventDefault(); s.run(() => api.post("/api/auth/password/reset", { token: params.get("token") || "", password: pw }), t("recovery.resetDone")); }}>
          {s.err && <Notice kind="danger">{s.err.message}</Notice>}
          <Field label={t("recovery.newPassword")} hint={t("recovery.rules")}>{(id, d) => <input id={id} aria-describedby={d} className="input" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} />}</Field>
          <Field label={t("recovery.repeat")} error={mismatch ? t("recovery.mismatch") : undefined}>{(id, d) => <input id={id} aria-describedby={d} aria-invalid={mismatch} className="input" type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} />}</Field>
          <Button type="submit" variant="primary" busy={s.busy} disabled={!pw || pw !== pw2}>{t("recovery.reset")}</Button>
        </form>
      )}
    </AuthFrame>
  );
}

export function Register() {
  const { t, locale } = useI18n();
  const [f, setF] = useState({ email: "", display_name: "", password: "" });
  const s = useSubmit();
  return (
    <AuthFrame>
      <h1 style={{ fontSize: "1.5rem" }}>{t("register.title")}</h1>
      <p className="muted">{t("register.sub")}</p>
      {s.done ? (
        <Notice kind="success">{s.done} {t("recovery.mailpit")} <a href="http://localhost:8095" target="_blank" rel="noreferrer">localhost:8095</a></Notice>
      ) : (
        <form onSubmit={(e: FormEvent) => { e.preventDefault(); s.run(() => api.post("/api/auth/register", { ...f, locale }), t("register.done")); }}>
          {s.err && <Notice kind="danger">{s.err.message}</Notice>}
          <Field label={t("register.name")}>{(id) => <input id={id} className="input" value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} autoComplete="name" />}</Field>
          <Field label={t("login.email")}>{(id) => <input id={id} className="input" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} autoComplete="email" />}</Field>
          <Field label={t("login.password")} hint={t("recovery.rules")}>{(id, d) => <input id={id} aria-describedby={d} className="input" type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} autoComplete="new-password" />}</Field>
          <Notice kind="synthetic">{t("register.synthetic")}</Notice>
          <Button type="submit" variant="primary" busy={s.busy} disabled={!f.email || !f.password || f.display_name.length < 2}>{t("register.submit")}</Button>
        </form>
      )}
      <p className="small" style={{ marginTop: 16 }}><Link to="/login">{t("recovery.back")}</Link></p>
    </AuthFrame>
  );
}

export function VerifyEmail() {
  const { t } = useI18n();
  const [params] = useSearchParams();
  const [state, setState] = useState<"busy" | "ok" | "error">("busy");
  const [msg, setMsg] = useState("");
  const sent = useRef(false);
  useEffect(() => {
    if (sent.current) return; // single-use token: never submit twice
    sent.current = true;
    api.post("/api/auth/verify-email", { token: params.get("token") || "" }).then(() => setState("ok")).catch((e: ApiError) => { setState("error"); setMsg(e.message); });
  }, [params]);
  return (
    <AuthFrame>
      <h1 style={{ fontSize: "1.5rem" }}>{t("verify.title")}</h1>
      {state === "busy" && <p>{t("common.loading")}</p>}
      {state === "ok" && <Notice kind="success">{t("verify.ok")} <Link to="/login">{t("login.submit")}</Link></Notice>}
      {state === "error" && <Notice kind="danger">{msg}</Notice>}
    </AuthFrame>
  );
}
