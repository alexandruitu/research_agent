import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../../api/client";
import { JOB_ID, jobOut, session, testResult } from "../../test/fixtures";
import { mockApi } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";
import { CriteriaTestPanel } from "./CriteriaTestPanel";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const job = (over: Parameters<typeof jobOut>[0]) => ({ body: jobOut({ kind: "criteria_test", run_id: null, ...over }) });

function setup(handler: Parameters<typeof mockApi>[0][string]) {
  mockApi({ "GET /api/v1/auth/me": { body: session("member") }, "GET /api/v1/jobs/:id": handler });
  renderWithProviders(<CriteriaTestPanel jobId={JOB_ID} />);
}

describe("CriteriaTestPanel", () => {
  it("shows progress while the worker tests papers", async () => {
    setup(job({ status: "running", progress: { status: "running", done: 3, total: 20 } }));
    expect(await screen.findByText("Testing: 3 of 20 papers")).toBeInTheDocument();
  });

  it("shows one row per paper, one column per criterion, and marks the deciding cell in words", async () => {
    setup(job({ status: "done", progress: { status: "done", result: testResult() } }));
    const table = await screen.findByRole("table");
    expect(within(table).getByRole("columnheader", { name: "incl 1" })).toBeInTheDocument();
    const dropped = within(table).getByRole("row", { name: /a review/ });
    expect(dropped).toHaveTextContent("0.96 decided");
    expect(dropped).toHaveTextContent("dropped · excl 1");
    expect(within(table).getByRole("row", { name: /against invasive FFR/ })).toHaveTextContent("kept");
    expect(within(table).getByRole("row", { name: /without an abstract/ })).toHaveTextContent("not screened");
    expect(screen.getByText(/1 kept · 1 dropped · 0 to the LLM · 1 not screened/)).toBeInTheDocument();
    expect(screen.getByText(/Demo mode/)).toBeInTheDocument();
    expect(screen.getByText("The paper is a review or an editorial.")).toBeInTheDocument();
  });

  it("shows the job's sanitized error when the test fails", async () => {
    setup(job({ status: "failed", error: "TYPESAFE_API_KEY is not set in the worker" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The test failed: TYPESAFE_API_KEY is not set in the worker");
  });
});
