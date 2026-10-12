import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";

import { ApiError } from "../../api/client";
import { useDeleteUser, usePatchUser, useResetPassword, useUserReferences } from "../../api/hooks";
import type { UserDeleteOut, UserOut } from "../../api/types";
import { MIN_PASSWORD_LENGTH } from "./InviteForm";

const reason = (error: unknown) => (error instanceof ApiError ? error.message : "Could not reach the server.");

/** A modal <dialog>: focus goes to the first field, Escape closes, focus returns to the opener. */
function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: (titleId: string) => ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const node = dialog.current;
    if (node && !node.open) {
      if (typeof node.showModal === "function") node.showModal();
      else node.setAttribute("open", "");
    }
    node?.querySelector<HTMLElement>("input, button")?.focus();
    return () => opener?.focus?.();
  }, []);
  return (
    <dialog ref={dialog} className="modal" aria-labelledby={titleId} onCancel={(e) => { e.preventDefault(); onClose(); }}>
      <h2 id={titleId}>{title}</h2>
      {children(titleId)}
    </dialog>
  );
}

export function EditUserDialog({ user, onClose }: { user: UserOut; onClose: () => void }) {
  const patch = usePatchUser();
  const [name, setName] = useState(user.name);
  const [email, setEmail] = useState(user.email);
  const [problem, setProblem] = useState<string | null>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const body: { name?: string; email?: string } = {};
    if (name.trim() !== user.name) body.name = name.trim();
    if (email.trim().toLowerCase() !== user.email) body.email = email.trim();
    if (!name.trim() || !email.trim()) return setProblem("Name and email are required.");
    if (!/^[^@\s]+@[^@\s]+$/.test(email.trim())) return setProblem("Enter a valid email address.");
    if (!body.name && !body.email) return onClose();
    setProblem(null);
    try {
      await patch.mutateAsync({ id: user.id, ...body });
      onClose();
    } catch (error) {
      setProblem(reason(error));
    }
  };
  return (
    <Modal title={`Edit ${user.email}`} onClose={onClose}>
      {() => (
        <form onSubmit={submit} className="save-form" noValidate>
          <label className="block">Name<input autoComplete="off" maxLength={200} value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label className="block">Email<input type="email" autoComplete="off" maxLength={320} value={email} onChange={(e) => setEmail(e.target.value)} /></label>
          {problem && <p role="alert" className="form-error">{problem}</p>}
          <div className="actions">
            <button type="submit" className="primary" disabled={patch.isPending}>Save</button>
            <button type="button" onClick={onClose}>Cancel</button>
          </div>
        </form>
      )}
    </Modal>
  );
}

export function ResetPasswordDialog({ user, onClose, onDone }: { user: UserOut; onClose: () => void; onDone: () => void }) {
  const reset = useResetPassword();
  const [password, setPassword] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (password.length < MIN_PASSWORD_LENGTH) return setProblem(`The password needs at least ${MIN_PASSWORD_LENGTH} characters.`);
    setProblem(null);
    try {
      await reset.mutateAsync({ id: user.id, password });
      setPassword("");
      onDone();
    } catch (error) {
      setProblem(reason(error));
    }
  };
  return (
    <Modal title={`Reset the password of ${user.email}`} onClose={onClose}>
      {() => (
        <form onSubmit={submit} className="save-form">
          <label className="block">New password<input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
          <p className="hint">At least {MIN_PASSWORD_LENGTH} characters. {user.name} is signed out everywhere; tell them the new password yourself.</p>
          {problem && <p role="alert" className="form-error">{problem}</p>}
          <div className="actions">
            <button type="submit" className="primary" disabled={reset.isPending}>Set password</button>
            <button type="button" onClick={onClose}>Cancel</button>
          </div>
        </form>
      )}
    </Modal>
  );
}

export function DeleteUserDialog({ user, onClose, onDone }: { user: UserOut; onClose: () => void; onDone: (result: UserDeleteOut) => void }) {
  const refs = useUserReferences(user.id);
  const remove = useDeleteUser();
  const [typed, setTyped] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const matches = typed.trim().toLowerCase() === user.email.toLowerCase();
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!matches || !refs.data) return;
    setProblem(null);
    try {
      onDone(await remove.mutateAsync(user.id));
    } catch (error) {
      setProblem(reason(error));
    }
  };
  const total = refs.data?.total ?? 0;
  return (
    <Modal title={`Delete ${user.email}`} onClose={onClose}>
      {() => (
        <form onSubmit={submit} className="save-form">
          {refs.isLoading && <p role="status">Checking what points to this user…</p>}
          {refs.isError && <p role="alert" className="form-error">Could not check what points to this user.</p>}
          {refs.data?.outcome === "delete" && (
            <p>Nothing in the app points to this user, so the account is <strong>deleted permanently</strong> with its sessions.</p>
          )}
          {refs.data?.outcome === "anonymize" && (
            <p>
              {total} record{total === 1 ? "" : "s"} point to this user, so the account is <strong>anonymised</strong>, not removed:
              it becomes “Deleted user”, cannot sign in, and is hidden from this list. History keeps working.
            </p>
          )}
          <label className="block">Type <strong>{user.email}</strong> to confirm<input autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} /></label>
          {problem && <p role="alert" className="form-error">{problem}</p>}
          <div className="actions">
            <button type="submit" className="danger" disabled={!matches || !refs.data || remove.isPending}>Delete user</button>
            <button type="button" onClick={onClose}>Cancel</button>
          </div>
        </form>
      )}
    </Modal>
  );
}
