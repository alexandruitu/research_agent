# Reader and Validation section (slice 10)

Date: 2026-10-11 · Status: approved (user: "let's build in the above order")

## Goal

Separate the two audiences:

- **Researchers** browse, read and understand papers.
- **Validators** check that the pipeline is correct.

Give researchers a **Reader** to study one paper with grounded AI help. In-house search and "implement this
concept" are deferred: the user will propose an internal collection.

## Step 1: Navigation split

- **Main nav (researchers):** Fields · Papers · Library · Alerts · Runs.
- **New "Validation" section** (one nav entry, with sub-tabs):
  - **Evals:** moved as is.
  - **System map:** moved as is.
  - **How it works:** the content of `docs/agents.md` (flow, anatomy of one agent, example skill) and
    `docs/architecture.md`, rendered in the app as static pages. No inline styles or HTML injection: build
    the content as React components or render Markdown with a safe renderer that is already a dependency, if
    there is one.
- **Old URLs** redirect to their new place.
- **Trust link:** Papers and the Reader show a small "How do we know this is right? →" link to Validation.

## Step 2: Reader v1

Route: `/read/:runId/:paperId`, opened from:

- the paper drawer ("Read the paper");
- a digest item in Alerts;
- a library item.

### Layout

- **Left: the text.**
  - The full text when we have it (stored full text, or an uploaded PDF's extracted text), split into
    sections.
  - Otherwise the abstract, with an honest banner: "Abstract only — upload the PDF to read and ask about
    the full paper".
  - Reviewer red-flag quotes and claim quotes are highlighted in place. Hovering one shows which reviewer
    or claim it came from.
- **Right: the tools panel.**
  - Run context first: quality group, why, red flags, team status.
  - Then the AI tools, which act on the current selection (or the whole paper when nothing is selected):
    - **Explain (from the paper):** explains the selected passage using only the paper's text. Every
      statement carries an exact quote, checked by code (`validate_evidence` style); the answer fails
      closed (retry, then an error shown) if quotes do not match.
    - **Ask:** a free question about the paper. Same grounding and quote rule; "the paper does not say" is
      a valid answer.
    - **Background explanation:** explains a concept in general terms, clearly labelled "General
      knowledge — not from this paper, verify before relying on it". No quote rule, and no paper text
      beyond the selection.
  - Later (step 3, same panel): **Find related**, **Earlier work**.
  - Disabled, with an explanation: **In-house** ("needs an internal collection — coming").
- **Notes.** Every answer can be saved as a note on the paper: highlight + question + answer + quotes +
  model + date.
  - Stored per paper, with `reader_notes` linked to the paper (and to the library item when one exists).
  - Visible in the Library item and in the Reader.
  - If the paper is not in the library, saving a note offers to save it there.

### Calls

- New worker job kind `reader_ask`: payload {run_id, paper_id, tool: explain|ask|background, selection,
  question}.
- The worker builds the prompt with the shared system rules and caches the call like every agent call
  (key = model, role, prompt version, input).
- Roles `reader_explain`, `reader_ask` and `reader_background` get their own instructions and output
  schemas:
  - explain/ask: {answer, statements: [{text, quote}], not_in_paper: bool};
  - background: {answer}.
- The model is configured as a new role in Settings → AI models (default: the screen model).
- The frontend polls the job (the existing pattern). Latency of a few seconds is acceptable in v1;
  streaming is a later decision.
- Text limits: the selection is at most 4,000 characters. Explain and ask get the paper text (full text,
  truncated to the existing max context the panel uses).
- Cost: the call is shown in the run's cost table under "reader". Cached repeats are free.

## Step 3: Find related and earlier work

- **Find related:**
  - Builds a short query from the selection with code (key terms, no AI), or with a cheap model call if
    code alone is too weak. Searches the enabled sources (max 10 results per source) plus the team
    library.
  - Lists the results: title, year, source, and "in library" / "seen in run X".
  - Runs as a worker job, `reader_related`.
- **Earlier work:** the same search, sorted by year ascending, with the paper's own year marked. The
  heading reads "Papers mentioning this before {year}". There is **no** novelty verdict, ever.

## Testing

- Nav and redirects.
- Validation pages render (axe).
- Reader:
  - full text vs abstract-only states;
  - highlight anchoring of red-flag quotes;
  - selection → tool → job → answer;
  - quote validation failing closed;
  - background is labelled;
  - notes save and appear in Library.
- Role guards: viewers read; members ask and save notes.
- One e2e in demo mode: open a paper → select text → Explain → save note.
- Targeted tests only (user preference).
