"""Sandbox integration: host-side tool endpoints the OpenShell sandbox can reach, and real deny-log ingestion."""
import json
from veil import sandbox_events
from veil.egress import Outbox

DENY = "[1793267452.424] [sandbox] [OCSF ] [ocsf] NET:OPEN [MED] DENIED /usr/bin/curl(1940) -> evil.example:443 [policy:- engine:opa] [reason:endpoint evil.example:443 is not allowed by any policy]"
OK = "[1793267452.500] [sandbox] [OCSF ] [ocsf] NET:OPEN [INFO] ALLOWED /usr/bin/curl(1941) -> host.openshell.internal:8000 [policy:veil engine:opa]"


def test_parse_real_ocsf_deny_line_and_ignore_allowed():
    d = sandbox_events.parse(DENY)
    assert d["bin"] == "/usr/bin/curl" and d["target"] == "evil.example:443" and d["kind"] == "NET:OPEN"
    assert sandbox_events.parse(OK) is None


def test_ingest_is_idempotent_and_marks_openshell_live(settings):
    ids = sandbox_events.ingest(settings, [DENY, OK], trigger="unit test")
    assert len(ids) == 1
    assert sandbox_events.ingest(settings, [DENY], trigger="again") == []
    from veil.ledger import Ledger
    e = Ledger(settings.ledger_db).get(ids[0])
    assert e["status"] == "blocked" and e["meta"]["source"] == "openshell" and e["meta"]["raw"] == DENY and e["meta"]["trigger"] == "unit test"
    assert sandbox_events.ingest(settings, [DENY], trigger="x", since=9e12) == []


def test_queue_email_blocks_unlisted_recipient_and_ledgers_it(client, settings):
    r = client.post("/tools/veil/queue_email", json={"to": "billing-audit@evil.example", "subject": "bill", "body": "SYNTHETIC"})
    assert r.status_code == 403 and r.json()["status"] == "blocked"
    from veil.ledger import Ledger
    rows = Ledger(settings.ledger_db).list(20, kind="egress")
    assert rows[0]["status"] == "blocked" and rows[0]["meta"]["source"] == "sandbox-agent"
    assert not list(settings.outbox.glob("*.json"))


def test_queue_email_allowed_recipient_is_only_a_pending_draft(client, settings):
    to = "appeals@northstarhealth.example"   # on demo/profile.json trusted_contacts
    r = client.post("/tools/veil/queue_email", json={"to": [to], "subject": "Appeal", "body": "SYNTHETIC draft"})
    assert r.status_code == 200 and r.json()["status"] == "pending_approval"
    assert not list(settings.mailbox.glob("*")) if settings.mailbox.exists() else True   # nothing delivered without approval


def test_audit_rejects_unknown_and_traversal_paths(client):
    r = client.post("/tools/veil/audit", json={"files": ["../../etc/passwd"]})
    assert r.status_code == 404 and "passwd" in r.text   # reduced to a basename, then not found in the corpus
    assert client.post("/tools/veil/audit", content="nope").status_code == 400


def test_lookup_rejects_free_text_topic(client):
    r = client.post("/tools/veil/lookup_appeal_rules", json={"insurer_type": "Jane Doe NSH884217353", "topic": "x"})
    assert r.status_code == 400


def test_tool_callbacks_loop_back_to_our_own_listener_not_the_host_header(client, monkeypatch):
    """From the sandbox the Host header is host.openshell.internal:8000, which does not resolve on the host: tool-internal gateway calls must use loopback."""
    import veil.sandbox_tools as st, veil.research as research
    seen = {}
    monkeypatch.setattr(research, "lookup", lambda gw, *a, **k: seen.setdefault("url", gw.url) and {"ok": True})
    r = client.post("/tools/veil/lookup_appeal_rules", json={"insurer_type": "aca_marketplace", "topic": "external_review"}, headers={"host": "host.openshell.internal:8000"})
    assert r.status_code == 200 and seen["url"].startswith("http://127.0.0.1:") and "openshell" not in seen["url"]
