"""Tamper-evident receipts: a hash chain over every outbound call the gateway logs.

Each receipt commits to the exact outbound bytes (sha256, byte count), where they went, when, how many tokens came back, and the previous
receipt's hash. Change any receipt, delete one, reorder two, or swap the stored bytes, and verification fails at the first affected entry.

What this is NOT: tamper-proof. A local chain cannot stop someone who can write the whole database from rebuilding every receipt from
genesis. Publish (or print on paper) the head hash somewhere you control, then pass it back with `veil verify --head <hash>`: a rebuilt or
truncated chain can no longer reproduce it. `web/receipts.js` implements the same algorithm with Web Crypto; tests pin the two together.

Two receipt types share one chain (their `seq` is the chain position, `ledger_id` points at the ledger row):
  call    sealed the moment the gateway logs the call: destination, byte_count, sha256 of the exact bytes. Blocked (422) and denied rows get
          a call receipt too, with no bytes, so deleting one leaves a visible gap.
  result  sealed when the call finishes: status, http_status and tokens (known only after the upstream answers).
"""
from __future__ import annotations
import hashlib, json, os
from urllib.parse import urlparse

GENESIS = "0919b0da835fb3a833bd2af748041718b08f2ee538356dfa1864b01bf464a547"  # sha256(b"veil/receipts/genesis/v1"), fixed
DEFAULT_UPSTREAM = "https://api.tokenfactory.nebius.com/v1"
RSCHEMA = "CREATE TABLE IF NOT EXISTS receipts(seq INTEGER PRIMARY KEY, receipt TEXT NOT NULL)"
FIELDS = ("seq", "type", "ts", "ledger_id", "kind", "destination_host", "destination_path", "status", "byte_count", "sha256",
          "tokens", "http_status", "origin", "prev_hash")


