import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

export type Theme = "system" | "light" | "dark" | "contrast";
interface Toast {
  id: number;
  kind: "success" | "error" | "info";
  text: string;
}
interface Prefs {
  theme: Theme;
  setTheme: (t: Theme) => void;
  toast: (text: string, kind?: Toast["kind"]) => void;
}
const Ctx = createContext<Prefs | null>(null);

function readTheme(): Theme {
  try {
    const v = localStorage.getItem("cb.theme");
    if (v === "light" || v === "dark" || v === "contrast" || v === "system") return v;
  } catch {
    /* ignore */
  }
  return "system";
}

let nextId = 1;

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(readTheme);
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
  }, [theme]);

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    try {
      localStorage.setItem("cb.theme", t);
    } catch {
      /* ignore */
    }
  }, []);

  const toast = useCallback((text: string, kind: Toast["kind"] = "success") => {
    const id = nextId++;
    setToasts((ts) => [...ts.slice(-3), { id, kind, text }]);
    setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== id)), kind === "error" ? 8000 : 4500);
  }, []);

  return (
    <Ctx.Provider value={{ theme, setTheme, toast }}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.kind}`}>
            <span>{t.text}</span>
            <button className="icon-btn" aria-label="Dismiss" onClick={() => setToasts((ts) => ts.filter((x) => x.id !== t.id))}>
              ×
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function usePrefs() {
  const v = useContext(Ctx);
  if (!v) throw new Error("PrefsProvider missing");
  return v;
}
