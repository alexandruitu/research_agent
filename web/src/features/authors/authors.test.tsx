import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AuthorOut, AuthorSuggestionOut } from "../../api/types";
import { paperRow, runDetail, runOut, session, STAGES } from "../../test/fixtures";
import { mockApi } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";
import { PapersPage } from "../../pages/PapersPage";
import { activeFilterChips, clearPaperFilters } from "../papers/activeFilters";
import { parseView } from "../papers/papersState";
import { AuthorFilter } from "./AuthorFilter";
import { AuthorDetails, AuthorLine } from "./AuthorList";
import { authorLine, identityWords, NAME_MATCH_NOTE } from "./authors";

afterEach(() => vi.unstubAllGlobals());

const AUTHOR_ID = "a1a1a1a1-a1a1-4a1a-8a1a-a1a1a1a1a1a1";
const NAME_ONLY_ID = "b2b2b2b2-b2b2-4b2b-8b2b-b2b2b2b2b2b2";
const author = (over: Partial<AuthorOut> = {}): AuthorOut => ({ id: AUTHOR_ID, name: "Ana Popescu", orcid: "0000-0002-1825-0097", openalex_id: "A1", position: 1, affiliations: ["Carol Davila University"], ...over });
const suggestion = (over: Partial<AuthorSuggestionOut> = {}): AuthorSuggestionOut => ({ ...author(), paper_count: 3, ...over });
const four = [author(), author({ id: "x2", name: "Jon Smith", orcid: null, openalex_id: null, position: 2, affiliations: [] }), author({ id: "x3", name: "C Third", position: 3 }), author({ id: "x4", name: "D Fourth", position: 4 })];

describe("author words", () => {
  it("shows the first three then et al., and says how each author is known", () => {
    expect(authorLine(four)).toBe("Ana Popescu, Jon Smith, C Third et al.");
    expect(authorLine(four.slice(0, 3), 7)).toBe("Ana Popescu, Jon Smith, C Third et al.");
    expect(authorLine(four.slice(0, 2))).toBe("Ana Popescu, Jon Smith");
    expect(authorLine([])).toBe("");
    expect(identityWords(four[0]!)).toBe("ORCID · OpenAlex");
    expect(identityWords(four[1]!)).toBe("name only");
  });
});

