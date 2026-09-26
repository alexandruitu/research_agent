"""Read-only access to a run folder's raw calls (the audit trail)."""

import json
import re
import sqlite3
from pathlib import Path

HEX64 = re.compile(r"[0-9a-f]{64}")


class CallStoreError(ValueError):
    pass


def connect_readonly(folder):
    path = Path(folder) / "research.sqlite"
    if not path.is_file():
        raise CallStoreError(f"{folder} has no research.sqlite")
    # as_uri() percent-encodes "?", "#" and "%" in folder names, so "?mode=ro" is always the query.
    return sqlite3.connect(f"{path.absolute().as_uri()}?mode=ro", uri=True)


def safe_folder(folder, roots):
    """Resolve `folder` and require it to live inside one of `roots` (symlinks and `..` cannot escape)."""
    resolved = Path(folder).resolve()
    for root in roots:
        if resolved.is_relative_to(Path(root).resolve()):
            return resolved
    raise CallStoreError("run folder is outside the configured directories")


class CallIndex:
    """Maps (role, paper id) and Jev (title, abstract) to call keys, for the importers."""

    def __init__(self, folder):
        self.by_paper, self.jev_by_text, self.empty = {}, {}, True
        try:
            connection = connect_readonly(folder)
        except CallStoreError:
            return
        with connection:
            for key, role, raw in connection.execute("select key, role, input from calls order by rowid"):
                self.empty = False
                data = json.loads(raw)
                if role == "jev_screen":
                    state = data.get("state", {})
                    self.jev_by_text[(state.get("title"), state.get("abstract"))] = key
                else:
                    paper = (data.get("payload") or {}).get("paper") or {}
                    if "id" in paper:
                        self.by_paper[(role, paper["id"])] = key
        connection.close()

    def key(self, role, paper_id):
        return self.by_paper.get((role, paper_id))

    def jev_key(self, title, abstract):
        return self.jev_by_text.get((title, abstract))


def read_call(folder, key):
    if not isinstance(key, str) or not HEX64.fullmatch(key):
        raise CallStoreError("call key must be 64 lowercase hex characters")
    try:
        connection = connect_readonly(folder)
        try:
            row = connection.execute(
                "select key, role, model, prompt_version, input, output from calls where key = ?", (key,)
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:  # corrupt file, not a database, or no `calls` table
        raise CallStoreError(f"{folder} has an unreadable research.sqlite") from exc
    if row is None:
        raise CallStoreError("call not found")
    return {
        "key": row[0],
        "role": row[1],
        "model": row[2],
        "prompt_version": row[3],
        "input": json.loads(row[4]),
        "output": json.loads(row[5]),
    }
