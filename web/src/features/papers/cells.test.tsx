import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { lostRow, paperRow } from "../../test/fixtures";
import type { PaperRow } from "../../api/types";
import { CriteriaCell, DecisionCell, RedFlagsCell, ExtractCellView, FoundByCell, InSrCell, ReviewsCellView, ScoreCell } from "./cells";

describe("tri-state cells", () => {
  it("shows a labelled dash when the stage does not apply", () => {
    render(<ExtractCellView cell={null} />);
    expect(screen.getByLabelText("not applicable")).toHaveTextContent("–");
  });

  it("shows a hatched marker, never a dash, when expected data is missing", () => {
    render(<ReviewsCellView cell={{ missing: true }} />);
    const marker = screen.getByText("missing");
    expect(marker).toHaveClass("missing");
    expect(screen.queryByLabelText("not applicable")).not.toBeInTheDocument();
  });

  it("shows the data when it is there", () => {
    render(<><ExtractCellView cell={{ claims: 5, quotes_verified: true }} /><ReviewsCellView cell={{ a: "include", b: "exclude", adjudicated: true, adjudicator: "uncertain" }} /></>);
    expect(screen.getByText("5 verified")).toBeInTheDocument();
    expect(screen.getByText(/inc \/ exc/)).toBeInTheDocument();
    expect(screen.getByText(/adj: unc/)).toBeInTheDocument();
  });
});

describe("screening cells", () => {
  it("shows the Jev probability with a Jev badge when Jev decided", () => {
    render(<CriteriaCell screen={paperRow().screen} />);
    expect(screen.getByText("0.99")).toBeInTheDocument();
    expect(screen.getByText("Jev", { selector: ".term" })).toBeInTheDocument();
  });

  it("marks an escalated paper and names the deciding tier", () => {
    render(<><CriteriaCell screen={lostRow().screen} /><DecisionCell screen={lostRow().screen} /></>);
    expect(screen.getByText("0.06")).toBeInTheDocument();
    expect(screen.getByText("escalated")).toBeInTheDocument();
    expect(screen.getByText("drop")).toBeInTheDocument();
    expect(screen.getByText("LLM")).toBeInTheDocument();
  });

  it("shows a dash when there is no Jev score, and prefixes keys when there are several criteria", () => {
    const { rerender } = render(<CriteriaCell screen={{ ...paperRow().screen, criteria: {} }} />);
    expect(screen.getByLabelText("not applicable")).toBeInTheDocument();
    rerender(<CriteriaCell screen={{ ...paperRow().screen, criteria: { topic_match: 0.9, uses_dl: 0.4 } }} />);
    expect(screen.getByText("uses_dl 0.40")).toBeInTheDocument();
  });

  it("shows SR membership as words, and a dash when the run has no gold set", () => {
    const { rerender } = render(<InSrCell value={true} />);
    expect(screen.getByText("yes")).toBeInTheDocument();
    rerender(<InSrCell value={false} />);
    expect(screen.getByText("no")).toBeInTheDocument();
    rerender(<InSrCell value={null} />);
    expect(screen.getByLabelText("not applicable")).toBeInTheDocument();
    rerender(<ScoreCell rank={{ score: 81.6, position: 2 }} />);
    expect(screen.getByText("82")).toBeInTheDocument();
  });
});

const fieldScreen = (over: Partial<PaperRow["screen"]> = {}): PaperRow["screen"] => ({
  tier: "jev", decision: "exclude", jev_decision: "exclude", llm_decision: null, criteria: { i1: 0.01, i2: 0.9, e1: 0.02 }, decided_by: "i1",
  cells: { i1: { kind: "include", jev_p: 0.01, llm: null, quote: null }, i2: { kind: "include", jev_p: 0.9, llm: null, quote: null }, e1: { kind: "exclude", jev_p: 0.02, llm: null, quote: null } },
  ...over,
});

describe("criteria cell for a field with criteria", () => {
  it("names the criterion Jev dropped the paper on", () => {
    render(<CriteriaCell screen={fieldScreen()} />);
    expect(screen.getByText("dropped by incl 1 (0.01)")).toBeInTheDocument();
  });

  it("names the criterion and the LLM's answer when the LLM decided", () => {
    render(<CriteriaCell screen={fieldScreen({ tier: "llm", jev_decision: "escalate", llm_decision: "exclude", decided_by: "e1", cells: { e1: { kind: "exclude", jev_p: 0.5, llm: "yes", quote: "a narrative review" } } })} />);
    expect(screen.getByText("dropped by excl 1 (LLM: yes)")).toBeInTheDocument();
    expect(screen.getByText("escalated")).toBeInTheDocument();
  });

  it("says all met when kept, and says so when no single criterion decided", () => {
    const { rerender } = render(<CriteriaCell screen={fieldScreen({ decision: "include", jev_decision: "include", decided_by: null })} />);
    expect(screen.getByText("all met")).toBeInTheDocument();
    rerender(<CriteriaCell screen={fieldScreen({ tier: "llm", decision: "uncertain", decided_by: null })} />);
    expect(screen.getByText("no single criterion decided")).toBeInTheDocument();
  });

  it("lists the sources a paper was found in", () => {
    const { rerender } = render(<FoundByCell foundBy="query" sources={["europepmc", "openalex"]} />);
    expect(screen.getByText("Europe PMC, OpenAlex")).toBeInTheDocument();
    rerender(<FoundByCell foundBy="query" sources={["semantic_scholar", "pubmed", "ieee", "crossref"]} />);
    expect(screen.getByText("Semantic Scholar, PubMed, IEEE Xplore, Crossref")).toBeInTheDocument();
    rerender(<FoundByCell foundBy="lookup" sources={[]} />);
    expect(screen.getByText("lookup")).toBeInTheDocument();
  });
});

