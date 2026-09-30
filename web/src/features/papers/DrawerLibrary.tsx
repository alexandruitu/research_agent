import { useState } from "react";

import { hasRole, type DrawerOut } from "../../api/types";
import { useAuth } from "../../auth/AuthProvider";
import { useStatusChange } from "../library/optimistic";
import { SaveDialog } from "../library/SaveDialog";
import { useSaveFlow } from "../library/saveFlow";
import { StatusControl } from "../library/StatusControl";
import { LibraryBadge } from "./PaperTable";

/** The drawer's sticky actions: save the paper, or see and change its team status. */
export function DrawerLibrary({ runId, drawer }: { runId: string; drawer: DrawerOut }) {
  const { user } = useAuth();
  const member = hasRole(user, "member");
  const flow = useSaveFlow();
  const status = useStatusChange();
  const [open, setOpen] = useState(false);
  const library = drawer.library ?? null;
  const pending = !!library?.item_id.startsWith("pending-");
  return (
    <div className="drawer-library">
      {library ? (
        <>
          <LibraryBadge library={library} />
          {member && !pending && <StatusControl label="Team status" value={library.status} onChange={(to) => status.change(library.item_id, library.status, to)} />}
        </>
      ) : member ? (
        <button type="button" className="primary" onClick={() => setOpen(true)} disabled={flow.pending}>Save to library…</button>
      ) : (
        <span className="sub">Not in the library.</span>
      )}
      {open && (
        <SaveDialog count={1} onClose={() => setOpen(false)} onSave={(choice) => { setOpen(false); void flow.save(runId, [drawer.paper.id], choice); }} />
      )}
    </div>
  );
}
