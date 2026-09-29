import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../../api/client";
import { fakeXhr } from "../../test/fakeXhr";
import { drawerOut, paperFile, panelOut, reviewSettings, lostRow, paperRow, runDetail, runOut, session, STAGES, RUN_ID } from "../../test/fixtures";
import { mockApi } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";
import { PapersPage } from "../../pages/PapersPage";
import { StagePanel } from "./StagePanel";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const LOST_ID = "55555555-5555-4555-8555-555555555555";

function Location() {
  return <output aria-label="location">{useLocation().search}</output>;
}

/** The drawer is on screen (with a loading heading) before its data arrives: wait for the paper itself. */
async function openDrawer() {
  const drawer = await screen.findByRole("complementary", { name: "Paper details" });
  await within(drawer).findByRole("heading", { name: /Change in CT-Derived FFR/ });
  return drawer;
}

function setup(role: "viewer" | "member" = "member", extra: Parameters<typeof mockApi>[0] = {}, route = `/?run=${RUN_ID}&paper=${LOST_ID}`) {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session(role) },
    "GET /api/v1/runs": { body: [runOut()] },
    "GET /api/v1/runs/:id": { body: runDetail() },
    "GET /api/v1/stages": { body: STAGES },
    "GET /api/v1/runs/:id/papers": { body: { items: [paperRow(), lostRow()], total: 2, page: 1, page_size: 25 } },
    "GET /api/v1/runs/:id/papers/:id": { body: drawerOut() },
    ...extra,
  });
  renderWithProviders(<><Routes><Route path="/" element={<PapersPage />} /></Routes><Location /></>, { route });
  return api;
}

