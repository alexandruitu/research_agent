# Field alerts: scheduled "what's new" runs with an in-app digest (slice 9)

Date: 2026-10-08 · Status: draft (user: "start with the diagram, then the alerts")

## Goal

Colleagues asked to be told when new literature appears in their field. An **alert** re-runs a field on a
schedule, reviews **only papers the field has not seen before**, and shows a short **digest** of the ones worth
reading. Cost and noise are bounded by code, not by the model.

Out of scope here: clinical-guidelines linking (separate pilot with a clinician), email/Teams delivery
(phase 2, below), hypothesis questions over the corpus.

## What "new" means

Sources filter by **year only** (Crossref, Semantic Scholar, OpenAlex, Europe PMC…), so a date filter alone
cannot say "since last Tuesday". New is decided in code:

1. **Search window:** current year and the previous year (overridable per alert); the field's own year range
   still applies when narrower.
2. **Seen set:** papers already screened in any finished run of the same field (any version), plus papers in
   the team library. Match by normalised DOI, else by `source_id`, else by normalised title + year (same rules
   as dedup).
3. After Deduplicate, a deterministic **Skip seen** step drops seen papers before Screen; counts are
   recorded (`found`, `already_seen`, `new`). No AI call is spent on a seen paper.

## Data model (migration 0011)

`alerts`: id, field_id (unique: one alert per field), enabled, cadence (`weekly` | `daily`), weekday/hour
(local time of the server, shown in the UI), next_run_at, last_run_id, max_new (default 50, ≤ 200),
min_group (`read_first` | `worth_a_look`, default `worth_a_look`), years_back (default 1), created_by,
created_at, updated_at.

`alert_subscriptions`: alert_id, user_id (members choose to follow a field; the creator follows by default).

`digests`: id, alert_id, run_id, created_at, counts {found, already_seen, new, reviewed, in_digest, over_cap},
items [{paper_id, group, why}] frozen at creation (survives run deletion, like the library).

`digest_reads`: digest_id, user_id, read_at (unread badge).

Runs get `trigger` (`manual` | `alert`) and keep the field version current at the time they start.

## Flow

- **Scheduler (worker tick):** each tick selects alerts with `enabled and next_run_at <= now`, with
  `FOR UPDATE SKIP LOCKED`, and enqueues one `research` job with payload `{field_id, alert_id}`. The
  idempotency key is `alert:<id>:<next_run_at>`, so two workers or a restart never double-run. `next_run_at`
  is then advanced. A missed slot (server off) runs once on start, never a backlog.
- **Run:** a normal panel run on the field's current version, with the Skip seen step and the cap. If more
  than `max_new` new papers are found, the newest (by year, then source order) are reviewed. The rest are
  counted as `over_cap` and named in the digest ("12 more not reviewed — run the field to see them").
- **Fail closed** as today. A failed alert run produces a digest row marked failed, with the reason, so silence
  never means "nothing new". After 3 consecutive failures the alert pauses itself and says why.
- **Digest:** built in code when the run finishes. It holds papers whose quality group is at or above
  `min_group`, using the same `QUALITY_GROUPS` rules as Papers, each with its one-sentence why. An empty digest
  is still recorded ("3 new papers, none worth reading").

## Cost control

- `max_new` caps AI calls per run. The estimate shown when saving an alert is `max_new` × calls per paper, from
  the existing estimate endpoint.
- Jev screens first as today. Cached calls are reused.
- A global admin setting `alerts_max_runs_per_day` (default 5) bounds the total. Excess alerts wait for the
  next day and the digest says so.

## Web

API (role-guarded; members create and follow, admins see all):

- `GET/PUT /fields/{id}/alert`
- `POST /fields/{id}/alert/run-now` (202 job)
- `POST/DELETE /alerts/{id}/subscription`
- `GET /digests?unread=1`
- `GET /digests/{id}`
- `POST /digests/{id}/read`

Frontend (reading-room design):

- **Field page:** an "Alert" card holds:
  - an on/off switch;
  - cadence, with day and time;
  - "Notify me about": Read first, or Read first + Worth a look;
  - max new papers per run, with a cost estimate;
  - next run, last run and a "Run now" button.
- **Nav:** "Alerts" with an unread count (number plus text, not colour only).
- **Alerts inbox:** one card per digest, newest first, with field, date, counts sentence, and up to 10 papers
  (title, group label, why, "Open" → the paper drawer in that run, "Save to library"). Failed and paused
  alerts appear here too.
- **Runs list:** alert runs labelled "alert".

## Phase 2 (not in this slice)

- Email digest via SMTP configured in the worker env (keys only there).
- Teams incoming webhook per field.
- Both reuse the frozen digest. Opt-in per user.

## Testing

Targeted tests only, per the user's preference:

- Seen-set matching: DOI, source_id, title+year, library.
- Skip seen counts.
- Cap ordering and `over_cap`.
- Digest group filter.
- Scheduler idempotency, with two ticks and a fake clock; missed slot runs once.
- Failure digest and auto-pause after 3.
- Daily budget.
- Role guards and unread counts.
- UI unit tests for the alert card and the inbox; one e2e: enable alert → run now (demo mode) → digest shows.
