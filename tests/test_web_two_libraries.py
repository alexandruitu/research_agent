"""Two libraries: My library (personal, owner only) and the Company library (everyone, full text only).

Visibility is checked on every endpoint that reads library items or collections: list, detail, patch, delete,
snapshot, export, collections, paper rows and drawer, run counts, the author typeahead, related-work badges
and Reader notes."""

import uuid

import pytest
from sqlalchemy import select
from web_fixtures import give_full_text

from research_agent.web.db.models import LibraryItem, Paper, PaperReview, ReaderNote, User

API = "/api/v1"


def pid(db, source_id):
    return str(db.scalar(select(Paper.id).where(Paper.source_id == source_id)))


def save(client, csrf, run, papers, **extra):
    return client.post(
        f"{API}/library", json={"run_id": str(run), "paper_ids": papers, **extra}, headers=csrf
    )


@pytest.fixture
def two(sign_in, users, db):
    """Two members (member, member2) and an admin, signed in."""
    from conftest import PASSWORD

    from research_agent.web.auth import create_user

    create_user(db, email="member2@example.org", name="Member Two", role="member", password=PASSWORD)
    db.commit()
    return {role: sign_in(role) for role in ("member", "member2", "admin", "viewer")}


# --- the full-text rule ---------------------------------------------------------------------------------------


def test_company_refuses_abstract_only_papers_and_saves_nothing(two, imported, db):
    member, csrf = two["member"]
    r = save(member, csrf, imported["research"], [pid(db, "demo:1")], scope="company")
    assert r.status_code == 422 and r.json()["code"] == "needs_full_text"
    assert "Upload the PDF" in r.json()["message"]
    give_full_text(db, "demo:1")
    mixed = save(member, csrf, imported["research"], [pid(db, "demo:1"), pid(db, "demo:2")], scope="company")
    assert mixed.status_code == 422 and mixed.json()["code"] == "needs_full_text"
    assert db.scalar(select(LibraryItem)) is None  # all or nothing
    personal = save(member, csrf, imported["research"], [pid(db, "demo:2")])  # My library takes abstracts
    assert personal.status_code == 201 and personal.json()["items"][0]["scope"] == "personal"
    assert personal.json()["items"][0]["has_full_text"] is False


def test_eligibility_names_the_text_and_its_licence(two, imported, db):
    member, _ = two["member"]
    run = imported["research"]
    give_full_text(db, "demo:2")
    db.add(
        PaperReview(
            run_id=run, paper_id=uuid.UUID(pid(db, "demo:3")), text_source="pmc", text_licence="cc-by"
        )
    )
    db.commit()
    body = {"run_id": str(run), "paper_ids": [pid(db, f"demo:{n}") for n in (1, 2, 3)]}
    r = member.post(f"{API}/library/eligibility", json=body, headers=two["member"][1])
    assert r.status_code == 200, r.text
    papers = r.json()["papers"]
    assert [(p["has_full_text"], p["text_source"], p["text_licence"]) for p in papers] == [
        (False, None, None),
        (True, "upload", "user_upload"),
        (True, "pmc", "cc-by"),
    ]
    saved = save(member, two["member"][1], run, body["paper_ids"][1:], scope="company").json()["items"]
    assert [(i["has_full_text"], i["text_source"], i["text_licence"]) for i in saved] == [
        (True, "upload", "user_upload"),
        (True, "pmc", "cc-by"),
    ]
    missing = member.post(
        f"{API}/library/eligibility",
        json={"run_id": str(uuid.uuid4()), "paper_ids": body["paper_ids"]},
        headers=two["member"][1],
    )
    assert missing.status_code == 404


# --- one paper, both libraries; visibility ---------------------------------------------------------------------


