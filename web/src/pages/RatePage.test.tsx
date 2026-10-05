import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { HUMAN_ID, SAMPLE_ID, jobOut, ratingNext, ratingSample, revealOut, session } from "../test/fixtures";
import { mockApi, type MockHandler } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { RatePage } from "./RatePage";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

function setup(extra: Record<string, MockHandler> = {}) {
  let nextCalls = 0;
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session("member") },
    "GET /api/v1/rating-samples/:id": { body: ratingSample() },
    "GET /api/v1/rating-samples/:id/next": () => ({ body: nextCalls++ === 0 ? ratingNext() : ratingNext({ done: true, paper: null, reviewers: [], position: 20 }) }),
    "POST /api/v1/rating-samples/:id/ratings": { status: 201, body: { paper_id: "MED:35097009", saved: 2, job: jobOut({ kind: "eval_run" }) } },
    "GET /api/v1/rating-samples/:id/papers/MED%3A35097009/reveal": { body: revealOut() },
    ...extra,
  });
  renderWithProviders(<Routes><Route path="/rate/:sampleId" element={<RatePage />} /></Routes>, { route: `/rate/${SAMPLE_ID}` });
  return api;
}

const item = (text: RegExp) => screen.getByRole("radiogroup", { name: text });

describe("Rate view", () => {
  it("shows the paper, its text source and the sample progress, and no model answers", async () => {
    const { calls } = setup();
    expect(await screen.findByRole("heading", { name: "Change in CT-Derived FFR" })).toBeInTheDocument();
    expect(screen.getByText("Paper 3 of 20")).toBeInTheDocument();
    expect(screen.getByText(/Abstract only/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Sample progress" })).toHaveTextContent("1 of 2 papers have 2 raters");
    expect(screen.getByRole("region", { name: "Paper text" })).toHaveTextContent("diagnostic performance of CT-FFR");
    expect(screen.queryByText(/single centre/)).not.toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/reveal"))).toBe(false);
  });

  it("submits only when every item has an answer, then reveals mine vs the model in words", async () => {
    const { calls } = setup();
    await screen.findByRole("heading", { name: "Change in CT-Derived FFR" });
    const submit = screen.getByRole("button", { name: /Submit ratings/ });
    expect(submit).toBeDisabled();
    expect(screen.getByText("0 of 2 items answered")).toBeInTheDocument();
    await userEvent.click(within(item(/external validation/)).getByRole("radio", { name: "No" }));
    await userEvent.type(screen.getByLabelText(/Quote for: Is there external validation/), "single centre only");
    await userEvent.click(within(item(/split by patient/)).getByRole("radio", { name: "Yes" }));
    expect(submit).toBeEnabled();
    await userEvent.click(submit);
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({
      paper_id: "MED:35097009",
      answers: [
        { reviewer: "methodologist", item: "m1", answer: "no", quote: "single centre only" },
        { reviewer: "statistician", item: "s1", answer: "yes", quote: "" },
      ],
    });
    const reveal = await screen.findByRole("region", { name: "You and the model" });
    expect(reveal).toHaveTextContent("You and the model agree on 1 of 2 items");
    expect(within(reveal).getByRole("row", { name: /external validation/ })).toHaveTextContent("agree");
    expect(within(reveal).getByRole("row", { name: /split by patient/ })).toHaveTextContent("disagree");
    expect(within(reveal).getByRole("row", { name: /split by patient/ })).toHaveTextContent("not reported");
    await userEvent.click(screen.getByRole("button", { name: "Next paper" }));
    expect(await screen.findByText(/You have rated every paper/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /human reference report/ })).toHaveAttribute("href", `/evals/${HUMAN_ID}`);
  });

  it("answers with the number keys on the focused item", async () => {
    setup();
    await screen.findByRole("heading", { name: "Change in CT-Derived FFR" });
    const yes = within(item(/external validation/)).getByRole("radio", { name: "Yes" });
    yes.focus();
    fireEvent.keyDown(yes, { key: "4" });
    expect(within(item(/external validation/)).getByRole("radio", { name: "Not reported" })).toBeChecked();
    fireEvent.keyDown(yes, { key: "3" });
    expect(within(item(/external validation/)).getByRole("radio", { name: "Unclear" })).toBeChecked();
  });

  it("says when the paper was already rated by this person", async () => {
    setup({ "POST /api/v1/rating-samples/:id/ratings": { status: 409, body: { code: "already_rated", message: "You already rated this paper", request_id: "r" } } });
    await screen.findByRole("heading", { name: "Change in CT-Derived FFR" });
    await userEvent.click(within(item(/external validation/)).getByRole("radio", { name: "No" }));
    await userEvent.click(within(item(/split by patient/)).getByRole("radio", { name: "No" }));
    await userEvent.click(screen.getByRole("button", { name: /Submit ratings/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already rated");
  });
});
