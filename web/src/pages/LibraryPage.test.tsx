import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { COLLECTION_ID, collectionOut, fieldDetail, ITEM_ID, ITEM_ID_2, libraryDetail, libraryItem, runOut, session } from "../test/fixtures";
import { mockApi, type MockHandler } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { eventSentence } from "../features/library/ReadingPane";
import { LibraryPage } from "./LibraryPage";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const page = (items = [libraryItem(), libraryItem({ id: ITEM_ID_2, status: "relevant", tags: [], collections: [], red_flag_count: 0, paper: { ...libraryItem().paper, id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd", title: "Plaque radiomics on CCTA" } })]) => ({ items, total: items.length, page: 1, page_size: 25 });

function setup(role: "viewer" | "member" | "admin" = "member", extra: Record<string, MockHandler> = {}, route = "/library") {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session(role) },
    "GET /api/v1/library": { body: page() },
    "GET /api/v1/library/collections": { body: [collectionOut()] },
    "GET /api/v1/library/:id": { body: libraryDetail() },
    "GET /api/v1/fields": { body: [fieldDetail()] },
    "GET /api/v1/runs": { body: [runOut({ status: "done" })] },
    ...extra,
  });
  renderWithProviders(<Routes><Route path="/library" element={<LibraryPage />} /></Routes>, { route });
  return api;
}

const lastSearch = (calls: { method: string; path: string; search: string }[]) =>
  new URLSearchParams([...calls].reverse().find((c) => c.method === "GET" && c.path === "/api/v1/library")!.search);

describe("LibraryPage", () => {
  it("lists saved papers with status in words, score, red flags, collections and tags", async () => {
    setup();
    const list = await screen.findByRole("list", { name: "Saved papers" });
    const first = within(list).getAllByRole("listitem")[0]!;
    expect(first).toHaveTextContent("To read");
    expect(first).toHaveTextContent("score 74");
    expect(first).toHaveTextContent("1 red flag");
    expect(first).toHaveTextContent("Plaque reading list");
    expect(first).toHaveTextContent("#ffr");
    expect(screen.getByText("2 papers")).toBeInTheDocument();
  });

  it("sends filters to the API, shows them as chips and clears them all", async () => {
    const { calls } = setup();
    await screen.findByRole("list", { name: "Saved papers" });
    await userEvent.click(within(screen.getByRole("group", { name: "Status" })).getByRole("button", { name: /Useful/ }));
    await userEvent.selectOptions(screen.getByLabelText("Collection"), COLLECTION_ID);
    await userEvent.click(screen.getByRole("button", { name: /Has red flags/ }));
    await userEvent.type(screen.getByRole("searchbox"), "radiomics{Enter}");
    await waitFor(() => {
      const search = lastSearch(calls);
      expect(search.get("status")).toBe("relevant");
      expect(search.get("collection_id")).toBe(COLLECTION_ID);
      expect(search.get("has_red_flags")).toBe("true");
      expect(search.get("q")).toBe("radiomics");
    });
    const chips = screen.getByRole("group", { name: "Active filters" });
    expect(chips).toHaveTextContent("Status: Useful");
    expect(chips).toHaveTextContent("Collection: Plaque reading list");
    await userEvent.click(within(chips).getByRole("button", { name: /Status: Useful/ }));
    await waitFor(() => expect(lastSearch(calls).get("status")).toBeNull());
    await userEvent.click(within(screen.getByRole("group", { name: "Active filters" })).getByRole("button", { name: "Clear all" }));
    expect(screen.queryByRole("group", { name: "Active filters" })).not.toBeInTheDocument();
    await waitFor(() => expect(lastSearch(calls).get("q")).toBeNull());
  });

  it("export links carry the current filters", async () => {
    setup("member", {}, "/library?status=relevant&q=plaque&page=2");
    await screen.findByRole("list", { name: "Saved papers" });
    expect(screen.getByRole("link", { name: "Export CSV" })).toHaveAttribute("href", "/api/v1/library/export?format=csv&sort=added_at&direction=desc&q=plaque&status=relevant");
    expect(screen.getByRole("link", { name: "Export BibTeX" }).getAttribute("href")).toContain("format=bibtex");
  });

  it("opens a paper in the reading pane: abstract, evidence and history", async () => {
    setup();
    await userEvent.click(await screen.findByRole("button", { name: /Diagnostic accuracy/ }));
    const pane = await screen.findByRole("complementary", { name: "Reading pane" });
    expect(await within(pane).findByText(/We trained a CNN/)).toBeInTheDocument();
    await userEvent.click(within(pane).getByRole("button", { name: "Evidence" }));
    expect(within(pane).getByText("No external validation")).toBeInTheDocument();
    expect(pane).toHaveTextContent("Evidence: “tested at the same hospital”Methods");
    expect(pane).toHaveTextContent("Checklist item: The model was validated on an external dataset.");
    expect(within(pane).getByText("include")).toBeInTheDocument();
    await userEvent.click(within(pane).getByRole("button", { name: /History/ }));
    expect(within(pane).getByText("Admin changed the status from to read to read.")).toBeInTheDocument();
  });

  it("changes the status at once, and Undo puts it back", async () => {
    let status = "to_read";
    const { calls } = setup("member", {
      "GET /api/v1/library/:id": () => ({ body: libraryDetail({ status }) }),
      "PATCH /api/v1/library/:id": ({ body }) => {
        status = (body as { status: string }).status;
        return { body: libraryDetail({ status }) };
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: /Diagnostic accuracy/ }));
    const pane = await screen.findByRole("complementary", { name: "Reading pane" });
    await userEvent.click(await within(pane).findByRole("radio", { name: /Useful/ }));
    expect(within(pane).getByRole("radio", { name: /Useful/ })).toBeChecked();
    expect(await screen.findByText("Marked useful")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PATCH").map((c) => c.body)).toEqual([{ status: "relevant" }, { status: "to_read" }]));
  });

  it("rolls the status back when the server refuses", async () => {
    setup("member", { "PATCH /api/v1/library/:id": { status: 500, body: { code: "internal_error", message: "Unexpected error", request_id: "r" } } });
    await userEvent.click(await screen.findByRole("button", { name: /Diagnostic accuracy/ }));
    const pane = await screen.findByRole("complementary", { name: "Reading pane" });
    await userEvent.click(await within(pane).findByRole("radio", { name: /Rejected/ }));
    expect(await screen.findByText("Unexpected error")).toBeInTheDocument();
    await waitFor(() => expect(within(pane).getByRole("radio", { name: /To read/ })).toBeChecked());
  });

  it("edits tags, the note and collections", async () => {
    const { calls } = setup("member", { "PATCH /api/v1/library/:id": { body: libraryDetail() } });
    await userEvent.click(await screen.findByRole("button", { name: /Diagnostic accuracy/ }));
    const pane = await screen.findByRole("complementary", { name: "Reading pane" });
    await userEvent.type(await within(pane).findByLabelText("Tags"), "must-read{Enter}");
    await userEvent.type(within(pane).getByLabelText("Note"), "Check the cohort.");
    await userEvent.click(within(pane).getByRole("button", { name: "Save note" }));
    await userEvent.click(within(pane).getByRole("checkbox", { name: "Plaque reading list" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PATCH").map((c) => c.body)).toEqual([
      { tags: ["ffr", "must-read"] }, { note: "Check the cohort." }, { collection_ids: [] },
    ]));
  });

  it("removes an item only after confirmation", async () => {
    const confirm = vi.fn(() => true);
    vi.stubGlobal("confirm", confirm);
    const { calls } = setup("member", { "DELETE /api/v1/library/:id": { status: 204 } });
    await userEvent.click(await screen.findByRole("button", { name: /Diagnostic accuracy/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Remove from library" }));
    expect(confirm).toHaveBeenCalled();
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path.endsWith(ITEM_ID))).toBe(true));
  });

  it("offers to update the evidence from a newer run of the field", async () => {
    const NEWER = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";
    const { calls } = setup("member", {
      "GET /api/v1/runs": { body: [runOut({ status: "done" }), runOut({ id: NEWER, status: "done", created_at: "2026-09-30T12:00:00Z" })] },
      "POST /api/v1/library/:id/snapshot": { body: libraryDetail() },
    });
    await userEvent.click(await screen.findByRole("button", { name: /Diagnostic accuracy/ }));
    const pane = await screen.findByRole("complementary", { name: "Reading pane" });
    await userEvent.click(await within(pane).findByRole("button", { name: "Evidence" }));
    await userEvent.click(await within(pane).findByRole("button", { name: "Update evidence from the newer run" }));
    await waitFor(() => expect(calls.find((c) => c.path.endsWith("/snapshot"))?.body).toEqual({ run_id: NEWER }));
  });

  it("keyboard: j moves, o opens, 3 marks relevant, ? lists the shortcuts", async () => {
    const { calls } = setup("member", { "PATCH /api/v1/library/:id": { body: libraryDetail({ status: "relevant" }) } });
    await screen.findByRole("list", { name: "Saved papers" });
    await userEvent.keyboard("j");
    expect(screen.getByRole("button", { name: /Plaque radiomics/ })).toHaveFocus();
    await userEvent.keyboard("k");
    await userEvent.keyboard("o");
    expect(await screen.findByRole("complementary", { name: "Reading pane" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("heading", { level: 2, name: /Diagnostic accuracy/ })).toHaveFocus());
    await userEvent.keyboard("3");
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ status: "relevant" }));
    await userEvent.keyboard("?");
    expect(screen.getByRole("dialog", { name: "Library shortcuts" })).toBeInTheDocument();
  });

  it("an empty library says how to fill it", async () => {
    setup("member", { "GET /api/v1/library": { body: page([]) } });
    expect(await screen.findByText("The library is empty")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to Papers" })).toHaveAttribute("href", "/");
  });

  it("viewers read but cannot change anything", async () => {
    setup("viewer");
    await userEvent.click(await screen.findByRole("button", { name: /Diagnostic accuracy/ }));
    const pane = await screen.findByRole("complementary", { name: "Reading pane" });
    expect(await within(pane).findByRole("radio", { name: /To read/ })).toBeDisabled();
    expect(within(pane).getByLabelText("Note")).toBeDisabled();
    expect(within(pane).queryByRole("button", { name: "Save note" })).not.toBeInTheDocument();
  });

  it("manages collections: create, a taken name, rename; archive for admins only", async () => {
    const { calls } = setup("member", {
      "POST /api/v1/library/collections": ({ body }) => ((body as { name: string }).name === "Plaque reading list"
        ? { status: 409, body: { code: "name_taken", message: "taken", request_id: "r" } }
        : { status: 201, body: collectionOut({ id: "ffffffff-ffff-4fff-8fff-ffffffffffff", name: "Screening Q4" }) }),
      "PATCH /api/v1/library/collections/:id": { body: collectionOut({ name: "Plaque, must read" }) },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Manage collections" }));
    const manager = screen.getByRole("region", { name: "Collections" });
    await userEvent.type(within(manager).getByLabelText("New collection"), "Plaque reading list");
    await userEvent.click(within(manager).getByRole("button", { name: "Create collection" }));
    expect(await within(manager).findByRole("alert")).toHaveTextContent("exists already");
    await userEvent.clear(within(manager).getByLabelText("New collection"));
    await userEvent.type(within(manager).getByLabelText("New collection"), "Screening Q4");
    await userEvent.click(within(manager).getByRole("button", { name: "Create collection" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "POST").map((c) => c.body)).toContainEqual({ name: "Screening Q4" }));
    expect(within(manager).queryByRole("button", { name: /Archive/ })).not.toBeInTheDocument();
    await userEvent.click(within(manager).getByRole("button", { name: /Rename/ }));
    await userEvent.clear(within(manager).getByLabelText(/Name of/));
    await userEvent.type(within(manager).getByLabelText(/Name of/), "Plaque, must read");
    await userEvent.click(within(manager).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ name: "Plaque, must read" }));
  });

  it("admins archive a collection after confirming", async () => {
    vi.stubGlobal("confirm", vi.fn(() => true));
    const { calls } = setup("admin", { "POST /api/v1/library/collections/:id/archive": { body: collectionOut({ archived_at: "2026-09-30T12:00:00Z" }) } });
    await userEvent.click(await screen.findByRole("button", { name: "Manage collections" }));
    await userEvent.click(within(screen.getByRole("region", { name: "Collections" })).getByRole("button", { name: /Archive/ }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/archive"))).toBe(true));
  });
});

describe("history sentences", () => {
  it("say who did what in words", () => {
    const at = "2026-09-30T10:00:00Z";
    expect(eventSentence({ id: "1", kind: "tags", detail: { added: ["a"], removed: ["b"] }, user_name: "Mia", created_at: at })).toBe("Mia added tags a and removed tags b.");
    expect(eventSentence({ id: "2", kind: "collections", detail: { added: ["X"], removed: [] }, user_name: null, created_at: at })).toBe("Someone added it to X.");
    expect(eventSentence({ id: "3", kind: "snapshot", detail: {}, user_name: "Ada", created_at: at })).toBe("Ada updated the evidence from a newer run.");
  });
});
