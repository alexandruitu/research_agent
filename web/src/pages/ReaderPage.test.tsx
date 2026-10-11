import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import type { ReaderNoteOut, ReaderOut, ReaderResult } from "../api/types";
import { drawerOut, JOB_ID, jobOut, PAPER_ID, RUN_ID, session } from "../test/fixtures";
import { mockApi, type MockHandler } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { segments } from "../features/reader/segments";
import { ReaderPage } from "./ReaderPage";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
  window.getSelection()?.removeAllRanges();
});

const METHODS = "Data were split at patient level. The test set was external to the training hospitals.";
const reader = (over: Partial<ReaderOut> = {}): ReaderOut => ({
  paper: { id: PAPER_ID, source_id: "MED:1", title: "CT-FFR at scale", abstract: "An abstract.", year: 2026, doi: "" },
  run_id: RUN_ID, run_name: "Weekly CT-FFR", group: "worth_a_look", max_selection: 4000,
  text: { kind: "full_text", source: "pmc_oa", licence: "cc-by", truncated: false, sections: [{ title: "Methods", text: METHODS }, { title: "Results", text: "AUC 0.91." }] },
  highlights: [{ kind: "red_flag", quote: "split at patient level", label: "No external validation", by: "Reviewer statistician, item s3" }],
  ...over,
});
const result = (over: Partial<ReaderResult> = {}): ReaderResult => ({
  tool: "explain", mode: "demo", model: "synthetic-demo-v1", prompt_version: "reader-1", answer: "The data were split by patient.",
  statements: [{ text: "Split by patient", quote: "Data were split at patient level." }], not_in_paper: false, general: false,
  selection: "Data were split at patient level.", question: "", ...over,
});
const note = (): ReaderNoteOut => ({
  id: "abababab-abab-4bab-8bab-abababababab", paper_id: PAPER_ID, run_id: RUN_ID, library_item_id: null, selection: "Data were split at patient level.",
  tool: "explain", question: "", answer: "The data were split by patient.", not_in_paper: false, general: false,
  quotes: [{ text: "Split by patient", quote: "Data were split at patient level." }], model: "synthetic-demo-v1", created_by_name: "Member", created_at: "2026-10-11T10:00:00Z",
});

function setup(role: "viewer" | "member", data: ReaderOut = reader(), extra: Record<string, MockHandler> = {}) {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session(role) },
    "GET /api/v1/runs/:id/papers/:id/reader": { body: data },
    "GET /api/v1/runs/:id/papers/:id": { body: drawerOut({ library: null }) },
    "GET /api/v1/papers/:id/notes": { body: [] },
    ...extra,
  });
  renderWithProviders(
    <Routes><Route path="/read/:runId/:paperId" element={<ReaderPage />} /></Routes>,
    { route: `/read/${RUN_ID}/${PAPER_ID}` },
  );
  return api;
}

function select(text: string) {
  const article = screen.getByRole("article", { name: "Paper text" });
  const node = [...article.querySelectorAll("span")].map((s) => s.firstChild).find((n) => n?.textContent?.includes(text))!;
  const start = node.textContent!.indexOf(text);
  const range = document.createRange();
  range.setStart(node, start);
  range.setEnd(node, start + text.length);
  window.getSelection()!.removeAllRanges();
  window.getSelection()!.addRange(range);
  fireEvent.mouseUp(article);
}

describe("segments", () => {
  it("marks every quote and merges overlaps", () => {
    const hl = (quote: string, kind: "claim" | "red_flag" = "claim") => ({ kind, quote, label: quote, by: "x" });
    const parts = segments("abc def ghi", [hl("abc def"), hl("def ghi", "red_flag")]);
    expect(parts.map((p) => [p.text, p.marks.length])).toEqual([["abc ", 1], ["def", 2], [" ghi", 1]]);
    expect(segments("plain", [hl("absent")])).toEqual([{ text: "plain", marks: [] }]);
  });
});

