import { NavLink, Outlet } from "react-router-dom";

const TABS = [
  { to: "/validation/evals", label: "Evals" },
  { to: "/validation/system", label: "System map" },
  { to: "/validation/how-it-works", label: "How it works" },
];

/** Validation: the pages for checking that the pipeline is right (evals, system map, how it works). */
export function ValidationPage() {
  return (
    <section className="validation">
      <p className="validation-intro">Validation <span className="sub-inline">· how we check the pipeline is right</span></p>
      <p className="page-intro">For checking the tool itself, not for everyday reading: measure it against published reviews (Evals), see what is measured (System map) or how the runs work inside (How it works).</p>
      <nav aria-label="Validation sections" className="tabs">
        {TABS.map((tab) => <NavLink key={tab.to} to={tab.to}>{tab.label}</NavLink>)}
      </nav>
      <Outlet />
    </section>
  );
}
