"""Local vault: stable token <-> value map persisted in SQLite. Values never leave this file."""
from __future__ import annotations
import json, re, sqlite3, threading
from pathlib import Path

TOKEN_RE = re.compile(r"\\?\[([A-Z][A-Z_]*_\d+)\\?\]")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()).lower()


class Vault:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.lock = threading.RLock()
        self.version = 0
        with self.lock:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS entities(
                  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, canonical TEXT NOT NULL,
                  token TEXT NOT NULL UNIQUE, source TEXT NOT NULL DEFAULT 'detector');
                CREATE TABLE IF NOT EXISTS surface(
                  norm TEXT PRIMARY KEY, entity_id INTEGER NOT NULL REFERENCES entities(id), raw TEXT NOT NULL);
                """
            )
            self.db.commit()

    # -- writes -----------------------------------------------------------
    def _next_token(self, kind: str) -> str:
        row = self.db.execute("SELECT COUNT(*) FROM entities WHERE kind=?", (kind,)).fetchone()
        n = row[0] + 1
        while self.db.execute("SELECT 1 FROM entities WHERE token=?", (f"[{kind}_{n}]",)).fetchone():
            n += 1
        return f"[{kind}_{n}]"

    def add(self, kind: str, value: str, aliases: tuple[str, ...] | list[str] = (), source: str = "detector") -> str:
        """Return the stable token for value (creating it). Aliases map to the same token."""
        value = value.strip()
        with self.lock:
            row = self.db.execute("SELECT entity_id FROM surface WHERE norm=?", (norm(value),)).fetchone()
            if row:
                eid = row[0]
            else:
                token = self._next_token(kind)
                cur = self.db.execute(
                    "INSERT INTO entities(kind, canonical, token, source) VALUES(?,?,?,?)", (kind, value, token, source)
                )
                eid = cur.lastrowid
                self.db.execute("INSERT INTO surface(norm, entity_id, raw) VALUES(?,?,?)", (norm(value), eid, value))
                self.version += 1
            for a in aliases:
                a = a.strip()
                if a and not self.db.execute("SELECT 1 FROM surface WHERE norm=?", (norm(a),)).fetchone():
                    self.db.execute("INSERT INTO surface(norm, entity_id, raw) VALUES(?,?,?)", (norm(a), eid, a))
                    self.version += 1
            self.db.commit()
            return self.db.execute("SELECT token FROM entities WHERE id=?", (eid,)).fetchone()[0]

    def load_profile(self, path: str | Path) -> int:
        data = json.loads(Path(path).read_text())
        n = 0
        for e in data.get("entities", []):
            self.add(e["kind"], e["value"], e.get("aliases", []), source="profile")
            n += 1
        return n

    # -- reads ------------------------------------------------------------
    def token_for(self, value: str) -> str | None:
        row = self.db.execute(
            "SELECT e.token FROM surface s JOIN entities e ON e.id=s.entity_id WHERE s.norm=?", (norm(value),)
        ).fetchone()
        return row[0] if row else None

    def surfaces(self) -> list[tuple[str, str, str]]:
        """(raw surface, token, kind) for every known string, longest first."""
        with self.lock:
            rows = self.db.execute(
                "SELECT s.raw, e.token, e.kind FROM surface s JOIN entities e ON e.id=s.entity_id"
            ).fetchall()
        return sorted(rows, key=lambda r: -len(r[0]))

    def canon_map(self) -> dict[str, str]:
        with self.lock:
            return dict(self.db.execute("SELECT token, canonical FROM entities").fetchall())

    def kind_of(self, token: str) -> str | None:
        r = self.db.execute("SELECT kind FROM entities WHERE token=?", (token,)).fetchone()
        return r[0] if r else None

    def stats(self) -> dict:
        rows = self.db.execute("SELECT kind, COUNT(*) FROM entities GROUP BY kind").fetchall()
        return {"entities": sum(r[1] for r in rows), "by_kind": dict(rows)}

    def close(self):
        self.db.close()
