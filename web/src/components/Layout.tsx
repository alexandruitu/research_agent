import type { MouseEvent } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { useUnreadDigests } from "../api/hooks";
import { useAuth } from "../auth/AuthProvider";
import { DirtyGuardProvider, useLeaveGuard } from "../features/settings/dirtyGuard";
import { ErrorBoundary } from "./ErrorBoundary";
import { GlossaryLink, GlossaryProvider } from "./ui/GlossaryDialog";
import { StaleBanner } from "./StaleBanner";
import { ToastProvider } from "./ui/Toast";

const NAV = [
  { to: "/fields", label: "Fields" },
  { to: "/", label: "Papers", end: true },
  { to: "/library", label: "Library" },
  { to: "/alerts", label: "Alerts" },
  { to: "/runs", label: "Runs" },
  { to: "/validation", label: "Validation" },
  { to: "/settings", label: "Settings" },
];

function Chrome() {
  const { user, logout } = useAuth();
  const { pathname } = useLocation();
  const { confirmLeave } = useLeaveGuard();
  const unread = useUnreadDigests(!!user).data?.unread ?? 0;
  const guard = (event: MouseEvent) => {
    if (!confirmLeave()) event.preventDefault();
  };
  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="topbar">
        <Link to="/" className="brand" onClick={guard}><img className="brand-logo" src="/healthineers-logo.svg" alt="Siemens Healthineers" width="128" height="32" /><span className="brand-name">Literature Radar</span></Link>
        <nav aria-label="Main">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} onClick={guard}>
              {item.label}
              {item.to === "/alerts" && unread > 0 && <span className="nav-count">{unread}<span className="sr-only"> unread</span></span>}
            </NavLink>
          ))}
        </nav>
        <div className="who">
          <span>{user?.name}</span> <span className="role">{user?.role}</span>
          <button type="button" onClick={() => confirmLeave() && void logout()}>Sign out</button>
        </div>
      </header>
      <StaleBanner />
      <main id="main" tabIndex={-1}>
        {/* keyed by path: a crash on one page must not stick when the user navigates to another */}
        <ErrorBoundary key={pathname} label="this page">
          <Outlet />
        </ErrorBoundary>
      </main>
      <footer className="page-foot">
        <span>Unfamiliar word? Every technical term has a <span aria-hidden="true">?</span> next to it, or see the</span> <GlossaryLink>glossary</GlossaryLink>.
      </footer>
    </>
  );
}

export function Layout() {
  return (
    <ToastProvider>
      <DirtyGuardProvider>
        <GlossaryProvider>
          <Chrome />
        </GlossaryProvider>
      </DirtyGuardProvider>
    </ToastProvider>
  );
}
