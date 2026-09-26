import type { DrawerOut, PaperRow, RunDetailOut, RunOut, StageOut, UserOut } from "../api/types";

export const user = (role: "viewer" | "member" | "admin" = "member"): UserOut => ({
  id: "11111111-1111-4111-8111-111111111111",
  email: `${role}@example.org`,
  name: role[0]!.toUpperCase() + role.slice(1),
  role,
  active: true,
});

export const session = (role: "viewer" | "member" | "admin" = "member") => ({ user: user(role), csrf_token: "csrf-test" });

export const RUN_ID = "22222222-2222-4222-8222-222222222222";
export const PAPER_ID = "33333333-3333-4333-8333-333333333333";
export const FIELD_ID = "44444444-4444-4444-8444-444444444444";

export const runOut = (over: Partial<RunOut> = {}): RunOut => ({
  id: RUN_ID, field_id: FIELD_ID, field_name: "ML CT-FFR", kind: "eval", status: "done",
  finished_at: "2026-09-26T09:00:00Z", created_at: "2026-09-26T08:00:00Z", gold_set_name: "mlffrct-2024",
  paper_count: 151, error: null, models: {}, ...over,
});

export const runDetail = (over: Partial<RunDetailOut> = {}): RunDetailOut => ({
  ...runOut(), manifest: {}, counts: { screened: 151, kept: 112, dropped: 39, escalated: 82, in_sr: 16 }, ...over,
});

const stage = (id: string, title: string, status: StageOut["status"], headline: string | null = null, over: Partial<StageOut> = {}): StageOut => ({
  id, title, summary: `${title} summary.`, limits: `${title} limits.`, status, headline, caveat: null, data_link: null, ...over,
});

export const STAGES: StageOut[] = [
  stage("topic", "Topic", "input"),
  stage("plan", "Plan", "unmeasured"),
  stage("search", "Search", "measured", "recall 15/16", { data_link: "evals" }),
  stage("dedup", "Deduplicate", "unmeasured"),
  stage("screen", "Screen", "measured", "recall 15/16", { data_link: "papers", summary: "Jev decides when confident; Claude screens the rest.", limits: "Abstract only." }),
  stage("extract", "Extract", "measured", "36 papers, quotes verified", { data_link: "papers" }),
  stage("reviewers", "Reviewers A and B", "caveat", "kappa 0.94", { caveat: "one model family", data_link: "evals" }),
  stage("adjudicate", "Adjudicate", "measured", "fired 1 of 36", { data_link: "papers" }),
  stage("rank", "Rank", "unmeasured", null, { data_link: "papers" }),
];

export const paperRow = (over: Partial<PaperRow> = {}): PaperRow => ({
  paper: { id: PAPER_ID, source_id: "MED:1", title: "Diagnostic accuracy of a deep learning approach to calculate FFR", year: 2019, doi: "10.1000/x" },
  found_by: "query", in_sr: true,
  screen: { tier: "jev", decision: "include", jev_decision: "include", llm_decision: null, criteria: { topic_match: 0.99 } },
  extract: { claims: 5, quotes_verified: true },
  reviews: { a: "include", b: "include", adjudicated: false, adjudicator: null },
  rank: { score: 82, position: 1 },
  ...over,
});

/** The real paper the screen lost: Jev 0.06 (just above the auto-drop line), dropped by the LLM, included by the SR. */
export const lostRow = (): PaperRow =>
  paperRow({
    paper: { id: "55555555-5555-4555-8555-555555555555", source_id: "MED:35097009", title: "Change in CT-Derived FFR Across the Lesion Improve the Diagnostic Performance", year: 2021, doi: "10.3389/fcvm.2021.788703" },
    found_by: "lookup", in_sr: true,
    screen: { tier: "llm", decision: "exclude", jev_decision: "escalate", llm_decision: "exclude", criteria: { topic_match: 0.06 } },
    extract: null, reviews: null, rank: null,
  });

export const drawerOut = (over: Partial<DrawerOut> = {}): DrawerOut => ({
  paper: { id: "55555555-5555-4555-8555-555555555555", source_id: "MED:35097009", title: "Change in CT-Derived FFR Across the Lesion Improve the Diagnostic Performance", abstract: "This study sought to evaluate the diagnostic performance of change in CT-FFR across the lesion.", year: 2021, doi: "10.3389/fcvm.2021.788703" },
  found_by: "lookup", in_sr: true, label_source: "sr_included_list",
  screening: {
    tier: "llm", decision: "exclude", jev_decision: "escalate", llm_decision: "exclude", call_key: "a".repeat(64),
    reason: "Jev topic_match=0.06 (Jev was not confident, so the LLM decided); LLM screen: exclude",
    criteria: [{ key: "topic_match", question: "The paper's central subject is the topic.", probability: 0.06, jev_version: "jev-1.13.0" }],
  },
  claims: [{ statement: "ΔCT-FFR improves specificity over CCTA.", quote: "ΔCT-FFR and CT-FFR were 70.8 and 67.4%", call_key: "b".repeat(64) }],
  reviews: [
    { role: "a", verdict: "uncertain", relevance: 2, methods: 2, support: 2, detail: { assessment: "Retrospective diagnostic accuracy study; the abstract does not name ML.", strengths: ["Reference standard is invasive FFR"], weaknesses: ["Small cohort"] }, call_key: "c".repeat(64) },
    { role: "b", verdict: "exclude", relevance: 1, methods: 2, support: 2, detail: { assessment: "No machine learning is mentioned.", strengths: [], weaknesses: ["Off topic on the abstract"] }, call_key: "d".repeat(64) },
    { role: "adjudicator", verdict: "uncertain", relevance: 2, methods: 2, support: 2, detail: { assessment: "Uncertainty preserved.", reason: "The abstract neither confirms nor rules out ML/DL-based CT-FFR." }, call_key: "e".repeat(64) },
  ],
  rank: null,
  ...over,
});
