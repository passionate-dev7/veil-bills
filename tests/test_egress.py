import pathlib
import pytest
from veil.appeal import handle_tool, parse_args, safe_calc
from veil.config import Settings, ROOT
from veil.egress import Policy, Outbox


@pytest.fixture
def env(tmp_path):
    s = Settings(home=tmp_path / ".veil", api_key="x")
    return s, dict(policy=Policy(s), outbox=Outbox(s), run="t", tag="tag")


def test_injected_recipient_is_blocked_and_logged(env):
    s, ctx = env
    out, ev = handle_tool("queue_email", {"to": ["billing-audit@evil.example"], "subject": "bill", "body": "x"}, ctx)
    assert "REFUSED" in out and ev["allowed"] is False
    assert ctx["outbox"].list() == []                      # nothing queued
    row = ctx["policy"].ledger.list(kind="egress")[0]
    assert row["status"] == "blocked" and "evil.example" in row["reason"]


def test_trusted_recipient_queues_pending_then_human_approval_writes_sandbox_eml(env):
    s, ctx = env
    out, ev = handle_tool("queue_email", {"to": ["appeals@northstarhealth.example"], "subject": "Appeal", "body": "Dear plan"}, ctx)
    assert ev["allowed"] and ev["draft_id"]
    d = ctx["outbox"].get(ev["draft_id"])
    assert d["status"] == "pending_approval"
    assert not s.mailbox.exists() or not list(s.mailbox.glob("*.eml"))  # nothing delivered before approval
    d = ctx["outbox"].approve(d["id"], ctx["policy"])
    eml = pathlib.Path(d["eml"])
    assert d["status"] == "delivered_to_sandbox" and eml.parent == s.mailbox and "Dear plan" in eml.read_text()


def test_approval_rechecks_allowlist(env):
    s, ctx = env
    d = ctx["outbox"].queue(["x@evil.example"], "s", "b", "t")  # a tampered draft
    with pytest.raises(PermissionError):
        ctx["outbox"].approve(d["id"], ctx["policy"])


def test_package_has_no_network_mail_code():
    src = "\n".join(p.read_text() for p in (ROOT / "veil").glob("*.py"))
    assert "smtplib" not in src and "sendmail" not in src


def test_calc_and_arg_repair():
    assert safe_calc("2840 - 412") == "2428.00"
    assert safe_calc("__import__('os')").startswith("error")
    assert parse_args('{"body": "a\\[x]"}') == {"body": "a\\[x]"}  # stray backslash repaired, not fatal
