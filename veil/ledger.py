"""Ledger: SQLite log of the exact post-redaction bytes sent upstream, plus counts and egress decisions."""
from __future__ import annotations
import hashlib, json, sqlite3, threading, time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, run TEXT, tag TEXT, route TEXT, model TEXT, stream INTEGER,
  status TEXT, http_status INTEGER, outbound BLOB, outbound_sha256 TEXT, outbound_bytes INTEGER,
  redacted_total INTEGER DEFAULT 0, redacted_by_kind TEXT DEFAULT '{}', leaked_count INTEGER DEFAULT 0,
  leaked_kinds TEXT DEFAULT '[]', reason TEXT, latency_ms INTEGER, upstream_id TEXT, upstream_model TEXT,
  usage TEXT, response_text TEXT, meta TEXT DEFAULT '{}');
"""


class Ledger:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self.lock = threading.RLock()
        with self.lock:
            self.db.executescript(SCHEMA)
            self.db.commit()

    def add(self, **f) -> int:
        out = f.pop("outbound", None)
        if out is not None:
            f["outbound"] = out
            f["outbound_sha256"] = hashlib.sha256(out).hexdigest()
            f["outbound_bytes"] = len(out)
        for k in ("redacted_by_kind", "leaked_kinds", "usage", "meta"):
            if k in f and not isinstance(f[k], str):
                f[k] = json.dumps(f[k])
        f.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        cols = ",".join(f)
        with self.lock:
            cur = self.db.execute(f"INSERT INTO ledger({cols}) VALUES({','.join('?' * len(f))})", list(f.values()))
            self.db.commit()
            return cur.lastrowid

    def update(self, id: int, **f):
        for k in ("usage", "meta", "redacted_by_kind", "leaked_kinds"):
            if k in f and not isinstance(f[k], str):
                f[k] = json.dumps(f[k])
        with self.lock:
            self.db.execute(f"UPDATE ledger SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), id])
            self.db.commit()

    @staticmethod
    def _row(r, cols, with_bytes=True) -> dict:
        d = dict(zip(cols, r))
        out = d.pop("outbound", None)
        for k in ("redacted_by_kind", "leaked_kinds", "usage", "meta"):
            if isinstance(d.get(k), str):
                try:
                    d[k] = json.loads(d[k])
                except Exception:
                    pass
        if with_bytes and out is not None:
            d["outbound_text"] = out.decode("utf-8", "replace")
        return d

    def list(self, limit=100, kind=None, run=None, with_bytes=False) -> list[dict]:
        q, args = "SELECT * FROM ledger", []
        cond = []
        if kind:
            cond.append("kind=?"); args.append(kind)
        if run:
            cond.append("run=?"); args.append(run)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self.lock:
            cur = self.db.execute(q, args)
            cols = [c[0] for c in cur.description]
            rows = cur.fetchall()
        return [self._row(r, cols, with_bytes) for r in rows]

    def get(self, id: int) -> dict | None:
        with self.lock:
            cur = self.db.execute("SELECT * FROM ledger WHERE id=?", (id,))
            cols = [c[0] for c in cur.description]
            r = cur.fetchone()
        return self._row(r, cols, True) if r else None

    def totals(self, run=None) -> dict:
        rows = self.list(10000, kind="inference", run=run)
        u = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        for r in rows:
            for k in u:
                u[k] += (r.get("usage") or {}).get(k, 0) or 0
        return {"calls": len(rows), "redacted": sum(r["redacted_total"] or 0 for r in rows),
                "leaked": sum(r["leaked_count"] or 0 for r in rows),
                "blocked": sum(1 for r in rows if r["status"] == "blocked"),
                "latency_ms": sum(r["latency_ms"] or 0 for r in rows), **u}