describe("criteria values", () => {
  it("lists every criterion with its full value and marks the decider in words", () => {
    render(<CriteriaCell screen={fieldScreen({ cells: { ...fieldScreen().cells, e1: { kind: "exclude", jev_p: 0.02, llm: "no", quote: null } } })} />);
    const list = screen.getByRole("list", { name: "Criteria values" });
    const items = within(list).getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toEqual(["incl 1p 0.01◆ decided", "incl 2p 0.90", "excl 1p 0.02LLM no"]);
  });
});

describe("paper column", () => {
  it("clamps the title but keeps the full title on hover, and says abstract only once, in the Text reviewed column", async () => {
    const { PaperTable } = await import("./PaperTable");
    const row = paperRow({ text_source: "abstract", score: 70, coverage: 0.8, red_flag_count: 0 });
    render(<PaperTable rows={[row]} sort="title" direction="asc" onSort={() => {}} selectedPaperId={null} onOpen={() => {}} legacy={true} />);
    const title = screen.getByRole("button", { name: row.paper.title });
    expect(title).toHaveClass("title-clamp");
    expect(title).toHaveAttribute("title", row.paper.title);
    const marks = screen.getAllByText("abstract only");
    expect(marks).toHaveLength(1);
    const cell = marks[0].closest("td")!;
    const headers = Array.from(cell.closest("table")!.querySelectorAll("thead tr:last-child th")).map((th) => th.textContent ?? "");
    expect(headers[Array.from(cell.parentElement!.children).indexOf(cell)]).toMatch(/Text reviewed/);
  });
});

describe("provisional scores", () => {
  it("marks a panel score from under half of the checklist as provisional, in words with an explanation", async () => {
    const { PanelScoreCell } = await import("./cells");
    render(<PanelScoreCell score={90} coverage={0.3} provisional={true} answered={3} total={10} />);
    const marker = screen.getByRole("button", { name: "provisional" });
    fireEvent.focus(marker);
    expect(screen.getByRole("tooltip", { hidden: true })).toHaveTextContent("Only 3 of 10 checklist items could be answered (abstract only) — upload the full text to firm this up");
    expect(marker).toHaveAttribute("aria-describedby", screen.getByRole("tooltip", { hidden: true }).id);
    // the number stays (Detailed view) but is de-emphasised, never the big figure
    expect(screen.getByText("90")).toHaveClass("score-muted");
    expect(document.querySelector(".panel-score > strong")).toBeNull();
  });

  it("shows no marker on a firm score", async () => {
    const { PanelScoreCell } = await import("./cells");
    render(<PanelScoreCell score={90} coverage={0.8} provisional={false} answered={8} total={10} />);
    expect(screen.queryByText("provisional")).not.toBeInTheDocument();
  });
});

describe("compact criteria line", () => {
  it("summarises the criteria and lists each one on focus", async () => {
    const { CriteriaLine } = await import("./cells");
    const { default: userEvent } = await import("@testing-library/user-event");
    render(<CriteriaLine screen={fieldScreen()} texts={{ i1: "Uses deep learning." }} />);
    expect(screen.getByRole("button", { name: /dropped by incl 1/ })).toBeInTheDocument();
    await userEvent.tab();
    const tip = screen.getByRole("tooltip");
    expect(within(tip).getByText(/Uses deep learning/)).toHaveTextContent("incl 1 Uses deep learning. — fails · Jev p 0.01 · ◆ decided");
    expect(within(tip).getAllByRole("listitem")).toHaveLength(3);
  });
});

describe("red flags cell", () => {
  it("names the problem, never the positive checklist item", () => {
    render(<RedFlagsCell count={2} flags={["No external validation", "Data not split by patient"]} />);
    expect(screen.getByText(/No external validation/)).toBeInTheDocument();
    expect(screen.getByText("+1 more")).toBeInTheDocument();
  });
  it("falls back to the count without texts", () => {
    render(<RedFlagsCell count={1} />);
    expect(screen.getByText("⚑ 1 red flag")).toBeInTheDocument();
  });
});
