"""Reviewers: versioned profiles; everyone reads, admins write; 409 on stale saves; archive rules."""

from research_agent.panel import DEFAULT_PANEL

API = "/api/v1"


def body(**changes):
    data = {
        "name": "Radiologist",
        "perspective": "You read the paper as a practising radiologist.",
        "model": None,
        "items": [
            {"text": "The imaging protocol is described.", "weight": 2, "source": "CLAIM 2020 #7"},
            {
                "key": "r9",
                "text": "Readers were blinded.",
                "red_flag_if": "no",
                "flag_text": " Readers not blinded ",
            },
            {"text": "Scanner vendors are named."},
        ],
        "note": "first",
    }
    return data | changes


def test_everyone_lists_the_seeded_panel_in_default_order(sign_in):
    viewer, _ = sign_in("viewer")
    rows = viewer.get(f"{API}/reviewers").json()
    assert [r["key"] for r in rows] == ["methodologist", "clinician", "statistician"]
    first = rows[0]
    assert first["in_default_panel"] is True and first["current_version"] == 1
    assert first["current"]["items"] == DEFAULT_PANEL[0]["items"]
    assert first["current"]["note"] == "default" and first["current"]["run_count"] == 0
    assert first["default"]["name"] == "Methodologist" and first["versions"] == []


def test_admin_creates_a_reviewer_with_generated_keys(sign_in):
    admin, csrf = sign_in("admin")
    member, member_csrf = sign_in("member")
    assert member.post(f"{API}/reviewers", json=body(), headers=member_csrf).status_code == 403
    assert admin.post(f"{API}/reviewers", json=body()).status_code == 403  # no CSRF
    r = admin.post(f"{API}/reviewers", json=body(), headers=csrf)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["key"] == "radiologist" and data["in_default_panel"] is False and data["default"] is None
    assert [i["key"] for i in data["current"]["items"]] == ["r1", "r9", "r2"]
    assert data["current"]["items"][0] == {
        "key": "r1",
        "text": "The imaging protocol is described.",
        "weight": 2,
        "source": "CLAIM 2020 #7",
        "pass_if": "yes",
        "red_flag_if": None,
        "flag_text": None,
    }
    assert data["current"]["items"][1]["flag_text"] == "Readers not blinded"
    assert data["current"]["created_by_name"] == "Admin"
    again = admin.post(f"{API}/reviewers", json=body(), headers=csrf).json()
    assert again["key"] == "radiologist_2"
    taken = admin.post(f"{API}/reviewers", json=body(key="radiologist"), headers=csrf)
    assert taken.status_code == 409 and taken.json()["code"] == "key_taken"


def test_invalid_reviewers_are_refused(sign_in):
    admin, csrf = sign_in("admin")
    item = {"text": "An item."}
    for bad in (
        body(items=[]),
        body(items=[item] * 21),
        body(items=[{"text": "x", "weight": 4}]),
        body(items=[{"key": "Bad", "text": "An item."}]),
        body(items=[{"key": "a1", "text": "One item."}, {"key": "a1", "text": "Two items."}]),
        body(perspective="short"),
        body(name="line\nbreak"),
        body(key="9lives"),
        body(extra=1),
        body(items=[{"text": "An item.", "flag_text": "x" * 201}]),
    ):
        assert admin.post(f"{API}/reviewers", json=bad, headers=csrf).status_code == 422, bad


def test_versions_with_optimistic_concurrency(sign_in):
    admin, csrf = sign_in("admin")
    viewer, _ = sign_in("viewer")
    save = body(name="Methodologist", base_version=1, note="tighter")
    r = admin.post(f"{API}/reviewers/methodologist/versions", json=save, headers=csrf)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["current_version"] == 2 and [v["version"] for v in data["versions"]] == [2, 1]
    assert data["versions"][0]["item_count"] == 3 and data["versions"][0]["note"] == "tighter"
    assert [i["key"] for i in data["current"]["items"]] == ["m1", "r9", "m2"]
    old = viewer.get(f"{API}/reviewers/methodologist/versions/1").json()
    assert old["items"] == DEFAULT_PANEL[0]["items"]
    stale = admin.post(f"{API}/reviewers/methodologist/versions", json=save, headers=csrf)
    assert stale.status_code == 409 and stale.json() == {
        "code": "stale_version",
        "message": "This reviewer changed since you opened it (now v2)",
        "request_id": stale.json()["request_id"],
    }
    assert viewer.get(f"{API}/reviewers/methodologist/versions/3").status_code == 404
    assert viewer.get(f"{API}/reviewers/nobody").status_code == 404
    assert viewer.get(f"{API}/reviewers/NOT-A-KEY").status_code == 404


def test_archive_rules(sign_in):
    admin, csrf = sign_in("admin")
    member, member_csrf = sign_in("member")
    busy = admin.post(f"{API}/reviewers/clinician/archive", headers=csrf)
    assert busy.status_code == 409 and busy.json()["code"] == "in_default_panel"
    key = admin.post(f"{API}/reviewers", json=body(), headers=csrf).json()["key"]
    assert member.post(f"{API}/reviewers/{key}/archive", headers=member_csrf).status_code == 403
    r = admin.post(f"{API}/reviewers/{key}/archive", headers=csrf)
    assert r.status_code == 200 and r.json()["archived_at"]
    assert key not in [x["key"] for x in admin.get(f"{API}/reviewers").json()]
    assert key in [x["key"] for x in admin.get(f"{API}/reviewers?archived=true").json()]
    archived = admin.post(f"{API}/reviewers/{key}/versions", json=body(base_version=1), headers=csrf)
    assert archived.status_code == 409 and archived.json()["code"] == "archived"
    assert admin.post(f"{API}/reviewers/{key}/restore", headers=csrf).json()["archived_at"] is None
