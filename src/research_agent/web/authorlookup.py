"""Worker job `author_lookup` (topic editor, Researcher tab). Two steps, both by code (no model):

- `search`: OpenAlex author search for a typed name. Candidates {openalex_id, name, orcid, works_count,
  institution, concepts}; a human picks one, or several when OpenAlex split one person.
- `group`: for the picked people, their OpenAlex works: co-authors with the number of shared works (the
  editor checks those with >= min_shared), the institutions they worked at, and each person's Semantic
  Scholar id when an ORCID maps to one (a Semantic Scholar author on one of their works with that ORCID).

Demo mode answers deterministic stubs (no network). Network failures of the OpenAlex calls raise
SourceUnavailable (the job fails with a safe message); the Semantic Scholar mapping is best effort."""

import hashlib
import logging
from collections import Counter

from ..connectors import (
    SourceUnavailable,
    env_key,
    fetch,
    normalize_doi,
    normalize_name,
    normalize_orcid,
    openalex_author_id,
)

log = logging.getLogger(__name__)

AUTHORS_URL = "https://api.openalex.org/authors"
WORKS_URL = "https://api.openalex.org/works"
S2_PAPER = "https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
CANDIDATES = 10
MAX_WORKS = 1000  # works read per lookup (5 pages of 200)
MAX_COAUTHORS = 100  # listed in the checklist, most shared works first
S2_PROBES = 3  # works whose Semantic Scholar authors are checked for the ORCID


def _institution_id(value):
    tail = (value or "").rstrip("/").rsplit("/", 1)[-1]
    return tail.upper() if tail[:1].upper() == "I" and tail[1:].isdigit() else ""


def _openalex(client, url, params, contact):
    if contact:
        params = {**params, "mailto": contact}
    key = env_key("OPENALEX_API_KEY")
    sent = {**params, "api_key": key} if key else params
    return fetch(
        client,
        url,
        sent,
        "openalex",
        lambda response: response.json(),
        secret=key is not None,
        contact=contact,
        keyed=key is not None,
    )


def candidate(row):
    """One OpenAlex author as the editor lists it."""
    institutions = row.get("last_known_institutions") or (
        [row["last_known_institution"]] if row.get("last_known_institution") else []
    )
    first = institutions[0] if institutions else None
    concepts = [t.get("display_name") for t in (row.get("topics") or row.get("x_concepts") or [])]
    return {
        "openalex_id": openalex_author_id(row.get("id")),
        "name": row.get("display_name") or "",
        "orcid": normalize_orcid(row.get("orcid")),
        "works_count": int(row.get("works_count") or 0),
        "institution": (
            {"openalex_id": _institution_id(first.get("id")), "name": first.get("display_name") or ""}
            if first
            else None
        ),
        "concepts": [c for c in concepts if c][:5],
    }


def search_candidates(name, *, client=None, contact=None):
    params = {
        "search": name,
        "per-page": CANDIDATES,
        "select": "id,display_name,orcid,works_count,last_known_institutions,topics",
    }
    payload = _openalex(client, AUTHORS_URL, params, contact)
    try:
        rows = payload["results"]
        return [c for c in (candidate(r) for r in rows) if c["openalex_id"] and c["name"]]
    except (KeyError, TypeError, AttributeError) as exc:
        raise SourceUnavailable("openalex") from exc


def person_works(ids, *, client=None, contact=None, limit=MAX_WORKS):
    """The works (id, doi, authorships) of these OpenAlex authors, newest first, cursor-paged."""
    works, cursor = [], "*"
    while cursor and len(works) < limit:
        params = {
            "filter": "authorships.author.id:" + "|".join(ids),
            "per-page": 200,
            "select": "id,doi,authorships",
            "sort": "publication_date:desc",
            "cursor": cursor,
        }
        payload = _openalex(client, WORKS_URL, params, contact)
        try:
            rows = payload["results"]
            cursor = (payload.get("meta") or {}).get("next_cursor")
        except (KeyError, TypeError, AttributeError) as exc:
            raise SourceUnavailable("openalex") from exc
        works.extend(rows)
        if not rows:
            break
    return works[:limit]


def coauthors_of(works, people_ids):
    """Co-authors of the people across `works`: [{openalex_id, orcid, name, shared}] by shared works (most
    first, then name), each work counted once per co-author; and the people's institutions
    [{openalex_id, name, works}] by works. People are recognised by OpenAlex id only."""
    people_ids = {i.upper() for i in people_ids}
    shared, names, orcids = Counter(), {}, {}
    institutions, inst_names = Counter(), {}
    for work in works:
        seen = set()
        for authorship in work.get("authorships") or []:
            author = authorship.get("author") or {}
            aid = openalex_author_id(author.get("id"))
            if not aid:
                continue
            if aid in people_ids:
                for inst in authorship.get("institutions") or []:
                    iid = _institution_id(inst.get("id"))
                    if iid and iid not in seen:
                        seen.add(iid)
                        institutions[iid] += 1
                        inst_names[iid] = inst.get("display_name") or iid
                continue
            if aid in seen:
                continue
            seen.add(aid)
            shared[aid] += 1
            names[aid] = author.get("display_name") or aid
            orcids[aid] = orcids.get(aid) or normalize_orcid(author.get("orcid"))
    coauthors = [
        {"openalex_id": aid, "orcid": orcids[aid], "name": names[aid], "shared": n}
        for aid, n in shared.items()
    ]
    coauthors.sort(key=lambda c: (-c["shared"], normalize_name(c["name"]), c["openalex_id"]))
    insts = [{"openalex_id": i, "name": inst_names[i], "works": n} for i, n in institutions.items()]
    insts.sort(key=lambda i: (-i["works"], i["name"]))
    return coauthors[:MAX_COAUTHORS], insts


