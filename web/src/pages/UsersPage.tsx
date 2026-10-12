import { useState } from "react";

import { ApiError } from "../api/client";
import { usePatchUser, useUsers } from "../api/hooks";
import type { UserOut } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { InviteForm } from "../features/users/InviteForm";
import { DeleteUserDialog, EditUserDialog, ResetPasswordDialog } from "../features/users/UserDialogs";

type Open = { kind: "edit" | "password" | "delete"; user: UserOut } | null;

export function UsersPage() {
  const [showDeleted, setShowDeleted] = useState(false);
  const users = useUsers(showDeleted);
  const patch = usePatchUser();
  const { user: me } = useAuth();
  const [problem, setProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [open, setOpen] = useState<Open>(null);

  const change = async (id: string, body: { role?: string; active?: boolean }) => {
    setProblem(null);
    setNotice(null);
    try {
      await patch.mutateAsync({ id, ...body });
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : "Could not reach the server.");
    }
  };
  const close = () => setOpen(null);

  if (users.isLoading) return <p role="status">Loading…</p>;
  if (users.isError) return <p role="alert">Could not load the users.</p>;
  return (
    <section>
      <h2>Users</h2>
      <InviteForm />
      {problem && <p role="alert" className="form-error">{problem}</p>}
      {notice && <p role="status">{notice}</p>}
      <div className="actions">
        <label><input type="checkbox" checked={showDeleted} onChange={(e) => setShowDeleted(e.target.checked)} /> Show deleted</label>
      </div>
      <table className="runs">
        <thead><tr><th scope="col">Email</th><th scope="col">Name</th><th scope="col">Role</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
        <tbody>
          {users.data?.map((user) => {
            const deleted = !!user.deleted_at;
            const self = user.id === me?.id;
            return (
              <tr key={user.id}>
                <td>{user.email}</td>
                <td>{user.name}</td>
                <td>
                  {deleted ? user.role : (
                    <select aria-label={`Role for ${user.email}`} value={user.role} onChange={(e) => change(user.id, { role: e.target.value })}>
                      <option value="viewer">viewer</option><option value="member">member</option><option value="admin">admin</option>
                    </select>
                  )}
                </td>
                <td>{deleted ? "deleted" : user.active ? "active" : "inactive"}{self && " (you)"}</td>
                <td>
                  {!deleted && (
                    <div className="actions">
                      <button type="button" aria-label={`Edit ${user.email}`} onClick={() => setOpen({ kind: "edit", user })}>Edit</button>
                      <button type="button" aria-label={`Reset password of ${user.email}`} onClick={() => setOpen({ kind: "password", user })}>Reset password</button>
                      {!self && (
                        <button type="button" aria-label={`${user.active ? "Deactivate" : "Reactivate"} ${user.email}`} onClick={() => change(user.id, { active: !user.active })}>
                          {user.active ? "Deactivate" : "Reactivate"}
                        </button>
                      )}
                      {!self && <button type="button" className="danger" aria-label={`Delete ${user.email}`} onClick={() => setOpen({ kind: "delete", user })}>Delete</button>}
                    </div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {open?.kind === "edit" && <EditUserDialog user={open.user} onClose={close} />}
      {open?.kind === "password" && (
        <ResetPasswordDialog user={open.user} onClose={close} onDone={() => { setNotice(`New password set for ${open.user.email}; their sessions were ended.`); close(); }} />
      )}
      {open?.kind === "delete" && (
        <DeleteUserDialog
          user={open.user}
          onClose={close}
          onDone={(result) => { setNotice(result.outcome === "deleted" ? `${open.user.email} was deleted.` : `${open.user.email} was anonymised as “Deleted user”.`); close(); }}
        />
      )}
    </section>
  );
}
