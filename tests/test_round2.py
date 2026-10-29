"""Round 2: Tavily tool path, research whitelist, memory, scheduler, watcher, approval app, gateway identity."""
import json, sys
from datetime import date
from pathlib import Path
import httpx, pytest
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).parent))
from test_audit import E, bill, line   # noqa: E402
from veil import research, watch as watchmod   # noqa: E402
from veil.config import Settings   # noqa: E402
from veil.memory import Memory   # noqa: E402

AS_OF = date(2026, 10, 29)
CONTACT = "appeals@northstarhealth.example"


# ---- Tavily through the gateway ------------------------------------------------------------------
@pytest.fixture
def search_client(settings):
    from veil.gateway import create_app
    seen = []

    def handler(req: httpx.Request):
        seen.append(req.content)
        return httpx.Response(200, json={"request_id": "req-1", "answer": "180 days", "response_time": 0.5,
                                         "results": [{"title": "t", "url": "https://www.healthcare.gov/x", "content": "c", "score": 0.9}]})
    with TestClient(create_app(settings, transport=httpx.MockTransport(handler))) as c:
        c.seen = seen
        yield c


def test_search_query_with_a_vault_value_is_blocked_before_leaving(search_client, settings):
    pseudo = search_client.app.state.pseudo
    pseudo.redact_payload({"x": "Patient Jane Doe member NSH884217353"}, None)   # puts the identifiers in the vault
    orig = pseudo.redact_payload
    pseudo.redact_payload = lambda obj, counts=None: obj                          # simulate a redactor bug; the canary is the last line
    try:
        r = search_client.post("/tools/search", json={"query": "appeal for Jane Doe NSH884217353"})
    finally:
        pseudo.redact_payload = orig
    assert r.status_code == 422 and r.json()["error"]["code"] == "leak_blocked"
    assert search_client.seen == []                                               # nothing sent upstream
    row = search_client.get("/ledger").json()["entries"][0]
    assert row["kind"] == "search" and row["status"] == "blocked" and "Jane Doe" not in json.dumps(row)


def test_search_clean_query_ok_and_ledgered(search_client):
    r = search_client.post("/tools/search", json={"query": research.build_query("aca_marketplace", "internal_appeal_deadline")})
    assert r.status_code == 200 and r.json()["veil"]["ledger_id"]
    assert json.loads(search_client.seen[0])["query"].startswith("ACA marketplace")
    row = search_client.get("/ledger").json()["entries"][0]
    assert row["kind"] == "search" and row["route"] == "tavily" and row["status"] == "ok"


# ---- research tool whitelist ------------------------------------------------------------------------
def test_research_enums_only_and_query_is_non_identifying():
    for bad in (("aca_marketplace", "Jane Doe"), ("Jane Doe", "balance_billing"), ("x", "y")):
        with pytest.raises(ValueError):
            research.build_query(*bad)
    for i in research.INSURER_TYPES:
        for t in research.TOPICS:
            q = research.build_query(i, t)
            assert "@" not in q and not any(ch.isdigit() for ch in q.replace("180", "").replace("2026", ""))


# ---- memory persistence -------------------------------------------------------------------------------
def test_memory_survives_a_new_instance(tmp_path):
    p = tmp_path / "m.sqlite"
    m = Memory(p)
    m.add_note("called billing", "C1"); m.set_fact("deductible", {"met": 100}); m.event("x", "hello")
    m2 = Memory(p)
    assert m2.notes()[0]["text"] == "called billing" and m2.fact("deductible") == {"met": 100} and m2.events()[0]["title"] == "hello"


# ---- watcher + scheduler ------------------------------------------------------------------------------
class Gw:
    run = "t"


