"""Worker-side checks: a source's connection, a field's criteria (Jev only), and the provider keys.

These run only in the worker (the process that holds the keys). Nothing here writes to the paper tables;
results go into the job's progress, the `sources` row, or `worker_status` (never a key value).
"""

import hashlib
import time

from ..connectors import ArXiv, DemoConnector, EuropePMC, OpenAlex, SourceUnavailable, deduplicate
from ..criteria import decide_jev
from ..jev import JevScreener
from ..schemas import DomainSpec
from .runner import sanitize_error

CHECK_QUERY = "deep learning"
TEST_LIMIT = 20  # papers per criteria test
DEMO_JEV = "demo-jev"


def connector(name, store, *, mode="live", years=None, contact=None, http_client=None):
    if mode == "demo":
        return DemoConnector(store, source=name)
    if name == "europepmc":
        return EuropePMC(store, client=http_client, years=years)
    if name == "openalex":
        return OpenAlex(store, client=http_client, years=years, contact=contact)
    if name == "arxiv":
        return ArXiv(store, client=http_client, years=years)
    raise ValueError(f"unknown source {name!r}")


def source_check(name, store, *, contact=None, http_client=None, clock=time.monotonic):
    """One search for one result. {"ok", "ms", "count", "error"}; the error is safe to show."""
    start = clock()
    try:
        papers = connector(name, store, contact=contact, http_client=http_client).search(CHECK_QUERY, 1)
    except SourceUnavailable as exc:
        return {
            "ok": False,
            "ms": round((clock() - start) * 1000),
            "count": 0,
            "error": f"SourceUnavailable: {exc.source}",
        }
    except Exception as exc:  # noqa: BLE001 -- reported, sanitized, on the source row
        return {"ok": False, "ms": round((clock() - start) * 1000), "count": 0, "error": sanitize_error(exc)}
    return {"ok": True, "ms": round((clock() - start) * 1000), "count": len(papers), "error": None}


def demo_probabilities(domain, paper):
    """Offline stand-in for Jev in demo mode: a stable number per (criterion, paper), no network."""
    keys = [c["key"] for kind in ("include", "exclude") for c in domain["criteria"][kind]]
    return {
        key: round(int(hashlib.sha256(f"{key}:{paper['id']}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF, 3)
        for key in keys
    }


def criteria_test(
    domain, store, *, mode="live", api_key=None, jev_client=None, http_client=None, progress=None
):
    """Search the field's sources (≤ 20 papers after dedup) and ask Jev every criterion of each paper.
    Returns the job result; the decision per paper is the pipeline's own rule (`decide_jev`)."""
    spec = DomainSpec.model_validate(domain)
    domain = spec.model_dump(mode="json")
    if mode == "live" and not api_key:
        raise ValueError("TYPESAFE_API_KEY is not set in the worker")
    found = []
    for source in spec.sources:
        search = connector(
            source.name, store, mode=mode, years=spec.years, contact=source.contact, http_client=http_client
        )
        found.extend(search.search(spec.topic, TEST_LIMIT))
    papers = deduplicate(found)[:TEST_LIMIT]
    jev = JevScreener(store, api_key, client=jev_client) if mode == "live" else None
    rows, versions = [], set()
    for n, paper in enumerate(papers, start=1):
        data = paper.model_dump()
        row = {
            "source_id": paper.id,
            "title": paper.title,
            "year": paper.year,
            "sources": list(getattr(paper, "sources", []) or []),
        }
        if not (paper.abstract or "").strip():
            row |= {"probabilities": {}, "decision": "not_screened", "decided_by": None}
        elif jev is None:
            probabilities = demo_probabilities(domain, data)
            decision, decided_by = decide_jev(probabilities, domain["criteria"], domain["thresholds"])
            row |= {"probabilities": probabilities, "decision": decision, "decided_by": decided_by}
            versions.add(DEMO_JEV)
        else:
            result = jev.screen_criteria(data, domain)
            row |= {
                "probabilities": result["probabilities"],
                "decision": result["decision"],
                "decided_by": result["decided_by"],
            }
            versions.add(result["model_version"])
        rows.append(row)
        if progress:
            progress({"status": "running", "done": n, "total": len(papers)})
    decisions = [r["decision"] for r in rows]
    return {
        "mode": mode,
        "topic": spec.topic,
        "criteria": [
            {"key": c["key"], "kind": kind, "text": c["text"]}
            for kind in ("include", "exclude")
            for c in domain["criteria"][kind]
        ],
        "sources": [s.name for s in spec.sources],
        "thresholds": domain["thresholds"],
        "model_version": ", ".join(sorted(versions)) or None,
        "papers": rows,
        "summary": {
            "total": len(rows),
            "kept": decisions.count("include"),
            "dropped": decisions.count("exclude"),
            "to_llm": decisions.count("escalate"),
            "not_screened": decisions.count("not_screened"),
        },
    }
