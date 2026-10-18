import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, Link, useLocation, useNavigate } from "react-router";
import {
  Activity, AlertOctagon, BarChart3, Bell, BookOpen, Briefcase, Building2, CalendarClock, ClipboardList, Cpu, Database, FileStack,
  FolderOpen, Gauge, HandHeart, HelpCircle, Home, Landmark, Languages, LifeBuoy, ListChecks, LogOut, Map, Megaphone, Menu, MessageSquareWarning,
  Moon, Palette, Plug, Scale, ScrollText, Settings, Shield, ShieldCheck, Siren, Sun, User, Users, Video, WifiOff,
} from "lucide-react";
import { useAuth, WORKSPACE_HOME } from "../lib/auth";
import { LOCALES, useI18n } from "../lib/i18n";
import { usePrefs, type Theme } from "../lib/prefs";
import { useOnline, useOutbox, outbox } from "../lib/offline";
import { useApi, Confirm, CreditFooter } from "./ui";
import { helpFor } from "../help/articles";

type Item = { to: string; label: string; icon: ReactNode; end?: boolean };
const I = 18;

function useNav(): { group?: string; items: Item[] }[] {
  const { me } = useAuth();
  const { t } = useI18n();
  const ws = me?.active?.workspace || "citizen";
  const role = me?.active?.role;
  const handles = useApi<{ handles_incidents: boolean }>(["authority-stats"], ws === "authority" ? "/api/authority/stats" : null);
  const common: Item[] = [
    { to: "/meetings", label: t("nav.meetings"), icon: <Video size={I} /> },
    { to: "/notifications", label: t("nav.notifications"), icon: <Bell size={I} /> },
  ];
  if (ws === "authority")
    return [
      {
        items: [
          { to: "/authority", label: t("nav.dashboard"), icon: <Gauge size={I} />, end: true },
          { to: "/authority/queue", label: t("nav.queue"), icon: <ClipboardList size={I} /> },
          ...(handles.data?.handles_incidents ? [{ to: "/authority/incidents", label: t("nav.incidentQueue"), icon: <MessageSquareWarning size={I} /> }] : []),
          { to: "/authority/consents", label: t("nav.consentRequests"), icon: <ShieldCheck size={I} /> },
          ...(role === "authority_supervisor" ? [{ to: "/authority/notices", label: t("nav.notices"), icon: <Megaphone size={I} /> }] : []),
          ...common,
        ],
      },
    ];
  if (ws === "institution")
    return [{ items: [{ to: "/institution", label: t("nav.overview"), icon: <Building2 size={I} />, end: true }, { to: "/cases", label: t("nav.sharedCases"), icon: <FolderOpen size={I} /> }, ...common] }];
  if (ws === "professional")
    return [
      {
        items: [
          { to: "/professional", label: t("nav.overview"), icon: <Briefcase size={I} />, end: true },
          ...(role === "professional" ? [{ to: "/cases", label: t("nav.delegatedCases"), icon: <FolderOpen size={I} /> }, { to: "/translations", label: t("nav.translations"), icon: <Languages size={I} /> }] : []),
          ...common,
        ],
      },
    ];
  if (ws === "governance")
    return [
      {
        items: [
          { to: "/governance", label: t("nav.overview"), icon: <Gauge size={I} />, end: true },
          { to: "/governance/audit", label: t("nav.audit"), icon: <ScrollText size={I} /> },
          { to: "/governance/policies", label: t("nav.policies"), icon: <Settings size={I} /> },
          { to: "/governance/risks", label: t("nav.risks"), icon: <AlertOctagon size={I} /> },
          { to: "/governance/incidents", label: t("nav.securityIncidents"), icon: <Siren size={I} /> },
          { to: "/governance/integrations", label: t("nav.integrations"), icon: <Plug size={I} /> },
          { to: "/governance/jobs", label: t("nav.jobs"), icon: <Activity size={I} /> },
          { to: "/governance/quality", label: t("nav.dataQuality"), icon: <Database size={I} /> },
          { to: "/governance/reporting", label: t("nav.reporting"), icon: <BarChart3 size={I} /> },
          { to: "/governance/ai", label: t("nav.aiOversight"), icon: <Cpu size={I} /> },
          { to: "/notifications", label: t("nav.notifications"), icon: <Bell size={I} /> },
        ],
      },
    ];
  return [
    {
      items: [
        { to: "/", label: t("nav.overview"), icon: <Home size={I} />, end: true },
        { to: "/journeys", label: t("nav.journeys"), icon: <Map size={I} /> },
        { to: "/cases", label: t("nav.cases"), icon: <FolderOpen size={I} /> },
      ],
    },
    {
      group: t("nav.group.records"),
      items: [
        { to: "/wallet", label: t("nav.wallet"), icon: <FileStack size={I} /> },
        { to: "/consent", label: t("nav.consent"), icon: <ShieldCheck size={I} /> },
        { to: "/delegations", label: t("nav.delegations"), icon: <HandHeart size={I} /> },
      ],
    },
    {
      group: t("nav.group.services"),
      items: [
        { to: "/rights", label: t("nav.rights"), icon: <Scale size={I} /> },
        { to: "/translations", label: t("nav.translations"), icon: <Languages size={I} /> },
        { to: "/incidents", label: t("nav.incidents"), icon: <MessageSquareWarning size={I} /> },
        { to: "/meetings", label: t("nav.meetings"), icon: <Video size={I} /> },
        { to: "/continuity", label: t("nav.continuity"), icon: <LifeBuoy size={I} /> },
        { to: "/privacy", label: t("nav.privacy"), icon: <Shield size={I} /> },
      ],
    },
  ];
}

