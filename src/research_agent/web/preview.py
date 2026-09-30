"""Worker side of the field preview: the draft's queries against its sources, ≤ 10 papers each, no model.

A failing source reports its error and the others still answer. Nothing is kept (a scratch store)."""

from ..connectors import SourceKeyMissing, SourceUnavailable
from ..schemas import Years
from .checks import connector
from .runner import sanitize_error

PREVIEW_LIMIT = 10


def field_preview(payload, store, *, http_client=None):
    """payload: {"mode", "years": {"from", "to"}, "sources": [{"name", "contact"?}], "queries": {name: q}}.
    Returns {"mode", "years", "sources": [{source, query, effective_query, count, papers, error}]}."""
    mode = payload.get("mode", "live")
    years = Years.model_validate(payload.get("years") or {})
    queries = payload.get("queries") or {}
    rows = []
    for source in payload.get("sources") or []:
        name, query = source["name"], queries.get(source["name"])
        row = {
            "source": name,
            "query": query,
            "effective_query": None,
            "count": None,
            "papers": [],
            "error": None,
        }
        if not query:
            rows.append(row | {"error": "no query for this source"})
            continue
        search = connector(
            name,
            store,
            mode=mode,
            years=years,
            contact=source.get("contact"),
            http_client=http_client,
            keywords=payload.get("keywords"),
        )
        try:
            result = search.search_with_total(query, PREVIEW_LIMIT, raw=True)
        except SourceKeyMissing as exc:
            rows.append(row | {"error": str(exc)})
            continue
        except SourceUnavailable as exc:
            rows.append(row | {"error": f"SourceUnavailable: {exc.source}"})
            continue
        except Exception as exc:  # noqa: BLE001 -- one source must not sink the preview; reported, sanitized
            rows.append(row | {"error": sanitize_error(exc)})
            continue
        papers = [{"id": p.id, "title": p.title, "year": p.year} for p in result.papers[:PREVIEW_LIMIT]]
        rows.append(row | {"effective_query": result.query, "count": result.total, "papers": papers})
    return {"mode": mode, "years": years.model_dump(mode="json"), "sources": rows}
