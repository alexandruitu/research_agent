"""Team library: saving (idempotent), snapshots, filters, edits with history, roles, collections."""

import uuid

from sqlalchemy import select

from research_agent.web.db.models import LibraryEvent, LibraryItem, Paper

API = "/api/v1"


def pid(db, source_id):
    return str(db.scalar(select(Paper.id).where(Paper.source_id == source_id)))


def save(client, csrf, run, papers, **extra):
    return client.post(
        f"{API}/library", json={"run_id": str(run), "paper_ids": papers, **extra}, headers=csrf
    )


def test_saving_papers_into_a_new_collection(sign_in, imported, db):
    member, csrf = sign_in("member")
    papers = [pid(db, "demo:1"), pid(db, "demo:2")]
    r = save(
        member,
        csrf,
        imported["research"],
        papers,
        new_collection={"name": "Stenosis", "description": "to discuss"},
        tags=["  Deep  Learning ", "ct"],
        note="read first",
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["created"]) == 2 and body["existing"] == []
    assert body["collection"]["name"] == "Stenosis" and body["collection"]["item_count"] == 2
    first = body["items"][0]
    assert first["paper"]["id"] == papers[0] and first["status"] == "to_read"
    assert first["tags"] == ["ct", "deep learning"] and first["note"] == "read first"
    assert [c["name"] for c in first["collections"]] == ["Stenosis"]
    assert first["run_id"] == str(imported["research"]) and first["added_by_name"] == "Member"
    assert first["field"]["name"] and first["can_delete"] is True
    assert first["score"] is not None  # the ranking score of this legacy run
    item = member.get(f"{API}/library/{first['id']}").json()
    snapshot = item["snapshot"]
    assert snapshot["schema"] == 1 and snapshot["paper"]["title"].startswith("SYNTHETIC DEMO")
    assert snapshot["paper"]["abstract"] and snapshot["screening"]["decision"]
    assert snapshot["run"]["id"] == str(imported["research"]) and snapshot["panel"] is None
    assert item["abstract"] == snapshot["paper"]["abstract"]
    assert [e["kind"] for e in item["events"]] == ["added"]
    assert item["events"][0]["detail"]["collections"] == ["Stenosis"]


def test_saving_again_merges_collections_and_tags_and_keeps_the_rest(sign_in, imported, db):
    member, csrf = sign_in("member")
    paper = pid(db, "demo:1")
    first = save(member, csrf, imported["research"], [paper], tags=["a"], new_collection={"name": "One"})
    item_id = first.json()["created"][0]
    member.patch(f"{API}/library/{item_id}", json={"status": "read"}, headers=csrf)
    two = member.post(f"{API}/library/collections", json={"name": "Two"}, headers=csrf).json()
    again = save(
        member,
        csrf,
        imported["research"],
        [paper, pid(db, "demo:3")],
        tags=["b", "A"],
        collection_ids=[two["id"]],
        status="relevant",
        note="ignored for existing items",
    )
    assert again.status_code == 201
    body = again.json()
    assert body["existing"] == [item_id] and len(body["created"]) == 1
    existing = body["items"][0]
    assert existing["status"] == "read" and existing["note"] == ""
    assert existing["tags"] == ["a", "b"] and [c["name"] for c in existing["collections"]] == ["One", "Two"]
    assert body["items"][1]["status"] == "relevant"
    unchanged = save(member, csrf, imported["research"], [paper], tags=["a"])
    assert unchanged.status_code == 200 and unchanged.json()["created"] == []
    kinds = [e["kind"] for e in member.get(f"{API}/library/{item_id}").json()["events"]]
    assert kinds == ["added", "status", "resaved"]  # the unchanged save recorded nothing


def test_save_refusals(sign_in, imported, db):
    member, csrf = sign_in("member")
    outside = save(member, csrf, imported["research"], [pid(db, "MED:1")])  # an eval paper
    assert outside.status_code == 422 and outside.json()["code"] == "not_in_run"
    assert save(member, csrf, uuid.uuid4(), [pid(db, "demo:1")]).status_code == 404
    unknown = save(
        member, csrf, imported["research"], [pid(db, "demo:1")], collection_ids=[str(uuid.uuid4())]
    )
    assert unknown.status_code == 422 and unknown.json()["code"] == "unknown_collection"
    assert save(member, csrf, imported["research"], [pid(db, "demo:1")], tags=["x" * 51]).status_code == 422
    assert save(member, csrf, imported["research"], []).status_code == 422
    assert db.scalar(select(LibraryItem)) is None  # nothing half-saved
    viewer, vcsrf = sign_in("viewer")
    assert save(viewer, vcsrf, imported["research"], [pid(db, "demo:1")]).status_code == 403


