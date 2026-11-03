import { useState, type FormEvent } from "react";
import { Link, Navigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { useSignup, useSignupStatus } from "../api/meHooks";
import { useAuth } from "../auth/AuthProvider";

const MIN_PASSWORD = 12; // the same policy as invitations

export function SignupPage() {
  const { status } = useAuth();
  const open = useSignupStatus();
  const signup = useSignup();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  if (status === "authenticated") return <Navigate to="/" replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (password.length < MIN_PASSWORD) {
      setError(`The password needs at least ${MIN_PASSWORD} characters.`);
      return;
    }
    try {
      setDone((await signup.mutateAsync({ email, name, password })).message);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not reach the server. Try again.");
    }
  };

  return (
    <main className="login">
      <p className="login-brand"><img className="brand-logo" src="/healthineers-logo.svg" alt="Siemens Healthineers" width="128" height="32" /><span>Literature Radar</span></p>
      <h1>Create an account</h1>
      {open.data?.open === false && <p role="alert">Sign-up is not open on this server. Ask an admin for an invitation.</p>}
      {done ? (
        <>
          <p role="status">{done}</p>
          <p><Link to="/login">Go to sign in</Link></p>
        </>
      ) : (
        <form onSubmit={submit}>
          <label>
            Work email
            <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label>
            Name
            <input type="text" autoComplete="name" required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            Password (at least {MIN_PASSWORD} characters)
            <input type="password" autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          {error && <p role="alert" className="form-error">{error}</p>}
          <button type="submit" disabled={signup.isPending}>Create account</button>
          <p><Link to="/login">I already have an account</Link></p>
        </form>
      )}
    </main>
  );
}
