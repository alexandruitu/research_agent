# Milestone 1 verification — 12 September 2026

- Python 3.12, dependencies installed and actually imported.
- 12 pytest tests passed; Ruff check passed.
- Demo CLI: 12 synthetic candidates, stop after `extract`, resume in a separate process,
  12 adjudications and 10 results in the report. The report can be regenerated with `--resume`.
- Reviewer B failure test: checkpoint kept; resuming does not repeat reviewer A.
- Tests for deduplication/provenance, conflicting DOIs and ambiguous matching,
  nonexistent quotes, invalid output, agreement/disagreement, uncertain verdict, missing abstract,
  empty results, HTTP errors and the model adapter cache.
- Live Europe PMC smoke test: 3 public records retrieved, all with an abstract.
  Snapshot: `examples/live-connector/retrieved.json`; source payload: the accompanying SQLite database.
  This snapshot does not represent evaluated papers or a scientific top list.
- No run with external LLM models was executed. The live adapter test uses
  a substitute model; keys and model IDs must be configured before live verification.

`requirements.lock.txt` keeps the versions installed in the tested environment. To reproduce:

```sh
pip install -r requirements.lock.txt
pip install --no-deps -e .
pytest -q
```

The demo manifest and the included SQLite databases are sample data. For new experiments,
use a new run directory, as described in the README.

## Interface — verification 14 September 2026

18 tests passed, including rendering of the Streamlit interface, ranking filtering,
form validation, worker launch, blocking of duplicate launches and persistent
progress. Keys are excluded from process arguments and from configuration files;
provider error messages are filtered before display.

Verified in the browser: the results page, the new research form, launching a
12-candidate demo, pausing after evidence extraction and resuming from the interface.
The light theme is set by the launcher for readable contrast.