@pytest.fixture
def engine(settings, tmp_path, monkeypatch):
    docs = {"a_eob.pdf": dict(E, appeals_contact=CONTACT), "b_bill.pdf": bill([line("99283", 1640), line("73610", 480), line("29515", 720)], 2840)}
    monkeypatch.setattr(watchmod, "pdf_text", lambda p: f"{p.name} {CONTACT}")
    monkeypatch.setattr(watchmod, "extract", lambda gw, text, name: (dict(docs[name]), {}))
    inbox = tmp_path / "inbox"; inbox.mkdir()
    for n in docs:
        (inbox / n).write_bytes(b"%PDF-1.4 " + n.encode())
    return watchmod.Engine(settings, Gw(), as_of=AS_OF, say=lambda *a, **k: None, appeal=False, within=21), inbox


def test_watcher_ingests_once_finds_and_schedules_one_followup(engine):
    eng, inbox = engine
    r = eng.process_inbox(inbox, settle_s=0)
    assert sorted(r["added"]) == ["a_eob.pdf", "b_bill.pdf"] and r["new_findings"] == 2
    assert len(r["followups"]) == 1 and r["followups"][0]["status"] == "pending_approval" and r["followups"][0]["to"] == [CONTACT]
    r2 = eng.process_inbox(inbox, settle_s=0)                                # nothing new: no re-ingest, no second follow-up
    assert r2["added"] == [] and r2["followups"] == []
    assert len(eng.outbox.list()) == 1
    kinds = [e["kind"] for e in eng.mem.events(limit=50)]
    assert "document" in kinds and "finding" in kinds and "followup" in kinds


def test_scheduler_skips_expired_and_far_deadlines(engine):
    eng, inbox = engine
    eng.process_inbox(inbox, settle_s=0)
    far = watchmod.Engine(eng.s, Gw(), mem=Memory(eng.s.home / "far.sqlite"), as_of=date(2026, 6, 1), say=lambda *a, **k: None, appeal=False, within=21)
    for p in sorted(inbox.glob("*.pdf")):
        far.ingest(p)
    assert far.schedule() == []                                              # 164 days left > 21
    late = watchmod.Engine(eng.s, Gw(), mem=far.mem, as_of=date(2026, 12, 1), say=lambda *a, **k: None, appeal=False, within=21)
    assert late.schedule() == []                                             # closed on 2026-11-16


# ---- approval app ---------------------------------------------------------------------------------------
@pytest.fixture
def app_client(settings):
    from veil.app import create_app
    with TestClient(create_app(settings, AS_OF)) as c:
        yield c, settings


def test_approve_writes_only_an_eml_and_reject_and_allowlist(app_client):
    from veil.egress import Outbox
    c, s = app_client
    ob = Outbox(s)
    good = ob.queue([CONTACT], "Appeal", "Dear plan, $412.00", "t")
    bad = ob.queue(["billing-audit@evil.example"], "x", "y", "t")          # cannot be queued by the agent; forced in to test approve's re-check
    rej = ob.queue([CONTACT], "No", "no", "t")
    r = c.post(f"/api/drafts/{good['id']}/approve")
    assert r.status_code == 200 and "X-Veil-Sandbox" in r.json()["eml_text"]
    assert [p.name for p in s.mailbox.iterdir()] == [f"{good['id']}.eml"]
    assert c.post(f"/api/drafts/{good['id']}/approve").status_code == 409     # no double delivery
    assert c.post(f"/api/drafts/{bad['id']}/approve").status_code == 403
    assert c.post(f"/api/drafts/{rej['id']}/reject").json()["status"] == "rejected"
    assert c.post(f"/api/drafts/{rej['id']}/approve").status_code == 409
    assert sorted(p.name for p in s.mailbox.iterdir()) == [f"{good['id']}.eml"]
    assert c.post("/api/drafts/nope/approve").status_code == 404
    assert any(e["kind"] == "approved" for e in c.get("/api/run").json()["events"])


# ---- gateway identity -----------------------------------------------------------------------------------
def test_ensure_gateway_refuses_a_foreign_service(monkeypatch):
    import threading, http.server, socketserver
    from veil import client

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers(); self.wfile.write(b'{"ok":true,"service":"qwen-proxy"}')
        def log_message(self, *a): pass
    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pytest.raises(Exception, match="different service"):
            client.ensure_gateway(f"http://127.0.0.1:{srv.server_address[1]}")
    finally:
        srv.shutdown()
