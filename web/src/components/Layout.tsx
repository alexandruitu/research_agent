import { Fragment, type MouseEvent, Suspense } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useUnreadDigests } from "../api/hooks";
import { useAuth } from "../auth/AuthProvider";
import { DirtyGuardProvider, useLeaveGuard } from "../features/settings/dirtyGuard";
import { FEATURES } from "../config";
import { ErrorBoundary } from "./ErrorBoundary";
import { Skeleton } from "./ui/Skeleton";
import { GlossaryLink, GlossaryProvider } from "./ui/GlossaryDialog";
import { StaleBanner } from "./StaleBanner";
import { ToastProvider } from "./ui/Toast";
import { WELCOME_PAGES, WelcomeGuide, WelcomeProvider, useWelcome } from "./WelcomeGuide";

type NavItem = { to: string; label: string; step?: number; quiet?: boolean; separated?: boolean };

/** The research flow in order (④ Read opens from Results or the Library, so it has no nav item), then the tools. */
const NAV: NavItem[] = [
  { to: "/topics", label: "Topics", step: 1 },
  { to: "/screening", label: "Search", step: 2 },
  { to: "/results", label: "Results", step: 3 },
  { to: "/library", label: "Library", step: 5 },
  ...(FEATURES.alerts ? [{ to: "/alerts", label: "Alerts" }] : []),
  { to: "/settings", label: "Settings", separated: true },
  { to: "/validation", label: "Validation", separated: true, quiet: true },
];

function Chrome() {
  const { user, logout } = useAuth();
  const { pathname } = useLocation();
  const { confirmLeave } = useLeaveGuard();
  const welcome = useWelcome();
  const navigate = useNavigate();
  const showWelcome = welcome.open && WELCOME_PAGES.includes(pathname);
  const howItWorks = () => {
    if (!confirmLeave()) return;
    welcome.reopen();
    if (!WELCOME_PAGES.includes(pathname)) navigate("/");
    requestAnimationFrame(() => document.getElementById("welcome-title")?.scrollIntoView?.({ block: "nearest" }));
  };
  const unread = useUnreadDigests(!!user && FEATURES.alerts).data?.unread ?? 0;
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
            <Fragment key={item.to}>
            {item.separated && <span className="nav-sep" aria-hidden="true" />}
            <NavLink to={item.to} onClick={guard} className={item.quiet ? "nav-quiet" : undefined}>
              {item.step != null && <><span className="nav-step" aria-hidden="true">{item.step}</span><span className="sr-only">Step {item.step}:</span>{" "}</>}
              {item.label}
              {item.to === "/alerts" && unread > 0 && <span className="nav-count">{unread}<span className="sr-only"> unread</span></span>}
            </NavLink>
            </Fragment>
          ))}
        </nav>
        <div className="who">
          <button type="button" className="link-button how-link" onClick={howItWorks}>How it works</button>
          <span>{user?.name}</span> <span className="role">{user?.role}</span>
          <button type="button" onClick={() => confirmLeave() && void logout()}>Sign out</button>
        </div>
      </header>
      <StaleBanner />
      <main id="main" tabIndex={-1} className={pathname.startsWith("/read/") ? "main--wide" : undefined}>
        {/* keyed by path: a crash on one page must not stick when the user navigates to another */}
        <ErrorBoundary key={pathname} label="this page">
          {showWelcome && <WelcomeGuide />}
          <Suspense fallback={<Skeleton label="the page" rows={4} />}><Outlet /></Suspense>
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
          <WelcomeProvider>
            <Chrome />
          </WelcomeProvider>
        </GlossaryProvider>
      </DirtyGuardProvider>
    </ToastProvider>
  );
}
