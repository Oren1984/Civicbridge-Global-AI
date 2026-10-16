import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@fontsource-variable/inter";
import "@fontsource/heebo/400.css";
import "@fontsource/heebo/600.css";
import "@fontsource/heebo/700.css";
import "./styles.css";
import App from "./App";
import { I18nProvider } from "./lib/i18n";
import { AuthProvider } from "./lib/auth";
import { PrefsProvider } from "./lib/prefs";
import { ApiError } from "./lib/api";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (n, e) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2,
      refetchOnWindowFocus: false,
      staleTime: 10_000,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <PrefsProvider>
          <AuthProvider>
            <App />
          </AuthProvider>
        </PrefsProvider>
      </I18nProvider>
    </QueryClientProvider>
  </StrictMode>,
);

// App-shell service worker for low-connectivity use (static assets only; never caches API responses).
if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => undefined));
}
