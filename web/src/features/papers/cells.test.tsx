import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { lostRow, paperRow } from "../../test/fixtures";
import type { PaperRow } from "../../api/types";
import { CriteriaCell, DecisionCell, ExtractCellView, FoundByCell, InSrCell, ReviewsCellView, ScoreCell } from "./cells";

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
    expect(screen.getByText("Jev")).toBeInTheDocument();
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
