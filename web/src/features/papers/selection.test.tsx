import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../../api/client";
import { PapersPage } from "../../pages/PapersPage";
import { COLLECTION_ID, collectionOut, drawerOut, ITEM_ID, libraryItem, lostRow, paperRow, PAPER_ID, RUN_ID, runDetail, runOut, session, STAGES } from "../../test/fixtures";
import { mockApi, type MockHandler } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const LOST_ID = "55555555-5555-4555-8555-555555555555";
const page = (items: unknown[]) => ({ items, total: items.length, page: 1, page_size: 25 });

/** These tests cover the flat list (Group by: None); the grouped view has its own tests (features/papers/groups.test.tsx). */
const flat = (route: string) => route + (route.includes("?") ? "&" : "?") + "group=none";

function setup(role: "viewer" | "member" = "member", extra: Record<string, MockHandler> = {}, route = "/") {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session(role) },
    "GET /api/v1/runs": { body: [runOut()] },
    "GET /api/v1/runs/:id": { body: runDetail() },
    "GET /api/v1/stages": { body: STAGES },
    "GET /api/v1/runs/:id/papers": { body: page([paperRow(), lostRow()]) },
    "GET /api/v1/library/collections": { body: [collectionOut()] },
    ...extra,
  });
  renderWithProviders(<Routes><Route path="/" element={<PapersPage />} /></Routes>, { route: flat(route) });
  return api;
}

const saved = (paperId: string, itemId: string) => libraryItem({ id: itemId, paper: { ...libraryItem().paper, id: paperId } });

describe("saving papers to the library", () => {
  it("select two rows, choose a new collection, tags and status; the rows say In library before the server answers", async () => {
    let answer: (value: unknown) => void = () => undefined;
    const { calls } = setup("member", {
      "POST /api/v1/library": () => new Promise((resolve) => {
        answer = resolve;
      }).then(() => ({ status: 201, body: { created: [ITEM_ID, "cccccccc-cccc-4ccc-8ccc-cccccccccccc"], existing: [], items: [saved(PAPER_ID, ITEM_ID), saved(LOST_ID, "cccccccc-cccc-4ccc-8ccc-cccccccccccc")], collection: collectionOut({ name: "Friday" }) } })),
    });
    await userEvent.click(await screen.findByRole("checkbox", { name: /Select Diagnostic accuracy/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /Select Change in CT-Derived/ }));
    const bar = screen.getByRole("region", { name: "Selection" });
    expect(bar).toHaveTextContent("2 selected");
    await userEvent.click(within(bar).getByRole("button", { name: "Save to library…" }));
    const dialog = screen.getByRole("dialog", { name: "Save 2 papers to the library" });
    await userEvent.type(within(dialog).getByLabelText("New collection (optional)"), "Friday");
    await userEvent.type(within(dialog).getByLabelText("Tags"), "ffr{Enter}");
    await userEvent.click(within(dialog).getByRole("radio", { name: /Relevant/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save to library" }));
    expect(await screen.findAllByText("Saving to library…")).toHaveLength(2);
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      run_id: RUN_ID, paper_ids: [PAPER_ID, LOST_ID], collection_ids: [], new_collection: { name: "Friday", description: "" }, tags: ["ffr"], status: "relevant", note: "",
    });
    answer(null);
    expect(await screen.findByText("Saved 2 papers to Friday")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Selection" })).not.toBeInTheDocument();
  });

  it("Undo removes only the items the save created", async () => {
    const { calls } = setup("member", {
      "POST /api/v1/library": { status: 201, body: { created: [ITEM_ID], existing: ["cccccccc-cccc-4ccc-8ccc-cccccccccccc"], items: [saved(PAPER_ID, ITEM_ID), saved(LOST_ID, "cccccccc-cccc-4ccc-8ccc-cccccccccccc")], collection: null } },
      "DELETE /api/v1/library/:id": { status: 204 },
    });
    await userEvent.click(await screen.findByRole("checkbox", { name: "Select all papers on this page" }));
    await userEvent.click(screen.getByRole("button", { name: "Save to library…" }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("checkbox", { name: /Plaque reading list/ }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Save to library" }));
    expect(await screen.findByText("Saved 1 paper to the chosen collections (1 already there)")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ collection_ids: [COLLECTION_ID], new_collection: null });
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "DELETE").map((c) => c.path)).toEqual([`/api/v1/library/${ITEM_ID}`]));
  });

  it("a new collection name that exists already means that collection", async () => {
    const { calls } = setup("member", { "POST /api/v1/library": { status: 201, body: { created: [ITEM_ID], existing: [], items: [saved(PAPER_ID, ITEM_ID)], collection: null } } });
    await userEvent.click(await screen.findByRole("checkbox", { name: /Select Diagnostic accuracy/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save to library…" }));
    await userEvent.type(within(screen.getByRole("dialog")).getByLabelText("New collection (optional)"), "plaque READING list");
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Save to library" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ collection_ids: [COLLECTION_ID], new_collection: null }));
  });

  it("a refused save rolls the rows back and says why", async () => {
    setup("member", { "POST /api/v1/library": { status: 422, body: { code: "not_in_run", message: "1 of these papers are not part of this run", request_id: "r" } } });
    await userEvent.click(await screen.findByRole("checkbox", { name: /Select Diagnostic accuracy/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save to library…" }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Save to library" }));
    expect(await screen.findByText("Not saved: 1 of these papers are not part of this run")).toBeInTheDocument();
    expect(screen.queryByText("Saving to library…")).not.toBeInTheDocument();
    expect(screen.queryByText(/In library/)).not.toBeInTheDocument();
  });

  it("rows already saved show their status and link to the library", async () => {
    setup("member", { "GET /api/v1/runs/:id/papers": { body: page([paperRow({ library: { item_id: ITEM_ID, status: "relevant", collections: [] } })]) } });
    const badge = await screen.findByRole("link", { name: /In library · Relevant/ });
    expect(badge).toHaveAttribute("href", `/library?item=${ITEM_ID}`);
  });

  it("viewers get no checkboxes", async () => {
    setup("viewer");
    await screen.findByText(/Diagnostic accuracy/);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("the drawer header saves one paper, then shows and changes its status", async () => {
    let library: unknown = null;
    const { calls } = setup("member", {
      "GET /api/v1/runs/:id/papers/:id": () => ({ body: drawerOut({ library } as never) }),
      "POST /api/v1/library": () => {
        library = { item_id: ITEM_ID, status: "to_read", collections: [] };
        return { status: 201, body: { created: [ITEM_ID], existing: [], items: [saved(LOST_ID, ITEM_ID)], collection: null } };
      },
      "PATCH /api/v1/library/:id": ({ body }) => {
        library = { item_id: ITEM_ID, status: (body as { status: string }).status, collections: [] };
        return { body: {} };
      },
    }, `/?paper=${LOST_ID}`);
    const drawer = await screen.findByRole("complementary", { name: "Paper details" });
    await userEvent.click(await within(drawer).findByRole("button", { name: "Save to library…" }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Save to library" }));
    expect(await within(drawer).findByRole("link", { name: /In library · To read/ })).toBeInTheDocument();
    await userEvent.click(within(drawer).getByRole("radio", { name: /Read/ }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ status: "read" }));
  });
});
