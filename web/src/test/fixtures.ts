import type { EvalJobOut, GoldSetOut, RatingNextOut, RatingSampleOut, RevealOut, EstimateOut, CompareOut, CollectionOut, LibraryItemDetail, LibraryItemOut, PanelOut, PaperFileOut, ChecklistItemOut, ModelsAvailableOut, ReviewerOut, ReviewSettingsContent, ReviewSettingsOut, CriteriaTestResult, DrawerOut, EvalDetailOut, EvalSummaryOut, FieldOut, FieldVersionOut, JobOut, PaperRow, RunDetailOut, RunOut, SourceOut, StageOut, UserOut, WorkerStatusOut } from "../api/types";

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
  stage("reviewers", "Review panel", "caveat", "kappa 0.94", { caveat: "one model family", data_link: "evals" }),
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

export const JOB_ID = "66666666-6666-4666-8666-666666666666";

export const jobOut = (over: Partial<JobOut> = {}): JobOut => ({
  id: JOB_ID, kind: "research", status: "queued", progress: {}, error: null, run_id: RUN_ID, attempts: 0, created_at: "2026-09-26T10:00:00Z", ...over,
});

export const fieldOut = (): FieldOut => ({
  id: FIELD_ID, name: "ML CT-FFR", topic: "deep learning CT-FFR",
  criteria: [{ id: "77777777-7777-4777-8777-777777777777", key: "topic_match", question: "The paper's central subject is the topic.", version: 1, position: 0 }],
});

export const EVAL_ID = "99999999-9999-4999-8999-999999999999";
export const rate = (k: number, n: number, ci: [number, number]) => ({ k, n, value: n ? k / n : null, ci, reason: null });
const row = (inc: number, exc: number, saved: number, lost: number, lostIds: string[] = []) => ({
  min_confidence: inc, exclude_min_confidence: exc, recall: rate(16 - lost, 16, [0.72, 0.99]), missed: lost, lost_vs_llm: lost, lost_ids: lostIds,
  calls_saved: saved, auto_include: 10, auto_exclude: 20, escalated: 151 - saved, kept: 100, kept_negatives: 84,
});

export const evalMetrics = () => ({
  gold: { name: "mlffrct-2024", citation: "Zhao et al. 2024", topic: "ML CT-FFR", query: "q", sha256: "f".repeat(64) },
  counts: { candidates: 151, screened: 151, positives_total: 16, positives_resolved: 16, positives_screened: 16 },
  retrieval_recall: rate(15, 16, [0.72, 0.99]),
  default_thresholds: { min_confidence: 0.6, exclude_min_confidence: 0.9 },
  strategies: {
    llm_only: { recall: rate(15, 16, [0.72, 0.99]), calls_saved: 0, escalated: 151, kept: 112, kept_negatives: 97 },
    jev_only: { recall: rate(14, 16, [0.64, 0.97]), calls_saved: 151, escalated: 82, kept: 100, kept_negatives: 85 },
    cascade: { recall: rate(15, 16, [0.72, 0.99]), calls_saved: 69, escalated: 82, kept: 112, kept_negatives: 97 },
  },
  sweep: [row(0.6, 0.9, 69, 0), row(0.1, 0.7, 74, 0), row(0.1, 0.5, 80, 1, ["MED:1"]), row(0.6, 0.99, 40, 0)],
  holdout_sweep: { gold: "aiffr-slr-2023", n: 25, rows: [row(0.6, 0.9, 12, 0), row(0.1, 0.7, 14, 0), row(0.1, 0.5, 16, 1, ["MED:9"]), row(0.6, 0.99, 8, 1, ["MED:8"])] },
  recommended: { min_confidence: 0.1, exclude_min_confidence: 0.7, calls_saved: 74 },
  rejected_on_holdout: { thresholds: { min_confidence: 0.1, exclude_min_confidence: 0.5 }, lost: [{ id: "MED:9", title: "A holdout paper the pair would lose" }] },
  holdout: { gold: "aiffr-slr-2023", n: 25, recall: rate(4, 5, [0.38, 0.96]), thresholds: { min_confidence: 0.1, exclude_min_confidence: 0.7 }, calls_saved: 14, lost_vs_llm: [], missed: [] },
  agreement: {
    n: 36, verdict: { kappa: 0.945, agreement: 0.972, reason: null }, scores: {}, adjudication_rate: rate(1, 36, [0.005, 0.14]), same_family: true,
  },
  warnings: ["The main-set-only pick include>=0.1/exclude>=0.5 loses 1 SR-included paper on the holdout that llm_only keeps: MED:9 'A holdout paper the pair would lose'. Rejected."],
});

