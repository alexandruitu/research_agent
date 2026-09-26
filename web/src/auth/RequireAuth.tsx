import { Navigate, Outlet, useLocation } from "react-router-dom";

import { hasRole, type Role } from "../api/types";
import { useAuth } from "./AuthProvider";

export function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") return <p role="status">Loading…</p>;
  if (status === "anonymous") return <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />;
  return <Outlet />;
}

export function RequireRole({ role }: { role: Role }) {
  const { user } = useAuth();
  if (!hasRole(user, role)) {
    return (
      <section>
        <h1>Not allowed</h1>
        <p>Your role does not allow this page. Ask an administrator if you need access.</p>
      </section>
    );
  }
  return <Outlet />;
}
