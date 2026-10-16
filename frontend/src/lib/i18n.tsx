import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { en } from "../i18n/en";
import { he } from "../i18n/he";
import { de } from "../i18n/de";

export type Locale = "en" | "he" | "de";
const DICTS: Record<Locale, Record<string, string>> = { en, he, de };
export const LOCALES: { code: Locale; label: string }[] = [
  { code: "en", label: "English" },
  { code: "he", label: "עברית" },
  { code: "de", label: "Deutsch" },
];
const INTL: Record<Locale, string> = { en: "en-GB", he: "he-IL", de: "de-DE" };

type Vars = Record<string, string | number | undefined | null>;
interface I18n {
  locale: Locale;
  dir: "rtl" | "ltr";
  setLocale: (l: Locale) => void;
  t: (key: string, vars?: Vars) => string;
  fmtDate: (iso?: string | null, opts?: Intl.DateTimeFormatOptions & { tz?: string }) => string;
  fmtDateTime: (iso?: string | null, tz?: string) => string;
  fmtNumber: (n: number, opts?: Intl.NumberFormatOptions) => string;
  timeZone: string;
  setTimeZone: (tz: string) => void;
}

const Ctx = createContext<I18n | null>(null);

function stored(): Locale {
  try {
    const v = localStorage.getItem("cb.locale");
    if (v === "en" || v === "he" || v === "de") return v;
  } catch {
    /* storage unavailable */
  }
  return "en";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(stored);
  const [timeZone, setTimeZone] = useState<string>(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  const dir = locale === "he" ? "rtl" : "ltr";

  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = dir;
  }, [locale, dir]);

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    try {
      localStorage.setItem("cb.locale", l);
    } catch {
      /* ignore */
    }
  }, []);

  const t = useCallback(
    (key: string, vars?: Vars) => {
      let s = DICTS[locale][key] ?? en[key] ?? key;
      if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(v == null ? "" : String(v));
      return s;
    },
    [locale],
  );

  const value = useMemo<I18n>(
    () => ({
      locale,
      dir,
      setLocale,
      t,
      timeZone,
      setTimeZone,
      fmtDate: (iso, opts = {}) => {
        if (!iso) return "—";
        const { tz, ...rest } = opts;
        return new Intl.DateTimeFormat(INTL[locale], { dateStyle: "medium", timeZone: tz || timeZone, ...rest }).format(new Date(iso));
      },
      fmtDateTime: (iso, tz) => {
        if (!iso) return "—";
        return new Intl.DateTimeFormat(INTL[locale], { dateStyle: "medium", timeStyle: "short", timeZone: tz || timeZone }).format(new Date(iso));
      },
      fmtNumber: (n, opts) => new Intl.NumberFormat(INTL[locale], opts).format(n),
    }),
    [locale, dir, setLocale, t, timeZone],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n() {
  const v = useContext(Ctx);
  if (!v) throw new Error("I18nProvider missing");
  return v;
}

/** Human label for enum-like values: tries `enum.<value>` then prettifies. */
export function useEnum() {
  const { t } = useI18n();
  return (value?: string | null) => {
    if (!value) return "—";
    const k = `enum.${value}`;
    const s = t(k);
    return s === k ? value.replace(/_/g, " ") : s;
  };
}
