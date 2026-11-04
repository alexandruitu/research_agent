import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";

import { useRuns } from "./api/hooks";
import { RequireAuth, RequireRole } from "./auth/RequireAuth";
import { Skeleton } from "./components/ui/Skeleton";
import { FEATURES } from "./config";
import { AuthProvider } from "./auth/AuthProvider";
import { Layout } from "./components/Layout";
import { LoginPage } from "./pages/LoginPage";

// Each page is its own chunk, loaded when first opened: the sign-in page and the shell load fast.
const ModelsTab = lazy(() => import("./features/settings/ModelsTab").then((m) => ({ default: m.ModelsTab })));
const FulltextTab = lazy(() => import("./features/settings/FulltextTab").then((m) => ({ default: m.FulltextTab })));
const ReviewerEditorPage = lazy(() => import("./features/settings/ReviewerEditor").then((m) => ({ default: m.ReviewerEditorPage })));
const ReviewersTab = lazy(() => import("./features/settings/ReviewersTab").then((m) => ({ default: m.ReviewersTab })));
const ScreeningTab = lazy(() => import("./features/settings/ScreeningTab").then((m) => ({ default: m.ScreeningTab })));
const SourcesTab = lazy(() => import("./features/settings/SourcesTab").then((m) => ({ default: m.SourcesTab })));
const AlertsPage = lazy(() => import("./pages/AlertsPage").then((m) => ({ default: m.AlertsPage })));
const ComparePage = lazy(() => import("./pages/ComparePage").then((m) => ({ default: m.ComparePage })));
const EvalReportPage = lazy(() => import("./pages/EvalReportPage").then((m) => ({ default: m.EvalReportPage })));
const EvalsHomePage = lazy(() => import("./pages/EvalsHomePage").then((m) => ({ default: m.EvalsHomePage })));
const NewEvalPage = lazy(() => import("./pages/NewEvalPage").then((m) => ({ default: m.NewEvalPage })));
const FieldEditorPage = lazy(() => import("./pages/FieldEditorPage").then((m) => ({ default: m.FieldEditorPage })));
const FieldsPage = lazy(() => import("./pages/FieldsPage").then((m) => ({ default: m.FieldsPage })));
const LibraryPage = lazy(() => import("./pages/LibraryPage").then((m) => ({ default: m.LibraryPage })));
const SignupPage = lazy(() => import("./pages/SignupPage").then((m) => ({ default: m.SignupPage })));
const MyKeysTab = lazy(() => import("./features/me/MyKeysTab").then((m) => ({ default: m.MyKeysTab })));
const MyModelsTab = lazy(() => import("./features/me/MyModelsTab").then((m) => ({ default: m.MyModelsTab })));
const MyUsageTab = lazy(() => import("./features/me/MyUsageTab").then((m) => ({ default: m.MyUsageTab })));
const RatePage = lazy(() => import("./pages/RatePage").then((m) => ({ default: m.RatePage })));
const PapersPage = lazy(() => import("./pages/PapersPage").then((m) => ({ default: m.PapersPage })));
const ReaderPage = lazy(() => import("./pages/ReaderPage").then((m) => ({ default: m.ReaderPage })));
const RunComparePage = lazy(() => import("./pages/RunComparePage").then((m) => ({ default: m.RunComparePage })));
const RunDetailPage = lazy(() => import("./pages/RunDetailPage").then((m) => ({ default: m.RunDetailPage })));
const RunsPage = lazy(() => import("./pages/RunsPage").then((m) => ({ default: m.RunsPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));
const SystemMapPage = lazy(() => import("./pages/SystemMapPage").then((m) => ({ default: m.SystemMapPage })));
const HowItWorksPage = lazy(() => import("./pages/HowItWorksPage").then((m) => ({ default: m.HowItWorksPage })));
const ValidationPage = lazy(() => import("./pages/ValidationPage").then((m) => ({ default: m.ValidationPage })));
const UsersPage = lazy(() => import("./pages/UsersPage").then((m) => ({ default: m.UsersPage })));

/** Old top-level URL → its place under Validation, keeping the rest of the path, the query and the hash. */
function MovedTo({ to }: { to: string }) {
  const { search, hash } = useLocation();
  const rest = useParams()["*"];
  return <Navigate to={`${to}${rest ? `/${rest}` : ""}${search}${hash}`} replace />;
}

/** "/": old Papers links (`/?run=…&paper=…`) go to Results with their query and hash; a bare visit lands on
 *  Results once any search exists, else on Topics, the first step. */
function Home() {
  const { search, hash } = useLocation();
  const runs = useRuns();
  if (search || hash) return <Navigate to={`/results${search}${hash}`} replace />;
  if (runs.isLoading) return <section><Skeleton label="your searches" rows={4} /></section>;
  return <Navigate to={(runs.data ?? []).length > 0 ? "/results" : "/topics"} replace />;
}

export function App() {
  return (
    <AuthProvider>
      <Suspense fallback={<Skeleton label="the page" rows={4} />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route element={<RequireAuth />}>
          <Route element={<Layout />}>
            <Route path="/" element={<Home />} />
            <Route path="/results" element={<PapersPage />} />
            <Route path="/library" element={<LibraryPage />} />
            <Route path="/read/:runId/:paperId" element={<ReaderPage />} />
            <Route path="/screening" element={<RunsPage />} />
            <Route path="/screening/compare" element={<RunComparePage />} />
            <Route path="/screening/:runId" element={<RunDetailPage />} />
            {/* "/search" is the plain-language name of the same pages; links keep using /screening */}
            <Route path="/search" element={<RunsPage />} />
            <Route path="/search/compare" element={<RunComparePage />} />
            <Route path="/search/:runId" element={<RunDetailPage />} />
            <Route path="/topics" element={<FieldsPage />} />
            {FEATURES.alerts && <Route path="/alerts" element={<AlertsPage />} />}
            <Route element={<RequireRole role="member" />}>
              <Route path="/topics/new" element={<FieldEditorPage />} />
              <Route path="/rate/:sampleId" element={<RatePage />} />
            </Route>
            <Route path="/topics/:fieldId" element={<FieldEditorPage />} />
            {/* the flow's old names: Fields → Topics, Runs → Screening (shown as Search), Papers → Results */}
            <Route path="/fields/*" element={<MovedTo to="/topics" />} />
            <Route path="/runs/*" element={<MovedTo to="/screening" />} />
            <Route path="/papers/*" element={<MovedTo to="/results" />} />
            <Route path="/validation" element={<ValidationPage />}>
              <Route index element={<Navigate to="evals" replace />} />
              <Route path="evals" element={<EvalsHomePage />} />
              <Route element={<RequireRole role="member" />}>
                <Route path="evals/new" element={<NewEvalPage />} />
              </Route>
              <Route path="evals/compare" element={<ComparePage />} />
              <Route path="evals/:evalId" element={<EvalReportPage />} />
              <Route path="system" element={<SystemMapPage />} />
              <Route path="how-it-works" element={<HowItWorksPage />} />
            </Route>
            <Route path="/evals/*" element={<MovedTo to="/validation/evals" />} />
            <Route path="/system/*" element={<MovedTo to="/validation/system" />} />
            <Route path="/settings" element={<SettingsPage />}>
              <Route index element={<Navigate to="sources" replace />} />
              <Route path="sources" element={<SourcesTab />} />
              <Route path="models" element={<ModelsTab />} />
              <Route path="reviewers" element={<ReviewersTab />} />
              <Route element={<RequireRole role="admin" />}>
                <Route path="reviewers/new" element={<ReviewerEditorPage />} />
              </Route>
              <Route path="reviewers/:reviewerKey" element={<ReviewerEditorPage />} />
              <Route path="screening" element={<ScreeningTab />} />
              <Route path="fulltext" element={<FulltextTab />} />
              <Route element={<RequireRole role="member" />}>
                <Route path="keys" element={<MyKeysTab />} />
                <Route path="my-models" element={<MyModelsTab />} />
                <Route path="usage" element={<MyUsageTab />} />
              </Route>
              <Route element={<RequireRole role="admin" />}>
                <Route path="users" element={<UsersPage />} />
              </Route>
            </Route>
            <Route path="/users" element={<Navigate to="/settings/users" replace />} />
            {/* hidden features (FEATURES) and unknown paths land on the start page */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Route>
      </Routes>
      </Suspense>
    </AuthProvider>
  );
}