def test_archived_collections_take_no_new_items(sign_in, imported, db):
    member, csrf = sign_in("member")
    admin, acsrf = sign_in("admin")
    c = member.post(f"{API}/library/collections", json={"name": "Old"}, headers=csrf).json()
    assert member.post(f"{API}/library/collections/{c['id']}/archive", headers=csrf).status_code == 403
    assert admin.post(f"{API}/library/collections/{c['id']}/archive", headers=acsrf).json()["archived_at"]
    r = save(member, csrf, imported["research"], [pid(db, "demo:1")], collection_ids=[c["id"]])
    assert r.status_code == 422 and r.json()["code"] == "archived_collection"
    assert [x["name"] for x in member.get(f"{API}/library/collections").json()] == []
    assert [x["name"] for x in member.get(f"{API}/library/collections?archived=true").json()] == ["Old"]
    restored = admin.post(f"{API}/library/collections/{c['id']}/restore", headers=acsrf).json()
    assert restored["archived_at"] is None


def test_collections_names_are_unique_and_renamable(sign_in):
    member, csrf = sign_in("member")
    a = member.post(f"{API}/library/collections", json={"name": "Stenosis"}, headers=csrf)
    assert a.status_code == 201
    dup = member.post(f"{API}/library/collections", json={"name": " stenosis "}, headers=csrf)
    assert dup.status_code == 409 and dup.json()["code"] == "name_taken"
    b = member.post(f"{API}/library/collections", json={"name": "FFR"}, headers=csrf).json()
    clash = member.patch(f"{API}/library/collections/{b['id']}", json={"name": "STENOSIS"}, headers=csrf)
    assert clash.status_code == 409
    renamed = member.patch(
        f"{API}/library/collections/{b['id']}", json={"name": "CT-FFR", "description": "d"}, headers=csrf
    ).json()
    assert renamed["name"] == "CT-FFR" and renamed["description"] == "d"
    assert member.patch(f"{API}/library/collections/{uuid.uuid4()}", json={}, headers=csrf).status_code == 404


