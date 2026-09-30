# Slice 5 · Plan 1: Pipeline (more sources via official APIs) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nine new literature sources (Semantic Scholar, Crossref, PubMed, medRxiv, bioRxiv, CORE, IEEE Xplore,
Springer Nature, Scopus) and six new full-text resolvers behind one polite HTTP layer (shared token-bucket rate
limits, User-Agent with contact, Retry-After, keys from the environment only), cross-id identity and dedup,
Crossref DOI enrichment, per-source query building — with legacy runs byte-identical.

**Architecture:** `ratelimit.py` holds a thread-safe token bucket per rate bucket and the documented default
rates. `connectors.fetch` gains `headers`, `secret` (never chained into exceptions) and per-source rate limiting
and honours `Retry-After`. New search connectors live in `sources.py` next to a static `REGISTRY` (the data the
backend/frontend plan exposes). `querybuild` gains one builder per source plus a local keyword matcher for
sources without boolean search. `fulltext.FullText` gains six resolvers and records `text_licence`.
`deduplicate` merges on DOI and cross-ids (PMID, PMCID, arXiv, S2) before title+year; `CrossrefEnricher` fills
missing DOIs (≤ 50 lookups per run, cached in a new `lookups` table).

**Tech Stack:** Python 3.12, httpx (MockTransport fixtures), pydantic 2, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-30-more-sources-design.md` (Principles, Full-text order, Testing, Plans → 1).

---

## Decisions this plan takes

1. **medRxiv / bioRxiv go through Europe PMC**, not api.biorxiv.org. The bioRxiv/medRxiv API has no search: it
   returns every preprint of a date window, 100 per page (thousands per month), so keyword search would mean
   downloading whole months and filtering locally, with a total that only covers the fetched window. Europe PMC
   indexes both servers (source `PPR`, publisher field), supports the same boolean syntax we already build, and
   reports an honest hit count. Verified once against the live API: `(...) AND SRC:PPR AND PUBLISHER:"medRxiv"`
   → hitCount 103 (fixture `tests/fixtures/europepmc_preprints.json`). The connector appends the filter (like the
   years), so an override cannot drop it. Rate bucket shared with Europe PMC.
2. **Semantic Scholar uses `/graph/v1/paper/search` (relevance)**, not `/paper/search/bulk`. Bulk supports a
   boolean syntax but returns results unranked (paperId order), so the top `max_results` would be arbitrary. The
   relevance endpoint has no boolean syntax: the built query is the plain `all` + `any` terms, and results are
   filtered locally against the keywords (every `all`, one `any`, no `none`, whole-word, case-insensitive, in
   title+abstract). `total` is the API's hit count before local filtering; `SearchResult.note` says so.
   Crossref (`query.bibliographic`, no boolean) works the same way.
3. **Rate limits** (requests/second; token bucket, burst = max(1, rate)); a key raises it where documented:

   | bucket | no key | with key | basis |
   |---|---|---|---|
   | europepmc (also medrxiv, biorxiv, pmc_oa, europepmc full text) | 10 | – | EBI fair use |
   | openalex | 10 | 10 | OpenAlex: max 10 rps |
   | arxiv | 1/3 | – | arXiv terms: 1 request / 3 s (existing sleep kept) |
   | semantic_scholar | 1 | 1 | S2: introductory key rate 1 rps; shared pool 429s often |
   | crossref | 5 | – | Crossref public pool 5 rps (polite pool with mailto) |
   | pubmed | 3 | 10 | NCBI E-utilities |
   | core | 1/6 | – | CORE free key: 10 requests/minute |
   | ieee | 2 | – | IEEE Xplore API: 10 calls/s cap, 200/day |
   | springer | 1 | – | Springer Nature free plan (per minute caps) |
   | elsevier (scopus, sciencedirect) | 5 | – | Elsevier: 9 rps Scopus Search, 10 rps article |
   | unpaywall | 5 | – | 100 000/day |

   `max_results` default 100 (le=200) for every source, as today. Page size caps: S2 100, CORE 100, Springer 25,
   Scopus 25 (paged up to max_results); PubMed esearch retmax = max_results; Crossref rows = max_results.
4. **Retry policy** (all sources): 3 attempts; retry on transport errors and 429/500/502/503/504; wait =
   `Retry-After` (seconds or HTTP date) when present, else 1 s then 2 s; a `Retry-After` above 60 s fails closed
   at once. Timeout 30 s. The limiter is acquired before every attempt.
5. **Identification:** every request carries `User-Agent: research-agent/0.1 (+mailto:<contact>)` where contact
   is the source's `contact` or the env var `RESEARCH_AGENT_CONTACT`; without one: `research-agent/0.1`.
   Crossref gets `mailto`, PubMed `tool=research-agent` and `email`.
6. **Credentials** come from environment variables read at request time (`env_key`). They go into headers or
   query params only, never into provenance URLs, `raw` payloads, `lookups`, `fulltext` cache keys or exception
   messages; `fetch(..., secret=True)` raises `SourceUnavailable(...) from None` so no httpx URL with a key is
   chained. A sentinel test scans the whole `research.sqlite`.
7. **`SourceKeyMissing(source, env_var)`** subclasses `SourceUnavailable`; raised by `search_with_total` before
   any request (so a run fails in the discover stage). `str(exc)` and `exc.message` =
   `"<source>: set <ENV_VAR> in the worker environment"`; `exc.source` stays the bare name (preview/checks
   unchanged). `SourceUnavailable.message` = source; the runner writes `exc.message` to progress.
8. **Paper ids:** `Paper` gains `pmid`, `arxiv`, `s2` (default ""), dropped from dumps when empty so legacy
   dumps and cache keys are unchanged. The three existing connectors are not changed; dedup also derives ids from
   `Paper.id` prefixes (`MED:`, `PMC:`, `arxiv:`, `pubmed:`, `s2:`).
9. **Dedup:** papers merge when they share `id`, DOI, or any cross-id (pmid/pmcid/arxiv/s2) and have no
   conflicting DOI; else by normalized title+year (existing rule). Merged papers keep the first non-empty value
   of every id.
10. **Crossref enrichment** runs in `normalize` (before dedup) only in live mode and only when the field lists
    the `crossref` source (the Identity source; legacy and existing field runs unchanged). At most 50 lookups per
    run; a DOI is accepted only when Crossref's title (normalized) and year equal the paper's. Lookups cached in
    `lookups` (key = digest of title+year). Network failure fails closed (`SourceUnavailable("crossref")`).
11. **Query syntax per new source** (`querybuild.build`):
    - pubmed: `"t1"[tiab] AND ("a1"[tiab] OR a2[tiab]) NOT n1[tiab]`, wildcards kept.
    - medrxiv / biorxiv: Europe PMC syntax (`TITLE_ABS:`), connector appends `AND (SRC:PPR AND PUBLISHER:"…")`.
    - semantic_scholar / crossref: plain `t1 "t 2" a1 a2` (no `none`), local filter (decision 2).
    - core: `"t1" AND ("a1" OR "a2") AND NOT "n1"` over all fields (CORE has no title+abstract field pair; it
      also matches full text — documented limitation). Years: `AND yearPublished>=Y`.
    - ieee: `t1 AND (a1 OR a2) NOT n1` in `querytext` (metadata search: title, abstract, index terms); years
      via `start_year`/`end_year`.
    - springer: `t1 AND (a1 OR a2) NOT n1` in `q`; years via `datefrom:`/`dateto:` constraints.
    - scopus: `TITLE-ABS-KEY(t1) AND (TITLE-ABS-KEY(a1) OR …) AND NOT TITLE-ABS-KEY(n1)`, wildcards kept;
      years `AND PUBYEAR > Y-1 AND PUBYEAR < Z+1`. STANDARD view (no abstracts unless entitled; papers without an
      abstract are not screened, dedup can fill the abstract from another source).
12. **Full-text order** (constant `DEFAULT_ORDER`): `pmc_oa, europepmc, core, springer_oa, semantic_scholar_oa,
    unpaywall, ieee, sciencedirect, upload`. `FulltextSpec.sources` accepts all nine (max 9, unique); its default
    stays `["pmc_oa", "upload"]`. Missing keys make a resolver unavailable with reason `"<ENV_VAR> not set"`
    (full text is never fatal). `ieee` only for `access_type == "OPEN_ACCESS"` with a PDF; `sciencedirect` only
    when the Entitlement API says `entitled: true` and the article response carries `originalText`.
13. **`text_licence`** (new key of every `FullText.resolve` result): `cc-by`, `cc-by-sa`, `cc-by-nd`, `cc-by-nc`,
    `cc-by-nc-sa`, `cc-by-nc-nd`, `cc0` when the source states a Creative Commons licence; `open_access` for other
    open text; `publisher_licensed` for entitled non-OA text (ScienceDirect); `user_upload`; `abstract`.
    `publisher_licensed` texts must never be exported. Cached entries without a licence read as `open_access`
    (uploads `user_upload`), so `FULLTEXT_VERSION` stays `ft-1`.
14. **Demo mode:** every source name gets `DemoConnector(store, source=name)` (as today; no network); full-text
    resolvers other than `upload` report "not fetched in demo mode".
15. **Web column width:** `text_source` is `String(16)` in the web DB; `semantic_scholar_oa` is 19 characters.
    Plan 2 must widen it (and add `text_licence`). No web change here.

## File structure

- Create `src/research_agent/ratelimit.py` — `TokenBucket`, `RATES`, `limiter(bucket)`, `reset()`.
- Modify `src/research_agent/connectors.py` — `fetch` (headers, secret, limiter, Retry-After, UA),
  `SourceKeyMissing`, `env_key`, `user_agent`, `SearchResult.note`, OpenAlex key, `domain_connector` dispatch via
  `sources.make_connector`, cross-id `deduplicate`, `paper_ids`.
- Create `src/research_agent/sources.py` — `REGISTRY`, `SemanticScholar`, `Crossref`, `CrossrefEnricher`,
  `PubMed`, `Preprints`, `Core`, `IEEE`, `Springer`, `Scopus`, `make_connector`.
- Modify `src/research_agent/querybuild.py` — per-source builders, `matches(keywords, text)`.
- Modify `src/research_agent/schemas.py` — `Paper` ids, `SearchSourceName`, `FulltextSource`, limits.
- Modify `src/research_agent/fulltext.py` — six resolvers, `text_licence`, `DEFAULT_ORDER`.
- Modify `src/research_agent/storage.py` — `lookups` table.
- Modify `src/research_agent/graph.py` — enrichment hook in `normalize`.
- Modify `src/research_agent/runner.py` — progress message from `exc.message`.
- Tests: `tests/test_ratelimit.py`, `tests/test_sources.py`, `tests/test_sources_fulltext.py`,
  `tests/test_identity.py`, `tests/test_secrets.py`, additions to `tests/test_querybuild.py`,
  `tests/test_review_spec.py`, `tests/test_domain.py`.
- Fixtures (`tests/fixtures/`): recorded once from public APIs: `crossref_works.json`, `pubmed_esearch.json`,
  `pubmed_efetch.xml` (reference lists trimmed), `europepmc_preprints.json`; hand-written from docs (URL in a
  sibling `_README` table in the test module): `s2_search.json` (S2 answered 429 to three unauthenticated
  attempts), `core_search.json`, `ieee_search.json`, `springer_meta.json`, `springer_jats.xml`,
  `scopus_search.json`, `elsevier_entitlement.json`, `sciencedirect_article.xml`.

---

### Task 1: Rate limiter and polite fetch

**Files:** Create `src/research_agent/ratelimit.py`; modify `src/research_agent/connectors.py`; test
`tests/test_ratelimit.py`.

- [ ] **Step 1: failing tests** — `tests/test_ratelimit.py`:
  - `test_bucket_allows_a_burst_then_spaces_requests` (fake clock: rate 2, 4 acquires → sleeps 0, 0, 0.5, 0.5)
  - `test_bucket_is_shared_across_threads` (8 threads × 1 acquire on rate 4 → total fake sleep ≥ 1.0)
  - `test_limiter_registry_returns_one_bucket_per_name_and_key_state`
  - `test_retry_after_seconds_is_respected` (429 `Retry-After: 7` then 200 → slept [7])
  - `test_retry_after_http_date_is_respected`
  - `test_retry_after_above_cap_fails_closed_at_once` (`Retry-After: 3600` → SourceUnavailable, 1 request)
  - `test_user_agent_carries_the_contact` / `test_user_agent_contact_from_environment`
  - `test_headers_are_sent_and_secret_failures_do_not_chain` (`exc.__cause__ is None`, key not in `repr`)
  - `test_fetch_acquires_the_source_bucket_per_attempt`
  - `test_source_key_missing_message_names_the_variable`
- [ ] **Step 2:** `pytest tests/test_ratelimit.py -q` → FAIL (module missing).
- [ ] **Step 3: implement**

```python
# ratelimit.py
class TokenBucket:
    def __init__(self, rate, burst=None, clock=time.monotonic, sleep=time.sleep):
        self.rate, self.capacity = rate, burst or max(1.0, rate)
        self.tokens, self.clock, self.sleep = self.capacity, clock, sleep
        self.updated, self.lock = clock(), threading.Lock()

    def acquire(self):
        with self.lock:
            now = self.clock()
            self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
            self.updated = now
            self.tokens -= 1
            wait = -self.tokens / self.rate if self.tokens < 0 else 0.0
        if wait > 0:
            self.sleep(wait)
        return wait

