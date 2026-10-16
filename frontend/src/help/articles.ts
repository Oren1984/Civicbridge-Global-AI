// Help Center articles. Each article describes behaviour that exists in this installation; keep them in step with the code.
// Articles are written in English; the surrounding interface is translated.

export type Block = { h?: string; p?: string; ul?: string[] };
export interface Article {
  slug: string;
  title: string;
  summary: string;
  /** Workspaces the article is primarily for; "all" shows it to everyone. */
  workspaces: ("citizen" | "authority" | "institution" | "professional" | "governance")[] | "all";
  /** Route prefixes for the contextual Help button. The longest matching prefix wins. */
  paths: string[];
  keywords: string[];
  body: Block[];
}

export const ARTICLES: Article[] = [
  {
    slug: "getting-started",
    title: "Getting started",
    summary: "What CivicBridge is, what is simulated, and how to find your way around.",
    workspaces: "all",
    paths: ["/", "/authority", "/institution"],
    keywords: ["start", "overview", "demo", "synthetic", "home"],
    body: [
      { p: "CivicBridge helps residents organise cross-border life events (moving, work, study, family, retirement, starting a business) and work with public authorities through one case." },
      { h: "What is real and what is simulated", ul: [
        "All jurisdictions, authorities, rules, holidays and source texts in this installation are synthetic demo content. Authority names start with \"Demo\" and items carry a Synthetic badge.",
        "Exchanges with authorities happen inside CivicBridge only and are marked Simulated. Decisions are demo decisions, not legal acts.",
        "No official website links are invented. Where a real source would exist, the source is shown as a placeholder.",
      ] },
      { h: "Finding your way", ul: [
        "The side menu changes with your workspace (citizen, authority, institution, professional, governance).",
        "The question-mark button in the header opens the help article for the page you are on.",
        "The language button switches between English, Hebrew (right-to-left) and German, and between light, dark and high-contrast themes.",
        "The bell shows unread notifications; it refreshes every 30 seconds.",
      ] },
    ],
  },
  {
    slug: "accounts-mfa-sessions",
    title: "Accounts, MFA and sessions",
    summary: "Signing in, two-step verification, session expiry and revoking sessions.",
    workspaces: "all",
    paths: ["/account", "/login", "/mfa"],
    keywords: ["password", "login", "mfa", "totp", "authenticator", "session", "lockout", "expired", "recovery"],
    body: [
      { h: "Signing in", ul: [
        "After 5 failed attempts the account is locked for a short period. Sign-in attempts are also rate-limited.",
        "Forgotten passwords are reset through an emailed single-use link. In this installation all email goes to the local Mailpit inbox, not to real addresses.",
        "Passwords need at least 12 characters, upper and lower case, and a digit. Changing your password signs out all your other sessions.",
      ] },
      { h: "Two-step verification (MFA)", ul: [
        "Authority supervisors, governance and other privileged roles must use a time-based one-time code (TOTP) from an authenticator app.",
        "Set it up under Account › Two-step verification: copy the secret into your app, then enter a current 6-digit code to enable it. Each code can be used only once.",
        "For demo accounts, an operator can print current codes with the demo-credentials command (see the README).",
      ] },
      { h: "Sessions", ul: [
        "A session ends after 30 minutes without activity or 12 hours in total (the governance team can change these values). You are then returned to the sign-in page; drafts that were not yet sent stay on this device so you can send them after signing in again.",
        "Account › Active sessions lists your recent sessions. You can revoke any session other than the current one.",
        "Signing out removes this account's locally stored drafts. If unsent drafts exist, you are warned first.",
      ] },
    ],
  },
  {
    slug: "workspaces-roles",
    title: "Workspaces and roles",
    summary: "What each workspace can see and do, and how to switch.",
    workspaces: "all",
    paths: [],
    keywords: ["role", "workspace", "switch", "tenant", "authority", "institution", "professional", "governance", "read-only"],
    body: [
      { p: "One account can hold several memberships, for example a resident who also works for an authority. Use the context switcher in the header to choose which one is active. Everything you see is limited to the active membership." },
      { ul: [
        "Citizen: your own cases, documents, consents, delegations, incidents and privacy requests.",
        "Authority: the request queue of your authority only. You see a citizen's case only after it has been submitted to you, and documents only with the citizen's consent.",
        "Institution: cases and documents shared with your organisation through an approved handoff.",
        "Professional (adviser, interpreter): only what a citizen delegated to you, limited by scope, document category, case and expiry. An interpreter invited to a meeting gets no case or document access.",
        "Governance: policies, audit, risks, incidents, integrations, jobs and aggregate reporting. Governance roles never see case narratives or document contents.",
        "Read-only demo account: you can look around, but every change is blocked by the server. Buttons that would change something are disabled and show a lock.",
      ] },
      { p: "Requests for records outside your scope return \"not found\" and are recorded in the audit log." },
    ],
  },
  {
    slug: "cases-life-events",
    title: "Cases and life events",
    summary: "Journeys, checklists, requests to authorities, information requests and decisions.",
    workspaces: ["citizen", "professional", "authority", "institution"],
    paths: ["/journeys", "/cases", "/authority/queue", "/authority/requests"],
    keywords: ["journey", "life event", "relocation", "checklist", "task", "request", "deadline", "rfi", "information request", "decision"],
    body: [
      { h: "Starting a journey", p: "Under Journeys, choose a template (for example relocation from Israel to Germany) and answer a few questions. CivicBridge creates a case with a checklist per jurisdiction. Tasks can depend on other tasks, require evidence, have deadlines in the local time zone (calendar or working days) and appear only when a condition applies." },
      { h: "Reading the checklist", ul: [
        "Each task explains why it is blocked, which evidence is missing, whether it is overdue, and whether a human review step is involved.",
        "Attach evidence from your document wallet to a task. Attaching does not share the document; the authority still needs your consent for that document's category and case.",
      ] },
      { h: "Requests to authorities", ul: [
        "A request starts as your draft. The authority cannot see it until you submit it.",
        "After submission the request moves through triage, review, possibly an information request, a proposed decision and an approved decision. The service-level clock counts working days and pauses while the authority waits for information from you.",
        "Every decision needs two people: one officer proposes, a different supervisor approves.",
        "The case timeline records each step. Some authority-internal steps are visible only to the authority.",
      ] },
    ],
  },
  {
    slug: "documents-consent",
    title: "Documents, consent and revocation",
    summary: "The wallet, malware scanning, redaction, consent grants and what revoking does.",
    workspaces: ["citizen", "authority", "institution"],
    paths: ["/wallet", "/consent", "/authority/consents"],
    keywords: ["document", "upload", "wallet", "scan", "virus", "redact", "consent", "share", "revoke", "receipt", "handoff"],
    body: [
      { h: "Uploading", ul: [
        "Accepted files: PDF, PNG, JPEG and plain text, up to 15 MB each, within a 200 MB quota. The file type is checked from its content, not only its name.",
        "Every upload is scanned for malware. A file can be opened only when the scan result is clean. If the scanner is unavailable the file stays in \"scan unavailable\" and is retried automatically.",
        "New versions keep the old ones. Deleting a document removes it from view straight away and erases the stored files in the background.",
      ] },
      { h: "Redaction", p: "Redaction creates a new derived version and keeps the original. For images the selected areas are overwritten and metadata is removed; for text the chosen terms are removed; a PDF becomes a text-only derivative. Check the result before you share it." },
      { h: "Consent", ul: [
        "A consent names a recipient organisation, a purpose, data categories, an end date and optionally one case. A case-scoped consent covers only documents attached to that case.",
        "Authorities can ask for consent. A request on behalf of another organisation is a handoff: nothing is shared until you approve it.",
        "Every access by an organisation creates a receipt you can see in the consent centre.",
        "Revoking stops future access immediately and ends the organisation's participation that relied on it. It cannot undo copies that an organisation already viewed or downloaded.",
      ] },
    ],
  },
  {
    slug: "delegation",
    title: "Delegation to advisers and interpreters",
    summary: "Letting a professional act for you, with limits.",
    workspaces: ["citizen", "professional"],
    paths: ["/delegations", "/professional"],
    keywords: ["delegate", "adviser", "lawyer", "interpreter", "scope", "translation review", "on behalf"],
    body: [
      { p: "A delegation gives a professional limited access to your cases. You choose:" },
      { ul: [
        "Scopes: viewing the case, viewing documents, uploading documents, drafting messages, sending messages, responding to information requests, reviewing translations and attending meetings.",
        "Document categories (only when document viewing is included).",
        "Optionally a single case, and an end date of at most 180 days.",
      ] },
      { p: "You can revoke a delegation at any time; access ends immediately. Professionals see their delegations, the cases they cover and translations waiting for their review in the professional workspace." },
    ],
  },
  {
    slug: "rights-appeals",
    title: "Rights screening and appeals",
    summary: "What the Rights Navigator tells you, its limits, and how to appeal a decision.",
    workspaces: ["citizen", "professional", "authority"],
    paths: ["/rights"],
    keywords: ["rights", "eligibility", "screening", "benefit", "appeal", "citation", "uncertainty", "review"],
    body: [
      { h: "Screening", ul: [
        "The Rights Navigator runs deterministic rules on your answers. It tells you which programmes are likely applicable, likely not applicable, or need more information, and lists what is missing.",
        "Each result shows citations to source passages and warnings, for example when a rule is synthetic, its review date has passed, or the source is a placeholder.",
        "A screening result is an indication, never a decision. For consequential outcomes you can request a human review, which is sent to the responsible authority.",
      ] },
      { h: "Asking questions", p: "Questions are answered from the bundled source passages only, with citations. If the sources do not support an answer, the Navigator says so instead of guessing. Text inside documents that looks like instructions is treated as data and flagged." },
      { h: "Appeals", p: "After a decision is issued, open the case and choose Appeal while the appeal window is open (30 days by default). Explain your grounds. The appeal becomes a linked follow-up request; its outcome is a new decision version that supersedes the earlier one, and both stay visible." },
    ],
  },
  {
    slug: "incidents",
    title: "Reporting local issues",
    summary: "Reporting a pothole, broken light or similar, and following it to resolution.",
    workspaces: ["citizen", "authority"],
    paths: ["/incidents", "/authority/incidents"],
    keywords: ["incident", "report", "pothole", "streetlight", "photo", "voice", "location", "duplicate", "feedback"],
    body: [
      { h: "Reporting", ul: [
        "Describe the issue and choose the municipality. If you leave the category empty, a keyword rule suggests one from your text.",
        "Your location is rounded on your device to about 110 metres before it is sent; precise coordinates are never stored.",
        "You can add a photo, an audio file or a recorded voice note. Photos are not analysed automatically. Voice notes are not transcribed in this installation (a transcript appears only for the bundled demo audio), and the original audio is kept for staff.",
        "Without a connection the report is queued on this device and sent when you are back online.",
      ] },
      { h: "Following up", ul: [
        "Public updates show the status and the municipality's notes, never staff names.",
        "When the issue is marked resolved you can confirm and close it with a rating, or say it is not fixed, which reopens it.",
        "Staff may merge your report with an existing report of the same problem; progress is then tracked on the original.",
      ] },
      { h: "For municipal staff", p: "The incident queue shows reports for your municipality with SLA due dates. Triage sets category and priority, then assign, start and resolve. Resolving needs a description and can include a photo or PDF as evidence. Possible duplicates are suggested from category, distance and text similarity." },
    ],
  },
  {
    slug: "video-meetings",
    title: "Video meetings and troubleshooting",
    summary: "Scheduling, the waiting room, sharing documents and fixing camera or connection problems.",
    workspaces: "all",
    paths: ["/meetings"],
    keywords: ["video", "meeting", "call", "camera", "microphone", "screen", "waiting room", "interpreter", "livekit"],
    body: [
      { h: "How meetings work", ul: [
        "Meetings belong to a case and are scheduled from the case page. Times are shown in your time zone and in the organiser's time zone.",
        "Only people with a role on the case can be invited. Inviting an interpreter gives them access to the meeting only, not to the case or documents.",
        "The host opens the meeting. Everyone else asks to join and waits until the host admits them. The host can remove participants and end the meeting.",
        "Recording is disabled in this installation.",
      ] },
      { h: "Shared documents", p: "Documents shared in a meeting are checked for each viewer separately. If your consent or delegation does not cover a document, you see that it was shared but cannot open it." },
      { h: "Troubleshooting", ul: [
        "No camera or microphone: allow access in the browser's site settings, close other apps that use the camera, then press Connect again.",
        "Screen sharing needs a desktop browser; mobile browsers usually do not support it.",
        "\"Connection lost\": check your network and press Connect again. Media uses UDP ports that some networks block.",
        "If you were removed by the host, you cannot reconnect until the host admits you again.",
        "This installation is configured for use on the same computer. Joining from other devices needs the host setup described in docs/VIDEO_SETUP.md.",
      ] },
    ],
  },
  {
    slug: "ai-modes",
    title: "AI assistance: modes and limits",
    summary: "What the assistant does, what it never does, and how translation works.",
    workspaces: "all",
    paths: ["/translations", "/governance/ai"],
    keywords: ["ai", "assistant", "summary", "translation", "mock", "ollama", "rules", "model", "citation"],
    body: [
      { h: "Modes", ul: [
        "Rules: deterministic rules and templates only, no generated text.",
        "Mock (the default): deterministic, labelled demo outputs. No model, no downloads, no external services.",
        "Ollama (optional): a local model started separately. Answers must still cite sources; otherwise the extractive answer is used.",
      ] },
      { h: "What AI never does", p: "The assistant cannot submit applications, issue or approve decisions, deny eligibility, release records, dispatch emergency services, delete data or change a case's state. Sending a message it drafted always needs your explicit approval. Every AI tool call is recorded." },
      { h: "Translation", ul: [
        "In mock mode only phrases from the small demo glossary are translated. Everything else is shown as untranslated, never guessed.",
        "Translations can be reviewed and approved by you or by a delegated professional with translation-review scope.",
        "No translation is certified.",
      ] },
    ],
  },
  {
    slug: "emergency-offline",
    title: "Emergency notices and working offline",
    summary: "Notices from authorities, what happens without a connection, and resolving conflicts.",
    workspaces: ["citizen", "authority"],
    paths: ["/continuity", "/authority/notices"],
    keywords: ["offline", "emergency", "notice", "sync", "conflict", "draft", "outbox", "connection"],
    body: [
      { p: "CivicBridge is not an emergency service. In danger, call your local emergency number." },
      { h: "Emergency notices", p: "Authority supervisors can publish notices. Each notice names its source, which in this installation is always a synthetic demo authority, not an official alerting channel." },
      { h: "Offline", ul: [
        "The app shell is cached, so pages open without a connection, but case data is not stored offline.",
        "Incident reports and drafts you make offline go into an outbox on this device. The outbox is stored in the browser and is not encrypted.",
        "When the connection returns, queued items are sent automatically. Each item is applied once, even if it is sent twice.",
        "If a draft was changed on another device in the meantime, Continuity shows both versions and you choose which to keep.",
      ] },
    ],
  },
  {
    slug: "privacy",
    title: "Privacy, exports and deletion",
    summary: "Getting a copy of your data and asking for deletion.",
    workspaces: ["citizen"],
    paths: ["/privacy"],
    keywords: ["privacy", "export", "download", "delete", "erase", "gdpr", "data"],
    body: [
      { h: "Export", p: "Request an export to receive a ZIP file with your profile, cases, tasks, requests, messages, documents (all versions), consents, delegations, incident reports, screenings and notifications. The file is scanned before you can download it and expires after 7 days." },
      { h: "Deletion", ul: [
        "Deletion erases your documents, revokes your consents and delegations, anonymises your incident reports and deactivates your account.",
        "Cases that contain an authority decision are kept, because authorities keep records of their decisions (an illustrative rule in this demo). The request result says what was kept and why.",
        "The audit log is kept. Deletion cannot be undone.",
      ] },
    ],
  },
  {
    slug: "admin-operations",
    title: "Administrator operations",
    summary: "Policies, audit verification, risks, incidents, integrations and jobs.",
    workspaces: ["governance"],
    paths: ["/governance"],
    keywords: ["admin", "policy", "audit", "verify", "risk", "breach", "integration", "job", "dead letter", "backup", "quality"],
    body: [
      { ul: [
        "Policies: governance administrators can change unlocked values such as session timeouts, upload limits and AI mode. Locked policies (for example meeting recording) cannot be changed here.",
        "Audit: events are pseudonymised for governance viewers. Verify chain recomputes the hash chain and reports the first broken event. The chain is tamper-evident, not tamper-proof: a database superuser could rewrite it, so compare the head hash with an anchor stored elsewhere.",
        "Security and privacy incidents follow open, triaged, contained, notified, closed. A breach involving personal data cannot be closed without recording the notification step, and shows a notification deadline.",
        "Integrations: every adapter is mock, public data or sandbox; none is connected to a live government system. You can run a health check, disable an adapter or inject timeouts and errors to test retries.",
        "Jobs: background work runs in a database queue. Failed jobs retry with back-off and then move to the dead-letter list, where an administrator can re-queue them.",
        "Reporting: aggregate figures hide groups smaller than the suppression threshold (5 by default).",
        "Backups and restore checks are run from the command line; see docs/OPERATIONS.md.",
      ] },
    ],
  },
];

/** The article for a route: longest matching path prefix, "/" only for the exact home page. */
export function helpFor(path: string): string | undefined {
  let best: { slug: string; len: number } | undefined;
  for (const a of ARTICLES) {
    for (const p of a.paths) {
      const hit = p === "/" ? path === "/" : path === p || path.startsWith(`${p}/`);
      if (hit && (!best || p.length > best.len)) best = { slug: a.slug, len: p.length };
    }
  }
  return best?.slug;
}
