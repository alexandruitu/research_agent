import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .connectors import canonical_json, digest


class MissingCall(LookupError):
    """A call needed by an offline computation is not in the cache."""


class Store:
    """Separate connections per operation permit concurrent reviewer writes."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "research.sqlite"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS raw (hash TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS calls (key TEXT PRIMARY KEY, role TEXT, model TEXT,
                    prompt_version TEXT, input TEXT, output TEXT);
                CREATE TABLE IF NOT EXISTS papers (run_id TEXT, paper_id TEXT, payload TEXT,
                    PRIMARY KEY(run_id, paper_id));
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def raw(self, payload):
        key = digest(payload)
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO raw VALUES (?, ?)", (key, canonical_json(payload)))
        return key

    def cached(self, key):
        with self.connect() as db:
            row = db.execute("SELECT output FROM calls WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def record(self, key, role, model, version, inputs, output):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO calls VALUES (?, ?, ?, ?, ?, ?)",
                (key, role, model, version, canonical_json(inputs), canonical_json(output)),
            )

    def save_papers(self, run_id, papers):
        with self.connect() as db:
            db.executemany(
                "INSERT OR REPLACE INTO papers VALUES (?, ?, ?)",
                [(run_id, p["id"], canonical_json(p)) for p in papers],
            )
