import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";
import { api, ApiError } from "../../lib/api";
import { useAuth, WORKSPACE_HOME, type Me } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { Button, Field, Loading, Notice } from "../../components/ui";
import { AuthFrame } from "./Login";

export function MfaVerify() {
  const { t } = useI18n();
  const { me, loading, setMe, logout } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (loading) return <Loading />;
  if (!me) return <Navigate to="/login" replace />;
  if (!me.mfa_required) return <Navigate to={WORKSPACE_HOME[me.active?.workspace || "citizen"]} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const m = await api.post<Me>("/api/auth/mfa/verify", { code: code.replace(/\s/g, "") });
      setMe(m);
      nav((loc.state as any)?.from || WORKSPACE_HOME[m.active?.workspace || "citizen"], { replace: true });
    } catch (e2) {
      const er = e2 as ApiError;
      setErr(er.code === "invalid_mfa_code" ? t("mfa.invalid") : er.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <AuthFrame>
      <h1 style={{ fontSize: "1.5rem" }}>{t("mfa.title")}</h1>
      <p className="muted">{t("mfa.sub", { role: me.active ? t(`role.${me.active.role}`) : "" })}</p>
      {err && <Notice kind="danger">{err}</Notice>}
      <form onSubmit={submit}>
        <Field label={t("mfa.code")} hint={t("mfa.hint")}>
          {(id, d) => (
            <input id={id} aria-describedby={d} className="input mono" inputMode="numeric" autoComplete="one-time-code" maxLength={8} value={code}
              onChange={(e) => setCode(e.target.value)} autoFocus style={{ letterSpacing: "0.3em", fontSize: "1.3rem" }} />
          )}
        </Field>
        <Button type="submit" variant="primary" busy={busy} disabled={code.replace(/\s/g, "").length !== 6} style={{ width: "100%" }}>
          {t("mfa.verify")}
        </Button>
      </form>
      <p className="small muted" style={{ marginTop: 16 }}>
        {t("mfa.demoHint")} <code>python -m app.cli totp &lt;key&gt;</code>
      </p>
      <Button variant="ghost" onClick={() => logout().then(() => nav("/login"))}>
        {t("user.logout")}
      </Button>
    </AuthFrame>
  );
}
