# Research Agent — context pentru Claude Code

Framework de cercetare multi-agent, auditabil și cumulativ, pentru imagistică medicală AI
(CT, MR, US, angiografie). Obiectiv: topic → căutare → deduplicare → screening → review
adversarial → scoring determinist → Top 10, apoi nivel de business value.
M1 (acest cod, generat inițial cu Codex) e verificat doar în mod demo; niciun run live încă.

## Comenzi
- Instalare: `python3.12 -m venv .venv && . .venv/bin/activate && pip install -e '.[dev,live,ui]'`
- Teste: `pytest -q` (18 teste) · Lint: `ruff check .`
- Demo: `research-agent "topic" --mode demo --run-dir runs/demo`
- Live: `research-agent "topic" --mode live --max-papers 5 --run-dir runs/live-01` (cere `.env`)
- UI: `research-ui`

## Principii (nu le încălca)
- Etapele deterministe (search, dedup, verificare citate, scoring) rămân cod, nu agenți.
- LLM-ul extrage, codul punctează. Orice claim are citat exact din sursă (`validate_evidence`).
- Revieweri A/B independenți, ideal din familii de modele diferite; dezacord → adjudicator.
- Fail closed: erori de rețea/schema/citate opresc run-ul, checkpoint păstrat.
- Prompturile sunt versionate (`PROMPT_VERSION`); cache-ul apelurilor (`calls` în research.sqlite)
  e Raw Layer-ul pentru viitorul Research Wiki.
- Chei doar în `.env` (gitignored). Nu loga și nu comite chei.

## Roadmap
1. M1.5 — primul run live pe un topic din domeniu (ex. deep learning CT-FFR), 5 lucrări.
2. Nivel Jev (TypeSafe, `POST https://api.typesafe.ai/v1/systemone`, `TYPESAFE_API_KEY`) la
   screening: criterii ca întrebări `noul`/`choice`/`score`, `min_confidence` → escaladare la LLM.
   Praguri asimetrice (recall contează mai mult). Cache verdicte + versiunea modelului în audit.
   Trimite evidence, nu concluzii. MCP opțional: github.com/itsmostafa/system-one-connector
3. Conectori OpenAlex (snowballing, afilieri) și arXiv (preprinturi MICCAI/cs.CV); Europe PMC există.
4. Eval harness: gold set din review-uri sistematice publicate → recall screening, kappa revieweri.
5. Scoring pe checklist (CLAIM, TRIPOD+AI) cu citat per item, scor calculat în cod; red flags
   data leakage (split pe imagini vs pacienți, lipsă validare externă).
6. Research Wiki (patterns, logs, skill-impact) + Research Skills cu gating pe gold set (WikiSkill,
   arXiv:2608.27454): skill-urile se pot rollback, wiki-ul nu.
7. Full text (Unpaywall, PMC OA), PostgreSQL + pgvector, nivel business (portofoliu, FDA AI
   devices list, brevete Lens.org, competitori).
