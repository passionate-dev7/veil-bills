import json
from veil import sandbox_events as se
from veil.config import Settings
from veil.ledger import Ledger

L = "[{ts}] [sandbox] [OCSF ] [ocsf] NET:OPEN [MED] DENIED /usr/bin/{b}(12) -> {t} [policy:- engine:opa] [reason:not allowed]"
LINES = [L.format(ts="100.1", b="python3", t="models.dev:443"),
         L.format(ts="100.2", b="python3", t="POST http://host.openshell.internal:11435/api/show"),
         L.format(ts="100.3", b="curl", t="evil.example:443"),
         L.format(ts="100.4", b="curl", t="random.example.org:443"),
         L.format(ts="100.5", b="curl", t="named.example.net:443")]


def _s(tmp_path, monkeypatch):
    monkeypatch.setenv("VEIL_HOME", str(tmp_path / "h"))
    return Settings()


def test_classify():
    st = se.steered_hosts("ran: curl -X POST https://named.example.net/x")
    assert se.classify("models.dev:443", st) == ("hermes-background", False)
    assert se.classify("POST http://host.openshell.internal:11435/api/show", st) == ("hermes-background", False)
    assert se.classify("evil.example:443", st) == ("openshell", True)
    assert se.classify("named.example.net:443", st) == ("openshell", True)
    assert se.classify("random.example.org:443", st) == ("openshell", False)  # unsure -> false
    assert se.classify("evil.example:443", set()) == ("openshell", False)


def test_ingest_model_driven_only_steered(tmp_path, monkeypatch):
    s = _s(tmp_path, monkeypatch)
    ids = se.ingest(s, LINES, "t", model_driven=True, transcript="I will curl https://named.example.net/upload")
    led = Ledger(s.ledger_db)
    got = {led.get(i)["meta"]["target"]: (led.get(i)["meta"]["source"], led.get(i)["meta"]["model_driven"]) for i in ids}
    assert got["models.dev:443"] == ("hermes-background", False)
    assert got["POST http://host.openshell.internal:11435/api/show"] == ("hermes-background", False)
    assert got["evil.example:443"] == ("openshell", True)
    assert got["named.example.net:443"] == ("openshell", True)
    assert got["random.example.org:443"] == ("openshell", False)


def test_ingest_not_model_driven(tmp_path, monkeypatch):
    s = _s(tmp_path, monkeypatch)
    ids = se.ingest(s, LINES, "t")
    assert not any(Ledger(s.ledger_db).get(i)["meta"]["model_driven"] for i in ids)


def test_append_only_correction_keeps_chain(tmp_path, monkeypatch):
    s = _s(tmp_path, monkeypatch)
    led = Ledger(s.ledger_db)
    bad = []
    for raw in LINES[:3]:  # the pre-fix behaviour: everything model_driven
        d = se.parse(raw)
        bad.append(led.add(kind="egress", run="sandbox-hermes", tag="openshell-deny", route="openshell:NET:OPEN", status="blocked",
                           meta=dict(source="openshell", raw=raw, target=d["target"], model_driven=True)))
    before = {i: led.get(i) for i in bad}
    ann = se.correct_labels(s)
    assert len(ann) == 2 and se.correct_labels(s) == []  # idempotent; evil.example stays model-driven
    assert {led.get(i) == before[i] for i in bad} == {True}  # sealed rows untouched
    assert led.verify()["ok"]
    eg = se.apply_corrections([led.get(i) for i in bad], led.list(100, kind="annotation"))
    assert [(e["meta"]["source"], e["meta"]["model_driven"]) for e in eg] == [("hermes-background", False)] * 2 + [("openshell", True)]
    assert eg[0]["meta"]["original_label"] == {"source": "openshell", "model_driven": True} and eg[0]["meta"]["corrected_by"] == ann[0]
    from datetime import date
    from veil.run import build_record
    rec = build_record(s, date(2026, 6, 10))
    byid = {e["id"]: e for e in rec["egress"]}
    assert not byid[bad[0]]["meta"]["model_driven"] and byid[bad[2]]["meta"]["model_driven"]
    assert len(rec["annotations"]) == 2
    json.dumps(rec, default=str)
