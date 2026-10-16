import { useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from "react-router";
import { ApiError } from "../../lib/api";
import { useAuth, WORKSPACE_HOME } from "../../lib/auth";
import { LOCALES, useI18n } from "../../lib/i18n";
import { Button, Field, Notice } from "../../components/ui";

export function AuthFrame({ children }: { children: ReactNode }) {
  const { t, locale, setLocale } = useI18n();
  return (
    <div className="auth-wrap">
      <section className="auth-hero">
        <div>
          <div className="row" style={{ marginBottom: 32 }}>
            <svg width="40" height="40" viewBox="0 0 64 64" aria-hidden>
              <rect width="64" height="64" rx="14" fill="#ffffff22" />
              <path d="M10 42c8-14 36-14 44 0" stroke="#fff" strokeWidth="5" fill="none" strokeLinecap="round" />
              <path d="M18 42v-8M32 42V28M46 42v-8" stroke="#8fd3c7" strokeWidth="5" strokeLinecap="round" />
            </svg>
            <b style={{ fontSize: "1.2rem" }}>CivicBridge Global AI</b>
          </div>
          <h1>{t("login.heroTitle")}</h1>
          <p>{t("login.heroBody")}</p>
          <ul className="hide-mobile">
            <li>{t("login.point1")}</li>
            <li>{t("login.point2")}</li>
            <li>{t("login.point3")}</li>
          </ul>
        </div>
        <p className="small hide-mobile" style={{ opacity: 0.8 }}>
          {t("env.banner")}
        </p>
      </section>
      <section className="auth-panel">
        <div className="auth-card">
          <div className="row" style={{ justifyContent: "flex-end", marginBottom: 16 }}>
            <label className="sr-only" htmlFor="lang">
              {t("prefs.language")}
            </label>
            <select id="lang" className="select" style={{ width: "auto" }} value={locale} onChange={(e) => setLocale(e.target.value as any)}>
              {LOCALES.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.label}
                </option>
              ))}
            </select>
          </div>
          {children}
        </div>
      </section>
    </div>
  );
}

export function Login() {
  const { t } = useI18n();
  const { me, login } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  if (me && !me.mfa_required) return <Navigate to={WORKSPACE_HOME[me.active?.workspace || "citizen"]} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const m = await login(email.trim(), password);
      if (m.mfa_required) nav("/mfa", { replace: true, state: loc.state });
      else nav((loc.state as any)?.from || WORKSPACE_HOME[m.active?.workspace || "citizen"], { replace: true });
    } catch (e2) {
      setErr(e2 as ApiError);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthFrame>
      <h1 style={{ fontSize: "1.5rem" }}>{t("login.title")}</h1>
      <p className="muted">{t("login.sub")}</p>
      {params.get("expired") && <Notice kind="warning">{t("login.expired")}</Notice>}
      {err && (
        <Notice kind="danger">
          {err.code === "invalid_credentials" ? t("login.invalid") : err.code === "account_locked" ? t("login.locked") : err.code === "email_not_verified" ? t("login.unverified") : err.message}
        </Notice>
      )}
      <form onSubmit={submit} noValidate>
        <Field label={t("login.email")}>
          {(id) => <input id={id} className="input" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />}
        </Field>
        <Field label={t("login.password")}>
          {(id) => <input id={id} className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />}
        </Field>
        <Button type="submit" variant="primary" busy={busy} disabled={!email || !password} className="w-full" style={{ width: "100%" }}>
          {t("login.submit")}
        </Button>
      </form>
      <div className="row-between small" style={{ marginTop: 16 }}>
        <Link to="/forgot-password">{t("login.forgot")}</Link>
        <Link to="/register">{t("login.register")}</Link>
      </div>
      <hr />
      <Notice kind="synthetic" title={t("login.demoTitle")}>
        {t("login.demoBody")} <code>docker compose exec backend python -m app.cli demo-credentials</code>
      </Notice>
      <p className="small">
        <Link to="/transparency">{t("nav.transparency")}</Link>
      </p>
    </AuthFrame>
  );
}