def s2_id_for(orcid, dois, *, client=None):
    """The Semantic Scholar author id of the author with this ORCID on one of these works ("" when none is
    found). Best effort: a failing request is logged and skipped."""
    if not orcid:
        return ""
    key = env_key("S2_API_KEY")
    headers = {"x-api-key": key} if key else None
    for doi in dois[:S2_PROBES]:
        try:
            paper = fetch(
                client,
                S2_PAPER.format(doi=doi),
                {"fields": "authors.externalIds"},
                "semantic_scholar",
                lambda response: response.json(),
                headers=headers,
                secret=key is not None,
                keyed=key is not None,
            )
        except SourceUnavailable as exc:
            log.info("author lookup: Semantic Scholar %s failed (%s)", doi, exc.reason)
            continue
        for author in (paper or {}).get("authors") or []:
            ids = author.get("externalIds") or {}
            if normalize_orcid(ids.get("ORCID")) == orcid and author.get("authorId"):
                return str(author["authorId"])
    return ""


def group_for(people, *, client=None, contact=None):
    ids = [p["openalex_id"] for p in people if p.get("openalex_id")]
    if not ids:
        raise ValueError("pick at least one person with an OpenAlex id")
    works = person_works(ids, client=client, contact=contact)
    coauthors, institutions = coauthors_of(works, ids)
    dois = [normalize_doi(w["doi"]) for w in works if w.get("doi")]
    out_people = []
    for person in people:
        orcid = normalize_orcid(person.get("orcid"))
        out_people.append(
            {
                "openalex_id": person.get("openalex_id", ""),
                "name": person["name"],
                "orcid": orcid,
                "s2_id": person.get("s2_id") or s2_id_for(orcid, dois, client=client),
            }
        )
    return {"people": out_people, "works": len(works), "coauthors": coauthors, "institutions": institutions}


# ---------- demo stubs (deterministic, no network) ----------


def _demo_number(text, digits):
    return str(int(hashlib.sha256(text.encode()).hexdigest()[:12], 16))[:digits].rjust(digits, "0")


def demo_candidates(name):
    name = " ".join(name.split()) or "Demo Researcher"
    n = _demo_number(normalize_name(name), 8)
    return [
        {
            "openalex_id": f"A9{n}",
            "name": name,
            "orcid": f"0000-0002-{n[:4]}-{n[4:7]}X",
            "works_count": 42,
            "institution": {"openalex_id": "I9000000001", "name": "Synthetic Institute of Imaging"},
            "concepts": ["Medical imaging", "Deep learning"],
        },
        {
            "openalex_id": f"A8{n}",
            "name": name,
            "orcid": "",
            "works_count": 3,
            "institution": None,
            "concepts": ["Radiology"],
        },
    ]


def demo_group(people):
    return {
        "people": [
            {**p, "orcid": p.get("orcid", ""), "s2_id": p.get("s2_id") or ("9" + _demo_number(p["name"], 6))}
            for p in people
        ],
        "works": 42,
        "coauthors": [
            {
                "openalex_id": "A9100000001",
                "orcid": "0000-0001-0000-0001",
                "name": "Synthetic Coauthor One",
                "shared": 7,
            },
            {"openalex_id": "A9100000002", "orcid": "", "name": "Synthetic Coauthor Two", "shared": 3},
            {"openalex_id": "A9100000003", "orcid": "", "name": "Synthetic Coauthor Three", "shared": 1},
        ],
        "institutions": [
            {"openalex_id": "I9000000001", "name": "Synthetic Institute of Imaging", "works": 30}
        ],
    }


def author_lookup(payload, *, client=None, contact=None):
    """payload {"step": "search", "name", "mode"} -> {"step", "candidates"};
    {"step": "group", "people": [{openalex_id, name, orcid?}], "mode"} -> {"step", "people", "works",
    "coauthors", "institutions"}."""
    step, demo = payload.get("step"), payload.get("mode") == "demo"
    if step == "search":
        name = " ".join(str(payload.get("name") or "").split())
        if not name:
            raise ValueError("type a name to search")
        found = demo_candidates(name) if demo else search_candidates(name, client=client, contact=contact)
        return {"step": "search", "name": name, "candidates": found}
    if step == "group":
        people = payload.get("people") or []
        result = demo_group(people) if demo else group_for(people, client=client, contact=contact)
        return {"step": "group", **result}
    raise ValueError("unknown author lookup step")