describe("ReaderPage", () => {
  it("shows the full text by sections with the red flag marked and its source on focus", async () => {
    setup("viewer");
    expect(await screen.findByRole("heading", { name: "Methods" })).toBeInTheDocument();
    expect(screen.queryByText(/Abstract only/)).not.toBeInTheDocument();
    const mark = screen.getByText("split at patient level", { selector: "mark" });
    expect(mark).toHaveTextContent("Red flag quote:");
    fireEvent.focus(mark);
    expect(screen.getByText("Red flag: No external validation (Reviewer statistician, item s3)", { selector: ".reader-active p" })).toBeInTheDocument();
    expect(mark.getAttribute("aria-describedby")).toBe("hl-0");
    expect(screen.getByText(/Viewers can read the paper/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Explain (from the paper)" })).not.toBeInTheDocument();
  });

  it("says honestly when only the abstract is available", async () => {
    setup("member", reader({ text: { kind: "abstract", source: "abstract", licence: "abstract", truncated: false, sections: [{ title: "Abstract", text: "An abstract." }] }, highlights: [] }));
    expect(await screen.findByText("Abstract only — upload the PDF to read and ask about the full paper.")).toBeInTheDocument();
  });

  it("explains the selection, then saves the answer as a note and offers the library", async () => {
    const api = setup("member", reader(), {
      "POST /api/v1/runs/:id/papers/:id/reader/ask": { status: 202, body: jobOut({ kind: "reader_ask", run_id: null }) },
      "GET /api/v1/jobs/:id": { body: jobOut({ kind: "reader_ask", run_id: null, status: "done", progress: { result: result() } }) },
      "POST /api/v1/runs/:id/papers/:id/notes": { status: 201, body: note() },
    });
    await screen.findByRole("heading", { name: "Methods" });
    select("The test set was external");
    expect(screen.getByText(/Selected: “The test set was external”/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Explain (from the paper)" }));
    expect(await screen.findByText("The data were split by patient.")).toBeInTheDocument();
    const ask = api.calls.find((c) => c.method === "POST" && c.path.endsWith("/reader/ask"))!;
    expect(ask.body).toEqual({ tool: "explain", selection: "The test set was external", question: "" });
    expect(screen.getByText("Data were split at patient level.", { selector: "q" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save as note" }));
    expect(await screen.findByText("Note saved.")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path.endsWith("/notes") && c.method === "POST")!.body).toEqual({ job_id: JOB_ID });
    expect(screen.getByRole("button", { name: "Save it to the library too" })).toBeInTheDocument();
  });

  it("shows a failed answer as an error, nothing kept", async () => {
    setup("member", reader(), {
      "POST /api/v1/runs/:id/papers/:id/reader/ask": { status: 202, body: jobOut({ kind: "reader_ask", run_id: null }) },
      "GET /api/v1/jobs/:id": { body: jobOut({ kind: "reader_ask", run_id: null, status: "failed", error: "The answer's quotes did not match the paper's text after 3 attempts" }) },
    });
    await userEvent.type(await screen.findByLabelText("Question about the paper"), "Was it external?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/quotes did not match.*Nothing was kept/);
    expect(screen.queryByRole("button", { name: "Save as note" })).not.toBeInTheDocument();
  });

  it("labels a background explanation as general knowledge", async () => {
    setup("member", reader(), {
      "POST /api/v1/runs/:id/papers/:id/reader/ask": { status: 202, body: jobOut({ kind: "reader_ask", run_id: null }) },
      "GET /api/v1/jobs/:id": { body: jobOut({ kind: "reader_ask", run_id: null, status: "done", progress: { result: result({ tool: "background", general: true, statements: [], answer: "AUC is the area under the ROC curve." }) } }) },
    });
    await screen.findByRole("heading", { name: "Methods" });
    select("AUC 0.91.");
    await userEvent.click(screen.getByRole("button", { name: "Background explanation" }));
    const answer = await screen.findByText("AUC is the area under the ROC curve.");
    expect(within(answer.parentElement!).getByText("General knowledge — not from this paper, verify before relying on it")).toBeInTheDocument();
  });

  it("refuses a selection over 4,000 characters", async () => {
    const long = "word ".repeat(900).trim();
    setup("member", reader({ text: { kind: "full_text", source: "upload", licence: "user_upload", truncated: false, sections: [{ title: "Methods", text: long }] }, highlights: [] }));
    await screen.findByRole("heading", { name: "Methods" });
    select(long);
    expect(screen.getByRole("alert")).toHaveTextContent("select at most 4,000");
    expect(screen.getByRole("button", { name: "Explain (from the paper)" })).toBeDisabled();
  });

  it("lists the team's notes and the coming tools", async () => {
    setup("member", reader(), { "GET /api/v1/papers/:id/notes": { body: [note()] } });
    expect(await screen.findByRole("heading", { name: "Reader notes" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/Explain · Member/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "In-house" })).toBeDisabled();
    expect(screen.getByText("needs an internal collection — coming")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Find related" })).toBeDisabled();
  });
});
