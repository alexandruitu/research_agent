import { useState } from "react";

import { ApiError } from "../api/client";
import { usePatchUser, useUsers } from "../api/hooks";
import { InviteForm } from "../features/users/InviteForm";

export function UsersPage() {
  const users = useUsers();
  const patch = usePatchUser();
  const [problem, setProblem] = useState<string | null>(null);

  const change = async (id: string, body: { role?: string; active?: boolean }) => {
    setProblem(null);
    try {
      await patch.mutateAsync({ id, ...body });
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : "Could not reach the server.");
    }
  };

  if (users.isLoading) return <p role="status">Loading…</p>;
  if (users.isError) return <p role="alert">Could not load the users.</p>;
  return (
    <section>
      <h1>Users</h1>
      <InviteForm />
      {problem && <p role="alert" className="form-error">{problem}</p>}
      <table className="runs">
        <thead><tr><th scope="col">Email</th><th scope="col">Name</th><th scope="col">Role</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
        <tbody>
          {users.data?.map((user) => (
            <tr key={user.id}>
              <td>{user.email}</td>
              <td>{user.name}</td>
              <td>
                <select aria-label={`Role for ${user.email}`} value={user.role} onChange={(e) => change(user.id, { role: e.target.value })}>
                  <option value="viewer">viewer</option><option value="member">member</option><option value="admin">admin</option>
                </select>
              </td>
              <td>{user.active ? "active" : "inactive"}</td>
              <td>
                <button type="button" aria-label={`${user.active ? "Deactivate" : "Reactivate"} ${user.email}`} onClick={() => change(user.id, { active: !user.active })}>
                  {user.active ? "Deactivate" : "Reactivate"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