def test_a_paper_can_be_in_both_libraries_and_personal_items_stay_private(two, imported, db):
    member, csrf = two["member"]
    other, ocsrf = two["member2"]
    admin, _ = two["admin"]
    give_full_text(db, "demo:1")
    paper = pid(db, "demo:1")
    company = save(member, csrf, imported["research"], [paper], scope="company").json()["created"][0]
    mine = save(member, csrf, imported["research"], [paper], note="my own").json()["created"][0]
    theirs = save(other, ocsrf, imported["research"], [paper]).json()["created"][0]
    assert len({company, mine, theirs}) == 3

    def listed(client, scope):
        return [i["id"] for i in client.get(f"{API}/library", params={"scope": scope}).json()["items"]]

    assert listed(member, "company") == [company] == listed(other, "company") == listed(admin, "company")
    assert listed(member, "personal") == [mine] and listed(other, "personal") == [theirs]
    assert listed(admin, "personal") == []  # admins do not see anyone's own library
    assert member.get(f"{API}/library").json()["items"][0]["id"] == company  # company by default
    for client in (other, admin):
        assert client.get(f"{API}/library/{mine}").status_code == 404
        assert client.patch(f"{API}/library/{mine}", json={"status": "read"}, headers=ocsrf).status_code in (
            403,
            404,
        )
        snap = client.post(f"{API}/library/{mine}/snapshot", json={"run_id": str(imported["research"])})
        assert snap.status_code in (403, 404)
    assert other.patch(f"{API}/library/{mine}", json={"status": "read"}, headers=ocsrf).status_code == 404
    assert other.delete(f"{API}/library/{mine}", headers=ocsrf).status_code == 404
    admin_client, acsrf = two["admin"]
    assert admin_client.delete(f"{API}/library/{mine}", headers=acsrf).status_code == 404
    assert member.get(f"{API}/library/{mine}").json()["note"] == "my own"
    # the search words never reach another person's note
    assert other.get(f"{API}/library", params={"scope": "personal", "q": "my own"}).json()["total"] == 0


def test_export_holds_one_library_as_its_viewer_sees_it(two, imported, db):
    member, csrf = two["member"]
    other, _ = two["member2"]
    give_full_text(db, "demo:1")
    save(member, csrf, imported["research"], [pid(db, "demo:1")], scope="company")
    save(member, csrf, imported["research"], [pid(db, "demo:2")], note="secret plan")

    def rows(client, scope):
        r = client.get(f"{API}/library/export", params={"format": "csv", "scope": scope})
        return r.text.strip().splitlines()[1:]

    assert len(rows(member, "company")) == 1 and len(rows(member, "personal")) == 1
    assert len(rows(other, "company")) == 1 and rows(other, "personal") == []
    bib = other.get(f"{API}/library/export", params={"format": "bibtex", "scope": "personal"}).text
    assert "secret plan" not in bib


def test_rows_drawer_and_run_counts_show_only_what_the_viewer_sees(two, imported, db):
    member, csrf = two["member"]
    other, _ = two["member2"]
    run = imported["research"]
    give_full_text(db, "demo:1")
    company = save(member, csrf, run, [pid(db, "demo:1")], scope="company").json()["created"][0]
    mine = save(member, csrf, run, [pid(db, "demo:1"), pid(db, "demo:2")]).json()["created"]

    def refs(client):
        rows = client.get(f"{API}/runs/{run}/papers").json()["items"]
        return {r["paper"]["source_id"]: r["library"] for r in rows}

    ref = refs(member)["demo:1"]
    assert ref["item_id"] == company and ref["scope"] == "company"
    assert ref["company_item_id"] == company and ref["personal_item_id"] in mine
    assert refs(member)["demo:2"]["scope"] == "personal"
    seen = refs(other)
    assert seen["demo:1"]["personal_item_id"] is None and seen["demo:2"] is None
    assert other.get(f"{API}/runs/{run}/papers/{pid(db, 'demo:2')}").json()["library"] is None
    groups = {g["key"]: g["count"] for g in other.get(f"{API}/runs/{run}/papers/groups?by=library").json()}
    assert groups.get("to_read") == 1  # the Company item only
    assert member.get(f"{API}/runs/{run}").json()["links"]["library_count"] == 3
    assert other.get(f"{API}/runs/{run}").json()["links"]["library_count"] == 1


def test_related_badges_never_show_another_persons_library(two, imported, db, users):
    from research_agent.web.related import _badges, search_local

    member, csrf = two["member"]
    save(member, csrf, imported["research"], [pid(db, "demo:2")])
    paper = db.get(Paper, uuid.UUID(pid(db, "demo:2")))
    other = db.scalar(select(User).where(User.email == "member2@example.org"))
    owner = db.scalar(select(User).where(User.email == "member@example.org"))
    assert _badges(db, [paper], other)[paper.id]["library_item_id"] is None
    assert _badges(db, [paper], owner)[paper.id]["library_item_id"] is not None
    words = paper.title.split()[:2]
    exclude = uuid.uuid4()
    # the paper is still known from the run (screened), so search_local finds it either way; the badge differs
    assert any(p.id == paper.id for p in search_local(db, words, exclude, viewer=other))


# --- collections per library ---------------------------------------------------------------------------------


