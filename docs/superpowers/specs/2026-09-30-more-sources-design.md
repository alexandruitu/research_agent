# Professional source access: more platforms via official APIs (slice 5)

Date: 2026-09-30 · Status: approved (user: add all platforms from their list; no Google Scholar)

## Goal

Search and full-text access through **official APIs only**, with professional handling of credentials,
rate limits, polite identification, health, licences and cross-source identity.

Today: Europe PMC, OpenAlex, arXiv (search); PMC OA and Unpaywall (full text).

Add:

| Platform | Role | Credential (worker env only) |
|---|---|---|
| Semantic Scholar | search, citations, TLDR, OA PDF links | `S2_API_KEY` optional (higher rate) |
| Crossref | DOI canonicalization, metadata enrichment, dedup | none (polite mailto) |
| PubMed (NCBI E-utilities) | search incl. MeSH | `NCBI_API_KEY` optional (10 rps instead of 3) |
| medRxiv / bioRxiv | preprint search (via their API + date windows) and full-text links | none |
| CORE | search + OA full text | `CORE_API_KEY` required |
| IEEE Xplore | search (metadata/abstract); OA full text where licensed | `IEEE_API_KEY` required |
| Springer Nature | search; OA JATS full text | `SPRINGER_API_KEY` required |
| Scopus (Elsevier) | search (metadata/abstract) | `ELSEVIER_API_KEY` required (+ `ELSEVIER_INSTTOKEN` optional) |
| ScienceDirect (Elsevier) | full text where entitled (TDM) | same Elsevier key; entitlement checked per article |
| OpenAlex | existing; add optional `OPENALEX_API_KEY` | optional |

Google Scholar is **not** integrated (no official API; scraping violates its terms). The UI says so.

## Principles

- Keys live only in the worker's environment. The API never receives, stores or returns key values; it shows
  per source: `needs_key`, `key_present`, `key_accepted` (from a worker check), rate limit in use, last check.
- Every connector: official endpoint, polite identification (User-Agent with contact email, `mailto` where the
  API asks), a per-source **token-bucket rate limiter** shared by all worker threads, retries with backoff and
  `Retry-After` respect, timeouts, HTTP caching in `research.sqlite` (as today), fail-closed per source during a
  run (`SourceUnavailable`), per-source isolation in preview.
- A source whose required key is missing cannot be enabled (422 `key_missing`), and is shown with the exact
  variable name to set.
- Licensed full text (IEEE, Springer non-OA, ScienceDirect) is used only when the API itself grants access for
  that article; licence/terms metadata is stored with the text (`text_licence`), and texts from licensed
  sources are never exported by the library export.
- Query building (`querybuild`) extends to every new source with its own syntax; overrides per source.
- **Identity**: DOI normalized; papers without DOI get Crossref lookup by title+year (bounded, cached);
  dedup merges by DOI, then PMID/PMCID/arXiv id cross-references, then normalized title+year.

## Full-text resolution order (configurable in Settings → Full text)

`pmc_oa → europepmc → core → springer_oa → semantic_scholar_oa → unpaywall → ieee → sciencedirect → upload`,
each skipped if disabled or not entitled; the first successful text wins; reasons recorded per attempt.

## Web

- Settings → Sources: grouped (Biomedical, Preprints, Multidisciplinary, Publishers/licensed, Identity),
  each row: what it covers, auth status, "Enable", max results, rate limit, Test; licensed rows explain what
  is needed. Settings → Full text: ordered, toggleable resolver list (drag or up/down).
- Fields editor: source picker grouped the same way; query preview per source (existing step 2/3 extended).
- Paper rows "Found by" list new sources; drawer shows text source and licence.

## Testing

Each connector against recorded fixtures (no network in tests), including rate-limit/Retry-After handling,
pagination caps, error mapping; querybuild table tests per new source; Crossref identity enrichment; dedup by
cross-ids; key status never leaks values (sentinel test); UI tests for grouped sources, key-missing states and
resolver ordering; Playwright smoke with demo connectors.

## Plans

1. Pipeline: rate limiter + polite HTTP base, connectors (S2, Crossref, PubMed, medRxiv/bioRxiv, CORE, IEEE,
   Springer, Scopus), full-text resolvers (CORE, Springer OA, S2 OA, IEEE, ScienceDirect), identity/dedup,
   querybuild extensions.
2. Backend + frontend: source registry and key status, settings for resolver order, grouped Sources UI,
   field source picker, drawer licence, e2e.
