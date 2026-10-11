"""The Reader: one paper's text (by sections) with the run's quotes, and grounded AI help on it.

The text is the one the panel reviewed (from the run's call cache), else an uploaded PDF's extracted text, else
the abstract. `reader_ask` runs only in the worker (the process with the keys); its calls are cached under
RESEARCH_CACHE_DIR/reader/<run id>, so a repeated question costs nothing and the run's cost table lists them."""

import re

from sqlalchemy import select

from ..agents import (
    PAPER_MAP_PROMPT_VERSION,
    READER_PROMPT_VERSION,
    Evaluator,
    EvidenceQuoteError,
    PaperMapError,
    ReaderAnswerError,
)
from ..fulltext import FulltextUnavailable, assemble, pdf_sections
from ..schemas import BackgroundAnswer, PaperMap, ReaderAnswer
from ..storage import Store
from .callstore import CallStoreError, read_call, safe_folder
from .db.models import EvidenceClaim, PanelReport, PaperFile, PaperReview, RedFlag
from .uploads import blob_path

MAX_SELECTION = 4000
MAX_QUESTION = 1000
DEFAULT_MAX_CHARS = 60000
TOOLS = {"explain": "reader_explain", "ask": "reader_ask", "background": "reader_background"}
HEADING = re.compile(r"^## (.+)$", re.MULTILINE)


class ReaderFailed(ValueError):
    """Shown to the user as the job's error: clear, no internals."""


def split_content(content):
    """The assembled text ("## Title\\n\\ntext" blocks) back into sections."""
    marks = list(HEADING.finditer(content))
    sections = []
    head = content[: marks[0].start()] if marks else content
    if head.strip():
        sections.append({"title": "", "text": head.strip()})
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(content)
        body = content[mark.end() : end].strip()
        if body:
            sections.append({"title": mark.group(1).strip(), "text": body})
    return sections


def _reviewed_text(db, settings, run, review):
    """The exact text the panel reviewed, read from the run's call cache; None when unavailable."""
    if review is None or review.text_source == "abstract" or not run.folder:
        return None
    keys = db.scalars(
        select(PanelReport.call_key)
        .where(PanelReport.paper_review_id == review.id, PanelReport.call_key.is_not(None))
        .order_by(PanelReport.position)
    )
    for key in keys:
        try:
            folder = safe_folder(run.folder, [settings.runs_dir, settings.evals_dir])
            safe_folder(folder / "research.sqlite", [settings.runs_dir, settings.evals_dir])
            content = read_call(folder, key)["input"]["payload"]["text"]["content"]
        except (CallStoreError, KeyError, TypeError, OSError):
            continue
        if isinstance(content, str) and content.strip():
            return content
    return None


def _uploaded_text(db, settings, paper, max_chars):
    row = db.scalar(
        select(PaperFile)
        .where(PaperFile.paper_id == paper.id)
        .order_by(PaperFile.created_at.desc(), PaperFile.id)
        .limit(1)
    )
    if row is None:
        return None
    try:
        sections = pdf_sections(blob_path(settings.uploads_dir, row.sha256).read_bytes())
    except (FulltextUnavailable, OSError, ValueError):
        return None
    content, _kept, truncated = assemble(sections, max_chars)
    return (content, truncated) if content.strip() else None


def max_chars_of(db):
    from .review import current_settings

    return int((current_settings(db).fulltext or {}).get("max_chars") or DEFAULT_MAX_CHARS)


def paper_text(db, settings, run, paper):
    """{kind: full_text | abstract, source, licence, truncated, content, sections}. `content` is what the model
    reads and what quotes are checked against."""
    review = db.scalar(
        select(PaperReview).where(PaperReview.run_id == run.id, PaperReview.paper_id == paper.id)
    )
    reviewed = _reviewed_text(db, settings, run, review)
    if reviewed:
        return {
            "kind": "full_text",
            "source": review.text_source,
            "licence": review.text_licence,
            "truncated": bool(review.text_truncated),
            "content": reviewed,
            "sections": split_content(reviewed),
        }
    uploaded = _uploaded_text(db, settings, paper, max_chars_of(db))
    if uploaded:
        content, truncated = uploaded
        return {
            "kind": "full_text",
            "source": "upload",
            "licence": "user_upload",
            "truncated": truncated,
            "content": content,
            "sections": split_content(content),
        }
    abstract = paper.abstract or ""
    return {
        "kind": "abstract",
        "source": "abstract",
        "licence": "abstract",
        "truncated": False,
        "content": abstract,
        "sections": [{"title": "Abstract", "text": abstract}] if abstract.strip() else [],
    }


def highlights(db, run, paper):
    """The run's quotes to mark in the text: red-flag quotes (with reviewer and item) and claim quotes."""
    out = []
    review = db.scalar(
        select(PaperReview).where(PaperReview.run_id == run.id, PaperReview.paper_id == paper.id)
    )
    if review is not None:
        for flag in db.scalars(
            select(RedFlag).where(RedFlag.paper_review_id == review.id).order_by(RedFlag.position)
        ):
            for raised in flag.raised_by or []:
                quote = (raised.get("quote") or "").strip()
                if quote:
                    out.append(
                        {
                            "kind": "red_flag",
                            "quote": quote,
                            "label": flag.text,
                            "by": f"Reviewer {raised.get('reviewer') or '?'}, item {raised.get('item') or '?'}",
                        }
                    )
    for claim in db.scalars(
        select(EvidenceClaim)
        .where(EvidenceClaim.run_id == run.id, EvidenceClaim.paper_id == paper.id)
        .order_by(EvidenceClaim.created_at, EvidenceClaim.id)
    ):
        if claim.quote.strip():
            out.append(
                {"kind": "claim", "quote": claim.quote, "label": claim.statement, "by": "Extracted claim"}
            )
    return out