def test_collections_belong_to_one_library(two, imported, db):
    member, csrf = two["member"]
    other, ocsrf = two["member2"]
    admin, acsrf = two["admin"]
    mine = member.post(f"{API}/library/collections", json={"name": "Plaque"}, headers=csrf).json()
    assert mine["scope"] == "personal"
    shared = member.post(
        f"{API}/library/collections", json={"name": "Plaque", "scope": "company"}, headers=csrf
    )
    assert shared.status_code == 201  # the same name in the other library is fine
    theirs = other.post(f"{API}/library/collections", json={"name": "plaque"}, headers=ocsrf)
    assert theirs.status_code == 201  # and in another person's library
    again = member.post(f"{API}/library/collections", json={"name": "PLAQUE"}, headers=csrf)
    assert again.status_code == 409

    def names(client, scope):
        return [c["id"] for c in client.get(f"{API}/library/collections", params={"scope": scope}).json()]

    assert names(member, "personal") == [mine["id"]] and names(other, "personal") == [theirs.json()["id"]]
    assert names(admin, "personal") == [] and names(other, "company") == [shared.json()["id"]]
    assert (
        other.patch(f"{API}/library/collections/{mine['id']}", json={"name": "x"}, headers=ocsrf).status_code
        == 404
    )
    assert admin.post(f"{API}/library/collections/{mine['id']}/archive", headers=acsrf).status_code == 404
    assert member.post(f"{API}/library/collections/{mine['id']}/archive", headers=csrf).status_code == 200
    assert member.post(f"{API}/library/collections/{mine['id']}/restore", headers=csrf).status_code == 200
    assert (
        member.post(f"{API}/library/collections/{shared.json()['id']}/archive", headers=csrf).status_code
        == 403
    )  # a Company collection: admins only
    # a save puts its collections in its own library only
    wrong = save(
        member, csrf, imported["research"], [pid(db, "demo:1")], collection_ids=[shared.json()["id"]]
    )
    assert wrong.status_code == 422 and wrong.json()["code"] == "wrong_library"
    hidden = save(other, ocsrf, imported["research"], [pid(db, "demo:1")], collection_ids=[mine["id"]])
    assert hidden.status_code == 422 and hidden.json()["code"] == "unknown_collection"
    new = save(
        member, csrf, imported["research"], [pid(db, "demo:1")], new_collection={"name": "Fresh"}
    ).json()
    assert new["collection"]["scope"] == "personal"
    assert "Fresh" not in [c["name"] for c in other.get(f"{API}/library/collections?scope=personal").json()]


# --- removal ---------------------------------------------------------------------------------------------------


def test_company_items_are_removed_by_their_adder_or_an_admin(two, imported, db):
    member, csrf = two["member"]
    other, ocsrf = two["member2"]
    admin, acsrf = two["admin"]
    give_full_text(db, "demo:1", "demo:2")
    first, second = save(
        member, csrf, imported["research"], [pid(db, "demo:1"), pid(db, "demo:2")], scope="company"
    ).json()["created"]
    assert [i["can_delete"] for i in other.get(f"{API}/library").json()["items"]] == [False, False]
    assert all(i["can_delete"] for i in admin.get(f"{API}/library").json()["items"])
    denied = other.delete(f"{API}/library/{first}", headers=ocsrf)
    assert denied.status_code == 403 and denied.json()["code"] == "not_owner"
    assert member.delete(f"{API}/library/{first}", headers=csrf).status_code == 204
    assert admin.delete(f"{API}/library/{second}", headers=acsrf).status_code == 204
    mine = save(member, csrf, imported["research"], [pid(db, "demo:3")]).json()["items"][0]
    assert mine["can_delete"] is True
    assert member.delete(f"{API}/library/{mine['id']}", headers=csrf).status_code == 204


# --- Reader notes ----------------------------------------------------------------------------------------------


def test_reader_notes_private_or_company(two, imported, db):
    member, _ = two["member"]
    other, _ = two["member2"]
    paper = uuid.UUID(pid(db, "demo:1"))
    owner = db.scalar(select(User.id).where(User.email == "member@example.org"))
    for visibility in ("private", "company"):
        db.add(
            ReaderNote(
                paper_id=paper, tool="explain", question=visibility, visibility=visibility, created_by=owner
            )
        )
    db.commit()

    def seen(client):
        return sorted(n["question"] for n in client.get(f"{API}/papers/{paper}/notes").json())

    assert seen(member) == ["company", "private"]
    assert seen(other) == ["company"] and seen(two["admin"][0]) == ["company"]
    assert {n["visibility"] for n in member.get(f"{API}/papers/{paper}/notes").json()} == {
        "private",
        "company",
    }
