# Research Agent: architecture

Literature screening for medical-imaging AI: topic → search → dedupe → screen → extract → review →
rank, measured against published systematic reviews, browsable by a department in a web app.

Rules the design keeps: deterministic stages are code; the LLM extracts, the code scores; every claim
quotes the source exactly; fail closed; keys only in `.env` / the worker; measurement runs offline from
the call cache; the UI shows a stage as green only when it is measured.

## 1. System overview

```mermaid
flowchart LR
  subgraph Sources
    EPMC[Europe PMC]
  end
  subgraph Models
    CL[Anthropic LLM]
    JEV[TypeSafe Jev]
  end
  CLI[research-agent CLI] --> PIPE[Pipeline<br/>graph.py]
  PIPE --> EPMC & CL & JEV
  PIPE --> RUN[(Run folder<br/>report.json · research.sqlite)]
  EVAL[research-eval] --> EVD[(Eval folder<br/>metrics.json)]
  EVAL -. offline from cache .-> RUN
  RUN & EVD --> IMP[Importers] --> PG[(PostgreSQL)]
  API[FastAPI /api/v1] --> PG
  WK[Worker] --> PG
  WK -- child process --> PIPE
  UI[React app] --> API
```

| Module | Path | Role |
|---|---|---|
| Pipeline | `src/research_agent/{graph,agents,connectors,storage,report,cli}.py` | runs a research run |
| Jev tier | `src/research_agent/jev.py` | cheap confident screening, escalates to the LLM |
| Eval harness | `src/research_agent/eval/` | recall, threshold sweep, reviewer agreement |
| Web backend | `src/research_agent/web/` | DB, importers, auth, API, worker |
| Frontend | `web/` | React single-page app |
| Deployment | `deploy/`, `.github/workflows/ci.yml` | Compose, nginx, CI |

## 2. Pipeline (`graph.py`)

LangGraph state machine; each node checkpoints, so a failed run resumes (`--resume`).

```mermaid
flowchart LR
  S((start)) --> plan --> discover --> normalize --> screen --> extract
  extract --> A[review_a] & B[review_b]
  A & B --> adj[adjudicate] --> rank --> E((end))
  classDef code fill:#e6f4f1,stroke:#2a9d8f
  classDef llm fill:#fdf2e3,stroke:#e9a23b
  class discover,normalize,rank code
  class plan,screen,extract,A,B,adj llm
```

- **Code (teal):** search (Europe PMC), dedupe, quote validation (`validate_evidence`), scoring and rank.
- **LLM (amber):** plan the query, screen, extract claims with exact quotes, two independent reviewers,
  an adjudicator only when they disagree.
- Every model call is cached in `research.sqlite` (`calls`), keyed by a digest of model, prompt version
  and input. This is the raw audit trail.

## 3. Screening cascade (`jev.py`)

```mermaid
flowchart TD
  P[Paper title + abstract] --> NA{Abstract?}
  NA -- no --> R[tier=rule · uncertain<br/>not screened]
  NA -- yes --> J[Jev: p = P topic_match]
  J --> C{"confidence |2p−1|"}
  C -- "p ≥ 0.8 (include ≥ 0.6)" --> INC[include · tier=jev]
  C -- "p ≤ 0.05 (exclude ≥ 0.9)" --> EXC[exclude · tier=jev]
  C -- otherwise --> L[LLM screen · tier=llm] --> D[include / exclude / uncertain]
```

Thresholds are asymmetric because losing a relevant paper costs more than reading an extra one. Raw
probabilities are cached, so thresholds can be changed and re-evaluated without new calls.

## 4. Eval harness (`eval/`)

```mermaid
flowchart LR
  SR[Published SR<br/>sr_specs/*.yaml] --> GB[build-gold<br/>resolve DOIs/titles] --> G[(gold/*.json<br/>content hash)]
  G --> SC[screen<br/>Jev + LLM on every candidate] --> EV[(evals/name)]
  EV --> AG[agreement<br/>A/B/adjudicator on a sample]
  EV & AG --> RP[report<br/>offline] --> M[(metrics.json)]
  H[(holdout eval)] --> RP
```

`report` computes recall with Wilson intervals for `llm_only`, `jev_only` and `cascade`; sweeps every
threshold pair; recommends only pairs that lose no SR-included paper that `llm_only` keeps, on the main
set **and** the holdout; and reports reviewer kappa with a same-family flag.

## 5. Web backend (`web/`)

