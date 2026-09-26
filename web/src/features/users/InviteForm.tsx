import { useState, type FormEvent } from "react";

import { ApiError } from "../../api/client";
import { useCreateUser } from "../../api/hooks";

export const MIN_PASSWORD_LENGTH = 12;

export function InviteForm() {
  const create = useCreateUser();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("member");
  const [password, setPassword] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!email || !name) return setProblem("Email and name are required.");
    if (password.length < MIN_PASSWORD_LENGTH) return setProblem(`The password needs at least ${MIN_PASSWORD_LENGTH} characters.`);
    setProblem(null);
    try {
      await create.mutateAsync({ email, name, role, password });
      setEmail("");
      setName("");
      setPassword("");
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : "Could not reach the server.");
    }
  };

  return (
    <form onSubmit={submit} className="start-run" aria-label="Invite a user">
      <label>Email<input type="email" autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
      <label>Name<input autoComplete="off" value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label>Role
        <select value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="viewer">viewer</option><option value="member">member</option><option value="admin">admin</option>
        </select>
      </label>
      <label>Initial password<input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
      <button type="submit" disabled={create.isPending}>Invite</button>
      {problem && <p role="alert" className="form-error">{problem}</p>}
    </form>
  );
}
