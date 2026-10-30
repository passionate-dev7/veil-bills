"""Tamper-evident receipt chain: intact, edit, delete, reorder, swapped bytes, ledger-side tampering, and JS == Python hashing."""
import copy, hashlib, json, shutil, sqlite3, subprocess
import pytest
from veil import receipts as rc
from veil.config import ROOT
from veil.ledger import Ledger

BODY = json.dumps({"model": "m", "messages": [{"role": "user", "content": "hello [PERSON_1] CPT 36415 $35.00 caf\u00e9"}]}, ensure_ascii=False).encode()


@pytest.fixture
def led(tmp_path):
    L = Ledger(tmp_path / "ledger.sqlite")
    a = L.add(kind="inference", route="chat", model="m", tag="a", status="pending", outbound=BODY)
    L.update(a, status="ok", http_status=200, usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}, upstream_id="chatcmpl-x")
    L.add(kind="inference", route="chat", model="m", tag="b", status="blocked", leaked_count=2, reason="canary")  # 422: no bytes
    L.add(kind="egress", route="tool:queue_email", status="blocked", reason="recipient not on allowlist", meta={"to": ["x@evil.example"]})
    c = L.add(kind="search", route="tavily", model="tavily/search", status="pending", outbound=b'{"query":"CPT 36415"}')
    L.update(c, status="ok", http_status=200, usage={"credits": 1})
    d = L.add(kind="inference", route="chat", model="m", tag="d", status="pending", outbound=BODY + b" ")
    L.update(d, status="ok", http_status=200, usage={"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6})
    return L


def chain(L):
    return rc.load(L.db)


def test_genesis_is_the_documented_constant():
    assert rc.GENESIS == hashlib.sha256(b"veil/receipts/genesis/v1").hexdigest()


def test_intact_chain_verifies_and_every_call_has_a_receipt(led):
    rs = chain(led)
    assert [r["seq"] for r in rs] == list(range(1, len(rs) + 1))
    assert rs[0]["prev_hash"] == rc.GENESIS
    assert all(rs[i]["prev_hash"] == rs[i - 1]["receipt_hash"] for i in range(1, len(rs)))
    calls = [r for r in rs if r["type"] == "call"]
    assert len(calls) == 5  # every ledger row, including the 422 and the denied egress
    v = led.verify()
    assert v["ok"] and v["count"] == len(rs) and v["head"] == rs[-1]["receipt_hash"] and v["ledger_rows"] == 5
    assert v["bytes_checked"] == 3


def test_receipt_fields(led):
    rs = chain(led)
    c, res = rs[0], rs[1]
    assert (c["type"], c["status"], c["destination_host"], c["destination_path"]) == ("call", "pending", "api.tokenfactory.nebius.com", "/v1/chat/completions")
    assert c["byte_count"] == len(BODY) and c["sha256"] == hashlib.sha256(BODY).hexdigest() and c["tokens"] is None
    assert (res["type"], res["ledger_id"], res["status"], res["http_status"]) == ("result", 1, "sent", 200)
    assert res["tokens"] == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
    blocked = next(r for r in rs if r["status"] == "blocked_422")
    assert blocked["byte_count"] == 0 and blocked["sha256"] is None  # nothing left, nothing stored
    denied = next(r for r in rs if r["status"] == "denied")
    assert denied["destination_host"] == "evil.example" and denied["destination_path"] == "tool:queue_email"
    assert next(r for r in rs if r["destination_host"] == "api.tavily.com")["destination_path"] == "/search"


def test_receipt_is_written_when_the_call_is_logged(led):
    n = len(chain(led))
    i = led.add(kind="inference", route="chat", model="m", status="pending", outbound=b"{}")
    assert len(chain(led)) == n + 1 and chain(led)[-1]["type"] == "call"  # sealed at log time, before the upstream answers
    assert led.verify()["ok"]
    led.update(i, status="error", reason="upstream: Timeout")
    assert chain(led)[-1]["type"] == "result" and chain(led)[-1]["status"] == "error"


def test_edit_a_receipt_field(led):
    led.db.execute("UPDATE receipts SET receipt=? WHERE seq=3", (json.dumps({**chain(led)[2], "byte_count": 999}),)); led.db.commit()
    b = led.verify()["broken"]
    assert (b["seq"], b["code"]) == (3, "edited")


def test_edit_and_rehash_breaks_the_next_link(led):
    r = chain(led)[2]; r["status"] = "sent"; r["receipt_hash"] = rc.receipt_hash(r)
    led.db.execute("UPDATE receipts SET receipt=? WHERE seq=3", (json.dumps(r),)); led.db.commit()
    b = led.verify()["broken"]
    assert (b["seq"], b["code"]) == (4, "link")


def test_delete_a_receipt(led):
    led.db.execute("DELETE FROM receipts WHERE seq=4"); led.db.commit()
    b = led.verify()["broken"]
    assert (b["seq"], b["code"]) == (4, "missing")


def test_delete_the_422_receipt_is_visible(led):
    seq = next(r["seq"] for r in chain(led) if r["status"] == "blocked_422")
    led.db.execute("DELETE FROM receipts WHERE seq=?", (seq,)); led.db.commit()
    b = led.verify()["broken"]
    assert b["seq"] == seq and b["code"] == "missing"


def test_reorder_receipts(led):
    swapped = copy.deepcopy(chain(led)); swapped[0], swapped[1] = swapped[1], swapped[0]
    b = rc.verify_chain(swapped)["broken"]
    assert (b["seq"], b["code"]) == (1, "reordered")


def test_truncated_tail_needs_the_anchored_head(led):
    head = led.verify()["head"]
    led.db.execute("DELETE FROM receipts WHERE seq=(SELECT MAX(seq) FROM receipts)"); led.db.commit()
    assert not led.verify()["ok"]  # against the ledger the missing result is visible too; the chain alone is not enough
    rs = chain(led)
    assert rc.verify_chain(rs)["ok"]  # the chain alone cannot see the truncation ...
    b = rc.verify_chain(rs, expect_head=head)["broken"]  # ... the anchored head can
    assert b["code"] == "head"


def test_swapped_stored_bytes_are_caught(led):
    led.db.execute("UPDATE ledger SET outbound=? WHERE id=1", (BODY.replace(b"hello", b"jello"),)); led.db.commit()
    b = led.verify()["broken"]
    assert (b["seq"], b["code"]) == (1, "bytes")


def test_one_flipped_byte_changes_the_hash_not_the_length(led):
    flipped = bytearray(BODY); flipped[10] ^= 1
    led.db.execute("UPDATE ledger SET outbound=? WHERE id=1", (bytes(flipped),)); led.db.commit()
    assert len(flipped) == len(BODY) and led.verify()["broken"]["code"] == "bytes"


def test_length_change_is_caught(led):
    led.db.execute("UPDATE ledger SET outbound=? WHERE id=1", (BODY + b"x",)); led.db.commit()
    assert led.verify()["broken"]["code"] == "byte_count"


def test_ledger_row_deleted_or_inserted_or_status_edited(led, tmp_path):
    import shutil
    for sql, code in [("DELETE FROM ledger WHERE id=2", "ledger_row_deleted"),
                      ("INSERT INTO ledger(kind,route,status) VALUES('inference','chat','ok')", "unreceipted"),
                      ("UPDATE ledger SET status='ok', leaked_count=0 WHERE id=2", "ledger_edited"),
                      ("UPDATE ledger SET usage='{\"total_tokens\": 1, \"prompt_tokens\": 1, \"completion_tokens\": 0}' WHERE id=1", "ledger_edited")]:
        shutil.copy(tmp_path / "ledger.sqlite", tmp_path / "c.sqlite")
        db = sqlite3.connect(tmp_path / "c.sqlite"); db.execute(sql); db.commit()
        v = rc.verify_db(db)
        assert not v["ok"] and v["broken"]["code"] == code, (sql, v["broken"])


def test_first_open_backfills_existing_rows_once(tmp_path):
    db = sqlite3.connect(tmp_path / "old.sqlite")
    from veil.ledger import SCHEMA
    db.executescript(SCHEMA)
    db.execute("INSERT INTO ledger(id,ts,kind,route,status,outbound,outbound_sha256,outbound_bytes) VALUES(5,'t','inference','chat','ok',?,?,?)", (BODY, hashlib.sha256(BODY).hexdigest(), len(BODY)))
    db.execute("INSERT INTO ledger(id,ts,kind,route,status,leaked_count) VALUES(9,'t','inference','chat','blocked',3)")  # gaps in ids are fine
    db.commit(); db.close()
    L = Ledger(tmp_path / "old.sqlite")
    rs = chain(L)
    assert [r["origin"] for r in rs] == ["backfill"] * 3 and [r["ledger_id"] for r in rs] == [5, 5, 9]
    assert L.verify()["ok"]
    n = len(rs)
    Ledger(tmp_path / "old.sqlite")  # reopening does not re-backfill
    assert len(chain(Ledger(tmp_path / "old.sqlite"))) == n


def test_gateway_logs_receipts(client, fake):
    from tests.test_gateway import chat
    assert chat(client).status_code == 200
    L = client.app_.state.ledger
    rs = chain(L)
    assert [r["type"] for r in rs] == ["call", "result"]
    assert rs[0]["sha256"] == hashlib.sha256(fake.received[0]).hexdigest() and rs[1]["tokens"]["total_tokens"] == 18
    assert L.verify()["ok"]


def test_gateway_422_gets_a_receipt(client, fake, monkeypatch):
    from tests.test_gateway import chat
    monkeypatch.setattr(client.app_.state.pseudo, "redact_payload", lambda obj, counts=None: obj)
    assert chat(client).status_code == 422
    rs = chain(client.app_.state.ledger)
    assert [(r["type"], r["status"]) for r in rs] == [("call", "blocked_422")] and rs[0]["sha256"] is None
    assert client.app_.state.ledger.verify()["ok"]


def test_export_chain_verifies_standalone(led):
    ex = led.chain()
    assert ex["head"] == led.verify()["head"] and ex["genesis"] == rc.GENESIS and ex["count"] == len(ex["entries"])
    blobs = {int(k): v.encode() for k, v in ex["bytes"].items()}
    assert rc.verify_chain(ex["entries"], blobs)["ok"] and len(blobs) == 3


def _variants(led):
    ex = led.chain(); E, B = ex["entries"], ex["bytes"]
    seq_b = next(r["seq"] for r in E if r["type"] == "call" and str(r["seq"]) in B)
    v = [dict(name="intact", entries=E, bytes=B)]
    e = copy.deepcopy(E); e[2]["byte_count"] += 1; v.append(dict(name="edit", entries=e, bytes=B))
    e = copy.deepcopy(E); del e[3]; v.append(dict(name="delete", entries=e, bytes=B))
    e = copy.deepcopy(E); e[0], e[1] = e[1], e[0]; v.append(dict(name="reorder", entries=e, bytes=B))
    b = dict(B); t = bytearray(b[str(seq_b)].encode()); t[12] ^= 1; b[str(seq_b)] = t.decode(); v.append(dict(name="bytes", entries=E, bytes=b))
    v.append(dict(name="head", entries=E[:-1], bytes=B, head=ex["head"]))
    return v


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_js_and_python_agree(led, tmp_path):
    variants = _variants(led)
    canon_cases = [{"b": [1, None, True], "a": "caf\u00e9 \u007f \"q\" \\ \n \u2028 \U0001F600"}, {"z": {"y": 1, "x": None}}, [], "x"]
    p = tmp_path / "in.json"; p.write_text(json.dumps({"canon": canon_cases, "variants": variants}))
    out = json.loads(subprocess.run(["node", str(ROOT / "tests" / "receipts_parity.mjs"), str(p)], capture_output=True, text=True, check=True).stdout)
    assert [c.encode("ascii") for c in out["canon"]] == [rc.canonical(c) for c in canon_cases]
    assert out["hashes"] == [rc.receipt_hash(r) for r in variants[0]["entries"]] == [r["receipt_hash"] for r in variants[0]["entries"]]
    for v in variants:
        py = rc.verify_chain(v["entries"], {int(k): t.encode() for k, t in v["bytes"].items()}, v.get("head"))
        assert out["results"][v["name"]] == py, v["name"]
    assert out["results"]["intact"]["ok"]
    assert {n: r["broken"]["code"] for n, r in out["results"].items() if not r["ok"]} == {"edit": "edited", "delete": "missing", "reorder": "reordered", "bytes": "bytes", "head": "head"}


def _cli(*args):
    import sys
    return subprocess.run([sys.executable, "-m", "veil", *args], cwd=ROOT, capture_output=True, text=True)


def test_cli_verify_exits_zero_when_intact_and_nonzero_at_the_first_break(led, tmp_path):
    db = tmp_path / "ledger.sqlite"
    ok = _cli("verify", "--db", str(db))
    assert ok.returncode == 0 and ok.stdout.startswith("OK") and "head " in ok.stdout and "tamper-evident, not tamper-proof" in ok.stdout
    head = [l for l in ok.stdout.splitlines() if l.strip().startswith("head ")][0].split()[1]
    assert _cli("verify", "--db", str(db), "--head", head).returncode == 0
    assert _cli("verify", "--db", str(db), "--head", "0" * 64).returncode == 1
    con = sqlite3.connect(db)
    con.execute("UPDATE ledger SET outbound=? WHERE id=1", (BODY.replace(b"hello", b"jello"),)); con.commit(); con.close()
    bad = _cli("verify", "--db", str(db))
    assert bad.returncode == 1 and bad.stdout.startswith("FAIL") and "seq 1 (bytes)" in bad.stdout and "hash mismatch" in bad.stdout
    assert json.loads(_cli("verify", "--db", str(db), "--json").stdout)["broken"]["code"] == "bytes"


def test_cli_verify_run_json_and_demo(led, tmp_path):
    rec = tmp_path / "run.json"
    rec.write_text(json.dumps({"chain": led.chain()}))
    assert _cli("verify", "--run-json", str(rec)).returncode == 0
    d = json.loads(rec.read_text()); d["chain"]["entries"][1]["status"] = "denied"; rec.write_text(json.dumps(d))
    out = _cli("verify", "--run-json", str(rec))
    assert out.returncode == 1 and "seq 2 (edited)" in out.stdout
    demo = _cli("receipts", "demo", "--db", str(tmp_path / "ledger.sqlite"))
    assert demo.returncode == 0 and "FAIL tampered copy" in demo.stdout and "(bytes)" in demo.stdout