```mermaid
flowchart TB
  subgraph API[FastAPI /api/v1]
    MW[Middleware: request id · security headers · redacted 500s]
    G[require_role: viewer · member · admin<br/>+ CSRF on writes]
    R1[auth · users] & R2[fields · runs · papers · drawer] & R3[stages · evals] & R4[POST runs · resume · jobs · imports]
  end
  MW --> G --> R1 & R2 & R3 & R4
  R2 -- raw calls, members --> CS[callstore<br/>64-hex key · folder confined · read-only]
  CS --> RF[(run folders)]
  R1 & R2 & R3 & R4 --> DB[(PostgreSQL)]
  R3 --> ST[stages.yaml<br/>status computed from metrics]
```

- **Auth:** server-side sessions (`HttpOnly` cookie), argon2 passwords, CSRF token header, login rate limit.
- **Paper table:** each cell is data, `null` (stage does not apply) or `{"missing": true}` (expected but absent).
- **Import:** one transaction per folder, idempotent by content hash, refuses a changed gold file.

### Data model

```mermaid
erDiagram
  FIELD ||--o{ CRITERION : has
  FIELD ||--o{ RUN : groups
  RUN ||--o{ SCREENING : has
  SCREENING ||--o{ CRITERION_SCORE : has
  RUN ||--o{ EVIDENCE_CLAIM : has
  RUN ||--o{ REVIEW : has
  RUN ||--o{ RANKING : has
  PAPER ||--o{ SCREENING : "is screened in"
  GOLD_SET ||--o{ GOLD_LABEL : has
  GOLD_SET ||--o{ EVAL_REPORT : "measured by"
  RUN ||--o| EVAL_REPORT : produces
  USER ||--o{ SESSION : has
  USER ||--o{ JOB : creates
  JOB }o--|| RUN : runs
```

## 6. Worker and jobs (`jobs.py`, `worker.py`, `runner.py`)

```mermaid
sequenceDiagram
  participant UI
  participant API
  participant DB as PostgreSQL
  participant W as Worker
  participant P as Pipeline child
  UI->>API: POST /runs (Idempotency-Key)
  API->>DB: insert run + job (queued)
  API-->>UI: 202 job id
  W->>DB: claim (FOR UPDATE SKIP LOCKED)
  W->>P: spawn (topic after --, keys in env only, .env disabled)
  loop every poll
    W->>DB: progress + heartbeat (only if still owner)
    UI->>API: GET /jobs/id
  end
  P-->>W: exit 0
  W->>DB: import run + complete job (one transaction)
```

- **Failure:** sanitized text `failed at stage 'X': Type: message`; the checkpoint is kept for resume.
- **Stale heartbeat** (DB clock): the job is requeued, and the old worker stops its child.
- **Time limit:** `RESEARCH_WEB_JOB_TIMEOUT_SECONDS`.
- **SIGTERM:** the child is stopped and the job released without counting an attempt.
- **Folder lock held** (exit 75): the job goes back to the queue.

## 7. Frontend (`web/`)

```mermaid
flowchart TB
  App --> Auth[AuthProvider · RequireAuth · RequireRole]
  Auth --> Layout[Layout: nav · stale banner · error boundary]
  Layout --> Papers & Runs & Evals & System[System map] & Users
  Papers --> Strip[Pipeline strip] & Table[Paper table] & Filters & Drawer[Paper drawer + raw calls]
  Runs --> Start[Start form] & Job[Job progress, polls 2 s]
  Evals --> Cards & Recall[Recall intervals] & Grid[Threshold grid]
  subgraph Data
    Hooks[TanStack Query hooks] --> Client[fetch client: cookies · CSRF · errors]
    Types[schema.d.ts generated from OpenAPI]
  end
  Papers & Runs & Evals & System & Users --> Hooks
```

View state (run, filters, sort, page, open paper, stage) lives in the URL. Status is never shown by colour
alone. Types are generated from the API, and CI fails if they are stale.

## 8. Deployment (`deploy/`)

```mermaid
flowchart LR
  B[Browser] -- HTTPS --> RP[TLS reverse proxy]
  RP --> WEB["web: nginx<br/>SPA + strict CSP<br/>127.0.0.1:8080"]
  WEB -- /api/ --> API["api: research-web serve<br/>no keys"]
  API --> DB[(db: postgres 16)]
  WK["worker: research-web worker<br/>worker.env = keys"] --> DB
  MIG[migrate: one-shot] --> DB
  API -. read-only .-> V[(runs volume)]
  WK --> V
```

Only `web` publishes a port. Provider keys exist only in the worker. CI runs the lint, unit and browser
tests (with axe), `pip-audit` and `npm audit`, and builds both images.

## Running it

See `docs/web-app.md` (local development, commands, real-data checks) and `docs/deployment.md`.
