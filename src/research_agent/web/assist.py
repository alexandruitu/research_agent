"""Worker side of the field assist: one cached model call that suggests keywords, synonyms and criteria.

Runs only in the worker (the process that holds the keys). Calls are cached in a persistent store under
RESEARCH_CACHE_DIR/assist, so the same draft never costs twice; demo mode is deterministic and offline."""

from ..agents import Evaluator
from ..schemas import FieldSuggestions

ROLE = "assist"


def assist_model(env):
    """RESEARCH_ASSIST_MODEL, else RESEARCH_MODEL (e.g. "anthropic:claude-haiku-..."), else None."""
    return env.get("RESEARCH_ASSIST_MODEL") or env.get("RESEARCH_MODEL") or None


def assist_payload(draft):
    keywords = draft.get("keywords") or {}
    return {
        "description": (draft.get("description") or "").strip(),
        "topic": (draft.get("topic") or "").strip(),
        "keywords": {g: list(keywords.get(g) or []) for g in ("all", "any", "none")},
    }


def field_assist(draft, store, *, mode="live", model=None):
    """The job result: {"mode", "model", "suggestions": FieldSuggestions as a dict}."""
    if mode == "live" and not model:
        raise ValueError("Set RESEARCH_ASSIST_MODEL or RESEARCH_MODEL in the worker")
    evaluator = Evaluator(store, mode, {ROLE: model} if mode == "live" else {})
    suggestions = evaluator.ask(ROLE, FieldSuggestions, assist_payload(draft))
    return {"mode": mode, "model": evaluator.model_for(ROLE), "suggestions": suggestions.model_dump()}
