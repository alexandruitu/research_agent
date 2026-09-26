import shutil
import uuid
from pathlib import Path

from sqlalchemy import select

from research_agent.web.db.models import Paper, Run


def paper_id(db, source_id):
    return db.scalar(select(Paper.id).where(Paper.source_id == source_id))


def drawer(client, run, paper):
    return client.get(f"/api/v1/runs/{run}/papers/{paper}")


def test_drawer_for_a_paper_the_screen_dropped(sign_in, imported, db):
    viewer, _ = sign_in("viewer")
    body = drawer(viewer, imported["eval"], paper_id(db, "MED:3")).json()
    assert body["paper"]["source_id"] == "MED:3" and body["paper"]["abstract"]
    assert (
        body["in_sr"] is True and body["label_source"] == "sr_included_list" and body["found_by"] == "query"
    )
    screening = body["screening"]
    assert (screening["tier"], screening["decision"], screening["jev_decision"]) == (
        "jev",
        "exclude",
        "exclude",
    )
    assert (
        screening["criteria"][0]["key"] == "topic_match" and screening["criteria"][0]["probability"] == 0.03
    )
    assert screening["criteria"][0]["question"] and "Jev" in screening["reason"]
    # Every SR positive is in the agreement sample, whatever the screen decided.
    assert len(body["claims"]) == 1 and len(body["reviews"]) == 3 and body["rank"] is None
    outside = drawer(viewer, imported["eval"], paper_id(db, "MED:5")).json()  # dropped, not sampled
    assert outside["in_sr"] is False and outside["screening"]["decision"] == "exclude"
    assert outside["claims"] == [] and outside["reviews"] == [] and outside["rank"] is None


def test_drawer_for_a_reviewed_paper(sign_in, imported, db):
    viewer, _ = sign_in("viewer")
    body = drawer(viewer, imported["eval"], paper_id(db, "MED:1")).json()
    assert len(body["claims"]) == 1 and body["claims"][0]["quote"] in body["paper"]["abstract"]
    assert [r["role"] for r in body["reviews"]] == ["a", "b", "adjudicator"]
    assert body["reviews"][0]["detail"]["assessment"] and body["reviews"][2]["detail"]["reason"]
    assert all(r["call_key"] for r in body["reviews"])


def test_drawer_of_a_research_run_has_a_rank(sign_in, imported, db):
    viewer, _ = sign_in("viewer")
    body = drawer(viewer, imported["research"], paper_id(db, "demo:1")).json()
    assert body["in_sr"] is None and body["label_source"] is None and body["rank"]["position"] >= 1


def test_drawer_404s(sign_in, imported, db):
    viewer, _ = sign_in("viewer")
    assert drawer(viewer, imported["eval"], uuid.uuid4()).status_code == 404
    assert drawer(viewer, uuid.uuid4(), paper_id(db, "MED:1")).status_code == 404
    assert drawer(viewer, imported["eval"], paper_id(db, "demo:1")).status_code == 404  # not part of that run


def test_raw_calls_are_for_members_and_confined(sign_in, imported, db):
    viewer, _ = sign_in("viewer")
    member, _ = sign_in("member")
    key = drawer(viewer, imported["eval"], paper_id(db, "MED:2")).json()["screening"]["call_key"]
    url = f"/api/v1/runs/{imported['eval']}/calls/{key}"
    assert viewer.get(url).status_code == 403
    call = member.get(url).json()
    assert (
        call["role"] == "screen"
        and call["input"]["payload"]["paper"]["id"] == "MED:2"
        and call["output"]["decision"]
    )
    bad = member.get(f"/api/v1/runs/{imported['eval']}/calls/not-hex")
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_call_key"
    unknown = member.get(f"/api/v1/runs/{imported['eval']}/calls/{'0' * 64}")
    assert unknown.status_code == 404 and unknown.json()["code"] == "call_not_found"
    run = db.get(Run, imported["eval"])
    run.folder = "/etc"
    db.commit()
    gone = member.get(url)
    assert gone.status_code == 409 and gone.json()["code"] == "no_audit_trail"


