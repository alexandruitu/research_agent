import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AuthorSearch } from "../../api/types";
import { jobOut, session } from "../../test/fixtures";
import { mockApi } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";
import { activeFilterChips } from "../papers/activeFilters";
import { parseView } from "../papers/papersState";
import { emptyForm, toDraft, validate } from "../fields/fieldForm";
import { MatchedBy } from "./MatchedBy";
import { defaultCoauthors, matchWords } from "./researcher";
import { ResearcherPanel } from "./ResearcherPanel";

afterEach(() => vi.unstubAllGlobals());

const SEARCH_JOB = "11111111-1111-4111-8111-111111111111";
const GROUP_JOB = "22222222-2222-4222-8222-222222222222";
const candidates = [
  { openalex_id: "A1", name: "Ana Popescu", orcid: "0000-0002-1825-0097", works_count: 40, institution: { openalex_id: "I5", name: "UMF Iasi" }, concepts: ["Imaging"] },
  { openalex_id: "A7", name: "Ana Popescu", orcid: "", works_count: 2, institution: null, concepts: [] },
];
const coauthors = [
  { openalex_id: "A2", orcid: "", name: "Bob Stan", shared: 5 },
  { openalex_id: "A3", orcid: "", name: "Cid Ene", shared: 3 },
  { openalex_id: "A4", orcid: "", name: "Dan Rus", shared: 1 },
];

describe("researcher words", () => {
  it("checks co-authors with at least N shared works and words every match kind", () => {
    expect(defaultCoauthors(coauthors, 3).map((c) => c.openalex_id)).toEqual(["A2", "A3"]);
    expect(defaultCoauthors(coauthors, 5).map((c) => c.openalex_id)).toEqual(["A2"]);
    expect(matchWords({ kind: "person", name: "Ana" })).toBe("the person (Ana)");
    expect(matchWords({ kind: "coauthor", name: "Bob" })).toBe("co-author Bob");
    expect(matchWords({ kind: "institution", name: "UMF" })).toBe("institution UMF");
    expect(matchWords({ kind: "name_match", name: "Ana" })).toMatch(/^name match: Ana/);
  });

  it("a researcher topic needs no criteria and sends its authors", () => {
    const authors: AuthorSearch = { people: [{ openalex_id: "A1", name: "Ana Popescu", orcid: "", s2_id: "" }], group: "person", coauthors: [], institutions: [], min_shared: 3 };
    const form = { ...emptyForm(["openalex"]), name: "Ana", authors };
    expect(validate(form)).toEqual([]);
    expect(toDraft(form)).toMatchObject({ topic: "Papers by Ana Popescu", include: [], authors });
    expect(validate({ ...form, authors: null })).toContain("Add at least one inclusion or exclusion criterion.");
  });
});

describe("Matched by", () => {
  it("shows a chip per match in words, nothing for other topics", () => {
    const { container, rerender } = render(<MatchedBy matches={[{ kind: "person", name: "Ana" }, { kind: "name_match", name: "Bob" }]} />);
    expect(container).toHaveTextContent("Matched by: the person (Ana)name match: Bob — may be another person");
    rerender(<MatchedBy matches={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("filters from the URL and shows a removable chip", () => {
    const view = parseView(new URLSearchParams("run=r1&match=coauthor"));
    expect(view.params.matched_by).toBe("coauthor");
    expect(activeFilterChips(view, []).map((c) => c.label)).toContain("Matched by a co-author");
    expect(parseView(new URLSearchParams("match=bogus")).params.matched_by).toBeUndefined();
  });
});

describe("ResearcherPanel", () => {
  function Host({ onChange }: { onChange: (a: AuthorSearch | null) => void }) {
    const [authors, setAuthors] = useState<AuthorSearch | null>(null);
    return <ResearcherPanel authors={authors} demo onChange={(next) => { setAuthors(next); onChange(next); }} />;
  }

  it("finds the person, picks them, and checks frequent co-authors by default", async () => {
    const api = mockApi({
      "GET /api/v1/auth/me": { body: session("member") },
      "POST /api/v1/authors/lookup": ({ body }) => ({ status: 202, body: jobOut({ id: (body as { step: string }).step === "search" ? SEARCH_JOB : GROUP_JOB, kind: "author_lookup", run_id: null }) }),
      [`GET /api/v1/jobs/${SEARCH_JOB}`]: { body: jobOut({ id: SEARCH_JOB, kind: "author_lookup", status: "done", progress: { result: { step: "search", name: "Ana", candidates } } }) },
      [`GET /api/v1/jobs/${GROUP_JOB}`]: {
        body: jobOut({ id: GROUP_JOB, kind: "author_lookup", status: "done", progress: { result: { step: "group", works: 40, coauthors, institutions: [{ openalex_id: "I5", name: "UMF Iasi", works: 30 }],
          people: [{ openalex_id: "A1", name: "Ana Popescu", orcid: "0000-0002-1825-0097", s2_id: "777" }] } } }),
      },
    });
    const onChange = vi.fn();
    renderWithProviders(<Host onChange={onChange} />);
    await userEvent.type(screen.getByRole("textbox", { name: "Researcher name" }), "Ana");
    await userEvent.click(screen.getByRole("button", { name: "Find researcher" }));
    const first = await screen.findByRole("checkbox", { name: /Ana Popescu UMF Iasi · 40 works · ORCID 0000-0002-1825-0097/ });
    await userEvent.click(first);
    await userEvent.click(screen.getByRole("button", { name: "Use selected (1)" }));
    const list = await screen.findByRole("list", { name: "Co-authors" });
    const boxes = within(list).getAllByRole("checkbox");
    expect(boxes.map((b) => (b as HTMLInputElement).checked)).toEqual([true, true, false]);
    expect(api.calls.filter((c) => c.path === "/api/v1/authors/lookup").map((c) => c.body)).toEqual([
      { step: "search", name: "Ana", mode: "demo" },
      { step: "group", people: [{ openalex_id: "A1", name: "Ana Popescu", orcid: "0000-0002-1825-0097", s2_id: "" }], mode: "demo" },
    ]);
    const last = () => onChange.mock.calls.at(-1)![0] as AuthorSearch;
    expect(last().coauthors?.map((c) => c.openalex_id)).toEqual(["A2", "A3"]);
    expect(last().people[0]!.s2_id).toBe("777");
    await userEvent.click(boxes[2]!);
    expect(last().coauthors?.map((c) => c.openalex_id)).toEqual(["A2", "A3", "A4"]);
    await userEvent.click(screen.getByRole("radio", { name: /institution/ }));
    expect(last().group).toBe("institution");
    expect(screen.getByRole("checkbox", { name: /UMF Iasi 30 works/ })).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Stop searching by researcher" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });
});
