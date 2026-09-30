import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/AuthProvider";
import { ErrorBoundary } from "./ErrorBoundary";
import { StaleBanner } from "./StaleBanner";
import { ToastProvider } from "./ui/Toast";

export function Layout() {
  const { user, logout } = useAuth();
  const { pathname } = useLocation();
  return (
    <ToastProvider>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="topbar">
        <Link to="/" className="brand"><span className="brand-mark" aria-hidden="true">R/A</span> Research Agent</Link>
        <nav aria-label="Main">
          <NavLink to="/" end>Papers</NavLink>
          <NavLink to="/library">Library</NavLink>
          <NavLink to="/runs">Runs</NavLink>
          <NavLink to="/fields">Fields</NavLink>
          <NavLink to="/evals">Evals</NavLink>
          <NavLink to="/system">System map</NavLink>
          <NavLink to="/settings">Settings</NavLink>
        </nav>
        <div className="who">
          <span>{user?.name}</span> <span className="role">{user?.role}</span>
          <button type="button" onClick={() => void logout()}>Sign out</button>
        </div>
      </header>
      <StaleBanner />
      <main id="main" tabIndex={-1}>
        {/* keyed by path: a crash on one page must not stick when the user navigates to another */}
        <ErrorBoundary key={pathname} label="this page">
          <Outlet />
        </ErrorBoundary>
      </main>
    </ToastProvider>
  );
}
