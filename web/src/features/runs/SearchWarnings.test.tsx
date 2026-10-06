import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { emptyForm, toDraft } from "../fields/fieldForm";
import { PartialSearchBanner, PartialSearchMarker, SearchWarningPanel, partialSearchSentence, type SearchWarning } from "./SearchWarnings";

const S2: SearchWarning = {
  source: "semantic_scholar",
  error_type: "SourceUnavailable",
  reason: "rate limited (HTTP 429)",
  detail: "The source is rate limiting this server; retry later or set S2_API_KEY in the worker environment for a higher limit.",
};

afterEach(() => sessionStorage.clear());

describe("partial search", () => {
  it("words the banner sentence with the source label and the reason", () => {
    expect(partialSearchSentence([S2])).toBe("Partial search: Semantic Scholar (rate limited) skipped. Results may be missing papers from this source.");
  });

  it("marks a run in words and lists skipped sources for screen readers", () => {
    render(<PartialSearchMarker warnings={[S2]} />);
    const marker = screen.getByText(/Partial search/);
    expect(marker.closest("span")).toHaveAttribute("title", "Skipped: Semantic Scholar (rate limited)");
    expect(screen.getByText(/skipped Semantic Scholar/)).toHaveClass("sr-only");
  });

  it("shows nothing when no source was skipped or nothing was recorded", () => {
    const { container } = render(<><PartialSearchMarker warnings={[]} /><PartialSearchMarker warnings={null} /></>);
    expect(container).toBeEmptyDOMElement();
  });

  it("explains each skipped source with its fix and links to Settings → Sources", () => {
    render(<MemoryRouter><SearchWarningPanel warnings={[S2]} /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: /Partial search/ })).toBeInTheDocument();
    expect(screen.getByText(/S2_API_KEY/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings → Sources" })).toHaveAttribute("href", "/settings/sources");
  });

  it("says the run stopped when every source failed", () => {
    render(<MemoryRouter><SearchWarningPanel warnings={[S2]} failed /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: /No search source answered/ })).toBeInTheDocument();
  });

  it("lets the papers banner be dismissed for the run", () => {
    const { unmount } = render(<PartialSearchBanner runId="r1" warnings={[S2]} />);
    fireEvent.click(screen.getByRole("button", { name: /Dismiss/ }));
    expect(screen.queryByText(/Partial search:/)).not.toBeInTheDocument();
    unmount();
    render(<PartialSearchBanner runId="r1" warnings={[S2]} />);
    expect(screen.queryByText(/Partial search:/)).not.toBeInTheDocument();
    render(<PartialSearchBanner runId="r2" warnings={[S2]} />);
    expect(screen.getByText(/Partial search:/)).toBeInTheDocument();
  });
});

describe("required sources in the field form", () => {
  const form = () => ({ ...emptyForm(["europepmc", "openalex"]), name: "F", topic: "deep learning", include: ["Uses DL."] });

  it("sends only required sources that are selected, and nothing when none", () => {
    expect(toDraft(form())).not.toHaveProperty("required_sources");
    expect(toDraft({ ...form(), required: ["openalex", "arxiv"] }).required_sources).toEqual(["openalex"]);
  });
});