RATES = {"europepmc": (10, 10), "openalex": (10, 10), "semantic_scholar": (1, 1), "crossref": (5, 5),
         "pubmed": (3, 10), "core": (1 / 6, 1 / 6), "ieee": (2, 2), "springer": (1, 1), "elsevier": (5, 5),
         "unpaywall": (5, 5)}
BUCKETS = {"medrxiv": "europepmc", "biorxiv": "europepmc", "pmc_oa": "europepmc", "scopus": "elsevier",
           "sciencedirect": "elsevier", "springer_oa": "springer", "semantic_scholar_oa": "semantic_scholar"}
def limiter(source, keyed=False): ...  # one TokenBucket per (bucket, keyed); None for unknown sources
```

`connectors.fetch(client, url, params, source, decode, headers=None, secret=False)`: builds
`{"User-Agent": user_agent(), **headers}`, acquires `limiter(source, keyed)` before each attempt, computes the
wait via `retry_after(response)` (cap 60 s), and raises `SourceUnavailable(source) from None` when `secret`.
- [ ] **Step 4:** tests pass; full `pytest -q` green (existing retry tests unchanged: 1 s then 2 s).
- [ ] **Step 5:** `ruff format src tests && ruff check .`; commit `ratelimit.py connectors.py test_ratelimit.py`.

### Task 2: Schemas — source names, paper ids, full-text sources

**Files:** `src/research_agent/schemas.py`; tests in `tests/test_domain.py`, `tests/test_review_spec.py`.

- [ ] **Step 1: failing tests:** `test_every_registry_source_is_a_valid_domain_source`,
  `test_a_field_may_list_twelve_sources`, `test_unknown_source_is_rejected`,
  `test_paper_dump_omits_empty_new_ids`, `test_paper_dump_keeps_set_ids`,
  `test_fulltext_accepts_every_resolver_in_any_order`, `test_fulltext_default_is_unchanged`,
  `test_fulltext_rejects_duplicates_and_unknown`.
- [ ] **Step 3: implement:** `SEARCH_SOURCES` tuple of 12 names; `SourceName = Literal[...]` used by
  `SourceSpec.name` and `DomainSpec.queries`; `sources` max 12; `FulltextSource = Literal[9 names]`, max 9;
  `Paper.pmid/arxiv/s2 = ""` with a wrap serializer that pops them when empty.
- [ ] Steps 2/4/5 as Task 1; commit.

### Task 3: querybuild per source and local keyword matching

**Files:** `src/research_agent/querybuild.py`; `tests/test_querybuild.py`.

- [ ] **Step 1: failing tests** (table test over the keywords `{"all": ["deep learning"], "any": ["CT", "MRI*"],
  "none": ["mouse"]}`), expected strings per decision 11:
  `test_build_new_sources[pubmed|medrxiv|biorxiv|semantic_scholar|crossref|core|ieee|springer|scopus]`,
  `test_plain_sources_drop_none_terms`, `test_matches_requires_all_any_and_no_none`,
  `test_matches_is_whole_word_and_case_insensitive`, `test_matches_star_is_a_prefix`,
  `test_override_rules_apply_to_new_sources`, `test_existing_sources_unchanged` (existing tests stay).
- [ ] **Step 3: implement** `SYNTAXES` dict {source: (prefix, suffix, not_op, wildcard, plain)} and
  `matches(keywords, text)`.
- [ ] Steps 2/4/5; commit.

### Task 4: Registry, Semantic Scholar and Crossref connectors

**Files:** create `src/research_agent/sources.py`, `tests/test_sources.py`; fixtures `s2_search.json`,
`crossref_works.json`.

- [ ] **Step 1: failing tests:** `test_registry_covers_every_search_source_and_resolver`,
  `test_registry_auth_matches_env_vars`, `test_s2_parses_ids_and_open_access_pdf`,
  `test_s2_sends_year_range_fields_and_optional_key_header`, `test_s2_pages_up_to_max_results`,
  `test_s2_raw_filters_locally_and_reports_api_total_with_note`, `test_crossref_parses_and_strips_jats`,
  `test_crossref_sends_mailto_filter_and_rows`, `test_new_sources_fail_closed_on_malformed_bodies[...]`.
- [ ] **Step 3: implement** `SourceInfo` dataclass, `REGISTRY`, `SemanticScholar`, `Crossref` (see file).
- [ ] Steps 2/4/5; commit.

### Task 5: PubMed and medRxiv/bioRxiv

- [ ] Tests: `test_pubmed_esearch_then_efetch_parses_ids_and_abstracts`, `test_pubmed_sends_tool_email_and_dates`,
  `test_pubmed_key_goes_to_params_and_raises_bucket`, `test_pubmed_empty_result_makes_no_efetch`,
  `test_preprints_append_the_server_filter_and_years`, `test_preprints_name_their_source`.
- [ ] Implement `PubMed` (esearch JSON → efetch XML; only `PubmedData/ArticleIdList`) and `Preprints(EuropePMC)`;
  commit.

### Task 6: CORE, IEEE Xplore, Springer Nature, Scopus

- [ ] Tests: `test_<source>_parses_fixture`, `test_<source>_sends_query_years_and_key` (header for CORE/Scopus,
  param for IEEE/Springer), `test_key_required_sources_raise_before_any_request[core|ieee|springer|scopus]`,
  `test_scopus_empty_result_entry_is_zero_papers`, `test_scopus_insttoken_header_is_optional`,
  `test_springer_and_core_page_up_to_max_results`, `test_provenance_urls_never_contain_keys`.
- [ ] Implement; commit.

### Task 7: Wiring — domain_connector, OpenAlex key, runner message, demo

- [ ] Tests: `test_domain_connector_builds_every_new_live_source`,
  `test_domain_connector_demo_covers_every_source`, `test_run_with_missing_key_fails_in_discover_naming_the_variable`
  (live run with a stub connector list, no network: `progress.json` message), `test_openalex_key_param_optional`.
- [ ] Implement `sources.make_connector(source, domain, store, mode)`; `domain_connector` delegates; runner uses
  `exc.message`; commit.

### Task 8: Identity — cross-id dedup and Crossref enrichment

**Files:** `connectors.py` (`paper_ids`, `deduplicate`), `sources.py` (`CrossrefEnricher`), `storage.py`
(`lookups`), `graph.py` (`normalize` hook); `tests/test_identity.py`.

- [ ] Tests: `test_dois_are_normalized_before_matching`, `test_pubmed_and_europepmc_merge_by_pmid`,
  `test_s2_and_arxiv_merge_by_arxiv_id`, `test_pmcid_merges`, `test_conflicting_dois_never_merge_by_cross_id`,
  `test_merged_paper_keeps_every_id`, `test_enricher_fills_doi_on_exact_title_and_year`,
  `test_enricher_rejects_near_titles_and_other_years`, `test_enricher_is_bounded_to_50_lookups`,
  `test_enricher_caches_lookups`, `test_normalize_enriches_only_with_crossref_in_live_mode`,
  existing dedup tests unchanged.
- [ ] Implement; commit.

### Task 9: Full-text resolvers and text_licence

**Files:** `fulltext.py`, `tests/test_sources_fulltext.py`; fixtures listed above.

- [ ] Tests: `test_default_order_constant`, `test_resolve_records_text_licence_for_every_path`,
  `test_pmc_oa_licence_from_jats`, `test_europepmc_resolver_uses_oa_pdf_links_and_skips_pmc`,
  `test_core_uses_full_text_then_pdf`, `test_springer_oa_parses_jats_and_licence`,
  `test_s2_oa_downloads_open_access_pdf`, `test_ieee_only_open_access`,
  `test_sciencedirect_only_when_entitled`, `test_sciencedirect_without_original_text_is_unavailable`,
  `test_missing_keys_make_resolvers_unavailable_with_the_variable_name`, `test_cached_entries_without_licence`.
- [ ] Implement; commit.

### Task 10: Secret sentinel and docs

- [ ] `tests/test_secrets.py::test_no_key_value_reaches_the_store_or_errors` — sets every key env var to a
  sentinel, runs every connector and resolver against MockTransport (including failures), then greps every
  table of `research.sqlite` and every exception string for the sentinel.
- [ ] `docs/architecture.md`: sources, rate limits, env vars. Commit.

## Self-review

- Spec coverage: rate limiter/UA/Retry-After/timeouts (T1), connectors (T4–T7), querybuild (T3), resolvers +
  licence (T9), identity/dedup/enrichment (T8), key-missing (T1, T6, T7), demo (T7), no-network fixtures (all),
  sentinel (T10). UI/API items belong to Plan 2 (column width, registry endpoint, settings).
- Names used consistently: `SourceKeyMissing`, `env_key`, `limiter`, `REGISTRY`, `make_connector`,
  `CrossrefEnricher`, `text_licence`, `DEFAULT_ORDER`.