describe("author display", () => {
  it("renders a short line and nothing when no author is stored", () => {
    const { container, rerender } = render(<AuthorLine authors={four.slice(0, 3)} count={4} />);
    expect(container).toHaveTextContent("Authors: Ana Popescu, Jon Smith, C Third et al.");
    rerender(<AuthorLine authors={[]} count={0} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("lists every author with ORCID and OpenAlex links that open externally", () => {
    render(<AuthorDetails authors={four} />);
    const list = screen.getByRole("list", { name: "Authors" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(4);
    const orcid = screen.getByRole("link", { name: "ORCID 0000-0002-1825-0097 of Ana Popescu (opens in a new tab)" });
    expect(orcid).toHaveAttribute("href", "https://orcid.org/0000-0002-1825-0097");
    expect(orcid).toHaveAttribute("target", "_blank");
    expect(orcid).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getAllByRole("link", { name: /OpenAlex profile of Ana Popescu/ })[0]).toHaveAttribute("href", "https://openalex.org/A1");
    expect(within(list).getAllByRole("listitem")[1]).toHaveTextContent("Jon Smith (name only)");
  });

  it("says when authors are not stored yet (missing is not none)", () => {
    render(<AuthorDetails authors={[]} />);
    expect(screen.getByText(/Authors not stored yet/)).toBeInTheDocument();
  });
});

describe("AuthorFilter typeahead", () => {
  function setup(props: Partial<Parameters<typeof AuthorFilter>[0]> = {}) {
    const api = mockApi({
      "GET /api/v1/auth/me": { body: session("viewer") },
      "GET /api/v1/authors": { body: [suggestion(), suggestion({ id: NAME_ONLY_ID, name: "Ana Popescu", orcid: null, openalex_id: null, paper_count: 5 })] },
    });
    const onChange = vi.fn();
    renderWithProviders(<AuthorFilter scope={{ run_id: "r1" }} onChange={onChange} debounceMs={0} {...props} />);
    return { api, onChange };
  }

  it("suggests stored authors with their identifier badge and paper count, scoped to the run", async () => {
    const { api, onChange } = setup();
    await userEvent.type(screen.getByRole("combobox", { name: "Author" }), "ana");
    const options = await screen.findAllByRole("option");
    expect(options[0]).toHaveTextContent("Ana Popescu ORCID · OpenAlex 3 papers");
    expect(options[1]).toHaveTextContent("Ana Popescu name only 5 papers");
    expect(options[2]).toHaveTextContent(`Any author named “ana” (${NAME_MATCH_NOTE})`);
    const request = new URLSearchParams([...api.calls].reverse().find((c) => c.path === "/api/v1/authors")!.search);
    expect(request.get("q")).toBe("ana");
    expect(request.get("run_id")).toBe("r1");
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenCalledWith({ author: AUTHOR_ID, aname: null });
  });

  it("filters by name on Enter with free text, and labels it a name match", async () => {
    const { onChange } = setup();
    await userEvent.type(screen.getByRole("combobox", { name: "Author" }), "  Jon Smith {Enter}");
    expect(onChange).toHaveBeenCalledWith({ author: null, aname: "Jon Smith" });
  });

  it("shows the name-match note while a name filter is active", () => {
    setup({ authorName: "Jon Smith" });
    expect(screen.getByRole("note")).toHaveTextContent(`Author “Jon Smith”: ${NAME_MATCH_NOTE}.`);
  });
});

describe("author filter in the URL", () => {
  it("parses author and aname, makes chips, and clears them", () => {
    const search = new URLSearchParams(`author=${AUTHOR_ID}&aname=%20Jon%20Smith%20&decision=include`);
    const view = parseView(search);
    expect(view.params.author_id).toBe(AUTHOR_ID);
    expect(view.params.author_name).toBe("Jon Smith");
    expect(parseView(new URLSearchParams("author=not-an-id")).params.author_id).toBeUndefined();
    const labels = activeFilterChips(view, [], "Ana Popescu (ORCID)").map((c) => c.label);
    expect(labels).toContain("Author: Ana Popescu (ORCID)");
    expect(labels).toContain("Author named “Jon Smith” (name match)");
    const cleared = clearPaperFilters(search);
    expect(cleared.get("author")).toBeNull();
    expect(cleared.get("aname")).toBeNull();
  });

  it("Results: picking an author puts it in the URL and the papers request; the chip names the person", async () => {
    function Location() {
      return <output aria-label="location">{useLocation().search}</output>;
    }
    localStorage.setItem("papers.view.11111111-1111-4111-8111-111111111111", "simple");
    const api = mockApi({
      "GET /api/v1/auth/me": { body: session("member") },
      "GET /api/v1/runs": { body: [runOut()] },
      "GET /api/v1/runs/:id": { body: runDetail() },
      "GET /api/v1/stages": { body: STAGES },
      "GET /api/v1/runs/:id/papers": { body: { items: [paperRow({ authors: four.slice(0, 3), author_count: 4 })], total: 1, page: 1, page_size: 25 } },
      "GET /api/v1/authors": { body: [suggestion()] },
      "GET /api/v1/authors/:id": { body: suggestion() },
    });
    renderWithProviders(<><Routes><Route path="/results" element={<PapersPage />} /></Routes><Location /></>, { route: "/results?group=none" });
    expect(await screen.findByText("Ana Popescu, Jon Smith, C Third et al.")).toBeInTheDocument();
    await userEvent.type(screen.getByRole("combobox", { name: "Author" }), "ana");
    await userEvent.click(await screen.findByRole("option", { name: /ORCID · OpenAlex/ }));
    await waitFor(() => expect(screen.getByLabelText("location")).toHaveTextContent(`author=${AUTHOR_ID}`));
    await waitFor(() => {
      const last = [...api.calls].reverse().find((c) => c.path.endsWith("/papers"))!;
      expect(new URLSearchParams(last.search).get("author_id")).toBe(AUTHOR_ID);
    });
    expect(await screen.findByRole("button", { name: /Author: Ana Popescu \(ORCID · OpenAlex\)/ })).toBeInTheDocument();
    localStorage.clear();
  });
});