export const evalSummary = (over: Partial<EvalSummaryOut> = {}): EvalSummaryOut => ({
  id: EVAL_ID, gold_set: { id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", name: "mlffrct-2024", citation: "Zhao et al. 2024" }, run_id: RUN_ID, created_at: "2026-09-26T09:00:00Z",
  headline: { retrieval_recall: { k: 15, n: 16 }, cascade_recall: { k: 15, n: 16 }, recommended: { min_confidence: 0.1, exclude_min_confidence: 0.7 }, kappa: 0.945, same_family: true, screened: 151 }, ...over,
});

export const evalDetail = (metrics: Record<string, unknown> = evalMetrics()): EvalDetailOut => ({
  id: EVAL_ID, gold_set: evalSummary().gold_set, run_id: RUN_ID, created_at: "2026-09-26T09:00:00Z", metrics, agreement: (metrics.agreement as Record<string, unknown>) ?? null,
});

export const userRows = (): UserOut[] => [
  { id: "10000000-0000-4000-8000-000000000001", email: "admin@example.org", name: "Ada Admin", role: "admin", active: true },
  { id: "10000000-0000-4000-8000-000000000002", email: "member@example.org", name: "Mia Member", role: "member", active: true },
  { id: "10000000-0000-4000-8000-000000000003", email: "old@example.org", name: "Olga Old", role: "viewer", active: false },
];

export const versionOut = (over: Partial<FieldVersionOut> = {}): FieldVersionOut => ({
  version: 2, name: "ML CT-FFR", topic: "deep learning CT-FFR",
  include: [{ key: "i1", text: "The study uses machine learning or deep learning." }, { key: "i2", text: "FFR is estimated from coronary CT angiography." }],
  exclude: [{ key: "e1", text: "The paper is a review or an editorial." }],
  legacy: [], sources: ["europepmc"], years: { from: 2018, to: null }, note: "added the exclusion", imported: false,
  created_by_name: "Mia Member", created_at: "2026-09-28T10:00:00Z", run_count: 1, ...over,
});

export const legacyVersion = (): FieldVersionOut => versionOut({
  version: 1, include: [], exclude: [], legacy: [{ key: "topic_match", text: "The paper's central subject is the topic." }],
  years: { from: null, to: null }, note: "imported", imported: true, created_by_name: null, created_at: "2026-09-26T08:00:00Z", run_count: 3,
});

export const fieldDetail = (over: Partial<FieldOut> = {}): FieldOut => ({
  ...fieldOut(), current_version: 2, archived_at: null, current: versionOut(),
  last_run: { id: RUN_ID, kind: "research", status: "done", created_at: "2026-09-28T11:00:00Z", field_version: 2 },
  versions: [
    { version: 2, note: "added the exclusion", imported: false, created_by_name: "Mia Member", created_at: "2026-09-28T10:00:00Z", run_count: 1, include_count: 2, exclude_count: 1 },
    { version: 1, note: "imported", imported: true, created_by_name: null, created_at: "2026-09-26T08:00:00Z", run_count: 3, include_count: 0, exclude_count: 0 },
  ],
  ...over,
});

export const legacyField = (): FieldOut => fieldDetail({
  current_version: 1, current: legacyVersion(), last_run: null,
  versions: [{ version: 1, note: "imported", imported: true, created_by_name: null, created_at: "2026-09-26T08:00:00Z", run_count: 3, include_count: 0, exclude_count: 0 }],
});

const source = (o: Partial<SourceOut> & Pick<SourceOut, "name" | "label" | "group">): SourceOut => ({
  covers: "", auth: "none", env: [], capabilities: ["search"], rps: 10, rps_keyed: 10, rps_in_use: 10,
  key_present: true, key_accepted: null, key_detail: "no key needed", key_checked_at: "2026-09-28T10:00:00Z",
  enabled: false, max_results: 100, last_check_at: null, last_check_ok: null, last_check_ms: null, last_check_error: null,
  ...o,
});

export const sourceRows = (): SourceOut[] => [
  source({ name: "europepmc", label: "Europe PMC", group: "biomedical", covers: "Life-science literature incl. PubMed and PMC", capabilities: ["search", "fulltext"], enabled: true, last_check_at: "2026-09-28T10:12:00Z", last_check_ok: true, last_check_ms: 800 }),
  source({ name: "pubmed", label: "PubMed", group: "biomedical", covers: "MEDLINE citations with MeSH", auth: "optional", env: ["NCBI_API_KEY"], rps: 3, rps_in_use: 3, key_present: false, key_detail: "NCBI_API_KEY not set; lower rate limit" }),
  source({ name: "arxiv", label: "arXiv", group: "preprints", covers: "Preprints in cs.CV, eess.IV, physics.med-ph", rps: 0, rps_keyed: 0, rps_in_use: 0, max_results: 50, last_check_at: "2026-09-28T10:13:00Z", last_check_ok: false, last_check_ms: 30000, last_check_error: "SourceUnavailable: arxiv" }),
  source({ name: "openalex", label: "OpenAlex", group: "multidisciplinary", covers: "Open catalogue of scholarly works", auth: "optional", env: ["OPENALEX_API_KEY"], key_present: false, key_detail: "OPENALEX_API_KEY not set; lower rate limit" }),
  source({ name: "core", label: "CORE", group: "multidisciplinary", covers: "Open-access research outputs", auth: "required", env: ["CORE_API_KEY"], capabilities: ["search", "fulltext"], rps: 0.17, rps_keyed: 0.17, rps_in_use: 0.17, key_accepted: true, key_detail: "accepted" }),
  source({ name: "unpaywall", label: "Unpaywall", group: "multidisciplinary", covers: "Legal open-access PDFs by DOI", capabilities: ["fulltext"], rps: 5, rps_keyed: 5, rps_in_use: 5 }),
  source({ name: "ieee", label: "IEEE Xplore", group: "publishers", covers: "IEEE journals and conferences", auth: "required", env: ["IEEE_API_KEY"], rps: 2, rps_keyed: 2, rps_in_use: 2, key_present: false, key_detail: "IEEE_API_KEY not set" }),
  source({ name: "crossref", label: "Crossref", group: "identity", covers: "DOI registry", rps: 5, rps_keyed: 5, rps_in_use: 5 }),
];

export const workerRows = (): WorkerStatusOut[] => [
  { role: "screen", provider: "anthropic", model: "claude-sonnet-5", key_present: true, key_accepted: true, detail: "", checked_at: "2026-09-28T10:00:00Z", worker_id: "w1" },
  { role: "adjudicate", provider: "openai", model: "gpt-6", key_present: true, key_accepted: false, detail: "rejected (401)", checked_at: "2026-09-28T10:00:00Z", worker_id: "w1" },
  { role: "jev", provider: "typesafe", model: "jev-latest", key_present: false, key_accepted: null, detail: "", checked_at: "2026-09-28T10:00:00Z", worker_id: "w1" },
];

export const testResult = (over: Partial<CriteriaTestResult> = {}): CriteriaTestResult => ({
  mode: "demo", topic: "deep learning CT-FFR",
  criteria: [{ key: "i1", kind: "include", text: "The study uses machine learning or deep learning." }, { key: "e1", kind: "exclude", text: "The paper is a review or an editorial." }],
  sources: ["europepmc"], model_version: "demo-jev",
  papers: [
    { source_id: "MED:1", title: "Deep learning CT-FFR against invasive FFR", year: 2020, sources: ["europepmc"], probabilities: { i1: 0.97, e1: 0.02 }, decision: "include", decided_by: null },
    { source_id: "MED:2", title: "Machine learning in cardiac imaging: a review", year: 2021, sources: ["europepmc"], probabilities: { i1: 0.93, e1: 0.96 }, decision: "exclude", decided_by: "e1" },
    { source_id: "MED:3", title: "A paper without an abstract", year: 2019, sources: ["europepmc"], probabilities: {}, decision: "not_screened", decided_by: null },
  ],
  summary: { total: 3, kept: 1, dropped: 1, to_llm: 0, not_screened: 1 }, field_id: FIELD_ID, version: null, ...over,
});

export const settingsContent = (): ReviewSettingsContent => ({
  models: { plan: null, screen: "anthropic:claude-sonnet-5", screen_criteria: null, extract: null },
  screening: { keep_min: 0.8, include_fail_max: 0.05, exclude_hit_min: 0.95, exclude_clear_max: 0.2 },
  fulltext: { sources: ["pmc_oa", "unpaywall", "upload"], contact: "lab@example.org", max_chars: 60000, upload_max_mb: 30 },
  default_panel: ["methodologist", "clinician", "statistician"],
  editor: { model: "anthropic:claude-opus-5-5", instructions: "Weigh the reports and give one verdict." },
});

export const reviewSettings = (over: Partial<ReviewSettingsContent> = {}, version = 3): ReviewSettingsOut => ({
  current: { ...settingsContent(), ...over, version, note: "tightened", imported: false, created_by_name: "Ada Admin", created_at: "2026-09-29T10:00:00Z", run_count: 2 },
  versions: [{ version, note: "tightened", imported: false, created_by_name: "Ada Admin", created_at: "2026-09-29T10:00:00Z", run_count: 2 }],
  defaults: { ...settingsContent(), fulltext: { sources: ["pmc_oa", "upload"], contact: null, max_chars: 60000, upload_max_mb: 30 }, editor: { model: null, instructions: "Default editor." } },
});

const item = (key: string, text: string, over: Partial<ChecklistItemOut> = {}): ChecklistItemOut => ({ key, text, weight: 1, source: "CLAIM 7", pass_if: "yes", red_flag_if: null, ...over });

export const reviewerOut = (key = "methodologist", name = "Methodologist", over: Partial<ReviewerOut> = {}): ReviewerOut => ({
  key, current_version: 2, archived_at: null, in_default_panel: true,
  current: {
    version: 2, name, perspective: `You judge the study as a ${name.toLowerCase()}. Focus on design.`, model: "anthropic:claude-sonnet-5",
    items: [
      item(`${key[0]}1`, "Data were split at patient level, not image level.", { weight: 2, red_flag_if: "no", source: "CLAIM 21", flag_text: "Data not split by patient" }),
      item(`${key[0]}2`, "The model was validated on an external dataset.", { weight: 3, source: "TRIPOD+AI 12" }),
    ],
    note: "added external validation", imported: false, created_by_name: "Ada Admin", created_at: "2026-09-29T09:00:00Z", run_count: 1,
  },
  default: { name, perspective: "Default perspective.", model: null, items: [item(`${key[0]}1`, "Default item.")] },
  versions: [
    { version: 2, note: "added external validation", imported: false, created_by_name: "Ada Admin", created_at: "2026-09-29T09:00:00Z", run_count: 1, item_count: 2 },
    { version: 1, note: "default", imported: false, created_by_name: null, created_at: "2026-09-28T09:00:00Z", run_count: 3, item_count: 1 },
  ],
  ...over,
});

export const reviewerRows = (): ReviewerOut[] => [
  reviewerOut(),
  reviewerOut("clinician", "Clinician"),
  reviewerOut("statistician", "Statistician", { current: { ...reviewerOut("statistician", "Statistician").current, model: "openai:gpt-6" } }),
];

export const modelsAvailable = (): ModelsAvailableOut => ({
  models: [
    { id: "anthropic:claude-sonnet-5", provider: "anthropic", available: true, roles: ["screen"], in_settings: true },
    { id: "anthropic:claude-opus-5-5", provider: "anthropic", available: true, roles: [], in_settings: true },
    { id: "openai:gpt-6", provider: "openai", available: false, roles: ["adjudicate"], in_settings: true },
  ],
  providers: [{ provider: "anthropic", key_present: true, key_accepted: true }, { provider: "openai", key_present: true, key_accepted: false }],
});

export const panelOut = (over: Partial<PanelOut> = {}): PanelOut => ({
  text_source: "pmc_oa", text_reason: null, text_origin: "PMC8812345", text_sections: ["methods", "results"], text_truncated: true, text_chars: 41000,
  editor: {
    verdict: "include", reason: "Sound design with external validation; the split is the main doubt.", call_key: "f".repeat(64),
    disagreements: [{ item: "m1", reviewers: ["methodologist", "statistician"], note: "the methods section is ambiguous about the split." }],
  },
  reviews: [
    {
      key: "methodologist", name: "Methodologist", version: 2, verdict: "include", score: 80, coverage: 1, strengths: ["External test set"], weaknesses: ["Single vendor"],
      summary: "Well designed retrospective study.", call_key: "1".repeat(64),
      answers: [
        { key: "m1", text: "Data were split at patient level, not image level.", source: "CLAIM 21", weight: 2, answer: "yes", quote: "patients were randomly assigned to training and test sets", section: "Methods", red_flag: false },
        { key: "m2", text: "The model was validated on an external dataset.", source: "TRIPOD+AI 12", weight: 3, answer: "yes", quote: "an external cohort from a second hospital", section: "Results", red_flag: false },
      ],
    },
    {
      key: "statistician", name: "Statistician", version: 1, verdict: "uncertain", score: 50, coverage: 0.5, strengths: [], weaknesses: ["No confidence intervals"],
      summary: "Metrics lack uncertainty.", call_key: "2".repeat(64),
      answers: [
        { key: "m1", text: "Data were split at patient level, not image level.", source: "CLAIM 21", weight: 2, answer: "no", quote: "images were split 80/20", section: "Methods", red_flag: true, flag: "Data not split by patient" },
        { key: "s2", text: "Metrics are reported with confidence intervals.", source: "CLAIM 29", weight: 1, answer: "not_reported", quote: "", section: "", red_flag: false },
      ],
    },
  ],
  red_flags: [{ text: "Data not split by patient", item_text: "Data were split at patient level, not image level.", source: "CLAIM 21", raised_by: [{ reviewer: "statistician", item: "m1", answer: "no", quote: "images were split 80/20", section: "Methods" }] }],
  score: 65, coverage: 0.75, red_flag_count: 1,
  ...over,
});

export const paperFile = (over: Partial<PaperFileOut> = {}): PaperFileOut => ({
  id: "12121212-1212-4212-8212-121212121212", filename: "paper.pdf", size: 245_760, sha256: "a".repeat(64), uploaded_by_name: "Mia Member", created_at: "2026-09-29T11:00:00Z", can_delete: true, ...over,
});

export const COLLECTION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
export const ITEM_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
export const ITEM_ID_2 = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";

export const collectionOut = (over: Partial<CollectionOut> = {}): CollectionOut => ({
  id: COLLECTION_ID, name: "Plaque reading list", description: "", archived_at: null, item_count: 2, created_by_name: "Member", created_at: "2026-09-30T08:00:00Z", ...over,
});

export const libraryItem = (over: Partial<LibraryItemOut> = {}): LibraryItemOut => ({
  id: ITEM_ID,
  paper: { id: PAPER_ID, source_id: "MED:1", title: "Diagnostic accuracy of a deep learning approach to calculate FFR", year: 2019, doi: "10.1000/x" },
  status: "to_read", note: "", tags: ["ffr"], collections: [{ id: COLLECTION_ID, name: "Plaque reading list" }],
  field: { id: FIELD_ID, name: "ML CT-FFR", version: 2 }, run_id: RUN_ID, score: 74, red_flag_count: 1, text_source: "abstract", editor_verdict: "include",
  added_by_name: "Member", added_at: "2026-09-30T09:00:00Z", updated_at: "2026-09-30T09:00:00Z", can_delete: true,
  ...over,
});

export const libraryDetail = (over: Partial<LibraryItemDetail> = {}): LibraryItemDetail => ({
  ...libraryItem(),
  abstract: "We trained a CNN to estimate FFR from coronary CT angiography.",
  snapshot: {
    schema: 1, taken_at: "2026-09-30T09:00:00Z", run: { id: RUN_ID, kind: "research", created_at: "2026-09-26T08:00:00Z" },
    field: { id: FIELD_ID, name: "ML CT-FFR", version: 2 },
    screening: { decision: "include", tier: "jev", reason: "all met", decided_by: null, criteria_table: [{ key: "i1", text: "Uses deep learning.", decided: false, quote: "We trained a CNN" }] },
    rank: null,
    panel: {
      score: 74, coverage: 0.8, red_flag_count: 1, text_source: "abstract", editor: { verdict: "include", reason: "Solid validation." },
      red_flags: [{ text: "No external validation", item_text: "The model was validated on an external dataset.", source: "TRIPOD+AI 12", quote: "tested at the same hospital", section: "Methods" }],
      reviewers: [{ key: "methodologist", name: "Methodologist", version: 2, verdict: "include", score: 70, summary: "Adequate." }],
    },
    files: [],
  },
  events: [
    { id: "e1", kind: "added", detail: { run_id: RUN_ID, status: "to_read", collections: ["Plaque reading list"], tags: ["ffr"] }, user_name: "Member", created_at: "2026-09-30T09:00:00Z" },
    { id: "e2", kind: "status", detail: { from: "to_read", to: "read" }, user_name: "Admin", created_at: "2026-09-30T10:00:00Z" },
  ],
  files: [],
  ...over,
});

// --- live evals (slice 6) ----------------------------------------------------------------------------------
export const PANEL_ID = "aaaa0000-0000-4000-8000-000000000001";
export const ABLATION_ID = "aaaa0000-0000-4000-8000-000000000002";
export const HUMAN_ID = "aaaa0000-0000-4000-8000-000000000003";
export const SAMPLE_ID = "aaaa0000-0000-4000-8000-000000000004";
const cohen = (agreement: number, prevalence: number, kappa: number | null, n = 10) => ({ n, agreement, prevalence, kappa, reason: kappa === null ? "one class only" : null });

export const humanSection = () => ({
  ratings_sha256: "h".repeat(64), ratings: 40, stale_or_unknown: 0, raters: ["u1", "u2"], units: 40, papers: 5,
  inter_rater: { share: rate(34, 40, [0.71, 0.93]), fleiss: { kappa: 0.61 }, reason: null },
  panel: { accuracy: rate(30, 40, [0.6, 0.86]), kappa: cohen(0.75, 0.6, 0.48, 40) },
  per_reviewer: { methodologist: { accuracy: rate(16, 20, [0.58, 0.92]), kappa: cohen(0.8, 0.6, 0.55, 20) }, statistician: { accuracy: rate(14, 20, [0.48, 0.85]), kappa: cohen(0.7, 0.6, 0.4, 20) } },
  per_item: [
    { reviewer: "statistician", item: "s1", text: "Was the test set split by patient?", n: 5, accuracy: rate(2, 5, [0.12, 0.77]), kappa: cohen(0.4, 0.5, 0.1, 5) },
    { reviewer: "methodologist", item: "m1", text: "Is there external validation?", n: 5, accuracy: rate(5, 5, [0.57, 1]), kappa: cohen(1, 0.5, 1, 5) },
  ],
  scores: { papers: [{ paper_id: "MED:1", human: 70, panel: 72, reviewers: {} }], spearman: { n: 5, rho: 0.8, reason: null } },
});

export const panelMetrics = (over: Record<string, unknown> = {}) => ({
  kind: "panel",
  config: { mode: "demo", panel: [{ key: "methodologist", name: "Methodologist", version: 2, model: "anthropic:claude-sonnet-4-5" }, { key: "statistician", name: "Statistician", version: 1, model: "anthropic:claude-sonnet-4-5" }, { key: "clinician", name: "Clinician", version: 1, model: "anthropic:claude-sonnet-4-5" }], prompt_version: "p7" },
  panel: {
    n: 10, reviewers: ["methodologist", "statistician", "clinician"], text_sources: { fulltext: 6, abstract: 4 },
    verdicts: { fleiss: { n: 10, raters: 3, agreement: 0.73, prevalence: 0.8, kappa: 0.42, reason: null }, pairwise: { "methodologist|statistician": cohen(0.8, 0.7, 0.5) }, reason: null },
    editor_vs_majority: rate(9, 10, [0.6, 0.98]),
    items: [
      { items: [{ reviewer: "statistician", item: "s1" }], text: "Was the test set split by patient?", source: "CLAIM 7", answerers: ["statistician"], share: { k: 0, n: 0, value: null, ci: null, reason: "single answerer: agreement undefined" }, kappa: null, reason: "single answerer: agreement undefined", answers: { yes: 2, not_reported: 8 }, unanswered_share: 0.8, reword_candidate: true },
      { items: [{ reviewer: "methodologist", item: "m1" }, { reviewer: "clinician", item: "c1" }], text: "Is there external validation?", source: null, answerers: ["methodologist", "clinician"], share: rate(9, 10, [0.6, 0.98]), kappa: cohen(0.9, 0.5, 0.8), reason: null, answers: { yes: 12, no: 8 }, unanswered_share: 0, reword_candidate: false },
    ],
    coverage: {
      statistician: { s1: { fulltext: rate(2, 6, [0.1, 0.7]), abstract: rate(0, 4, [0, 0.5]) } },
      methodologist: { m1: { fulltext: rate(6, 6, [0.6, 1]), abstract: { k: 0, n: 0, value: null, ci: null, reason: "no papers" } } },
    },
    dispersion: [
      { paper_id: "MED:35097009", title: "Change in CT-Derived FFR", score: 55, scores: { methodologist: 80, statistician: 30, clinician: 55 }, n: 3, range: 50, sd: 25 },
      { paper_id: "MED:1", title: "Diagnostic accuracy of deep learning FFR", score: 72, scores: { methodologist: 70, statistician: 74, clinician: 72 }, n: 3, range: 4, sd: 2 },
    ],
    sr_inclusion_auc: { value: 0.71, ci: [0.48, 0.94], n_pos: 4, n_neg: 6, method: "hanley-mcneil", unscored: 0, note: "SR inclusion is not a quality label", reason: null },
    model_families: { providers: { methodologist: "anthropic", statistician: "anthropic", clinician: "anthropic" }, single_family: true, families: { single: "anthropic" }, note: "one family" },
  },
  ...over,
});

export const ablationMetrics = () => ({
  kind: "ablation",
  config: { reviewers: ["methodologist", "statistician", "clinician"], rerun_editor: false, mode: "demo" },
  ablation: {
    papers: 10, reviewers: ["methodologist", "statistician", "clinician"], rerun_editor: false, cost_basis: "chars", token_usage: null,
    subsets: [
      { subset: "methodologist", reviewers: ["methodologist"], size: 1, papers: 10, verdict_changed: rate(4, 10, [0.17, 0.69]), editor_verdict_changed: null, red_flags_missed: rate(6, 10, [0.31, 0.83]), mean_abs_score_delta: 9.5, scored_pairs: 10, cost: { calls: 10, chars: 40000 }, cost_delta: { calls: -20, chars: -80000 } },
      { subset: "methodologist+statistician", reviewers: ["methodologist", "statistician"], size: 2, papers: 10, verdict_changed: rate(1, 10, [0.02, 0.4]), editor_verdict_changed: null, red_flags_missed: rate(2, 10, [0.06, 0.51]), mean_abs_score_delta: 3.1, scored_pairs: 10, cost: { calls: 20, chars: 80000 }, cost_delta: { calls: -10, chars: -40000 } },
      { subset: "methodologist+statistician+clinician", reviewers: ["methodologist", "statistician", "clinician"], size: 3, papers: 10, verdict_changed: rate(0, 10, [0, 0.28]), editor_verdict_changed: null, red_flags_missed: rate(0, 10, [0, 0.28]), mean_abs_score_delta: 0, scored_pairs: 10, cost: { calls: 30, chars: 120000 }, cost_delta: { calls: 0, chars: 0 } },
    ],
    sizes: {
      "1": { subsets: 3, verdict_changed: 0.4, red_flags_missed: 0.6, mean_abs_score_delta: 9.5, cost_calls: 10, cost_chars: 40000 },
      "2": { subsets: 3, verdict_changed: 0.1, red_flags_missed: 0.2, mean_abs_score_delta: 3.1, cost_calls: 20, cost_chars: 80000 },
      "3": { subsets: 1, verdict_changed: 0, red_flags_missed: 0, mean_abs_score_delta: 0, cost_calls: 30, cost_chars: 120000 },
    },
    summary: { from_size: 2, to_size: 3, verdict_changed: 0.1, red_flags_added: 1.5, cost_increase: 0.5, sentence: "Going from 2 to 3 reviewers changed the majority verdict on 10% of papers and added 1.5 red flags on average; cost +50% (prompt + output characters)." },
    full_editor_vs_majority: rate(9, 10, [0.6, 0.98]),
  },
});

const headline = (over: Record<string, unknown> = {}) => ({ retrieval_recall: null, cascade_recall: null, recommended: null, kappa: null, same_family: null, screened: null, ...over });

export const panelSummary = (over: Partial<EvalSummaryOut> = {}): EvalSummaryOut => ({
  id: PANEL_ID, gold_set: { id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", name: "mlffrct-2024", citation: "Zhao et al. 2024" }, run_id: RUN_ID, created_at: "2026-10-05T09:00:00Z",
  kind: "panel", status: "done", parent_id: null, chips: ["gold mlffrct-2024", "demo", "3 reviewers", "provider anthropic", "n=10 seed 0"],
  headline: headline({ papers: 10, reviewers: 3, fleiss_kappa: 0.42, raw_agreement: 0.73, editor_vs_majority: 0.9, sr_auc: 0.71, same_family: true }), ...over,
});
export const ablationSummary = (over: Partial<EvalSummaryOut> = {}): EvalSummaryOut => ({
  ...panelSummary(), id: ABLATION_ID, kind: "ablation", parent_id: PANEL_ID, chips: ["demo", "3 reviewers", "offline"],
  headline: headline({ papers: 10, reviewers: 3, summary: ablationMetrics().ablation.summary.sentence, verdict_changed: 0.1, red_flags_added: 1.5, cost_increase: 0.5 }), ...over,
});
export const humanSummary = (over: Partial<EvalSummaryOut> = {}): EvalSummaryOut => ({
  ...panelSummary(), id: HUMAN_ID, kind: "human", parent_id: PANEL_ID, chips: ["human reference"],
  headline: headline({ papers: 10, human_accuracy: 0.75, human_kappa: 0.48, human_raters: 2, human_units: 40, spearman: 0.8 }), ...over,
});

export const panelDetail = (over: Partial<EvalDetailOut> = {}): EvalDetailOut => ({
  ...panelSummary(), metrics: panelMetrics(), agreement: null, config: panelMetrics().config,
  children: [{ id: ABLATION_ID, kind: "ablation", created_at: "2026-10-05T10:00:00Z" }], rating_sample_ids: [SAMPLE_ID], ...over,
});
export const ablationDetail = (): EvalDetailOut => ({ ...ablationSummary(), metrics: ablationMetrics(), agreement: null, config: ablationMetrics().config, children: [], rating_sample_ids: [] });
export const humanDetail = (): EvalDetailOut => ({ ...humanSummary(), metrics: panelMetrics({ human: humanSection() }), agreement: null, config: {}, children: [], rating_sample_ids: [SAMPLE_ID] });

export const evalJob = (over: Partial<EvalJobOut> = {}): EvalJobOut => ({
  kind: "panel", parent_id: null, chips: ["demo", "n=10 seed 0"],
  job: jobOut({ id: JOB_ID, kind: "eval_run", status: "running", run_id: null, progress: { status: "running", kind: "panel", step: "panel", steps: ["panel", "report", "import"], done: 3, total: 10 } }),
  ...over,
});

export const goldSet = (over: Partial<GoldSetOut> = {}): GoldSetOut => ({
  id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", name: "mlffrct-2024", citation: "Zhao et al. 2024", candidates: 151, positives: 16, unresolved: 0, built_in_app: false, usable: true, created_at: "2026-09-26T09:00:00Z", ...over,
});

export const estimateOut = (over: Partial<EstimateOut> = {}): EstimateOut => ({
  kind: "panel", calls: 40, input_chars: 400000, input_tokens: 100000, output_tokens: 20000, cost_usd: null,
  lines: [{ role: "review:methodologist", model: "anthropic:claude-sonnet-4-5", calls: 10, input_chars: 100000, output_tokens: 5000, cost_usd: 0.45 }, { role: "review:statistician", model: "google_genai:gemini-9", calls: 10, input_chars: 100000, output_tokens: 5000, cost_usd: null }],
  notes: ["Upper bound: cached calls are not subtracted."], ...over,
});

export const compareOut = (): CompareOut => ({
  family: "panel", reports: [panelSummary(), humanSummary()],
  metrics: [
    { section: "agreement", key: "panel.verdicts.fleiss.kappa", label: "Fleiss kappa", values: [0.42, 0.42], differs: false },
    { section: "agreement", key: "panel.editor_vs_majority.value", label: "Editor vs majority", values: [0.9, 0.8], differs: true },
  ],
  config: [{ section: "config", key: "mode", label: "Mode", values: ["demo", "live"], differs: true }],
});

export const ratingSample = (over: Partial<RatingSampleOut> = {}): RatingSampleOut => ({
  id: SAMPLE_ID, eval_id: PANEL_ID, size: 20, seed: 0, created_at: "2026-10-05T11:00:00Z", raters_needed: 2,
  papers: [
    { paper_id: "MED:1", title: "Diagnostic accuracy of deep learning FFR", score: 72, raters: 2, rated_by_me: true },
    { paper_id: "MED:35097009", title: "Change in CT-Derived FFR", score: 55, raters: 1, rated_by_me: false },
  ],
  complete_papers: 1, my_rated: 1, latest_human_eval_id: HUMAN_ID, ...over,
});

export const ratingNext = (over: Partial<RatingNextOut> = {}): RatingNextOut => ({
  done: false, position: 3, total: 20,
  paper: { paper_id: "MED:35097009", title: "Change in CT-Derived FFR", year: "2021", text: { source: "abstract", content: "This study sought to evaluate the diagnostic performance of CT-FFR.", chars: 66 } },
  reviewers: [
    { key: "methodologist", name: "Methodologist", version: 2, items: [{ key: "m1", text: "Is there external validation?" }] },
    { key: "statistician", name: "Statistician", version: 1, items: [{ key: "s1", text: "Was the test set split by patient?" }] },
  ],
  ...over,
});

export const revealOut = (): RevealOut => ({
  paper_id: "MED:35097009", title: "Change in CT-Derived FFR", agreed: 1, compared: 2,
  items: [
    { reviewer: "methodologist", item: "m1", text: "Is there external validation?", mine: { answer: "no", quote: "", section: "" }, model: { answer: "no", quote: "single centre", section: "methods" }, agree: true },
    { reviewer: "statistician", item: "s1", text: "Was the test set split by patient?", mine: { answer: "yes", quote: "", section: "" }, model: { answer: "not_reported", quote: "", section: "" }, agree: false },
  ],
});
