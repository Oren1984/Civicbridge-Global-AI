import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError, onAuthProblem, setCsrf } from "./api";
import { purgeOfflineData } from "./offline";
import { useI18n, type Locale } from "./i18n";

export interface Membership {
  id: string;
  role: string;
  workspace: "citizen" | "authority" | "institution" | "professional" | "governance";
  tenant: { id: string; name: string; kind: string; slug: string };
  privileged: boolean;
}
export interface Me {
  user: { id: string; email: string; display_name: string; locale: Locale; timezone: string; read_only: boolean; mfa_enabled: boolean; email_verified: boolean; synthetic: boolean };
  memberships: Membership[];
  active: Membership | null;
  mfa_verified: boolean;
  mfa_required: boolean;
  mfa_setup_required: boolean;
  csrf_token: string;
  session: { idle_expires_at: string; absolute_expires_at: string };
}

interface AuthState {
  me: Me | null;
  loading: boolean;
  expired: boolean;
  login: (email: string, password: string) => Promise<Me>;
  logout: () => Promise<void>;
  refresh: () => Promise<Me | null>;
  setMe: (m: Me) => void;
  switchTo: (membershipId: string) => Promise<Me>;
  readOnly: boolean;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMeState] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [expired, setExpired] = useState(false);
  const qc = useQueryClient();
  const { setLocale, setTimeZone } = useI18n();

  const setMe = useCallback(
    (m: Me | null) => {
      setMeState(m);
      setCsrf(m?.csrf_token ?? null);
      if (m) {
        setTimeZone(m.user.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone);
        setExpired(false);
      }
    },
    [setTimeZone],
  );

  const refresh = useCallback(async () => {
    try {
      const m = await api.get<Me>("/api/auth/me");
      setMe(m);
      return m;
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setMe(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, [setMe]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(
    () =>
      onAuthProblem((e) => {
        if (e.status === 401) {
          if (me) {
            // Session ended server-side (expiry or revocation): clear local state safely.
            purgeOfflineData(me.user.id, false);
            qc.clear();
            setExpired(true);
          }
          setMe(null);
        } else if (e.code === "mfa_required") {
          refresh();
        }
      }),
    [me, qc, refresh, setMe],
  );

  const login = useCallback(
    async (email: string, password: string) => {
      const m = await api.post<Me>("/api/auth/login", { email, password });
      qc.clear();
      setMe(m);
      if (m.user.locale) setLocale(m.user.locale);
      return m;
    },
    [qc, setMe, setLocale],
  );

  const logout = useCallback(async () => {
    const uid = me?.user.id;
    try {
      await api.post("/api/auth/logout");
    } catch {
      /* already logged out */
    }
    if (uid) purgeOfflineData(uid, true);
    qc.clear();
    setMe(null);
  }, [me, qc, setMe]);

  const switchTo = useCallback(
    async (membershipId: string) => {
      const m = await api.post<Me>("/api/auth/context", { membership_id: membershipId });
      qc.clear();
      setMe(m);
      return m;
    },
    [qc, setMe],
  );

  const value = useMemo<AuthState>(
    () => ({ me, loading, expired, login, logout, refresh, setMe, switchTo, readOnly: !!me?.user.read_only }),
    [me, loading, expired, login, logout, refresh, setMe, switchTo],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error("AuthProvider missing");
  return v;
}

export const WORKSPACE_HOME: Record<string, string> = {
  citizen: "/",
  authority: "/authority",
  institution: "/institution",
  professional: "/professional",
  governance: "/governance",
};