describe("paper drawer", () => {
  it("tells the story of the paper the screen lost, stage by stage", async () => {
    setup();
    const drawer = await openDrawer();
    expect(within(drawer).getByRole("heading", { name: /Change in CT-Derived FFR/ })).toHaveFocus();
    expect(within(drawer).getByText(/Found by direct lookup/)).toBeInTheDocument();
    expect(within(drawer).getByText("0.06")).toBeInTheDocument();
    expect(within(drawer).getByText("Jev was not confident, so the LLM decided.")).toBeInTheDocument();
    expect(within(drawer).getByText(/Auto-drop needs/)).toBeInTheDocument();
    expect(within(drawer).getByText(/70.8 and 67.4%/)).toBeInTheDocument();
    expect(within(drawer).getByText("Reviewer A")).toBeInTheDocument();
    expect(within(drawer).getByText("Adjudicator")).toBeInTheDocument();
    expect(within(drawer).getByText(/neither confirms nor rules out/)).toBeInTheDocument();
    expect(within(drawer).getByText(/Included by the systematic review/)).toBeInTheDocument();
  });

  it("shows the abstract on demand and never renders it as HTML", async () => {
    setup("viewer", { "GET /api/v1/runs/:id/papers/:id": { body: drawerOut({ paper: { ...drawerOut().paper, abstract: "<img src=x onerror=alert(1)> plain text" } }) } });
    await openDrawer();
    await userEvent.click(screen.getByRole("button", { name: "Abstract" }));
    expect(screen.getByText("<img src=x onerror=alert(1)> plain text")).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });

  it("hides raw calls from viewers", async () => {
    setup("viewer");
    await openDrawer();
    expect(screen.queryByRole("button", { name: "Raw calls" })).not.toBeInTheDocument();
  });

  it("members can inspect the exact prompt and response of a call", async () => {
    const call = { key: "a".repeat(64), role: "screen", model: "anthropic:claude-sonnet-5", prompt_version: "m1.1", input: { payload: { topic: "t" } }, output: { decision: "exclude" } };
    const { calls } = setup("member", { [`GET /api/v1/runs/${RUN_ID}/calls/${"a".repeat(64)}`]: { body: call } });
    const drawer = await openDrawer();
    await userEvent.click(within(drawer).getByRole("button", { name: "Raw calls" }));
    await userEvent.click(within(drawer).getByRole("button", { name: /Screen/ }));
    expect(await screen.findByText("anthropic:claude-sonnet-5")).toBeInTheDocument();
    expect(screen.getByText(/"decision": "exclude"/)).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith(`/calls/${"a".repeat(64)}`))).toBe(true);
  });

  it("explains an unavailable audit trail instead of failing silently", async () => {
    setup("member", { [`GET /api/v1/runs/${RUN_ID}/calls/${"a".repeat(64)}`]: { status: 409, body: { code: "no_audit_trail", message: "This run's audit trail is not available", request_id: "r" } } });
    const drawer = await openDrawer();
    await userEvent.click(within(drawer).getByRole("button", { name: "Raw calls" }));
    await userEvent.click(within(drawer).getByRole("button", { name: /Screen/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("audit trail is not available");
  });

  it("closes with Escape or the close button and returns focus to the paper's title", async () => {
    setup();
    await openDrawer();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("complementary", { name: "Paper details" })).not.toBeInTheDocument());
    expect(screen.getByLabelText("location")).not.toHaveTextContent("paper=");
    await waitFor(() => expect(screen.getByRole("button", { name: /Change in CT-Derived FFR/ })).toHaveFocus());
    await userEvent.click(screen.getByRole("button", { name: /Change in CT-Derived FFR/ }));
    await openDrawer();
    await userEvent.click(screen.getByRole("button", { name: "Close paper details" }));
    await waitFor(() => expect(screen.queryByRole("complementary", { name: "Paper details" })).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("button", { name: /Change in CT-Derived FFR/ })).toHaveFocus());
  });

  it("ignores review detail keys it does not know, such as adjudicated", async () => {
    const base = drawerOut();
    const reviews = base.reviews.map((review) => ({ ...review, detail: { ...review.detail, adjudicated: true } }));
    setup("member", { "GET /api/v1/runs/:id/papers/:id": { body: drawerOut({ reviews }) } });
    const drawer = await openDrawer();
    expect(within(drawer).getByText(/neither confirms nor rules out/)).toBeInTheDocument();
    expect(within(drawer).queryByText(/true/)).not.toBeInTheDocument();
  });

  it("clicking a paper title opens its drawer and puts it in the URL", async () => {
    setup("member", {}, `/?run=${RUN_ID}`);
    await userEvent.click(await screen.findByRole("button", { name: /Change in CT-Derived FFR/ }));
    expect(await screen.findByRole("complementary", { name: "Paper details" })).toBeInTheDocument();
    expect(screen.getByLabelText("location")).toHaveTextContent(`paper=${LOST_ID}`);
  });

  it("shows a research-run paper without an SR section", async () => {
    setup("member", { "GET /api/v1/runs/:id/papers/:id": { body: drawerOut({ in_sr: null, label_source: null, found_by: "query" }) } });
    const drawer = await openDrawer();
    expect(within(drawer).queryByText(/systematic review/)).not.toBeInTheDocument();
    expect(within(drawer).getByText(/Found by the search query/)).toBeInTheDocument();
  });
  it("shows the screen per criterion, marks the criterion that decided and names the sources", async () => {
    const drawer = drawerOut({
      sources: ["europepmc", "openalex"], found_by: "query",
      screening: {
        ...drawerOut().screening, tier: "llm", decision: "exclude", jev_decision: "escalate", llm_decision: "exclude", decided_by: "i1",
        criteria_table: [
          { key: "i1", kind: "include", text: "The study uses machine learning.", jev_p: 0.2, llm: "no", quote: "change in CT-FFR across the lesion was calculated", decided: true },
          { key: "e1", kind: "exclude", text: "The paper is a review.", jev_p: 0.02, llm: "no", quote: null, decided: false },
        ],
      },
    });
    setup("member", { "GET /api/v1/runs/:id/papers/:id": { body: drawer } });
    const panel = await openDrawer();
    const table = within(panel).getByRole("table", { name: "Screening per criterion" });
    expect(within(table).getByRole("row", { name: /incl 1/ })).toHaveTextContent("(decided)");
    expect(within(table).getByRole("row", { name: /incl 1/ })).toHaveTextContent("“change in CT-FFR across the lesion was calculated”");
    expect(within(table).getByRole("row", { name: /excl 1/ })).not.toHaveTextContent("decided");
    expect(within(panel).getByText(/because incl 1 is not met \(decided by the LLM; Jev was unsure\)/)).toBeInTheDocument();
    expect(within(panel).getByText(/Found by the search query in Europe PMC, OpenAlex/)).toBeInTheDocument();
  });
});

