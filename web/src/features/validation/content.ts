// Static content of the "How it works" pages, taken from docs/agents.md, docs/architecture.md and
// src/research_agent/panel.py (DEFAULT_PANEL, Statistician v1). Keep in sync when those change.

export type Kind = "AI" | "Code";

export const FLOW: { name: string; kind: Kind; what: string; parallel?: { name: string; what: string }[] }[] = [
  { name: "Topic", kind: "Code", what: "The topic, keywords, inclusion and exclusion criteria and sources a run starts from." },
  { name: "Plan", kind: "AI", what: "Turns the topic into search queries." },
  { name: "Search", kind: "Code", what: "Queries each source in turn. A failing optional source is skipped with a visible warning." },
  { name: "Deduplicate", kind: "Code", what: "Merges the same paper found in several sources." },
  { name: "Screen", kind: "AI", what: "Jev decides when confident; the AI model answers when Jev is unsure. One answer per criterion, with a quote for every “no”." },
  { name: "Full text", kind: "Code", what: "Fetches the full text from PubMed Central, Unpaywall or an upload." },
  { name: "Extract claims", kind: "AI", what: "Extracts claims; code checks that every quote occurs exactly in the paper." },
  {
    name: "Reviewers",
    kind: "AI",
    what: "1–5 reviewers (default three) run at the same time on the same papers, independently: none sees another's report.",
    parallel: [
      { name: "Methodologist", what: "Study design and data handling: partitioning, leakage, external validation, reference standard." },
      { name: "Clinician", what: "Clinical relevance: population, intended use, reference standard, clinical workflow." },
      { name: "Statistician", what: "Statistics: metrics and their uncertainty, sample size, calibration, subgroups." },
    ],
  },
  { name: "Editor", kind: "AI", what: "Waits for all reviewers, reads their reports side by side, names disagreements and gives the final verdict with a reason." },
  { name: "Score and red flags", kind: "Code", what: "Computed from the checklist answers, never asked of a model." },
  { name: "Rank", kind: "Code", what: "Orders the papers. Results go to Results and the Library." },
];

export const FLOW_RULES = [
  "Sequential stages: each stage finishes for every paper before the next starts.",
  "Checkpoints: the state is saved after every stage; a failed or cancelled run resumes from the last completed stage.",
  "Every AI call is cached, so a resume never pays twice.",
  "The run stops only if a required source or every source fails.",
];

export type ChecklistItem = { key: string; text: string; source: string; weight: number; redFlag?: string };

export const STATISTICIAN = {
  name: "Statistician",
  version: 1,
  perspective:
    "You review statistical analysis: performance metrics and their uncertainty, sample size, calibration, missing data, class imbalance and subgroup performance.",
  items: [
    { key: "s1", text: "Performance metrics are reported with confidence intervals.", source: "CLAIM 2020 #36", weight: 3, redFlag: "No confidence intervals for performance" },
    { key: "s2", text: "The sample size is justified.", source: "TRIPOD+AI 10", weight: 2 },
    { key: "s3", text: "The number of patients and images in each data set is reported.", source: "CLAIM 2020 #33", weight: 2 },
    { key: "s4", text: "Calibration of predicted probabilities is assessed.", source: "TRIPOD+AI 23a", weight: 2 },
    { key: "s5", text: "Missing data are quantified and the handling method is stated.", source: "TRIPOD+AI 11", weight: 1 },
    { key: "s6", text: "Performance is reported for relevant subgroups (e.g. sex, age, scanner, site).", source: "TRIPOD+AI 23b", weight: 2 },
    { key: "s7", text: "The statistical tests used to compare models or readers are named.", source: "CLAIM 2020 #29", weight: 1 },
    { key: "s8", text: "Class imbalance is reported and addressed.", source: "TRIPOD+AI 13", weight: 1 },
    { key: "s9", text: "The operating threshold was chosen without using the test set.", source: "CLAIM 2020 #26", weight: 2, redFlag: "Threshold may have been tuned on the test set" },
    { key: "s10", text: "Robustness or sensitivity analyses are reported.", source: "CLAIM 2020 #30", weight: 1 },
  ] satisfies ChecklistItem[],
};

export const MODULES = [
  { name: "Pipeline", path: "src/research_agent/{graph,agents,connectors,storage,report,cli}.py", role: "Runs a research run (a LangGraph state graph)." },
  { name: "Sources", path: "src/research_agent/{sources,ratelimit,querybuild,fulltext}.py", role: "Official-API search, full text, paper identity." },
  { name: "Jev tier", path: "src/research_agent/jev.py", role: "Cheap confident screening; escalates to the AI model when unsure." },
  { name: "Eval harness", path: "src/research_agent/eval/", role: "Recall, threshold sweep, reviewer agreement, offline from the call cache." },
  { name: "Web backend", path: "src/research_agent/web/", role: "Database, importers, sign-in, API, worker." },
  { name: "Frontend", path: "web/", role: "This app." },
  { name: "Deployment", path: "deploy/, .github/workflows/ci.yml", role: "Compose, nginx, CI." },
];

export const DESIGN_RULES = [
  "Deterministic stages (search, deduplication, quote checks, scoring) are code, not agents.",
  "The AI model extracts; the code scores.",
  "Every claim quotes the source exactly.",
  "Fail closed: a network, schema or quote error stops the run and keeps the checkpoint.",
  "Keys live only with the worker; the web API never holds them.",
  "Measurement runs offline from the call cache.",
  "The app shows a stage as green only when it is measured.",
];
