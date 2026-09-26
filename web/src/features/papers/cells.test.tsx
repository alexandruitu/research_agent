import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { lostRow, paperRow } from "../../test/fixtures";
import { DecisionCell, ExtractCellView, InSrCell, ReviewsCellView, ScoreCell, TopicMatchCell } from "./cells";

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
    render(<TopicMatchCell screen={paperRow().screen} />);
    expect(screen.getByText("0.99")).toBeInTheDocument();
    expect(screen.getByText("Jev")).toBeInTheDocument();
  });

  it("marks an escalated paper and names the deciding tier", () => {
    render(<><TopicMatchCell screen={lostRow().screen} /><DecisionCell screen={lostRow().screen} /></>);
    expect(screen.getByText("0.06")).toBeInTheDocument();
    expect(screen.getByText("escalated")).toBeInTheDocument();
    expect(screen.getByText("drop")).toBeInTheDocument();
    expect(screen.getByText("LLM")).toBeInTheDocument();
  });

  it("shows a dash when there is no Jev score, and prefixes keys when there are several criteria", () => {
    const { rerender } = render(<TopicMatchCell screen={{ ...paperRow().screen, criteria: {} }} />);
    expect(screen.getByLabelText("not applicable")).toBeInTheDocument();
    rerender(<TopicMatchCell screen={{ ...paperRow().screen, criteria: { topic_match: 0.9, uses_dl: 0.4 } }} />);
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
