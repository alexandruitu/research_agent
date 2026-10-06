# Papers tab: quality groups (slice 8) — design

Approved by the user on 2026-10-06 ("decide details yourself"). Decisions taken without questions are marked **D**.

## Goal
Turn the Papers table from one flat, wide list into a reading list: papers grouped by what to do with them,
with readable criteria values and a narrower title column.

## Layout
- Paper column: title clamped to 2 lines (`-webkit-line-clamp`), full title in `title=` (hover) and in the
  drawer; year · source id below; library badge. "abstract only" appears once, in words, in the Text reviewed column.
- Criteria column: one line per criterion, `label  value` where value is the Jev probability (2 decimals)
  and/or the LLM answer (`yes`/`no`/`unclear`); the deciding criterion is marked with `◆` and the word
  "decided" (never colour alone). No truncation: values wrap. The summary line ("dropped by …") stays.

## Quality groups (computed in SQL, `research_agent.web.papers.QUALITY_GROUPS`)
Verdict `v`: panel runs → the editor verdict (`paper_reviews.editor_verdict`); legacy A/B runs
(**D**) → the adjudicator's verdict when there is one, else A's verdict when A and B agree, else
`uncertain` (A and B disagree, no adjudicator), else none. Red flags `f`: panel `red_flag_count`;
legacy runs have no red-flag check (`f` unknown).

Evaluated in order, first match wins:
1. `not_relevant` "Not relevant" — dropped by screening (`decision = exclude`, tier ≠ `rule`).
2. `has_problems` "Has problems" — `f ≥ 2` or `v = exclude`.
3. `read_first` "Read first" — `v = include` and `f = 0` (a measured zero: **D** legacy papers never qualify,
   their red flags were not checked).
   A **provisional** paper (panel coverage < `PROVISIONAL_COVERAGE` = 0.5: the score counts too few answered
   items, typically abstract only) never qualifies and falls to `worth_a_look`. `PaperRow.provisional` (+
   `checklist_answered`/`checklist_total`) marks it; filter `provisional=true|false` (URL `prov`); inside a
   group provisional papers sort after the firm ones.
4. `worth_a_look` "Worth a look" — `v ∈ {include, uncertain}` and (`f ≤ 1` or `f` unknown).
5. `not_reviewed` "Not reviewed" (**D**, fifth group) — everything else: kept but no verdict (outside an
   eval agreement sample, panel did not review it, no editor verdict), and papers never screened
   (tier `rule`, no abstract). Never hidden.

The rule text is part of the API response (`rule`) and shown on each group header.

## Other groupings ("Group by")
`quality` (default) | `source` (a paper found by several sources appears in each; `none` for eval
candidates) | `year` (`none` = unknown) | `decided_by` (dropped papers by their criterion; `kept`; `not_screened`;
`unattributed` = dropped with no single criterion) | `library` (`to_read|read|relevant|rejected|not_saved`) |
`none` (flat list, existing paging). URL param `group` (absent = quality, `none` = flat).

## API (additive)
- `PaperRow.group`: the quality group key (always sent).
- `GET /runs/{id}/papers?group_by=…&group=<key>`: filter on one group (same filters/sort/paging otherwise).
- `GET /runs/{id}/papers/groups?by=…` + the same filter params: `[{key, label, count, rule}]` in display order;
  quality always returns the four main groups (count may be 0) and `not_reviewed` only when non-empty.

## Frontend
- Each section: `<section>` with a header button (`aria-expanded`, `aria-controls`) showing icon + name +
  count + rule; body is a `PaperTable` with its own page (25 rows) and "Show more" (loads the next page,
  appending). Collapsed state per user in `localStorage` key `papers.collapsed.<userId>.<by>` (try/catch).
  "Expand all / Collapse all".
- Selection, save-to-library and j/k/o/s/x work across visible rows of all expanded groups (DOM order).
- Sorting: within groups the default is panel score desc (nulls last); a sort the user picks applies to every group.
