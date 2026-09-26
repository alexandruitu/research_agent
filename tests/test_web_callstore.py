import pytest

from research_agent.agents import Evaluator
from research_agent.schemas import Screen
from research_agent.storage import Store
from research_agent.web.callstore import CallIndex, CallStoreError, read_call, safe_folder

PAYLOAD = {"topic": "t", "paper": {"id": "MED:1", "title": "T", "abstract": "A."}}


def make_store(tmp_path):
    store = Store(tmp_path)
    Evaluator(store).ask("screen", Screen, PAYLOAD)  # demo call recorded in `calls`
    store.record(
        "f" * 64,
        "jev_screen",
        "jev-latest",
        "jev-screen.1",
        {"model": "jev-latest", "state": {"title": "T", "abstract": "A."}, "questions": {}},
        {"model": "jev-1.13.0", "answers": {}},
    )
    return store


def test_index_finds_calls_by_role_and_paper_and_by_jev_title(tmp_path):
    make_store(tmp_path)
    index = CallIndex(tmp_path)
    key = index.key("screen", "MED:1")
    assert key and len(key) == 64
    assert index.key("screen", "MED:2") is None and index.key("extract", "MED:1") is None
    assert index.jev_key("T", "A.") == "f" * 64
    assert index.jev_key("T", "other") is None


def test_index_of_a_folder_without_a_store_is_empty(tmp_path):
    index = CallIndex(tmp_path)
    assert index.key("screen", "MED:1") is None and index.empty


def test_read_call_returns_input_and_output(tmp_path):
    make_store(tmp_path)
    key = CallIndex(tmp_path).key("screen", "MED:1")
    call = read_call(tmp_path, key)
    assert call["role"] == "screen" and call["input"]["payload"]["paper"]["id"] == "MED:1"
    assert call["output"]["decision"] == "include" and call["prompt_version"]


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "abc",
        "../etc/passwd",
        "F" * 64,
        "g" * 64,
        "a" * 63,
        "a" * 65,
        "a" * 64 + "\n",
        "a'; drop table calls;--",
    ],
)
def test_call_keys_must_be_64_lowercase_hex(tmp_path, bad):
    make_store(tmp_path)
    with pytest.raises(CallStoreError, match="call key"):
        read_call(tmp_path, bad)


def test_unknown_key_and_missing_store(tmp_path):
    make_store(tmp_path)
    with pytest.raises(CallStoreError, match="not found"):
        read_call(tmp_path, "0" * 64)
    with pytest.raises(CallStoreError, match="research.sqlite"):
        read_call(tmp_path / "nowhere", "0" * 64)


def test_the_store_is_opened_read_only(tmp_path):
    make_store(tmp_path)
    from research_agent.web.callstore import connect_readonly

    with pytest.raises(Exception, match="readonly"):
        connect_readonly(tmp_path).execute("delete from calls")


def test_safe_folder_only_allows_paths_inside_the_configured_roots(tmp_path):
    root = tmp_path / "runs"
    (root / "a").mkdir(parents=True)
    assert safe_folder(str(root / "a"), [root]) == (root / "a").resolve()
    with pytest.raises(CallStoreError, match="outside"):
        safe_folder(str(root / ".." / "etc"), [root])
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside)
    with pytest.raises(CallStoreError, match="outside"):
        safe_folder(str(root / "link"), [root])
