# Research Agent — context for Claude Code

Auditable, cumulative multi-agent research framework for AI medical imaging
(CT, MR, US, angiography). Goal: topic → search → deduplication → screening → adversarial
review → deterministic scoring → Top 10, then a business-value layer.
M1 (this code, initially generated with Codex) has run in demo and in a small live run (`runs/live-01`, 5 papers,
Jev + Anthropic layer); scientific precision is not measured yet (see `research-eval`).

## Commands
- Install: `python3.12 -m venv .venv && . .venv/bin/activate && pip install -e '.[dev,live,ui]'`
- Tests: `pytest -q` · Lint: `ruff check .`
- Demo: `research-agent "topic" --mode demo --run-dir runs/demo`
- Live: `research-agent "topic" --mode live --max-papers 5 --run-dir runs/live-01` (requires `.env`)
- UI: `research-ui`
- Web (backend): `research-web dev --import-all --admin-email <email>` (local server, embedded PostgreSQL, password in `RESEARCH_WEB_ADMIN_PASSWORD`); see `docs/web-app.md`
- Web (production): `research-web serve` (API) and `research-web worker` (the only process with keys); see `docs/deployment-docker.md` (Docker install) and `docs/deployment.md`
- Web (frontend): `cd web && npm run dev` (with `research-web dev --import-all --with-worker --allow-demo` running) · browser tests: `npm run e2e`
- Eval: `research-eval --help` · `build-gold` · `screen` · `agreement` · `report` (see README, section Evaluation)

## Principles (do not break them)
- Deterministic stages (search, dedup, quote verification, scoring) stay code, not agents.
- The LLM extracts, the code scores. Every claim has an exact quote from the source (`validate_evidence`).
- Independent A/B reviewers, ideally from different model families; disagreement → adjudicator.
- Fail closed: network/schema/quote errors stop the run, checkpoint kept. Exception: optional search sources, which are skipped with a recorded, visible warning (the run fails only if a `required` source fails or all sources fail).
- Prompts are versioned (`PROMPT_VERSION`); the call cache (`calls` in research.sqlite)
  is the Raw Layer for the future Research Wiki.
- Measurement stages run offline from the cache (Raw Layer); report never calls APIs.
- Keys only in `.env` (gitignored). Do not log and do not commit keys.
- UI: a stage is green only if a measurement exists; missing data ≠ not applicable; state is not conveyed by color alone.

## Roadmap
1. M1.5 — done: first live run on an in-domain topic, 5 papers (`runs/live-01`).
2. Jev layer (TypeSafe, `TYPESAFE_API_KEY`) at screening: IMPLEMENTED (`--jev`, cascade with escalation to the LLM,
   asymmetric thresholds `--jev-min-confidence`/`--jev-exclude-min-confidence`, raw probabilities in the cache
   with the model version). Remaining: calibrating the thresholds with `research-eval` on a real gold set.
   Optional MCP: github.com/itsmostafa/system-one-connector
3. OpenAlex connectors (snowballing, affiliations) and arXiv (MICCAI/cs.CV preprints); Europe PMC exists.
4. Eval harness: implemented (`research-eval`; recommends only threshold pairs that lose no positive
   kept by `llm_only`, on the main set and on the holdout; `--target-recall` is an
   optional constraint); next: a real run on 1–2 open-access SRs and calibration of the Jev thresholds.
5. Checklist scoring (CLAIM, TRIPOD+AI) with a quote per item, score computed in code; data leakage
   red flags (image-level vs patient-level split, no external validation).
6. Research Wiki (patterns, logs, skill-impact) + Research Skills with gating on a gold set (WikiSkill,
   arXiv:2608.27454): skills can be rolled back, the wiki cannot.
7. Full text (Unpaywall, PMC OA), PostgreSQL + pgvector, business layer (portfolio, FDA AI
   devices list, Lens.org patents, competitors).
