# Paper map (Reader tab)

Date: 2026-10-11 · Status: approved (user: "hai sa-l implementam")

## Goal

Give a visual, comparable summary of one AI-imaging paper. A **fixed schema** of branches; every node is an exact
quote from the paper, checked by code; a click on a node jumps to the passage in the text. Comparing several
maps side by side is planned for later, and the schema is designed for it now.

## Schema (fixed, same for every paper)

| Branch key | Title | What goes in |
|---|---|---|
| `task` | Clinical task | The clinical question or task, and the target condition |
| `data` | Data | Patients and images, centres, scanners or vendors, period, inclusion criteria |
| `method` | Method | Model or approach, input, reference standard (ground truth) |
| `validation` | Validation | How data were split (by patient or by image), internal vs external test, readers |
| `results` | Results | Main metrics with values and confidence intervals, comparison with baselines or readers |
| `limitations` | Limitations | Limitations the authors state |

- Each branch holds 0–5 nodes: `{label, quote}`. The label is at most 12 words in plain language; the quote is
  an exact span of the paper text.
- An empty branch has `not_reported: true` and is shown as **"Not reported"**. That is information, not a gap.
- **Red flags from the run** are added by code (no AI) under a separate "Reviewer red flags" branch, each with
  its reviewer quote.

## Generation

- New AI role `paper_map` (Reader prompt version, not the global one) and a pydantic schema.
- Worker job `reader_map`, payload `{reader_run_id, paper_id}`. Never `run_id`: a failing job carrying `run_id`
  marks the run failed.
- The model gets the same text the Reader shows, or the abstract when there is no full text. The map is then
  labelled "From the abstract only".
- **Validation:**
  - every node quote is snapped and checked against the text, as in Explain;
  - branch keys must be exactly the six;
  - at most 5 nodes per branch;
  - any failure is retried (3 attempts), then fails closed with a clear error.
- **Cache and storage:** cached like every call; the result is stored in table `paper_maps` (migration 0013),
  keyed by run, paper, prompt version and model. Viewers see a stored map; members build or rebuild one.
- **Demo mode:** a deterministic fake map, so e2e runs without keys.

## UI (Reader)

- A tab switch above the text column: **Text · Map**.
- **Map view:**
  - the paper title is the root, with the six branches plus "Reviewer red flags" around it;
  - layout: a radial or two-column tree in SVG or CSS grid (no canvas, no new heavy dependency unless already
    present). On narrow screens it falls back to a stacked outline;
  - each branch has a colour **and** a text title; a node shows its label;
  - hovering or focusing a node shows its quote in the side card style;
  - **clicking a node switches to Text and scrolls to the quote, highlighted for 2 s**.
- **States:**
  - no map yet: "Build the paper map" (member), with a cost line (one AI call);
  - building: progress;
  - failed: error message plus Retry;
  - stale (the prompt version changed): "Rebuild".
- **Accessibility:** the map is also an ordered outline for screen readers and keyboard. It is not
  colour-only. The SVG has role="img" plus the outline as the accessible equivalent.
- **Export:** "Copy as outline (Markdown)".

## Out of scope (later)

Comparing 2–5 maps branch by branch; a free-form concept map (background knowledge).

## Testing

- Schema and validation: the 6 keys, the node cap, quote snapping, the fail-closed retries.
- The job with a stub model; red flags added by code.
- Storage and staleness; role guards.
- Vitest: map states, the outline, a node click jumping to the text.
- An e2e step in `reader.spec.ts` (demo): build the map, then click a node and land on the text.
- Targeted tests only.
