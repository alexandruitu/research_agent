import { Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";

import { useRuns } from "./api/hooks";
import { RequireAuth, RequireRole } from "./auth/RequireAuth";
import { Skeleton } from "./components/ui/Skeleton";
import { FEATURES } from "./config";
import { AuthProvider } from "./auth/AuthProvider";
import { Layout } from "./components/Layout";
import { ModelsTab } from "./features/settings/ModelsTab";
import { FulltextTab } from "./features/settings/FulltextTab";
import { ReviewerEditorPage } from "./features/settings/ReviewerEditor";
import { ReviewersTab } from "./features/settings/ReviewersTab";
import { ScreeningTab } from "./features/settings/ScreeningTab";
import { SourcesTab } from "./features/settings/SourcesTab";
import { AlertsPage } from "./pages/AlertsPage";
import { ComparePage } from "./pages/ComparePage";
import { EvalReportPage } from "./pages/EvalReportPage";
import { EvalsHomePage } from "./pages/EvalsHomePage";
import { NewEvalPage } from "./pages/NewEvalPage";
import { FieldEditorPage } from "./pages/FieldEditorPage";
import { FieldsPage } from "./pages/FieldsPage";
import { LibraryPage } from "./pages/LibraryPage";
import { LoginPage } from "./pages/LoginPage";
import { RatePage } from "./pages/RatePage";
import { PapersPage } from "./pages/PapersPage";
import { ReaderPage } from "./pages/ReaderPage";
import { RunComparePage } from "./pages/RunComparePage";
import { RunDetailPage } from "./pages/RunDetailPage";
import { RunsPage } from "./pages/RunsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SystemMapPage } from "./pages/SystemMapPage";
import { HowItWorksPage } from "./pages/HowItWorksPage";
import { ValidationPage } from "./pages/ValidationPage";
import { UsersPage } from "./pages/UsersPage";

/** Old top-level URL → its place under Validation, keeping the rest of the path, the query and the hash. */
function MovedTo({ to }: { to: string }) {
  const { search, hash } = useLocation();
  const rest = useParams()["*"];
  return <Navigate to={`${to}${rest ? `/${rest}` : ""}${search}${hash}`} replace />;
}

/** "/": old Papers links (`/?run=…&paper=…`) go to Results with their query and hash; a bare visit lands on
 *  Results once any run exists, else on Topics, the first step. */
function Home() {
  const { search, hash } = useLocation();
  const runs = useRuns();
  if (search || hash) return <Navigate to={`/results${search}${hash}`} replace />;
  if (runs.isLoading) return <section><Skeleton label="the runs" rows={4} /></section>;
  return <Navigate to={(runs.data ?? []).length > 0 ? "/results" : "/topics"} replace />;
}

export function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAuth />}>
          <Route element={<Layout />}>
            <Route path="/" element={<Home />} />
            <Route path="/results" element={<PapersPage />} />
            <Route path="/library" element={<LibraryPage />} />
            <Route path="/read/:runId/:paperId" element={<ReaderPage />} />
            <Route path="/screening" element={<RunsPage />} />
            <Route path="/screening/compare" element={<RunComparePage />} />
            <Route path="/screening/:runId" element={<RunDetailPage />} />
            <Route path="/topics" element={<FieldsPage />} />
            {FEATURES.alerts && <Route path="/alerts" element={<AlertsPage />} />}
            <Route element={<RequireRole role="member" />}>
              <Route path="/topics/new" element={<FieldEditorPage />} />
              <Route path="/rate/:sampleId" element={<RatePage />} />
            </Route>
            <Route path="/topics/:fieldId" element={<FieldEditorPage />} />
            {/* the flow's old names: Fields → Topics, Runs → Screening, Papers → Results */}
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
    </AuthProvider>
  );
}
