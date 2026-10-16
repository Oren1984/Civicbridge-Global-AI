import { test as setup } from "@playwright/test";
import { authFile, login } from "./helpers";

// Sign in each account once and reuse the session: the login endpoint is rate-limited per IP.
const KEYS = ["maya", "lena", "thomas", "amir", "petra", "david", "rina", "govadmin", "auditor", "viewer"];

for (const key of KEYS) {
  setup(`sign in ${key}`, async ({ page }) => {
    await login(page, key);
    await page.context().storageState({ path: authFile(key) });
  });
}
