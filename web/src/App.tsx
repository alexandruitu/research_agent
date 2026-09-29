import { Navigate, Route, Routes } from "react-router-dom";

import { RequireAuth, RequireRole } from "./auth/RequireAuth";
import { AuthProvider } from "./auth/AuthProvider";
import { Layout } from "./components/Layout";
import { EvalsPage } from "./pages/EvalsPage";
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
            <Route path="/evals" element={<EvalsPage />} />
            <Route path="/evals/:evalId" element={<EvalsPage />} />
            <Route path="/system" element={<SystemMapPage />} />
            <Route path="/settings" element={<SettingsPage />}>
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
