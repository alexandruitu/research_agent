import { useQueryClient } from "@tanstack/react-query";

import { ApiError } from "../../api/client";
import { useDeleteLibraryItems, useSaveToLibrary } from "../../api/hooks";
import type { DrawerOut, LibraryItemOut, LibraryRef, LibrarySaveOut, LibrarySaveRequest, LibraryScope, PaperPage } from "../../api/types";
import { useToast } from "../../components/ui/Toast";
import { setPaperLibrary } from "./optimistic";

/** Where a save goes: one or both libraries (My library by default), with the collections picked in each. */
export type SaveChoice = Partial<Pick<LibrarySaveRequest, "new_collection" | "tags" | "status" | "note">> & {
  scopes?: LibraryScope[];
  collections?: Partial<Record<LibraryScope, string[]>>;
};

export const LIBRARY_NAME: Record<LibraryScope, string> = { personal: "My library", company: "the Company library" };

/** The library ref every visible copy of a paper shows now (rows and drawers). */
function currentRefs(client: ReturnType<typeof useQueryClient>, paperIds: string[]): Record<string, LibraryRef | null> {
  const refs: Record<string, LibraryRef | null> = Object.fromEntries(paperIds.map((id) => [id, null]));
  for (const [, page] of client.getQueriesData<PaperPage>({ queryKey: ["papers"] })) {
    for (const row of Array.isArray(page?.items) ? page.items : []) if (row.paper.id in refs && row.library) refs[row.paper.id] = row.library;
  }
  for (const [, drawer] of client.getQueriesData<DrawerOut>({ queryKey: ["paper"] })) {
    if (drawer && drawer.paper.id in refs && drawer.library) refs[drawer.paper.id] = drawer.library;
  }
  return refs;
}

/** A paper's ref after saving: the Company item leads when there is one, the user's own is named too. */
export function mergeRef(before: LibraryRef | null, item: Pick<LibraryItemOut, "id" | "scope" | "status" | "collections">): LibraryRef {
  const scope = item.scope ?? "company";
  const company = scope === "company" ? item.id : before?.company_item_id ?? (before?.scope !== "personal" ? before?.item_id ?? null : null);
  const personal = scope === "personal" ? item.id : before?.personal_item_id ?? (before?.scope === "personal" ? before.item_id : null);
  const leadIsCompany = scope === "company" || !before || !company;
  return leadIsCompany
    ? { item_id: item.id, scope, status: item.status, collections: item.collections, company_item_id: company, personal_item_id: personal }
    : { ...before!, company_item_id: company, personal_item_id: personal };
}

const where = (scopes: LibraryScope[]) => scopes.map((s) => LIBRARY_NAME[s]).join(" and ");

/**
 * Save papers of a run into one or both libraries: the rows show "In library" at once; the toast offers Undo,
 * which removes only the items this save created (papers that were already saved keep everything). A refusal
 * rolls the rows back (a library that did take the papers keeps them, and the message says so).
 */
export function useSaveFlow() {
  const client = useQueryClient();
  const save = useSaveToLibrary();
  const remove = useDeleteLibraryItems();
  const toast = useToast();
  const run = async (runId: string, paperIds: string[], choice: SaveChoice): Promise<boolean> => {
    const scopes: LibraryScope[] = choice.scopes?.length ? [...new Set(choice.scopes)] : ["personal"];
    const before = currentRefs(client, paperIds);
    const optimistic = Object.fromEntries(
      paperIds.map((id) => [id, before[id] ?? { item_id: `pending-${id}`, status: choice.status ?? "to_read", collections: [] }]),
    );
    setPaperLibrary(client, optimistic);
    const done: { scope: LibraryScope; out: LibrarySaveOut }[] = [];
    try {
      for (const scope of scopes) {
        const out = await save.mutateAsync({
          run_id: runId, paper_ids: paperIds, scope,
          collection_ids: choice.collections?.[scope] ?? [],
          new_collection: choice.new_collection ? { ...choice.new_collection, scope } : null,  // one in each library
          tags: choice.tags ?? [], status: choice.status ?? "to_read", note: choice.note ?? "",
        });
        done.push({ scope, out });
      }
    } catch (error) {
      const reason = error instanceof ApiError ? error.message : "could not reach the server.";
      if (!done.length) {
        setPaperLibrary(client, before);
        toast.show({ tone: "bad", text: `Not saved: ${reason}` });
        return false;
      }
      toast.show({ tone: "bad", text: `Saved to ${where(done.map((d) => d.scope))}, but not to ${where(scopes.filter((s) => !done.some((d) => d.scope === s)))}: ${reason}` });
    }
    const refs: Record<string, LibraryRef | null> = { ...before };
    for (const { out } of done) for (const item of out.items) refs[item.paper.id] = mergeRef(refs[item.paper.id] ?? null, item);
    setPaperLibrary(client, refs);
    if (done.length < scopes.length) return true;
    const created = done.flatMap((d) => d.out.created);
    const n = paperIds.length;
    const named = done.map((d) => d.out.collection?.name).filter(Boolean);
    const anyCollection = Object.values(choice.collections ?? {}).some((ids) => ids?.length) || !!choice.new_collection;
    const target = named.length ? `${where(scopes)} (${[...new Set(named)].join(", ")})` : where(scopes);
    const existing = done.reduce((sum, d) => sum + d.out.existing.length, 0);
    const text = created.length === 0
      ? `${n === 1 ? "It was" : "They were"} already in ${where(scopes)}${anyCollection ? "; collections added" : ""}`
      : `Saved ${n} paper${n === 1 ? "" : "s"} to ${target}${existing ? ` (${existing} already there)` : ""}`;
    toast.show({
      text,
      action: created.length ? {
        label: "Undo",
        run: () => {
          setPaperLibrary(client, before);
          remove.mutateAsync(created).then(
            () => toast.show({ tone: "info", text: "Save undone" }),
            (error: unknown) => toast.show({ tone: "bad", text: error instanceof ApiError ? error.message : "Could not undo the save." }),
          );
        },
      } : undefined,
    });
    return true;
  };
  return { save: run, pending: save.isPending };
}
