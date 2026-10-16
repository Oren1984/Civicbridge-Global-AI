import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "./api";
import { usePrefs } from "./prefs";
import { useI18n } from "./i18n";

/** Run a mutation with consistent busy state, error capture, success toast and cache invalidation. */
export function useAction() {
  const qc = useQueryClient();
  const { toast } = usePrefs();
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const run = useCallback(
    async <T,>(fn: () => Promise<T>, opts: { success?: string; invalidate?: unknown[][]; silent?: boolean } = {}): Promise<T | undefined> => {
      setBusy(true);
      setError(null);
      try {
        const r = await fn();
        if (opts.success) toast(opts.success, "success");
        for (const key of opts.invalidate || [[]]) await qc.invalidateQueries({ queryKey: key.length ? key : undefined });
        return r;
      } catch (e) {
        const err = e instanceof ApiError ? e : new ApiError(500, "client_error", String(e));
        setError(err);
        if (!opts.silent) toast(err.network ? t("error.offline") : err.message, "error");
        return undefined;
      } finally {
        setBusy(false);
      }
    },
    [qc, toast, t],
  );
  return { run, busy, error, setError };
}
