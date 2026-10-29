"""Local memory store (SQLite): what Veil remembers across sessions. Lives in <home>/memory.sqlite, never leaves the machine.

documents  every PDF seen (content hash, extracted typed JSON, text)   findings  every finding with first/last seen + status
events     the notification feed shown in the UI                        notes     the user's own notes, optionally tied to a claim
facts      small key/value state (deductible, last scan, ...)           followups  deadline follow-ups already created (no duplicates)
"""
from __future__ import annotations
import hashlib, json, sqlite3, threading, time
from datetime import date
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(sha TEXT PRIMARY KEY, name TEXT, path TEXT, text TEXT, doc TEXT, first_seen TEXT, run TEXT);
CREATE TABLE IF NOT EXISTS findings(key TEXT PRIMARY KEY, data TEXT, first_seen TEXT, last_seen TEXT, status TEXT DEFAULT 'open');
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, title TEXT, detail TEXT, data TEXT DEFAULT '{}', seen INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, claim TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS facts(key TEXT PRIMARY KEY, data TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS followups(key TEXT PRIMARY KEY, draft_id TEXT, ts TEXT);
"""
DATES = ("document_date", "service_date")


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def freeze(doc: dict) -> str:
    return json.dumps(doc, default=lambda o: o.isoformat() if isinstance(o, date) else str(o))


def thaw(s: str) -> dict:
    d = json.loads(s)
    for k in DATES:
        if d.get(k): d[k] = date.fromisoformat(d[k])
    for l in d.get("lines", []):
        if l.get("service_date"): l["service_date"] = date.fromisoformat(l["service_date"])
    return d


def file_sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def finding_key(f: dict) -> str:
    return hashlib.sha1(f"{f['type']}|{f.get('bill_doc')}|{f.get('eob_doc')}|{f.get('amount')}".encode()).hexdigest()[:12]


class Memory:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self.lock = threading.RLock()
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript(SCHEMA)
            self.db.commit()

    def _q(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            cols = [c[0] for c in cur.description] if cur.description else []
            rows = cur.fetchall()
            self.db.commit()
        return [dict(zip(cols, r)) for r in rows]

    # documents
    def has_doc(self, sha: str) -> bool:
        return bool(self._q("SELECT 1 FROM documents WHERE sha=?", (sha,)))

    def add_doc(self, sha, name, path, text, doc, run):
        self._q("INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?,?,?)", (sha, name, str(path), text, freeze(doc), now(), run))

    def docs(self) -> list[dict]:
        out = []
        for r in self._q("SELECT * FROM documents ORDER BY name"):
            d = thaw(r["doc"]); d["_name"] = r["name"]; d["_sha"] = r["sha"]; d["_first_seen"] = r["first_seen"]; d["_text"] = r["text"]
            out.append(d)
        return out

    # findings: returns the keys that are new
    def sync_findings(self, findings: list[dict]) -> list[dict]:
        new, t = [], now()
        seen = set()
        for f in findings:
            k = finding_key(f); seen.add(k); f["key"] = k
            if self._q("SELECT 1 FROM findings WHERE key=?", (k,)):
                self._q("UPDATE findings SET last_seen=?, data=? WHERE key=?", (t, json.dumps(f, default=str), k))
            else:
                self._q("INSERT INTO findings VALUES(?,?,?,?,'open')", (k, json.dumps(f, default=str), t, t)); new.append(f)
        for r in self._q("SELECT key FROM findings WHERE status='open'"):
            if r["key"] not in seen:
                self._q("UPDATE findings SET status='no_longer_detected' WHERE key=?", (r["key"],))
        return new

    def findings(self) -> list[dict]:
        return [dict(json.loads(r["data"]), first_seen=r["first_seen"], last_seen=r["last_seen"], status=r["status"]) for r in self._q("SELECT * FROM findings ORDER BY first_seen, key")]

    # events
    def event(self, kind: str, title: str, detail: str = "", data: dict | None = None) -> int:
        with self.lock:
            cur = self.db.execute("INSERT INTO events(ts,kind,title,detail,data) VALUES(?,?,?,?,?)", (now(), kind, title, detail, json.dumps(data or {}, default=str)))
            self.db.commit()
            return cur.lastrowid

    def events(self, after: int = 0, limit: int = 100) -> list[dict]:
        rows = self._q("SELECT * FROM events WHERE id>? ORDER BY id DESC LIMIT ?", (after, limit))
        for r in rows: r["data"] = json.loads(r["data"] or "{}")
        return rows

    def mark_seen(self):
        self._q("UPDATE events SET seen=1")

    # notes
    def add_note(self, text: str, claim: str | None = None) -> int:
        with self.lock:
            cur = self.db.execute("INSERT INTO notes(ts,claim,text) VALUES(?,?,?)", (now(), claim, text)); self.db.commit(); return cur.lastrowid

    def notes(self) -> list[dict]:
        return self._q("SELECT * FROM notes ORDER BY id DESC")

    # facts + followups
    def set_fact(self, key, data):
        self._q("INSERT OR REPLACE INTO facts VALUES(?,?,?)", (key, json.dumps(data, default=str), now()))

    def fact(self, key, default=None):
        r = self._q("SELECT data FROM facts WHERE key=?", (key,))
        return json.loads(r[0]["data"]) if r else default

    def followup(self, key: str) -> dict | None:
        r = self._q("SELECT * FROM followups WHERE key=?", (key,)); return r[0] if r else None

    def add_followup(self, key, draft_id):
        self._q("INSERT OR REPLACE INTO followups VALUES(?,?,?)", (key, draft_id, now()))

    def snapshot(self) -> dict:
        """What the 'Veil remembers' panel shows."""
        return dict(documents=[dict(name=d["_name"], type=d["doc_type"], provider=d["provider"], date=str(d["document_date"]), first_seen=d["_first_seen"]) for d in self.docs()],
                    findings=self.findings(), notes=self.notes(), deductible=self.fact("deductible"), followups=self._q("SELECT * FROM followups"),
                    last_scan=self.fact("last_scan"))