def canonical(obj) -> bytes:
    """Canonical JSON: sorted keys, no spaces, ASCII-only escapes. web/receipts.js produces the identical bytes."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def receipt_hash(r: dict) -> str:
    return hashlib.sha256(canonical({k: v for k, v in r.items() if k != "receipt_hash"})).hexdigest()


def make(prev_hash: str, seq: int, **f) -> dict:
    r = {k: f.get(k) for k in FIELDS}
    r.update(seq=seq, prev_hash=prev_hash)
    r["receipt_hash"] = receipt_hash(r)
    return r


# ---------------------------------------------------------------- pure verification (no database)

def verify_chain(receipts: list[dict], blobs: dict | None = None, expect_head: str | None = None) -> dict:
    """Recompute the chain. `blobs` maps seq -> the stored outbound bytes of that call receipt (bytes), when available.
    Returns {ok, count, head, bytes_checked, broken}; broken = {seq, code, reason} for the FIRST failure."""
    prev, checked = GENESIS, 0
    later = {r.get("seq") for r in receipts}
    seen: set = set()

    def bad(seq, code, reason):
        return {"ok": False, "count": len(receipts), "head": None, "bytes_checked": checked, "broken": {"seq": seq, "code": code, "reason": reason}}

    for i, r in enumerate(receipts):
        want, s = i + 1, r.get("seq")
        if s != want:
            if s in seen:
                return bad(want, "duplicate", f"seq {s} appears twice")
            if want in later:
                return bad(want, "reordered", f"seq {s} sits where seq {want} belongs: entries were reordered")
            return bad(want, "missing", f"seq {want} is missing: an entry was deleted (next entry is seq {s})")
        seen.add(s)
        if receipt_hash(r) != r.get("receipt_hash"):
            return bad(s, "edited", "receipt was edited: its receipt_hash does not match its fields")
        if r.get("prev_hash") != prev:
            return bad(s, "link", f"link mismatch: prev_hash is not the hash of seq {s - 1}" if s > 1 else "link mismatch: first receipt does not start at the genesis hash")
        if blobs is not None and r.get("type") == "call" and s in blobs:
            b = blobs[s]
            if len(b) != r.get("byte_count"):
                return bad(s, "byte_count", f"byte count mismatch: stored bytes are {len(b)}, receipt says {r.get('byte_count')}")
            if hashlib.sha256(b).hexdigest() != r.get("sha256"):
                return bad(s, "bytes", "outbound bytes hash mismatch: the stored bytes are not the bytes that were receipted")
            checked += 1
        prev = r["receipt_hash"]
    if expect_head and prev != expect_head:
        return bad(len(receipts) + 1, "head", f"head mismatch: chain ends at {prev[:16]}, expected {expect_head[:16]}: entries were removed from the end or the chain was rebuilt")
    return {"ok": True, "count": len(receipts), "head": prev, "bytes_checked": checked, "broken": None}


# ---------------------------------------------------------------- deriving receipt fields from a ledger row

def receipt_status(row: dict) -> str:
    st = row.get("status")
    if st == "ok":
        return "sent"
    if st == "blocked":
        return "blocked_422" if (row.get("leaked_count") or 0) > 0 else "denied"
    return st or "unknown"


def destination(row: dict) -> tuple[str, str]:
    route, meta = row.get("route") or "", row.get("meta") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    if route == "chat":
        u = urlparse(os.environ.get("VEIL_UPSTREAM", DEFAULT_UPSTREAM))
        return u.netloc, u.path.rstrip("/") + "/chat/completions"
    if route == "tavily":
        return "api.tavily.com", "/search"
    if route.startswith("tool:"):
        doms = sorted({a.rsplit("@", 1)[-1].lower() for a in (meta.get("to") or []) if "@" in str(a)})
        return ",".join(doms), route
    if route.startswith("openshell:"):
        return str(meta.get("target") or ""), route
    return "", route


def tokens_of(row: dict) -> dict | None:
    u = row.get("usage") or {}
    if isinstance(u, str):
        try:
            u = json.loads(u)
        except Exception:
            u = {}
    t = {k: u[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens") if isinstance(u.get(k), int)}
    return t or None


def _call_fields(row: dict, status: str, origin: str) -> dict:
    h, p = destination(row)
    out = row.get("outbound")
    return dict(type="call", ts=row.get("ts"), ledger_id=row["id"], kind=row.get("kind"), destination_host=h, destination_path=p, status=status,
                byte_count=len(out) if out is not None else 0, sha256=hashlib.sha256(out).hexdigest() if out is not None else None, origin=origin)


def _result_fields(row: dict, origin: str, ts: str | None = None) -> dict:
    return dict(type="result", ts=ts or row.get("ts"), ledger_id=row["id"], kind=row.get("kind"), status=receipt_status(row),
                tokens=tokens_of(row), http_status=row.get("http_status"), origin=origin)


# ---------------------------------------------------------------- sqlite layer (called from Ledger, inside its lock)

def _tail(db) -> tuple[int, str]:
    r = db.execute("SELECT receipt FROM receipts ORDER BY seq DESC LIMIT 1").fetchone()
    if not r:
        return 0, GENESIS
    j = json.loads(r[0])
    return j["seq"], j["receipt_hash"]


def append(db, **f) -> dict:
    """Append one receipt. The caller holds a write transaction (BEGIN IMMEDIATE) so the tail read and insert are atomic across processes."""
    seq, prev = _tail(db)
    r = make(prev, seq + 1, **f)
    db.execute("INSERT INTO receipts(seq, receipt) VALUES(?,?)", (r["seq"], canonical(r).decode()))
    return r


def _row(db, id: int) -> dict:
    cur = db.execute("SELECT * FROM ledger WHERE id=?", (id,))
    cols = [c[0] for c in cur.description]
    d = dict(zip(cols, cur.fetchone()))
    d["meta"] = json.loads(d["meta"]) if isinstance(d.get("meta"), str) and d["meta"] else {}
    return d


def seal_call(db, id: int, origin: str = "live") -> dict:
    row = _row(db, id)
    return append(db, **_call_fields(row, receipt_status(row), origin))


def seal_result(db, id: int, origin: str = "live", ts: str | None = None) -> dict:
    return append(db, **_result_fields(_row(db, id), origin, ts))


def migrate(db) -> int:
    """First-run migration only (empty receipts table): chain the rows that already exist, oldest first, origin='backfill'. Never runs
    again, so a receipt that is later deleted is reported by verify instead of being quietly re-created."""
    db.execute("BEGIN IMMEDIATE")
    try:
        if db.execute("SELECT 1 FROM receipts LIMIT 1").fetchone():
            db.rollback(); return 0
        n = 0
        for (id,) in db.execute("SELECT id FROM ledger ORDER BY id").fetchall():
            row = _row(db, id)
            went = row.get("outbound") is not None and row.get("status") in ("ok", "error")
            append(db, **_call_fields(row, "pending" if went else receipt_status(row), "backfill")); n += 1
            if went:
                append(db, **_result_fields(row, "backfill")); n += 1
        db.commit()
        return n
    except Exception:
        db.rollback(); raise


def load(db) -> list[dict]:
    return [json.loads(r[0]) for r in db.execute("SELECT receipt FROM receipts ORDER BY seq")]


def verify_db(db, expect_head: str | None = None) -> dict:
    """Chain check plus cross-checks against the ledger table: stored bytes, deleted or unreceipted rows, edited status/tokens."""
    rs = load(db)
    rows = {}
    cur = db.execute("SELECT * FROM ledger")
    cols = [c[0] for c in cur.description]
    for t in cur.fetchall():
        d = dict(zip(cols, t))
        d["meta"] = json.loads(d["meta"]) if isinstance(d.get("meta"), str) and d["meta"] else {}
        rows[d["id"]] = d
    blobs = {r["seq"]: bytes(rows[r["ledger_id"]]["outbound"]) for r in rs
             if r.get("type") == "call" and r.get("ledger_id") in rows and rows[r["ledger_id"]].get("outbound") is not None}
    v = verify_chain(rs, blobs, expect_head)
    v.update(ledger_rows=len(rows))
    if not v["ok"]:
        return v
    fail = lambda seq, code, reason: {**v, "ok": False, "head": None, "broken": {"seq": seq, "code": code, "reason": reason}}
    calls = {r["ledger_id"]: r for r in rs if r["type"] == "call"}
    last: dict = {}
    for r in rs:
        if r["type"] == "result":
            last[r["ledger_id"]] = r
    for r in rs:
        if r["type"] == "call" and r["ledger_id"] not in rows:
            return fail(r["seq"], "ledger_row_deleted", f"ledger row #{r['ledger_id']} was deleted: its receipt exists but the row does not")
    for id in sorted(rows):
        if id not in calls:
            return fail(len(rs) + 1, "unreceipted", f"ledger row #{id} has no receipt: it was inserted outside the gateway or its receipt was removed")
    for id, row in sorted(rows.items()):
        c, res = calls[id], last.get(id)
        if res is None and c["status"] == "pending" and row.get("status") == "pending":
            continue  # still in flight
        want = res or c
        if want["status"] != receipt_status(row):
            return fail(want["seq"], "ledger_edited", f"ledger row #{id} was edited after it was receipted: status is {receipt_status(row)!r}, receipt says {want['status']!r}")
        if res is not None and (res["tokens"] != tokens_of(row) or res["http_status"] != row.get("http_status")):
            return fail(res["seq"], "ledger_edited", f"ledger row #{id} was edited after it was receipted: tokens or http_status differ from the receipt")
    return v


def export_chain(db, include_blobs: bool = True) -> dict:
    """The chain as the static page embeds it: receipts plus the exact stored bytes of each call, so a browser can re-hash them."""
    rs = load(db)
    blobs = {}
    if include_blobs:
        for r in rs:
            if r["type"] == "call" and r["byte_count"]:
                b = db.execute("SELECT outbound FROM ledger WHERE id=?", (r["ledger_id"],)).fetchone()
                if b and b[0] is not None:
                    try:
                        blobs[str(r["seq"])] = bytes(b[0]).decode("utf-8")
                    except UnicodeDecodeError:
                        pass
    v = verify_chain(rs, {int(k): v.encode() for k, v in blobs.items()})
    return {"algorithm": "sha256 over canonical JSON (sorted keys, no spaces, ASCII escapes) of every field except receipt_hash",
            "genesis": GENESIS, "count": len(rs), "head": v["head"], "entries": rs, "bytes": blobs, "scope": "every row in the gateway ledger"}
