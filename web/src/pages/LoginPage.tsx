import { useState, type FormEvent } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthProvider";

export function LoginPage() {
  const { status, login } = useAuth();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  if (status === "authenticated") return <Navigate to={from} replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not reach the server. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="login">
      <h1>Sign in</h1>
      <form onSubmit={submit}>
        <label>
          Email
          <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label>
          Password
          <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <p role="alert" className="form-error">{error}</p>}
        <button type="submit" disabled={busy}>Sign in</button>
      </form>
    </main>
  );
}
