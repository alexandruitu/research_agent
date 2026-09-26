import { NavLink, Outlet } from "react-router-dom";

import { hasRole } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { ErrorBoundary } from "./ErrorBoundary";
import { StaleBanner } from "./StaleBanner";

export function Layout() {
  const { user, logout } = useAuth();
  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="topbar">
        <strong className="brand">Research Agent</strong>
        <nav aria-label="Main">
          <NavLink to="/" end>Papers</NavLink>
          <NavLink to="/runs">Runs</NavLink>
          <NavLink to="/evals">Evals</NavLink>
          <NavLink to="/system">System map</NavLink>
          {hasRole(user, "admin") && <NavLink to="/users">Users</NavLink>}
        </nav>
        <div className="who">
          <span>{user?.name}</span> <span className="role">{user?.role}</span>
          <button type="button" onClick={() => void logout()}>Sign out</button>
        </div>
      </header>
      <StaleBanner />
      <main id="main" tabIndex={-1}>
        <ErrorBoundary label="this page">
          <Outlet />
        </ErrorBoundary>
      </main>
    </>
  );
}
