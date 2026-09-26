import { Route, Routes } from "react-router-dom";

import { RequireAuth, RequireRole } from "./auth/RequireAuth";
import { AuthProvider } from "./auth/AuthProvider";
import { Layout } from "./components/Layout";
import { LoginPage } from "./pages/LoginPage";
import { EvalsPage, PapersPage, RunsPage, SystemMapPage, UsersPage } from "./pages/PlaceholderPages";

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
            <Route element={<RequireRole role="admin" />}>
              <Route path="/users" element={<UsersPage />} />
            </Route>
          </Route>
        </Route>
      </Routes>
    </AuthProvider>
  );
}