def test_patch_records_history(sign_in, imported, db):
    member, csrf = sign_in("member")
    c = member.post(f"{API}/library/collections", json={"name": "C"}, headers=csrf).json()
    item_id = save(member, csrf, imported["research"], [pid(db, "demo:1")], tags=["x"]).json()["created"][0]
    r = member.patch(
        f"{API}/library/{item_id}",
        json={"status": "relevant", "note": "key paper", "tags": ["y"], "collection_ids": [c["id"]]},
        headers=csrf,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "relevant" and body["note"] == "key paper" and body["tags"] == ["y"]
    events = {e["kind"]: e["detail"] for e in body["events"]}
    assert events["status"] == {"from": "to_read", "to": "relevant"}
    assert events["tags"] == {"added": ["y"], "removed": ["x"]}
    assert events["collections"] == {"added": ["C"], "removed": []}
    assert events["note"]["to"] == "key paper"
    assert member.patch(f"{API}/library/{item_id}", json={"status": "done"}, headers=csrf).status_code == 422
    assert member.patch(f"{API}/library/{uuid.uuid4()}", json={}, headers=csrf).status_code == 404


def test_delete_is_for_the_adder_or_an_admin(app, sign_in, imported, db):
    from research_agent.web.auth import create_user

    create_user(db, email="other@example.org", name="Other", role="member", password="correct horse battery")
    db.commit()
    member, csrf = sign_in("member")
    first, second = (
        save(member, csrf, imported["research"], [pid(db, f"demo:{n}")]).json()["created"][0] for n in (1, 2)
    )
    from fastapi.testclient import TestClient

    other = TestClient(app)
    login = other.post(
        f"{API}/auth/login", json={"email": "other@example.org", "password": "correct horse battery"}
    )
    ocsrf = {"X-CSRF-Token": login.json()["csrf_token"]}
    listed = other.get(f"{API}/library").json()["items"]
    assert all(i["can_delete"] is False for i in listed)
    denied = other.delete(f"{API}/library/{first}", headers=ocsrf)
    assert denied.status_code == 403 and denied.json()["code"] == "not_owner"
    assert member.delete(f"{API}/library/{first}", headers=csrf).status_code == 204
    admin, acsrf = sign_in("admin")
    assert admin.delete(f"{API}/library/{second}", headers=acsrf).status_code == 204
    assert db.scalar(select(LibraryEvent)) is None  # history goes with the item
    assert member.get(f"{API}/library").json()["total"] == 0


def test_filters_sorting_and_paging(sign_in, imported, db):
    member, csrf = sign_in("member")
    ids = save(
        member, csrf, imported["research"], [pid(db, f"demo:{n}") for n in (1, 2, 3)], tags=["t"]
    ).json()
    first, second, third = ids["created"]
    c = member.post(f"{API}/library/collections", json={"name": "C"}, headers=csrf).json()
    member.patch(
        f"{API}/library/{first}",
        json={
            "status": "relevant",
            "note": "Unique_note 100%",
            "collection_ids": [c["id"]],
            "tags": ["solo"],
        },
        headers=csrf,
    )
    items = {i.id: i for i in db.scalars(select(LibraryItem))}
    items[uuid.UUID(second)].score, items[uuid.UUID(second)].red_flag_count = 90.0, 2
    items[uuid.UUID(third)].score, items[uuid.UUID(third)].red_flag_count = 10.0, 0
    db.commit()

    def found(**params):
        body = member.get(f"{API}/library", params=params).json()
        return [i["id"] for i in body["items"]], body["total"]

    assert found(q="unique_note 100%") == ([first], 1)  # %, _ are literal
    assert found(q="SYNTHETIC toy")[1] == 3  # every word, in title or abstract
    assert found(q="nothing-like-this") == ([], 0)
    assert found(status="relevant") == ([first], 1)
    assert found(collection_id=c["id"]) == ([first], 1)
    assert found(tag=" SOLO ") == ([first], 1)
    assert found(tag="t")[1] == 2
    assert set(found(min_score=50)[0]) >= {second} and third not in found(min_score=50)[0]
    assert found(has_red_flags="true") == ([second], 1)
    assert second not in found(has_red_flags="false")[0]
    field_id = member.get(f"{API}/library/{first}").json()["field"]["id"]
    assert found(field_id=field_id)[1] == 3 and found(field_id=str(uuid.uuid4()))[1] == 0
    assert found(sort="score", direction="desc")[0][0] == second
    assert found(sort="title", direction="asc")[0] == [first, second, third]
    page = member.get(
        f"{API}/library", params={"page": 2, "page_size": 2, "sort": "title", "direction": "asc"}
    )
    assert page.json()["items"][0]["id"] == third and page.json()["total"] == 3
    assert member.get(f"{API}/library", params={"sort": "nope"}).status_code == 422
    assert member.get(f"{API}/library", params={"page_size": 10_000}).status_code == 422
    viewer, _ = sign_in("viewer")
    assert viewer.get(f"{API}/library").json()["total"] == 3


def test_snapshot_update_from_another_run(sign_in, imported, db, tmp_path):
    from web_fixtures import make_demo_run

    from research_agent.web.importer.research import import_research_run

    member, csrf = sign_in("member")
    item_id = save(member, csrf, imported["research"], [pid(db, "demo:1")]).json()["created"][0]
    newer = import_research_run(db, make_demo_run(tmp_path / "runs" / "newer")).run_id
    db.commit()
    r = member.post(f"{API}/library/{item_id}/snapshot", json={"run_id": str(newer)}, headers=csrf)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_id"] == str(newer) and body["snapshot"]["run"]["id"] == str(newer)
    assert body["events"][-1]["kind"] == "snapshot"
    assert body["events"][-1]["detail"] == {"from_run": str(imported["research"]), "to_run": str(newer)}
    bad = member.post(
        f"{API}/library/{item_id}/snapshot", json={"run_id": str(imported["eval"])}, headers=csrf
    )
    assert bad.status_code == 422 and bad.json()["code"] == "not_in_run"


def test_rows_and_drawer_show_the_library_state(sign_in, imported, db):
    member, csrf = sign_in("member")
    paper = pid(db, "demo:1")
    body = save(member, csrf, imported["research"], [paper], new_collection={"name": "C"}).json()
    item_id = body["created"][0]
    rows = member.get(f"{API}/runs/{imported['research']}/papers").json()["items"]
    refs = {r["paper"]["id"]: r["library"] for r in rows}
    assert refs[paper] == {
        "item_id": item_id,
        "status": "to_read",
        "collections": [{"id": body["collection"]["id"], "name": "C"}],
    }
    assert refs[pid(db, "demo:2")] is None
    drawer = member.get(f"{API}/runs/{imported['research']}/papers/{paper}").json()
    assert drawer["library"]["item_id"] == item_id
    other = member.get(f"{API}/runs/{imported['research']}/papers/{pid(db, 'demo:2')}").json()
    assert other["library"] is None
