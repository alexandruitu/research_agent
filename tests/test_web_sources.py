"""Sources from the registry: metadata, key status from the worker, key-gated enabling, checks for every source."""

from datetime import UTC, datetime

from research_agent.sources import REGISTRY
from research_agent.web.db.models import SourceRow

API = "/api/v1"


def by_name(client):
    return {r["name"]: r for r in client.get(f"{API}/sources").json()}


def test_sources_carry_registry_metadata_and_the_key_status(sign_in, db):
    viewer, _ = sign_in("viewer")
    rows = by_name(viewer)
    ieee = rows["ieee"]
    assert ieee["label"] == "IEEE Xplore" and ieee["group"] == "publishers" and ieee["auth"] == "required"
    assert ieee["env"] == ["IEEE_API_KEY"] and "search" in ieee["capabilities"] and ieee["covers"]
    assert ieee["key_present"] is False and ieee["key_accepted"] is None and ieee["key_checked_at"] is None
    assert rows["scopus"]["env"] == ["ELSEVIER_API_KEY", "ELSEVIER_INSTTOKEN"]
    assert rows["unpaywall"]["capabilities"] == ["fulltext"]
    pubmed = rows["pubmed"]
    assert pubmed["rps"] == REGISTRY["pubmed"].rps == pubmed["rps_in_use"] == 3
    row = db.get(SourceRow, "pubmed")
    row.key_present, row.key_accepted, row.key_detail = True, True, "accepted"
    row.key_checked_at = datetime.now(UTC)
    db.commit()
    pubmed = by_name(viewer)["pubmed"]
    assert pubmed["key_present"] is True and pubmed["key_accepted"] is True and pubmed["key_checked_at"]
    assert pubmed["rps_in_use"] == REGISTRY["pubmed"].rps_keyed == 10


def test_enabling_a_source_whose_required_key_is_missing_is_refused(sign_in, db):
    admin, csrf = sign_in("admin")
    r = admin.patch(f"{API}/sources/ieee", json={"enabled": True}, headers=csrf)
    assert r.status_code == 422 and r.json()["code"] == "key_missing"
    assert "Set IEEE_API_KEY in the worker environment first" in r.json()["message"]
    assert admin.patch(f"{API}/sources/ieee", json={"max_results": 50}, headers=csrf).status_code == 200
    for name in ("pubmed", "crossref", "semantic_scholar"):  # optional or no key
        assert admin.patch(f"{API}/sources/{name}", json={"enabled": True}, headers=csrf).status_code == 200
    row = db.get(SourceRow, "ieee")
    row.key_present = True
    db.commit()
    r = admin.patch(f"{API}/sources/ieee", json={"enabled": True}, headers=csrf)
    assert r.status_code == 200 and r.json()["enabled"] is True
    assert admin.patch(f"{API}/sources/ieee", json={"enabled": False}, headers=csrf).json()["enabled"] is False


def test_a_source_without_search_has_no_connection_test(sign_in):
    admin, csrf = sign_in("admin")
    for name in ("unpaywall", "sciencedirect"):
        r = admin.post(f"{API}/sources/{name}/check", headers=csrf)
        assert r.status_code == 422 and r.json()["code"] == "not_searchable"
