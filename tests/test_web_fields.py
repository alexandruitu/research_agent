"""Fields: create, versions with optimistic concurrency, archive rules and roles."""

import pytest

API = "/api/v1"
DRAFT = {
    "name": "ML CT-FFR",
    "topic": "machine learning estimation of CT-derived fractional flow reserve",
    "include": [{"text": "The study uses machine learning."}, {"text": "The study reports CT-FFR."}],
    "exclude": [{"text": "The paper is a review without original results."}],
    "sources": ["europepmc", "openalex"],
    "years": {"from": 2018, "to": None},
    "note": "first draft",
}


def create(client, csrf, **overrides):
    return client.post(f"{API}/fields", json={**DRAFT, **overrides}, headers=csrf)


def save(client, csrf, field_id, base, **overrides):
    body = {**DRAFT, "base_version": base, **overrides}
    return client.post(f"{API}/fields/{field_id}/versions", json=body, headers=csrf)


def test_member_creates_a_field_with_generated_keys(sign_in):
    member, csrf = sign_in("member")
    r = create(member, csrf)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["current_version"] == 1 and body["archived_at"] is None
    assert [(c["key"], c["kind"]) for c in body["criteria"]] == [
        ("i1", "include"),
        ("i2", "include"),
        ("e1", "exclude"),
    ]
    current = body["current"]
    assert current["include"] == [
        {"key": "i1", "text": "The study uses machine learning."},
        {"key": "i2", "text": "The study reports CT-FFR."},
    ]
    assert current["sources"] == ["europepmc", "openalex"] and current["years"] == {"from": 2018, "to": None}
    assert current["note"] == "first draft" and current["created_by_name"] == "Member"
    assert current["imported"] is False and current["run_count"] == 0
    assert [v["version"] for v in body["versions"]] == [1]


def test_each_save_is_a_new_version_and_old_versions_stay(sign_in):
    member, csrf = sign_in("member")
    field_id = create(member, csrf).json()["id"]
    r = save(member, csrf, field_id, 1, include=[{"text": "Deep learning only."}], note="narrower")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["current_version"] == 2 and body["current"]["include"] == [
        {"key": "i1", "text": "Deep learning only."}
    ]
    assert [(v["version"], v["note"], v["include_count"]) for v in body["versions"]] == [
        (2, "narrower", 1),
        (1, "first draft", 2),
    ]
    old = member.get(f"{API}/fields/{field_id}/versions/1").json()
    assert [c["text"] for c in old["include"]] == [
        "The study uses machine learning.",
        "The study reports CT-FFR.",
    ]
    assert member.get(f"{API}/fields/{field_id}/versions/3").status_code == 404


def test_a_stale_base_version_is_refused_and_nothing_is_written(sign_in):
    member, csrf = sign_in("member")
    field_id = create(member, csrf).json()["id"]
    assert save(member, csrf, field_id, 1).status_code == 201
    r = save(member, csrf, field_id, 1, name="Other")
    assert r.status_code == 409
    assert r.json()["code"] == "stale_version"
    assert r.json()["message"] == "This field changed since you opened it (now v2)"
    body = member.get(f"{API}/fields/{field_id}").json()
    assert body["current_version"] == 2 and body["name"] == "ML CT-FFR" and len(body["versions"]) == 2


def test_archive_is_for_admins_and_hides_the_field(sign_in):
    member, csrf = sign_in("member")
    admin, admin_csrf = sign_in("admin")
    field_id = create(member, csrf).json()["id"]
    assert member.post(f"{API}/fields/{field_id}/archive", headers=csrf).status_code == 403
    r = admin.post(f"{API}/fields/{field_id}/archive", headers=admin_csrf)
    assert r.status_code == 200 and r.json()["archived_at"]
    assert field_id not in {f["id"] for f in member.get(f"{API}/fields").json()}
    assert field_id in {f["id"] for f in member.get(f"{API}/fields?archived=true").json()}
    refused = save(member, csrf, field_id, 1)
    assert refused.status_code == 409 and refused.json()["code"] == "archived"
    assert admin.post(f"{API}/fields/{field_id}/unarchive", headers=admin_csrf).json()["archived_at"] is None
    assert save(member, csrf, field_id, 1).status_code == 201


def test_viewers_read_but_cannot_create(sign_in):
    viewer, csrf = sign_in("viewer")
    assert create(viewer, csrf).status_code == 403
    assert viewer.get(f"{API}/fields").status_code == 200


@pytest.mark.parametrize(
    "overrides",
    [
        {"include": [], "exclude": []},
        {"include": [{"text": "x" * 20}] * 11},
        {"include": [{"text": "x" * 501}]},
        {"include": [{"text": "ab"}]},
        {"include": [{"text": "two\nlines"}]},
        {"sources": ["scholar"]},
        {"sources": []},
        {"sources": ["arxiv", "arxiv"]},
        {"years": {"from": 2020, "to": 2019}},
        {"years": {"from": 1800}},
        {"name": ""},
        {"topic": "ab"},
        {"unknown": 1},
    ],
)
def test_invalid_drafts_are_refused(sign_in, overrides):
    member, csrf = sign_in("member")
    assert create(member, csrf, **overrides).status_code == 422


def test_criteria_text_is_stored_verbatim_as_plain_text(sign_in):
    member, csrf = sign_in("member")
    text = "<b>Uses</b> CNNs & transformers"
    body = create(member, csrf, include=[{"text": f"  {text} "}]).json()
    assert body["current"]["include"] == [{"key": "i1", "text": text}]


def test_legacy_fields_list_with_one_legacy_criterion(sign_in, imported):
    viewer, _ = sign_in("viewer")
    fields = {f["topic"]: f for f in viewer.get(f"{API}/fields").json()}
    legacy = fields["retrieval augmented generation"]
    assert legacy["current_version"] == 1
    assert [(c["key"], c["kind"]) for c in legacy["criteria"]] == [("topic_match", "legacy")]
    assert legacy["current"]["legacy"][0]["key"] == "topic_match" and legacy["current"]["include"] == []
    assert legacy["last_run"]["kind"] == "research" and legacy["last_run"]["field_version"] == 1
    assert legacy["current"]["run_count"] == 1