def run_mode(run):
    return ((run.manifest or {}).get("contract") or {}).get("mode") or "live"


def reader_model(db, env):
    """Settings → AI models → Reader, else the Screen model, else the worker's RESEARCH_MODEL; None: unset."""
    from .review import current_settings

    models = current_settings(db).models or {}
    return models.get("reader") or models.get("screen") or env.get("RESEARCH_MODEL") or None


def reader_payload(tool, text, selection, question):
    selection = (selection or "")[:MAX_SELECTION]
    question = (question or "")[:MAX_QUESTION]
    if tool == "background":  # no paper text beyond the selection
        return {"selection": selection, "question": question}
    return {"paper_text": text["content"], "selection": selection, "question": question}


def reader_ask(tool, text, selection, question, store, *, mode="live", model=None):
    """The job result: {tool, mode, model, prompt_version, answer, statements, not_in_paper, general}."""
    role = TOOLS[tool]
    if mode == "live" and not model:
        raise ReaderFailed("No model is set for the Reader: choose one in Settings → AI models")
    if tool != "background" and not text["content"].strip():
        raise ReaderFailed("This paper has no text to read: no abstract and no full text")
    schema = BackgroundAnswer if tool == "background" else ReaderAnswer
    evaluator = Evaluator(
        store, mode, {role: model} if mode == "live" else {}, prompt_version=READER_PROMPT_VERSION
    )
    try:
        result = evaluator.ask(role, schema, reader_payload(tool, text, selection, question))
    except (EvidenceQuoteError, ReaderAnswerError):
        raise ReaderFailed(
            "The answer's quotes did not match the paper's text after 3 attempts, so nothing was kept. "
            "Try again, or select a shorter passage."
        ) from None
    data = result.model_dump()
    return {
        "tool": tool,
        "mode": mode,
        "model": evaluator.model_for(role),
        "prompt_version": READER_PROMPT_VERSION,
        "answer": data["answer"],
        "statements": data.get("statements", []),
        "not_in_paper": bool(data.get("not_in_paper", False)),
        "general": tool == "background",
        "selection": (selection or "")[:MAX_SELECTION],
        "question": (question or "")[:MAX_QUESTION],
    }


def reader_store(settings, run_id):
    return Store(settings.cache_dir / "reader" / str(run_id))


MAP_TITLES = {
    "task": "Clinical task",
    "data": "Data",
    "method": "Method",
    "validation": "Validation",
    "results": "Results",
    "limitations": "Limitations",
}
DEMO_MODEL = "synthetic-demo-v1"


def build_map(title, text, store, *, mode="live", model=None):
    """The paper map of one paper (job `reader_map`): {mode, model, prompt_version, text_kind, branches}. Every
    node quote is checked against the same text the Reader shows (the abstract when there is no full text);
    a failure is retried, then fails closed with a clear error."""
    if mode == "live" and not model:
        raise ReaderFailed("No model is set for the Reader: choose one in Settings → AI models")
    if not text["content"].strip():
        raise ReaderFailed("This paper has no text to map: no abstract and no full text")
    evaluator = Evaluator(
        store, mode, {"paper_map": model} if mode == "live" else {}, prompt_version=PAPER_MAP_PROMPT_VERSION
    )
    try:
        result = evaluator.ask("paper_map", PaperMap, {"title": title or "", "paper_text": text["content"]})
    except (EvidenceQuoteError, PaperMapError, ValueError) as exc:
        if isinstance(exc, ReaderFailed):
            raise
        raise ReaderFailed(
            "The map's quotes or branches did not check out against the paper's text after 3 attempts, so "
            "nothing was kept. Try again."
        ) from None
    return {
        "mode": mode,
        "model": evaluator.model_for("paper_map"),
        "prompt_version": PAPER_MAP_PROMPT_VERSION,
        "text_kind": text["kind"],
        "branches": result.model_dump()["branches"],
    }


def map_red_flags(db, run, paper):
    """The "Reviewer red flags" branch: the run's red-flag quotes, added by code (no AI)."""
    return [
        {"label": h["label"], "quote": h["quote"], "by": h["by"]}
        for h in highlights(db, run, paper)
        if h["kind"] == "red_flag"
    ]


def current_map_model(db, env, run):
    """The model a map built now would use; None when it cannot be known here (no model set)."""
    return DEMO_MODEL if run_mode(run) == "demo" else reader_model(db, env)


def map_staleness(row, current_model):
    """Why a stored map is out of date (None: it is current): the map prompt or the Reader's model changed."""
    if row.prompt_version != PAPER_MAP_PROMPT_VERSION:
        return "prompt_version"
    if current_model and row.model != current_model:
        return "model"
    return None
