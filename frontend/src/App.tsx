import { lazy, Suspense, useEffect, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router";
import { useAuth, WORKSPACE_HOME } from "./lib/auth";
import { Layout } from "./components/Layout";
import { Loading } from "./components/ui";
import { Login } from "./pages/public/Login";
import { useOnline, outbox } from "./lib/offline";
import { usePrefs } from "./lib/prefs";
import { useI18n } from "./lib/i18n";
import { useQueryClient } from "@tanstack/react-query";

const L = <T extends Record<string, any>>(f: () => Promise<T>, name: keyof T) => lazy(() => f().then((m) => ({ default: m[name] })));

const Forgot = L(() => import("./pages/public/Recovery"), "ForgotPassword");
const Reset = L(() => import("./pages/public/Recovery"), "ResetPassword");
const Register = L(() => import("./pages/public/Recovery"), "Register");
const VerifyEmail = L(() => import("./pages/public/Recovery"), "VerifyEmail");
const Transparency = L(() => import("./pages/public/Transparency"), "Transparency");
const CitizenHome = L(() => import("./pages/citizen/Overview"), "CitizenOverview");
const Journeys = L(() => import("./pages/citizen/Journeys"), "Journeys");
const Cases = L(() => import("./pages/shared/Cases"), "CaseList");
const CaseDetail = L(() => import("./pages/shared/CaseDetail"), "CaseDetail");
const Wallet = L(() => import("./pages/citizen/Wallet"), "Wallet");
const DocumentDetail = L(() => import("./pages/citizen/DocumentDetail"), "DocumentDetail");
const Consent = L(() => import("./pages/citizen/Consent"), "ConsentCenter");
const Delegations = L(() => import("./pages/citizen/Delegations"), "Delegations");
const Rights = L(() => import("./pages/citizen/Rights"), "Rights");
const Translations = L(() => import("./pages/shared/Translations"), "Translations");
const TranslationDetail = L(() => import("./pages/shared/Translations"), "TranslationDetail");
const Incidents = L(() => import("./pages/citizen/Incidents"), "Incidents");
const IncidentDetail = L(() => import("./pages/shared/IncidentDetail"), "IncidentDetail");
const Continuity = L(() => import("./pages/citizen/Continuity"), "Continuity");
const Privacy = L(() => import("./pages/citizen/Privacy"), "Privacy");
const AuthorityHome = L(() => import("./pages/authority/Dashboard"), "AuthorityDashboard");
const Queue = L(() => import("./pages/authority/Queue"), "Queue");
const RequestReview = L(() => import("./pages/authority/RequestReview"), "RequestReview");
const IncidentQueue = L(() => import("./pages/authority/IncidentQueue"), "IncidentQueue");
const Notices = L(() => import("./pages/authority/Notices"), "Notices");
const AuthorityConsents = L(() => import("./pages/authority/Notices"), "AuthorityConsents");
const InstitutionHome = L(() => import("./pages/shared/Workspaces"), "InstitutionOverview");
const ProfessionalHome = L(() => import("./pages/shared/Workspaces"), "ProfessionalOverview");
const GovHome = L(() => import("./pages/governance/Overview"), "GovernanceOverview");
const GovAudit = L(() => import("./pages/governance/Audit"), "Audit");
const GovPolicies = L(() => import("./pages/governance/Admin"), "Policies");
const GovRisks = L(() => import("./pages/governance/Admin"), "Risks");
const GovIncidents = L(() => import("./pages/governance/Admin"), "SecurityIncidents");
const GovIntegrations = L(() => import("./pages/governance/Ops"), "Integrations");
const GovJobs = L(() => import("./pages/governance/Ops"), "Jobs");
const GovQuality = L(() => import("./pages/governance/Ops"), "DataQuality");
const GovReporting = L(() => import("./pages/governance/Ops"), "Reporting");
const GovAI = L(() => import("./pages/governance/Ops"), "AIOversight");
const Notifications = L(() => import("./pages/shared/Notifications"), "Notifications");
const Account = L(() => import("./pages/shared/Account"), "Account");
const Meetings = L(() => import("./pages/shared/Meetings"), "Meetings");
const MeetingRoom = L(() => import("./pages/shared/MeetingRoom"), "MeetingRoom");
const Help = L(() => import("./pages/shared/Help"), "Help");
const MfaVerify = L(() => import("./pages/public/Mfa"), "MfaVerify");

/** Replays queued offline operations whenever the connection returns or the user signs in. */
function SyncOnReconnect() {
  const { me } = useAuth();
  const online = useOnline();
  const { toast } = usePrefs();
  const { t } = useI18n();
  const qc = useQueryClient();
  useEffect(() => {
    if (!online || !me || me.user.read_only || !outbox.list(me.user.id).length) return;
    outbox
      .flush(me.user.id)
      .then((r) => {
        if (r.applied) toast(t("offline.synced", { n: r.applied }), "success");
        if (r.conflicts) toast(t("offline.conflicts", { n: r.conflicts }), "info");
        qc.invalidateQueries();
      })
      .catch(() => undefined);
  }, [online, me, toast, t, qc]);
  return null;
}

function Protected({ children, ws }: { children: ReactNode; ws?: string[] }) {
  const { me, loading, expired } = useAuth();
  const loc = useLocation();
  if (loading) return <Loading />;
  if (!me) return <Navigate to={`/login${expired ? "?expired=1" : ""}`} state={{ from: loc.pathname }} replace />;
  if (me.mfa_required) return <Navigate to="/mfa" replace />;
  const current = me.active?.workspace || "citizen";
  if (ws && !ws.includes(current)) return <Navigate to={WORKSPACE_HOME[current]} replace />;
  return <Layout>{children}</Layout>;
}

function Home() {
  const { me } = useAuth();
  const ws = me?.active?.workspace || "citizen";
  if (ws !== "citizen") return <Navigate to={WORKSPACE_HOME[ws]} replace />;
  return <CitizenHome />;
}

export default function App() {
  const C = ["citizen"];
  return (
    <BrowserRouter>
      <SyncOnReconnect />
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/mfa" element={<MfaVerify />} />
          <Route path="/forgot-password" element={<Forgot />} />
          <Route path="/reset-password" element={<Reset />} />
          <Route path="/register" element={<Register />} />
          <Route path="/verify-email" element={<VerifyEmail />} />
          <Route path="/transparency" element={<Transparency />} />

          <Route path="/" element={<Protected><Home /></Protected>} />
          <Route path="/journeys" element={<Protected ws={C}><Journeys /></Protected>} />
          <Route path="/cases" element={<Protected ws={["citizen", "institution", "professional"]}><Cases /></Protected>} />
          <Route path="/cases/:id" element={<Protected ws={["citizen", "institution", "professional", "authority"]}><CaseDetail /></Protected>} />
          <Route path="/wallet" element={<Protected ws={C}><Wallet /></Protected>} />
          <Route path="/wallet/:id" element={<Protected ws={["citizen", "professional", "authority", "institution"]}><DocumentDetail /></Protected>} />
          <Route path="/consent" element={<Protected ws={C}><Consent /></Protected>} />
          <Route path="/delegations" element={<Protected ws={C}><Delegations /></Protected>} />
          <Route path="/rights" element={<Protected ws={["citizen", "professional"]}><Rights /></Protected>} />
          <Route path="/translations" element={<Protected ws={["citizen", "professional"]}><Translations /></Protected>} />
          <Route path="/translations/:id" element={<Protected ws={["citizen", "professional"]}><TranslationDetail /></Protected>} />
          <Route path="/incidents" element={<Protected ws={C}><Incidents /></Protected>} />
          <Route path="/incidents/:id" element={<Protected ws={C}><IncidentDetail /></Protected>} />
          <Route path="/continuity" element={<Protected ws={C}><Continuity /></Protected>} />
          <Route path="/privacy" element={<Protected ws={C}><Privacy /></Protected>} />

          <Route path="/authority" element={<Protected ws={["authority"]}><AuthorityHome /></Protected>} />
          <Route path="/authority/queue" element={<Protected ws={["authority"]}><Queue /></Protected>} />
          <Route path="/authority/requests/:id" element={<Protected ws={["authority"]}><RequestReview /></Protected>} />
          <Route path="/authority/incidents" element={<Protected ws={["authority"]}><IncidentQueue /></Protected>} />
          <Route path="/authority/incidents/:id" element={<Protected ws={["authority"]}><IncidentDetail /></Protected>} />
          <Route path="/authority/notices" element={<Protected ws={["authority"]}><Notices /></Protected>} />
          <Route path="/authority/consents" element={<Protected ws={["authority"]}><AuthorityConsents /></Protected>} />

          <Route path="/institution" element={<Protected ws={["institution"]}><InstitutionHome /></Protected>} />
          <Route path="/professional" element={<Protected ws={["professional"]}><ProfessionalHome /></Protected>} />

          <Route path="/governance" element={<Protected ws={["governance"]}><GovHome /></Protected>} />
          <Route path="/governance/audit" element={<Protected ws={["governance"]}><GovAudit /></Protected>} />
          <Route path="/governance/policies" element={<Protected ws={["governance"]}><GovPolicies /></Protected>} />
          <Route path="/governance/risks" element={<Protected ws={["governance"]}><GovRisks /></Protected>} />
          <Route path="/governance/incidents" element={<Protected ws={["governance"]}><GovIncidents /></Protected>} />
          <Route path="/governance/integrations" element={<Protected ws={["governance"]}><GovIntegrations /></Protected>} />
          <Route path="/governance/jobs" element={<Protected ws={["governance"]}><GovJobs /></Protected>} />
          <Route path="/governance/quality" element={<Protected ws={["governance"]}><GovQuality /></Protected>} />
          <Route path="/governance/reporting" element={<Protected ws={["governance"]}><GovReporting /></Protected>} />
          <Route path="/governance/ai" element={<Protected ws={["governance"]}><GovAI /></Protected>} />

          <Route path="/notifications" element={<Protected><Notifications /></Protected>} />
          <Route path="/account" element={<Protected><Account /></Protected>} />
          <Route path="/meetings" element={<Protected><Meetings /></Protected>} />
          <Route path="/meetings/:id" element={<Protected><MeetingRoom /></Protected>} />
          <Route path="/help" element={<Protected><Help /></Protected>} />
          <Route path="/help/:slug" element={<Protected><Help /></Protected>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