function useClickOutside(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && close();
    const k = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("mousedown", h);
    document.addEventListener("keydown", k);
    return () => {
      document.removeEventListener("mousedown", h);
      document.removeEventListener("keydown", k);
    };
  }, [open, close]);
  return ref;
}

function ContextSwitcher() {
  const { me, switchTo } = useAuth();
  const { t } = useI18n();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useClickOutside(open, () => setOpen(false));
  if (!me || me.memberships.length < 2) return null;
  return (
    <div className="menu" ref={ref}>
      <button className="btn btn-sm" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        <Users size={15} aria-hidden /> <span className="hide-mobile">{t("context.switch")}</span>
      </button>
      {open && (
        <div className="menu-pop" role="menu">
          <div className="head">{t("context.title")}</div>
          {me.memberships.map((m) => (
            <button
              key={m.id}
              role="menuitemradio"
              aria-checked={me.active?.id === m.id}
              className={me.active?.id === m.id ? "sel" : ""}
              onClick={async () => {
                setOpen(false);
                const r = await switchTo(m.id);
                nav(WORKSPACE_HOME[r.active?.workspace || "citizen"]);
              }}
            >
              <Landmark size={15} aria-hidden />
              <span>
                <b>{t(`role.${m.role}`)}</b>
                <br />
                <span className="xs muted">{m.tenant.name}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function PrefsMenu() {
  const { t, locale, setLocale } = useI18n();
  const { theme, setTheme } = usePrefs();
  const [open, setOpen] = useState(false);
  const ref = useClickOutside(open, () => setOpen(false));
  const themes: { id: Theme; label: string; icon: ReactNode }[] = [
    { id: "system", label: t("theme.system"), icon: <Palette size={15} /> },
    { id: "light", label: t("theme.light"), icon: <Sun size={15} /> },
    { id: "dark", label: t("theme.dark"), icon: <Moon size={15} /> },
    { id: "contrast", label: t("theme.contrast"), icon: <Palette size={15} /> },
  ];
  return (
    <div className="menu" ref={ref}>
      <button className="icon-btn" aria-label={t("prefs.label")} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        <Languages size={19} />
      </button>
      {open && (
        <div className="menu-pop" role="menu">
          <div className="head">{t("prefs.language")}</div>
          {LOCALES.map((l) => (
            <button key={l.code} role="menuitemradio" aria-checked={locale === l.code} className={locale === l.code ? "sel" : ""} onClick={() => setLocale(l.code)} lang={l.code}>
              {l.label}
            </button>
          ))}
          <div className="sep" />
          <div className="head">{t("prefs.theme")}</div>
          {themes.map((th) => (
            <button key={th.id} role="menuitemradio" aria-checked={theme === th.id} className={theme === th.id ? "sel" : ""} onClick={() => setTheme(th.id)}>
              {th.icon} {th.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function UserMenu() {
  const { me, logout } = useAuth();
  const { t } = useI18n();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const ref = useClickOutside(open, () => setOpen(false));
  const pending = me ? outbox.list(me.user.id).length + outbox.conflicts(me.user.id).length : 0;
  const doLogout = async () => {
    await logout();
    nav("/login");
  };
  return (
    <div className="menu" ref={ref}>
      <button className="icon-btn" aria-label={t("user.menu")} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        <User size={19} />
      </button>
      {open && (
        <div className="menu-pop" role="menu">
          <div style={{ padding: "6px 10px" }}>
            <b>{me?.user.display_name}</b>
            <div className="xs muted">{me?.user.email}</div>
          </div>
          <div className="sep" />
          <Link to="/account" role="menuitem" onClick={() => setOpen(false)}>
            <Settings size={15} /> {t("nav.account")}
          </Link>
          <Link to="/help" role="menuitem" onClick={() => setOpen(false)}>
            <BookOpen size={15} /> {t("nav.help")}
          </Link>
          <Link to="/transparency" role="menuitem" onClick={() => setOpen(false)}>
            <BarChart3 size={15} /> {t("nav.transparency")}
          </Link>
          <div className="sep" />
          <button role="menuitem" onClick={() => (pending ? setConfirm(true) : doLogout())}>
            <LogOut size={15} /> {t("user.logout")}
          </button>
        </div>
      )}
      {confirm && (
        <Confirm
          title={t("logout.pendingTitle")}
          body={<p>{t("logout.pendingBody", { n: pending })}</p>}
          confirmLabel={t("logout.discard")}
          danger
          onCancel={() => setConfirm(false)}
          onConfirm={doLogout}
        />
      )}
    </div>
  );
}

function NotificationBell() {
  const { t } = useI18n();
  const q = useApi<{ unread: number }>(["notifications", "count"], "/api/notifications?page_size=1", { refetchInterval: 30000 });
  const n = q.data?.unread || 0;
  return (
    <Link to="/notifications" className="icon-btn" aria-label={t("nav.notificationsCount", { n })}>
      <Bell size={19} />
      {n > 0 && <span className="dot">{n > 99 ? "99+" : n}</span>}
    </Link>
  );
}

function OfflinePill() {
  const { me } = useAuth();
  const online = useOnline();
  const { t } = useI18n();
  const { pending, conflicts } = useOutbox(me?.user.id);
  if (!online)
    return (
      <Link to="/continuity" className="offline-pill off">
        <WifiOff size={13} aria-hidden /> {t("offline.offline")}
      </Link>
    );
  if (pending.length || conflicts.length)
    return (
      <Link to="/continuity" className="offline-pill pending">
        <CalendarClock size={13} aria-hidden /> {t("offline.pending", { n: pending.length + conflicts.length })}
      </Link>
    );
  return null;
}

export function Layout({ children }: { children: ReactNode }) {
  const { me, readOnly } = useAuth();
  const { t } = useI18n();
  const groups = useNav();
  const loc = useLocation();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [loc.pathname]);
  const help = helpFor(loc.pathname);
  const ws = me?.active?.workspace || "citizen";
  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        {t("a11y.skip")}
      </a>
      <div style={{ gridArea: "banner" }}>
        <div className="env-banner">{t("env.banner")}</div>
        {readOnly && <div className="ro-banner">{t("readonly.banner")}</div>}
      </div>
      <header className="header">
        <button className="icon-btn menu-btn" aria-label={t("nav.open")} aria-expanded={open} aria-controls="sidebar" onClick={() => setOpen(!open)}>
          <Menu size={20} />
        </button>
        <Link to={WORKSPACE_HOME[ws]} className="brand">
          <svg width="28" height="28" viewBox="0 0 64 64" aria-hidden>
            <rect width="64" height="64" rx="14" fill="#1f4e79" />
            <path d="M10 42c8-14 36-14 44 0" stroke="#fff" strokeWidth="5" fill="none" strokeLinecap="round" />
            <path d="M18 42v-8M32 42V28M46 42v-8" stroke="#8fd3c7" strokeWidth="5" strokeLinecap="round" />
          </svg>
          <span>
            CivicBridge <small className="hide-mobile">Global AI</small>
          </span>
        </Link>
        <span className="spacer" />
        <OfflinePill />
        <ContextSwitcher />
        <Link to={help ? `/help/${help}` : "/help"} className="icon-btn" aria-label={t("help.contextual")} title={t("help.contextual")}>
          <HelpCircle size={19} />
        </Link>
        <PrefsMenu />
        <NotificationBell />
        <UserMenu />
      </header>
      <div className={`backdrop ${open ? "open" : ""}`} onClick={() => setOpen(false)} />
      <aside id="sidebar" className={`side ${open ? "open" : ""}`} aria-label={t("nav.label")}>
        <div className="ws-label">
          <b>{t(`workspace.${ws}`)}</b>
          <span>{me?.active ? `${t(`role.${me.active.role}`)} · ${me.active.tenant.name}` : ""}</span>
        </div>
        <nav>
          {groups.map((g, gi) => (
            <div key={gi}>
              {g.group && <div className="nav-group">{g.group}</div>}
              {g.items.map((it) => (
                <NavLink key={it.to} to={it.to} end={it.end}>
                  {it.icon}
                  <span>{it.label}</span>
                </NavLink>
              ))}
            </div>
          ))}
          <div className="nav-group">{t("nav.group.support")}</div>
          <NavLink to="/help">
            <BookOpen size={I} /> <span>{t("nav.help")}</span>
          </NavLink>
          <NavLink to="/account">
            <ListChecks size={I} /> <span>{t("nav.account")}</span>
          </NavLink>
        </nav>
      </aside>
      <main id="main" className="main" tabIndex={-1}>
        {children}
        <CreditFooter />
      </main>
    </div>
  );
}