describe("stage panel", () => {
  it("shows what a stage does, its status and its limits, and links to the eval data", () => {
    mockApi({ "GET /api/v1/auth/me": { body: session("viewer") } });
    renderWithProviders(<StagePanel stage={STAGES.find((s) => s.id === "reviewers")!} onClose={() => undefined} />);
    expect(screen.getByRole("heading", { name: "Reviewers A and B" })).toBeInTheDocument();
    expect(screen.getByText("caveat: one model family")).toBeInTheDocument();
    expect(screen.getByText(/limits\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the eval report" })).toHaveAttribute("href", "/evals");
  });

  it("opens from a strip header and closes when the header is pressed again", async () => {
    setup("member", {}, `/?run=${RUN_ID}`);
    const strip = await screen.findByRole("button", { name: /^Screen/ });
    await userEvent.click(strip);
    expect(await screen.findByRole("complementary", { name: "About Screen" })).toBeInTheDocument();
    expect(screen.getByLabelText("location")).toHaveTextContent("stage=screen");
    await userEvent.click(screen.getByRole("button", { name: /^Screen/ }));
    await waitFor(() => expect(screen.queryByRole("complementary", { name: "About Screen" })).not.toBeInTheDocument());
  });
});

describe("drawer · peer review", () => {
  it("puts the editor's decision first, then disagreements in words, red flags and one report per reviewer", async () => {
    setup("viewer", { "GET /api/v1/runs/:id/papers/:id": { body: drawerOut({ panel: panelOut(), files: [] }) } });
    const drawer = await openDrawer();
    const step = within(drawer).getByRole("heading", { name: "Peer review" }).closest("section")!;
    expect(within(drawer).queryByRole("heading", { name: "Reviewers" })).not.toBeInTheDocument();
    const text = step.textContent ?? "";
    expect(text.indexOf("Editor's decision")).toBeLessThan(text.indexOf("Methodologist v2"));
    expect(step).toHaveTextContent("Reviewed on the full text from PMC (Methods, Results; 41 000 characters, cut to the length limit).");
    expect(step).toHaveTextContent("Editor's decision include score 65 · 8/10 answered");
    expect(step).toHaveTextContent("Methodologist and Statistician disagree on m1");
    expect(step).toHaveTextContent("⚑ 1 red flag");
    expect(step).toHaveTextContent("raised by Statistician");

    const reports = step.querySelectorAll("details");
    expect(reports).toHaveLength(2);
    await userEvent.click(within(step).getByText("Statistician", { selector: "summary strong" }));
    const table = within(step).getByRole("table", { name: "Statistician's checklist" });
    const m1 = within(table).getByRole("row", { name: /m1/ });
    expect(m1).toHaveTextContent("✗ no ⚑ red flag");
    expect(m1).toHaveTextContent("“images were split 80/20”Methods");
    expect(within(table).getByRole("row", { name: /s2/ })).toHaveTextContent("– not reportedno quote");
  });

  it("says when only the abstract was reviewed", async () => {
    setup("viewer", { "GET /api/v1/runs/:id/papers/:id": { body: drawerOut({ panel: panelOut({ text_source: "abstract", text_reason: "no full-text source had it", red_flags: [], red_flag_count: 0 }), files: [] }) } });
    const drawer = await openDrawer();
    expect(drawer).toHaveTextContent("Reviewed on the abstract only (no full-text source had it).");
  });

  it("legacy runs keep the Reviewers step", async () => {
    setup("viewer");
    const drawer = await openDrawer();
    expect(within(drawer).getByRole("heading", { name: "Reviewers" })).toBeInTheDocument();
    expect(within(drawer).queryByRole("heading", { name: "Peer review" })).not.toBeInTheDocument();
  });
});

describe("drawer · full-text PDFs", () => {
  const abstractPanel = () => drawerOut({ panel: panelOut({ text_source: "abstract", red_flags: [], red_flag_count: 0 }), files: [] });
  const PAPER = "/api/v1/papers/55555555-5555-4555-8555-555555555555/files";
  const filesRoutes = (files: unknown[] = []) => ({
    "GET /api/v1/runs/:id/papers/:id": { body: abstractPanel() },
    "GET /api/v1/papers/:id/files": { body: files },
    "GET /api/v1/settings/review": { body: reviewSettings() },
  });

  it("offers the upload when only the abstract was reviewed, shows progress and lists the file", async () => {
    let listed: unknown[] = [];
    const { sent } = fakeXhr(() => {
      listed = [paperFile()];
      return { status: 201, body: paperFile(), progress: [0.4, 1] };
    });
    setup("member", { ...filesRoutes(), "GET /api/v1/papers/:id/files": () => ({ body: listed }) });
    const drawer = await openDrawer();
    expect(within(drawer).getByRole("heading", { name: "Upload full text (PDF)" })).toBeInTheDocument();
    const input = drawer.querySelector<HTMLInputElement>("input[type=file]")!;
    await userEvent.upload(input, new File(["%PDF-1.4"], "paper.pdf", { type: "application/pdf" }));
    expect(await within(drawer).findByText(/Uploaded paper.pdf/)).toBeInTheDocument();
    expect(sent[0]?.url).toBe(PAPER);
    expect(await within(drawer).findByText("paper.pdf", { selector: ".file-name" })).toBeInTheDocument();
    expect(within(drawer).getByRole("link", { name: "Download paper.pdf" })).toHaveAttribute("href", `${PAPER}/${paperFile().id}`);
  });

  it("refuses a non-PDF and a too-large file in the browser, and shows the server's refusal", async () => {
    const { sent } = fakeXhr({ status: 413, body: { code: "too_large", message: "The PDF is larger than 30 MB", request_id: "r" } });
    setup("member", filesRoutes());
    const drawer = await openDrawer();
    const input = drawer.querySelector<HTMLInputElement>("input[type=file]")!;
    await userEvent.upload(input, new File(["hello"], "notes.txt", { type: "text/plain" }), { applyAccept: false });
    expect(await within(drawer).findByRole("alert")).toHaveTextContent("notes.txt is not a PDF");
    expect(sent).toHaveLength(0);
    await userEvent.upload(input, new File(["%PDF-1.4"], "paper.pdf", { type: "application/pdf" }));
    expect(await within(drawer).findByRole("alert")).toHaveTextContent("The PDF is larger than 30 MB");
  });

  it("deletes a file after confirming", async () => {
    const { calls } = setup("member", { ...filesRoutes([paperFile()]), [`DELETE ${PAPER}/${paperFile().id}`]: { status: 204 } });
    const drawer = await openDrawer();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    await userEvent.click(await within(drawer).findByRole("button", { name: "Delete paper.pdf" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("Delete paper.pdf?"));
    confirm.mockRestore();
  });

  it("viewers see the list but cannot upload, download or delete", async () => {
    setup("viewer", filesRoutes([paperFile({ can_delete: false })]));
    const drawer = await openDrawer();
    expect(await within(drawer).findByText("paper.pdf", { selector: ".file-name" })).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: /Choose a PDF/ })).not.toBeInTheDocument();
    expect(within(drawer).queryByRole("link", { name: /Download/ })).not.toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: /Delete/ })).not.toBeInTheDocument();
  });

  it("says when uploads are turned off", async () => {
    setup("member", { ...filesRoutes(), "GET /api/v1/settings/review": { body: reviewSettings({ fulltext: { sources: ["pmc_oa"], contact: null, max_chars: 60000, upload_max_mb: 30 } }) } });
    const drawer = await openDrawer();
    expect(await within(drawer).findByText(/Uploads are turned off in Settings → Full text/)).toBeInTheDocument();
  });
});
