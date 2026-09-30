import { useQueryClient, type QueryClient } from "@tanstack/react-query";

import { ApiError } from "../../api/client";
import { keys, usePatchLibraryItem } from "../../api/hooks";
import type { DrawerOut, LibraryItemDetail, LibraryPage, LibraryPatch, LibraryRef, PaperPage } from "../../api/types";
import { statusMeta } from "../../components/ui/StatusMark";
import { useToast } from "../../components/ui/Toast";

/** Paper rows and drawers show the library state; patch them all by paper id (null: not saved). */
export function setPaperLibrary(client: QueryClient, refs: Record<string, LibraryRef | null>) {
  client.setQueriesData<PaperPage>({ queryKey: ["papers"] }, (page) =>
    page ? { ...page, items: page.items.map((row) => (row.paper.id in refs ? { ...row, library: refs[row.paper.id] } : row)) } : page,
  );
  client.setQueriesData<DrawerOut>({ queryKey: ["paper"] }, (drawer) =>
    drawer && drawer.paper.id in refs ? { ...drawer, library: refs[drawer.paper.id] } : drawer,
  );
}

/** Sets an item's status everywhere it is on screen, before the server answers. */
export function setItemStatus(client: QueryClient, itemId: string, status: string) {
  client.setQueryData<LibraryItemDetail>(keys.libraryItem(itemId), (item) => (item ? { ...item, status } : item));
  client.setQueriesData<LibraryPage>({ queryKey: ["library", "list"] }, (page) =>
    page ? { ...page, items: page.items.map((i) => (i.id === itemId ? { ...i, status } : i)) } : page,
  );
  client.setQueriesData<PaperPage>({ queryKey: ["papers"] }, (page) =>
    page ? { ...page, items: page.items.map((row) => (row.library?.item_id === itemId ? { ...row, library: { ...row.library, status } } : row)) } : page,
  );
  client.setQueriesData<DrawerOut>({ queryKey: ["paper"] }, (drawer) =>
    drawer?.library?.item_id === itemId ? { ...drawer, library: { ...drawer.library, status } } : drawer,
  );
}

/** Status changes are instant, announced in a toast with Undo, and rolled back if the server refuses. */
export function useStatusChange() {
  const client = useQueryClient();
  const patch = usePatchLibraryItem();
  const toast = useToast();
  const apply = async (itemId: string, from: string, to: string, undoable = true) => {
    if (from === to) return;
    setItemStatus(client, itemId, to);
    try {
      await patch.mutateAsync({ id: itemId, status: to as LibraryPatch["status"] });
      toast.show({
        text: `Marked ${statusMeta(to).word.toLowerCase()}`,
        action: undoable ? { label: "Undo", run: () => void apply(itemId, to, from, false) } : undefined,
      });
    } catch (error) {
      setItemStatus(client, itemId, from);
      toast.show({ tone: "bad", text: error instanceof ApiError ? error.message : "Could not change the status." });
    }
  };
  return { change: apply, pending: patch.isPending };
}
