import { Navigate, Route, Routes } from "react-router-dom";

import { RequireAuth, RequireRole } from "./auth/RequireAuth";
import { AuthProvider } from "./auth/AuthProvider";
import { Layout } from "./components/Layout";
import { ModelsTab } from "./features/settings/ModelsTab";
import { FulltextTab } from "./features/settings/FulltextTab";
import { ScreeningTab } from "./features/settings/ScreeningTab";
import { SourcesTab } from "./features/settings/SourcesTab";
import { EvalsPage } from "./pages/EvalsPage";
import { FieldEditorPage } from "./pages/FieldEditorPage";
import { FieldsPage } from "./pages/FieldsPage";
import { LoginPage } from "./pages/LoginPage";
import { PapersPage } from "./pages/PapersPage";
import { RunsPage } from "./pages/RunsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SystemMapPage } from "./pages/SystemMapPage";
import { UsersPage } from "./pages/UsersPage";

export function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAuth />}>
          <Route element={<Layout />}>
            <Route path="/" element={<PapersPage />} />
            <Route path="/runs" element={<RunsPage />} />
            <Route path="/fields" element={<FieldsPage />} />
            <Route element={<RequireRole role="member" />}>
              <Route path="/fields/new" element={<FieldEditorPage />} />
            </Route>
            <Route path="/fields/:fieldId" element={<FieldEditorPage />} />
            <Route path="/evals" element={<EvalsPage />} />
            <Route path="/evals/:evalId" element={<EvalsPage />} />
            <Route path="/system" element={<SystemMapPage />} />
            <Route path="/settings" element={<SettingsPage />}>
              <Route index element={<Navigate to="sources" replace />} />
              <Route path="sources" element={<SourcesTab />} />
              <Route path="models" element={<ModelsTab />} />
              <Route path="screening" element={<ScreeningTab />} />
              <Route path="fulltext" element={<FulltextTab />} />
              <Route element={<RequireRole role="admin" />}>
                <Route path="users" element={<UsersPage />} />
              </Route>
            </Route>
            <Route path="/users" element={<Navigate to="/settings/users" replace />} />
          </Route>
        </Route>
      </Routes>
    </AuthProvider>
  );
}
