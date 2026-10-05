# Live Evals: panel agreement, 1/2/3-reviewer comparison, human reference (slice 6)

Date: 2026-10-05 · Status: approved (user: build it; no second provider key yet)

## Goal

Turn Evals from a static page (two reports imported on 2026-09-26) into a living measurement tool:

1. **Run evaluations from the app** as worker jobs, each stored as a new report; compare reports side by side.
2. **Panel agreement** for the reviewer panel (not only the old A/B pair).
3. **Does each extra reviewer earn its cost?** 1 vs 2 vs 3 reviewers.
4. **Human reference ratings** so the panel can be checked for correctness, not only consistency.
5. **Model-family comparison** is designed in but disabled until a second provider key exists (UI explains).

## Evaluation kinds (worker job `eval_run`)

| Kind | Input | What it computes | Cost |
|---|---|---|---|
| `screening` | a gold set (existing ones or a new one built from an SR) + a field version or legacy topic | today's report: retrieval recall, strategy recall with CIs, threshold sweep, holdout check | Jev + LLM screen calls (cached) |
| `panel` | a gold set or a finished run + panel config (from current review settings or a chosen version) + sample size | runs fulltext + full panel + editor on N papers (the SR-included papers first, then a matched sample of excluded) | reviewers + editor calls (cached) |
| `ablation` | a finished `panel` eval | **offline** from cached calls: every reviewer subset (1, 2, 3) scored in code; editor re-run for each subset is optional (checkbox, costs calls) | 0, or editor calls if opted in |

Every eval report freezes its config (gold set hash, field version, settings version, panel versions, models,
prompt version) and is immutable. `research-eval` CLI gains `panel` and `ablation` subcommands that the worker
calls, so CLI and app produce identical reports (consistency test).

## Metrics

**Panel agreement** (from `panel` evals):
- Verdict agreement: Fleiss' kappa across reviewers + pairwise Cohen's kappa, with raw agreement and
  prevalence (kappa collapses with skewed classes — always shown next to it).
- Item agreement: per checklist item, the share of papers where reviewers who answered it agree, and a
  kappa where defined; items ranked worst-first with the item text — "candidates to reword".
- Coverage: per reviewer and item, share answered vs `not_reported` (full text vs abstract shown separately).
- Score dispersion: per paper, spread of reviewer scores; papers with the largest spread listed.

**Ablation** (1/2/3 reviewers):
- For each subset size k and each subset: paper score (code), red flags found, verdict by majority (and by
  editor if re-run). Compared with the full panel: verdict changes (%), red flags missed (%), score shift
  (mean |Δ|), and cost (calls/tokens from the cache metadata).
- Summary card: "A third reviewer changed the final verdict on X% of papers and added Y red flags; cost +Z%".

**Against references**:
- SR inclusion (weak signal): AUC of panel score for SR-included vs excluded papers, with CI; labelled
  clearly as "inclusion ≠ quality".
- **Human reference** (strong signal, when available): per item, panel answer vs human consensus →
  accuracy, Cohen's kappa per reviewer and for the panel; per paper, score correlation (Spearman) with
  the human score computed by the same code.

**Model families**: if reviewers use ≥ 2 providers, agreement is also split by family; otherwise the section
reads "All reviewers use one model family — add a second provider key to compare" (no action available).

## Human reference ratings

- From a `panel` eval, an admin creates a **rating sample** (e.g. 20 papers, stratified by panel score).
- Members rate papers in a focused **Rate** view: paper text (full text or abstract, PDFs viewable), the
  checklist items of the chosen reviewer profile(s), answer yes/no/unclear/not reported + optional quote;
  the model's answers are **hidden while rating** (blind), revealed after submitting.
- ≥ 2 human raters per paper recommended; inter-rater agreement shown; consensus = majority, ties → unclear.
- Ratings are versioned with the item texts they answered; changing a reviewer item later does not
  silently reuse old ratings for the new wording.

## Web

API: `POST /evals` (member; body: kind + inputs; 202 job), `GET /evals` (list with kind, status, config
summary, headline numbers), `GET /evals/{id}` (full metrics), `GET /evals/compare?ids=a,b` (aligned metrics),
gold sets list and `POST /gold-sets` from an SR (job wrapping build-gold: DOI list or SR DOI), rating samples
(`POST /evals/{id}/rating-samples`, `GET /rating-samples/{id}`, `POST /rating-samples/{id}/ratings`), all
role-guarded; cost estimate endpoint before starting (`POST /evals/estimate`). Old imported reports remain.

Frontend (reading-room design; frontend-design skill):
- **Evals home**: cards per report (kind, date, config chips, 2–3 headline numbers, status), "New evaluation"
  wizard (kind → inputs → cost estimate → start), compare mode (pick 2–3 reports → aligned view).
- **Screening report**: existing page, unchanged content.
- **Panel report**: agreement summary, item agreement table (worst first, reword hints), coverage heatmap
  (numbers + words, not colour only), dispersion list linking to papers.
- **Ablation report**: 1/2/3 comparison chart (native SVG, accessible table alternative), summary sentence,
  per-subset table.
- **Human reference**: sample progress (rated/needed), Rate view (blind), agreement with humans per item and
  reviewer.
- System map: Reviewers stage reads its status from the newest panel eval (caveat "one model family" stays).

## Testing

Metrics (Fleiss/Cohen with known values, item agreement, ablation subsets, AUC with CI, Spearman) table-tested;
panel/ablation evals on toy data with stub evaluators; CLI ↔ app consistency; job flow with fake spawn;
rating blindness (API never returns model answers to a rater before submit); role guards; UI unit tests for
wizard, reports, Rate view; targeted tests only per the user's instruction (full suites later).

## Plans

1. Pipeline/eval: panel and ablation evals, metrics, human-reference comparison, CLI subcommands.
2. Backend: eval jobs, gold-set builder job, compare, estimate, rating samples, importer.
3. Frontend: Evals home + wizard, panel/ablation/human reports, Rate view, compare mode.
