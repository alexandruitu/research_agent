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

const MINE = [
  { to: "/settings/keys", label: "My keys" },
  { to: "/settings/my-models", label: "My models" },
  { to: "/settings/usage", label: "My usage" },
];

function Tabs({ admin, member }: { admin: boolean; member: boolean }) {
  const { confirmLeave } = useLeaveGuard();
  const guard = (event: MouseEvent) => {
    if (!confirmLeave()) event.preventDefault();
  };
  return (
    <nav aria-label="Settings sections" className="tabs">
      {TABS.map((tab) => <NavLink key={tab.to} to={tab.to} onClick={guard}>{tab.label}</NavLink>)}
      {member && MINE.map((tab) => <NavLink key={tab.to} to={tab.to} onClick={guard}>{tab.label}</NavLink>)}
      {admin && <NavLink to="/settings/users" onClick={guard}>Users</NavLink>}
    </nav>
  );
}

export function SettingsPage() {
  const { user } = useAuth();
  const admin = hasRole(user, "admin");
  const member = hasRole(user, "member");
  return (
    <DirtyGuardProvider>
      <section>
        <h1>Settings</h1>
        <Tabs admin={admin} member={member} />
        {!admin && <p className="sub">Read-only: only admins change the team settings{member ? " (your own keys, models and usage are under the My tabs)" : ""}. Every run records the settings version it used.</p>}
        <Outlet />
      </section>
    </DirtyGuardProvider>
  );
}
