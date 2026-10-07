import { Term } from "../../components/ui/Term";

/** The three separate answers each paper gets, in one line: screening, appraisal and the team's call. */
export function AxesLegend() {
  return (
    <p className="axes-legend">
      Three separate answers per paper:{" "}
      <span className="axis"><Term k="search_match">Search match</Term> — fits your criteria? (Kept, Dropped, Unsure)</span>{" · "}
      <span className="axis"><Term k="quality">Quality</Term> — what the review panel found</span>{" · "}
      <span className="axis"><Term k="team_decision">Team decision</Term> — what your team decided</span>
    </p>
  );
}
