# Authors: stored, filterable, and searchable by researcher and group

Date: 2026-10-12 · Status: approved (user: all three steps; co-authors as the default group)

## Principle

Disambiguation is done by **identifiers** (ORCID, OpenAlex author id) and by a **human choosing among
candidates**, never by an AI. A match by name only is always labelled "name match" in the UI.

## Step 1: Store authors

- **Paper schema** (pipeline): `authors: [{name, orcid?, openalex_id?, affiliations: [str], position}]`.
  - Connectors that return authors fill it: OpenAlex (authorships with id, ORCID and institutions), Semantic
    Scholar (authorId, name), PubMed/Europe PMC (authorList, with ORCID when present), Crossref (author with
    ORCID), arXiv (names only).
  - Dedup merges authors from duplicate records and prefers the richer record.
- **Web DB:** migration with tables `authors` (id, name, normalized_name, orcid unique nullable, openalex_id
  unique nullable) and `paper_authors` (paper_id, author_id, position, affiliations JSON).
  - The importer stores authors when it imports a run.
  - An existing author is matched by ORCID, then by OpenAlex id. Name-only authors are never merged with an
    identified author.
- **Backfill:** worker job `authors_backfill` (admin, from Settings → Sources). It looks up papers that have a
  DOI and no authors in OpenAlex, rate-limited, with progress and a summary.
- **Display:** authors appear in Results rows (first 3, then "et al."), in the drawer, in the Reader header and
  in Library items. ORCID links open externally.

## Step 2: Filter by author (Results and Library)

- An "Author" filter with typeahead over the authors already stored, showing name, ORCID/OpenAlex badge and
  paper count.
- Selecting an identified author filters by author id. Free text filters by normalized name and shows a "name
  match — may include other people with this name" note.
- The filter is in the URL (shareable), works with the existing filters and grouping, and has API support on
  the papers and library list endpoints (`author_id` or `author_name`).

## Step 3: Search a researcher and their group (new topic kind)

- **Topic editor:** a new "Researcher" tab beside the keyword search.
  1. **Find the person.** Type a name, then a worker job `author_lookup` calls the OpenAlex author search and
     lists candidates: name, last known institution, works count, ORCID, top concepts. The user picks one, or
     several if OpenAlex split the same person.
  2. **Group** (default: frequent co-authors):
     - Co-authors: those with ≥ N shared works (default 3), computed by code from the person's OpenAlex works.
       They appear as a checklist the user can edit.
     - Option: the person's institution(s), labelled "much broader".
     - Option: the person only.
  3. **Optional topic restriction:** keywords or a topic, as today. Without one, every paper by the group in
     the year range is in scope.
- **Saved in the topic version:** `authors: {people: [{openalex_id, orcid?, name}], group: coauthors|institution|person, coauthors: [...], institutions: [...], min_shared}`.
- **Search:**
  - OpenAlex: filter by `authorships.author.id` (or institution id), plus the keyword query when given.
  - Semantic Scholar: by author id when known (mapped through ORCID), else skipped with a warning.
  - PubMed/Europe PMC: by ORCID where available, else by name with an `[au]`/`AUTH:` query, marked as name
    match.
  - Other sources: skipped for author search, with a visible note.
- **Screening:**
  - With a topic restriction: the normal criteria.
  - Without one: screening checks only that a paper is a research article (not an erratum or editorial). The
    rest of the pipeline is unchanged.
- **Results:** a "Matched by" chip per paper: the person / co-author X / institution / name match.

## Tests (targeted)

- Connector author parsing per source, using fixtures.
- Dedup merge.
- The importer, and the identifier-based merge.
- Backfill with a stub OpenAlex.
- Filter API by id and by name.
- Typeahead.
- Author lookup job, co-author computation (min shared), and the query each source receives.
- The topic version round-trip.
- "Matched by" in Results.
- UI vitest.
- One e2e in demo mode with a stubbed lookup.
