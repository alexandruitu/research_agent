# Research Agent — context pentru Claude Code

Framework de cercetare multi-agent, auditabil și cumulativ, pentru imagistică medicală AI
(CT, MR, US, angiografie). Obiectiv: topic → căutare → deduplicare → screening → review
adversarial → scoring determinist → Top 10, apoi nivel de business value.
M1 (acest cod, generat inițial cu Codex) a rulat în demo și într-un run live mic (`runs/live-01`, 5 lucrări,
nivel Jev + Anthropic); precizia științifică nu e încă măsurată (vezi `research-eval`).

## Comenzi
- Instalare: `python3.12 -m venv .venv && . .venv/bin/activate && pip install -e '.[dev,live,ui]'`
- Teste: `pytest -q` · Lint: `ruff check .`
- Demo: `research-agent "topic" --mode demo --run-dir runs/demo`
- Live: `research-agent "topic" --mode live --max-papers 5 --run-dir runs/live-01` (cere `.env`)
- UI: `research-ui`
- Web (backend): `research-web dev --import-all --admin-email <email>` (server local, PostgreSQL embedded, parola în `RESEARCH_WEB_ADMIN_PASSWORD`); vezi `docs/web-app.md`
- Web (producție): `research-web serve` (API) și `research-web worker` (singurul proces cu chei); vezi `docs/deployment.md`
- Web (frontend): `cd web && npm run dev` (cu `research-web dev --import-all --with-worker --allow-demo` pornit) · teste în browser: `npm run e2e`
- Eval: `research-eval --help` · `build-gold` · `screen` · `agreement` · `report` (vezi README, secțiunea Evaluare)

## Principii (nu le încălca)
- Etapele deterministe (search, dedup, verificare citate, scoring) rămân cod, nu agenți.
- LLM-ul extrage, codul punctează. Orice claim are citat exact din sursă (`validate_evidence`).
- Revieweri A/B independenți, ideal din familii de modele diferite; dezacord → adjudicator.
- Fail closed: erori de rețea/schema/citate opresc run-ul, checkpoint păstrat.
- Prompturile sunt versionate (`PROMPT_VERSION`); cache-ul apelurilor (`calls` în research.sqlite)
  e Raw Layer-ul pentru viitorul Research Wiki.
- Etapele de măsurare rulează offline din cache (Raw Layer); report nu apelează niciodată API-uri.
- Chei doar în `.env` (gitignored). Nu loga și nu comite chei.
- UI: o etapă e verde doar dacă există o măsurătoare; date lipsă ≠ nu se aplică; starea nu se transmite doar prin culoare.

## Roadmap
1. M1.5 — făcut: primul run live pe un topic din domeniu, 5 lucrări (`runs/live-01`).
2. Nivel Jev (TypeSafe, `TYPESAFE_API_KEY`) la screening: IMPLEMENTAT (`--jev`, cascadă cu escaladare la LLM,
   praguri asimetrice `--jev-min-confidence`/`--jev-exclude-min-confidence`, probabilități brute în cache
   cu versiunea modelului). Rămâne: calibrarea pragurilor cu `research-eval` pe un gold set real.
   MCP opțional: github.com/itsmostafa/system-one-connector
3. Conectori OpenAlex (snowballing, afilieri) și arXiv (preprinturi MICCAI/cs.CV); Europe PMC există.
4. Eval harness: implementat (`research-eval`; recomandă doar perechi de praguri care nu pierd niciun pozitiv
   păstrat de `llm_only`, pe setul principal și pe holdout; `--target-recall` e constrângere
   opțională); urmează un run real pe 1–2 SR-uri open-access și calibrarea pragurilor Jev.
5. Scoring pe checklist (CLAIM, TRIPOD+AI) cu citat per item, scor calculat în cod; red flags
   data leakage (split pe imagini vs pacienți, lipsă validare externă).
6. Research Wiki (patterns, logs, skill-impact) + Research Skills cu gating pe gold set (WikiSkill,
   arXiv:2608.27454): skill-urile se pot rollback, wiki-ul nu.
7. Full text (Unpaywall, PMC OA), PostgreSQL + pgvector, nivel business (portofoliu, FDA AI
   devices list, brevete Lens.org, competitori).
