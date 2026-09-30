import { useQueryClient } from "@tanstack/react-query";

import { ApiError } from "../../api/client";
import { useDeleteLibraryItems, useSaveToLibrary } from "../../api/hooks";
import type { DrawerOut, LibraryRef, LibrarySaveRequest, PaperPage } from "../../api/types";
import { useToast } from "../../components/ui/Toast";
import { setPaperLibrary } from "./optimistic";

export type SaveChoice = Pick<LibrarySaveRequest, "collection_ids" | "new_collection" | "tags" | "status" | "note">;

/** The library ref every visible copy of a paper shows now (rows and drawers). */
function currentRefs(client: ReturnType<typeof useQueryClient>, paperIds: string[]): Record<string, LibraryRef | null> {
  const refs: Record<string, LibraryRef | null> = Object.fromEntries(paperIds.map((id) => [id, null]));
  for (const [, page] of client.getQueriesData<PaperPage>({ queryKey: ["papers"] })) {
    for (const row of page?.items ?? []) if (row.paper.id in refs && row.library) refs[row.paper.id] = row.library;
  }
  for (const [, drawer] of client.getQueriesData<DrawerOut>({ queryKey: ["paper"] })) {
    if (drawer && drawer.paper.id in refs && drawer.library) refs[drawer.paper.id] = drawer.library;
  }
  return refs;
}

/**
 * Save papers of a run: the rows show "In library" at once; the toast offers Undo, which removes only the
 * items this save created (papers that were already saved keep everything). A refusal rolls the rows back.
 */
export function useSaveFlow() {
  const client = useQueryClient();
  const save = useSaveToLibrary();
  const remove = useDeleteLibraryItems();
  const toast = useToast();
  const run = async (runId: string, paperIds: string[], choice: SaveChoice): Promise<boolean> => {
    const before = currentRefs(client, paperIds);
    const optimistic = Object.fromEntries(
      paperIds.map((id) => [id, before[id] ?? { item_id: `pending-${id}`, status: choice.status ?? "to_read", collections: [] }]),
    );
    setPaperLibrary(client, optimistic);
    try {
      const out = await save.mutateAsync({ run_id: runId, paper_ids: paperIds, ...choice });
      setPaperLibrary(client, Object.fromEntries(out.items.map((item) => [item.paper.id, { item_id: item.id, status: item.status, collections: item.collections }])));
      const where = out.collection?.name ?? (choice.collection_ids?.length ? "the chosen collections" : "the library");
      const n = paperIds.length;
      const text = out.created.length === 0
        ? `${n === 1 ? "It was" : "They were"} already in the library${choice.collection_ids?.length || choice.new_collection ? `; added to ${where}` : ""}`
        : `Saved ${out.created.length} paper${out.created.length === 1 ? "" : "s"} to ${where}${out.existing.length ? ` (${out.existing.length} already there)` : ""}`;
      toast.show({
        text,
        action: out.created.length ? {
          label: "Undo",
          run: () => {
            setPaperLibrary(client, Object.fromEntries(out.items.filter((i) => out.created.includes(i.id)).map((i) => [i.paper.id, null])));
            remove.mutateAsync(out.created).then(
              () => toast.show({ tone: "info", text: "Save undone" }),
              (error: unknown) => toast.show({ tone: "bad", text: error instanceof ApiError ? error.message : "Could not undo the save." }),
            );
          },
        } : undefined,
      });
      return true;
    } catch (error) {
      setPaperLibrary(client, before);
      toast.show({ tone: "bad", text: error instanceof ApiError ? `Not saved: ${error.message}` : "Not saved: could not reach the server." });
      return false;
    }
  };
  return { save: run, pending: save.isPending };
}
