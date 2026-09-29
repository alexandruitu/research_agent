import type { MouseEvent } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { hasRole } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { DirtyGuardProvider, useLeaveGuard } from "../features/settings/dirtyGuard";

const TABS = [
  { to: "/settings/sources", label: "Sources" },
  { to: "/settings/reviewers", label: "Reviewers" },
  { to: "/settings/models", label: "AI models" },
  { to: "/settings/screening", label: "Screening" },
  { to: "/settings/fulltext", label: "Full text" },
];

function Tabs({ admin }: { admin: boolean }) {
  const { confirmLeave } = useLeaveGuard();
  const guard = (event: MouseEvent) => {
    if (!confirmLeave()) event.preventDefault();
  };
  return (
    <nav aria-label="Settings sections" className="tabs">
      {TABS.map((tab) => <NavLink key={tab.to} to={tab.to} onClick={guard}>{tab.label}</NavLink>)}
      {admin && <NavLink to="/settings/users" onClick={guard}>Users</NavLink>}
    </nav>
  );
}

export function SettingsPage() {
  const { user } = useAuth();
  const admin = hasRole(user, "admin");
  return (
    <DirtyGuardProvider>
      <section>
        <h1>Settings</h1>
        <Tabs admin={admin} />
        {!admin && <p className="sub">Read-only: only admins change settings. Every run records the settings version it used.</p>}
        <Outlet />
      </section>
    </DirtyGuardProvider>
  );
}
