import { NavLink, Outlet } from "react-router-dom";

import { hasRole } from "../api/types";
import { useAuth } from "../auth/AuthProvider";

export function SettingsPage() {
  const { user } = useAuth();
  const admin = hasRole(user, "admin");
  return (
    <section>
      <h1>Settings</h1>
      <nav aria-label="Settings sections" className="tabs">
        <NavLink to="/settings/sources">Sources</NavLink>
        <NavLink to="/settings/models">AI models</NavLink>
        {admin && <NavLink to="/settings/users">Users</NavLink>}
      </nav>
      {!admin && <p className="sub">Read-only: only admins change settings.</p>}
      <Outlet />
    </section>
  );
}