def test_a_key_with_a_trailing_newline_is_refused(sign_in, imported, db):
    viewer, _ = sign_in("viewer")
    member, _ = sign_in("member")
    key = drawer(viewer, imported["eval"], paper_id(db, "MED:2")).json()["screening"]["call_key"]
    r = member.get(f"/api/v1/runs/{imported['eval']}/calls/{key}%0A")
    assert r.status_code == 422 and r.json()["code"] == "invalid_call_key"


def test_a_run_without_a_folder_never_reads_the_working_directory(sign_in, imported, db, monkeypatch):
    viewer, _ = sign_in("viewer")
    member, _ = sign_in("member")
    key = drawer(viewer, imported["eval"], paper_id(db, "MED:2")).json()["screening"]["call_key"]
    run = db.get(Run, imported["eval"])
    monkeypatch.chdir(run.folder)  # the server's working directory happens to hold a store
    run.folder = None
    db.commit()
    r = member.get(f"/api/v1/runs/{imported['eval']}/calls/{key}")
    assert r.status_code == 409 and r.json()["code"] == "no_audit_trail"


def test_a_store_symlinked_out_of_the_roots_is_refused(sign_in, imported, db, tmp_path):
    viewer, _ = sign_in("viewer")
    member, _ = sign_in("member")
    key = drawer(viewer, imported["eval"], paper_id(db, "MED:2")).json()["screening"]["call_key"]
    store = Path(db.get(Run, imported["eval"]).folder) / "research.sqlite"
    outside = tmp_path / "outside" / "research.sqlite"
    outside.parent.mkdir()
    shutil.move(store, outside)
    store.symlink_to(outside)
    r = member.get(f"/api/v1/runs/{imported['eval']}/calls/{key}")
    assert r.status_code == 409 and r.json()["code"] == "no_audit_trail"


def test_a_jev_decided_paper_exposes_the_jev_call(sign_in, imported, db):
    viewer, _ = sign_in("viewer")
    member, _ = sign_in("member")
    key = drawer(viewer, imported["eval"], paper_id(db, "MED:1")).json()["screening"]["call_key"]
    call = member.get(f"/api/v1/runs/{imported['eval']}/calls/{key}").json()
    assert call["role"] == "jev_screen" and "questions" in call["input"]


def _member_and_key(sign_in, imported, db):
    viewer, _ = sign_in("viewer")
    member, _ = sign_in("member")
    key = drawer(viewer, imported["eval"], paper_id(db, "MED:2")).json()["screening"]["call_key"]
    return member, key


def test_a_corrupt_store_is_409_not_500(sign_in, imported, db):
    member, key = _member_and_key(sign_in, imported, db)
    store = Path(db.get(Run, imported["eval"]).folder) / "research.sqlite"
    store.write_bytes(b"this is not a sqlite database" * 64)
    r = member.get(f"/api/v1/runs/{imported['eval']}/calls/{key}")
    assert r.status_code == 409 and r.json()["code"] == "no_audit_trail"


def test_a_store_without_a_calls_table_is_409_not_500(sign_in, imported, db):
    import sqlite3

    member, key = _member_and_key(sign_in, imported, db)
    store = Path(db.get(Run, imported["eval"]).folder) / "research.sqlite"
    store.unlink()
    sqlite3.connect(store).execute("create table other (x)").connection.close()
    r = member.get(f"/api/v1/runs/{imported['eval']}/calls/{key}")
    assert r.status_code == 409 and r.json()["code"] == "no_audit_trail"


def test_a_run_folder_with_uri_characters_in_its_name_is_readable(sign_in, imported, db, settings):
    member, key = _member_and_key(sign_in, imported, db)
    run = db.get(Run, imported["eval"])
    odd = settings.runs_dir / "run?#%1"
    shutil.copytree(run.folder, odd)
    run.folder = str(odd)
    db.commit()
    r = member.get(f"/api/v1/runs/{imported['eval']}/calls/{key}")
    assert r.status_code == 200, r.text
    assert r.json()["key"] == key and r.json()["role"] == "screen"
