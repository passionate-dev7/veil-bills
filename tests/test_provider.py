"""DEV-ONLY upstream provider switch (VEIL_PROVIDER). Token Factory stays the default; openrouter runs are labelled everywhere and kept out of the static bundle."""
import json, re, shutil, subprocess, sys
import httpx, pytest
from fastapi.testclient import TestClient
from veil import providers, receipts as rc
from veil.config import Settings, ROOT, ULTRA, LIGHTNING
from veil.gateway import create_app
from veil.ledger import Ledger
from tests.conftest import FakeUpstream

PROMPT = "Patient: Jane Doe, Member ID: NSH884217353. Claim Number: CN77310452. CPT 36415 $35.00"
SECRET_KEY = "-".join(["dummy", "openrouter", "key", "for", "tests", "only"])  # not a real key; built at runtime so no key-shaped literal sits in the repo


def make_client(tmp_path, fake, **kw):
    s = Settings(home=tmp_path / "veil", profile=ROOT / "demo" / "profile.json", provider="openrouter", api_key=SECRET_KEY, retry_base_s=0.0, **kw)
    app = create_app(s, transport=httpx.MockTransport(fake.handler))
    return TestClient(app)


@pytest.fixture
def orc(tmp_path, fake):
    with make_client(tmp_path, fake) as c:
        yield c


def chat(c, model=LIGHTNING, **kw):
    return c.post("/v1/chat/completions", json={"model": model, "messages": [{"role": "user", "content": PROMPT}], **kw}, headers={"x-veil-tag": "t"})


# ---- default and config ---------------------------------------------------------------------------------------------------------------
def test_default_is_tokenfactory_and_unchanged(monkeypatch, tmp_path):
    monkeypatch.delenv("VEIL_PROVIDER", raising=False)
    monkeypatch.setenv("NEBIUS_API_KEY", "nebius-test")
    s = Settings(home=tmp_path / "v")
    assert s.provider == "tokenfactory" and not s.dev and s.upstream == providers.TOKENFACTORY_BASE
    assert s.api_key == "nebius-test" and s.key_env == "NEBIUS_API_KEY"
    assert providers.adapt_request("tokenfactory", {"model": ULTRA, "max_tokens": 5}) == {"model": ULTRA, "max_tokens": 5}  # body untouched


def test_openrouter_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("VEIL_PROVIDER", "openrouter"); monkeypatch.setenv("OPENROUTER_API_KEY", " k-test ")
    monkeypatch.setenv("VEIL_UPSTREAM", "https://elsewhere.example/v1")  # only ever honoured for Token Factory
    s = Settings(home=tmp_path / "v")
    assert s.provider == "openrouter" and s.dev and s.upstream == "https://openrouter.ai/api/v1" and s.api_key == "k-test" and s.key_env == "OPENROUTER_API_KEY"


def test_unknown_provider_is_an_error_not_a_fallback(monkeypatch):
    monkeypatch.setenv("VEIL_PROVIDER", "nope")
    with pytest.raises(ValueError):
        providers.active_provider()


def test_no_openrouter_key_means_none_not_a_nebius_key(monkeypatch, tmp_path):
    monkeypatch.setenv("VEIL_PROVIDER", "openrouter"); monkeypatch.delenv("OPENROUTER_API_KEY", raising=False); monkeypatch.setenv("NEBIUS_API_KEY", "nebius-test")
    assert Settings(home=tmp_path / "v").api_key is None  # the Nebius key must never be sent to OpenRouter


# ---- model map and reasoning adjustments ---------------------------------------------------------------------------------------------
def test_model_map_and_request_adjustments():
    assert providers.OPENROUTER_MODELS == {ULTRA: "nvidia/nemotron-3-ultra-550b-a55b:free", LIGHTNING: "nvidia/nemotron-3.5-lightning:free"}
    b = providers.adapt_request("openrouter", {"model": ULTRA, "max_tokens": 64, "messages": []})
    assert b["model"] == "nvidia/nemotron-3-ultra-550b-a55b:free" and b["max_tokens"] == providers.MIN_MAX_TOKENS
    b = providers.adapt_request("openrouter", {"model": LIGHTNING, "messages": []})
    assert b["max_tokens"] == providers.MIN_MAX_TOKENS  # reasoning models need room to think before answering
    b = providers.adapt_request("openrouter", {"model": LIGHTNING, "max_tokens": 50, "chat_template_kwargs": {"enable_thinking": False}})
    assert b["reasoning"] == {"enabled": False} and "chat_template_kwargs" not in b and b["max_tokens"] == 50
    b = providers.adapt_request("openrouter", {"model": LIGHTNING, "chat_template_kwargs": {"enable_thinking": False, "x": 1}})
    assert b["chat_template_kwargs"] == {"x": 1}


def test_outbound_bytes_carry_the_mapped_model_and_only_tokens(orc, fake):
    r = chat(orc, model=ULTRA, max_tokens=32)
    assert r.status_code == 200 and "Jane Doe" in r.json()["choices"][0]["message"]["content"]  # rehydrated for the caller
    sent = json.loads(fake.received[0])
    assert sent["model"] == "nvidia/nemotron-3-ultra-550b-a55b:free" and sent["max_tokens"] == providers.MIN_MAX_TOKENS
    for secret in ["Jane Doe", "NSH884217353", "CN77310452"]:
        assert secret not in fake.received[0].decode()
    e = orc.get("/ledger?full=true").json()["entries"][0]
    assert e["outbound_text"] == fake.received[0].decode()  # the ledger still holds the exact bytes sent


def test_upstream_request_uses_openrouter_url_and_key_header(tmp_path):
    seen = {}
    def h(req: httpx.Request):
        seen["url"], seen["auth"] = str(req.url), req.headers["authorization"]
        return httpx.Response(200, json={"id": "g1", "model": "x", "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}], "usage": {}})
    s = Settings(home=tmp_path / "v", profile=ROOT / "demo" / "profile.json", provider="openrouter", api_key=SECRET_KEY)
    with TestClient(create_app(s, transport=httpx.MockTransport(h))) as c:
        assert chat(c).status_code == 200
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions" and seen["auth"] == f"Bearer {SECRET_KEY}"


# ---- same safety behaviour --------------------------------------------------------------------------------------------------------------
def test_canary_fails_closed_under_openrouter(orc, fake, monkeypatch):
    monkeypatch.setattr(orc.app.state.pseudo, "redact_payload", lambda obj, counts=None: obj)  # simulate a redactor bug
    r = chat(orc)
    assert r.status_code == 422 and r.json()["error"]["code"] == "leak_blocked"
    assert fake.received == []  # nothing left the machine
    assert orc.get("/ledger").json()["entries"][0]["provider"] == "openrouter"  # the blocked row is labelled too


# ---- 429 handling ------------------------------------------------------------------------------------------------------------------------
def test_429_is_retried_then_succeeds(tmp_path):
    calls = {"n": 0}
    def h(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, json={"error": {"message": "rate limited"}}, headers={"retry-after": "0"})
        return httpx.Response(200, json={"id": "g1", "model": "m", "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok [PERSON_1]"}}], "usage": {"total_tokens": 3}})
    s = Settings(home=tmp_path / "v", profile=ROOT / "demo" / "profile.json", provider="openrouter", api_key=SECRET_KEY, retry_base_s=0.0)
    with TestClient(create_app(s, transport=httpx.MockTransport(h))) as c:
        r = chat(c)
        e = c.get("/ledger").json()["entries"][0]
    assert r.status_code == 200 and calls["n"] == 3 and e["status"] == "ok" and e["meta"]["retries"] == 2


def test_429_exhausted_fails_cleanly(tmp_path):
    calls = {"n": 0}
    def h(req):
        calls["n"] += 1
        return httpx.Response(429, json={"error": {"message": "rate limited"}})
    s = Settings(home=tmp_path / "v", profile=ROOT / "demo" / "profile.json", provider="openrouter", api_key=SECRET_KEY, retries=2, retry_base_s=0.0)
    with TestClient(create_app(s, transport=httpx.MockTransport(h))) as c:
        r = chat(c)
        e = c.get("/ledger").json()["entries"][0]
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited" and calls["n"] == 3
    assert e["status"] == "error" and e["http_status"] == 429 and "rate limited" in e["reason"]


def test_429_on_stream_retries_before_first_byte(tmp_path, fake):
    n = {"c": 0}
    def h(req):
        n["c"] += 1
        return httpx.Response(429, json={}, headers={"retry-after": "0"}) if n["c"] == 1 else fake.handler(req)
    s = Settings(home=tmp_path / "v", profile=ROOT / "demo" / "profile.json", provider="openrouter", api_key=SECRET_KEY, retry_base_s=0.0)
    with TestClient(create_app(s, transport=httpx.MockTransport(h))) as c:
        with c.stream("POST", "/v1/chat/completions", json={"model": LIGHTNING, "stream": True, "messages": [{"role": "user", "content": PROMPT}]}) as r:
            body = "".join(r.iter_lines())
    assert n["c"] == 2 and "Jane" in body


# ---- labelling: ledger, receipts, run record -------------------------------------------------------------------------------------------
def test_ledger_and_receipts_carry_provider_and_verify(orc, fake):
    chat(orc)
    led: Ledger = orc.app.state.ledger
    e = orc.get("/ledger").json()["entries"][0]
    assert e["provider"] == "openrouter"
    chain = rc.load(led.db)
    assert chain and all(r["provider"] == "openrouter" for r in chain if r["type"] in ("call", "result"))
    assert rc.destination(dict(kind="inference", route="chat", provider="openrouter"))[0] == "openrouter.ai"
    assert led.verify()["ok"]
    # editing the label after the fact is detected
    led.db.execute("UPDATE ledger SET provider='tokenfactory'"); led.db.commit()
    v = led.verify()
    assert not v["ok"] and v["broken"]["code"] == "ledger_edited"


def test_legacy_receipts_without_provider_keep_their_hashes():
    legacy = rc.make(rc.GENESIS, 1, type="call", ledger_id=1, status="ok")
    assert "provider" not in legacy
    assert rc.receipt_hash(legacy) == legacy["receipt_hash"]
    with_p = rc.make(rc.GENESIS, 1, type="call", ledger_id=1, status="ok", provider="openrouter")
    assert with_p["provider"] == "openrouter" and with_p["receipt_hash"] != legacy["receipt_hash"]


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_js_hash_agrees_with_python_for_provider_receipts(tmp_path):
    r1 = rc.make(rc.GENESIS, 1, type="call", ledger_id=1, status="ok", provider="openrouter")
    p = tmp_path / "in.json"; p.write_text(json.dumps({"canon": [], "variants": [{"name": "intact", "entries": [r1], "bytes": {}}]}))
    out = json.loads(subprocess.run(["node", str(ROOT / "tests" / "receipts_parity.mjs"), str(p)], capture_output=True, text=True, check=True).stdout)
    assert out["hashes"] == [r1["receipt_hash"]] and out["results"]["intact"]["ok"]


def test_run_record_is_labelled_and_unpriced(orc, fake):
    from datetime import date
    from veil.run import build_record
    chat(orc)
    rec = build_record(orc.app.state.settings, date(2026, 10, 30), None)
    assert rec["provider"] == "openrouter" and rec["dev_fallback"] is True and rec["provider_label"] == "OpenRouter dev fallback, not a Nebius Token Factory run"
    assert all(r["provider"] == "openrouter" for r in rec["receipts"]) and rec["cost"]["total_micro_usd"] == 0 and rec["cost"]["priced_calls"] == 0
    assert "Not a Token Factory run" in rec["receipts_source"]["note"]


def test_page_shows_the_dev_label():
    html = (ROOT / "web" / "index.html").read_text()
    assert "OpenRouter dev fallback, not a Nebius Token Factory run" in html and "R.provider==='openrouter'" in html


def test_health_reports_provider(orc):
    h = orc.get("/health").json()
    assert h["provider"] == "openrouter" and h["dev_fallback"] is True and h["provider_label"] == providers.DEV_LABEL


# ---- the key never lands anywhere -----------------------------------------------------------------------------------------------------
def test_key_and_authorization_never_in_ledger_or_responses(orc, fake):
    r = chat(orc)
    full = orc.get("/ledger?full=true")
    led = orc.app.state.ledger
    dump = "\n".join(str(t) for t in led.db.iterdump())
    blobs = [bytes(b) for (b,) in led.db.execute("SELECT outbound FROM ledger") if b]
    for hay in (r.text, full.text, dump):
        assert SECRET_KEY not in hay and "Authorization" not in hay and "Bearer" not in hay
    assert all(SECRET_KEY.encode() not in b for b in blobs)
    assert SECRET_KEY not in json.dumps(orc.get("/health").json())
    assert all(SECRET_KEY not in p.read_text(errors="ignore") for p in (orc.app.state.settings.home).rglob("*") if p.is_file() and p.suffix in (".json", ".txt", ".log"))


# ---- static bundle ---------------------------------------------------------------------------------------------------------------------
def test_static_bundle_has_no_openrouter_data():
    from veil.cli import STATIC_FILES, dev_data_in
    assert "dev_runs" not in " ".join(STATIC_FILES)
    for f in STATIC_FILES:
        assert dev_data_in(ROOT / "web" / f) is None, f
    run = json.loads((ROOT / "web" / "run.json").read_text())
    assert run.get("provider", "tokenfactory") == "tokenfactory" and not run.get("dev_fallback")
    assert all(e.get("provider") in (None, "tokenfactory") for e in run.get("egress", []) + run.get("receipts", []))
    assert all(r.get("provider") in (None, "tokenfactory") for r in run["chain"]["entries"])
    assert not re.search(r'"provider"\s*:\s*"openrouter"', (ROOT / "web" / "run.js").read_text())


def test_static_command_refuses_a_dev_record(tmp_path, monkeypatch):
    import veil.cli as cli
    web = tmp_path / "web"; web.mkdir()
    for f in cli.STATIC_FILES:
        (web / f).write_text("{}")
    (web / "run.json").write_text(json.dumps({"provider": "openrouter", "dev_fallback": True}))
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    class A: out = str(tmp_path / "out")
    assert cli.cmd_static(A) == 1 and not (tmp_path / "out").exists()


def test_export_refuses_to_write_a_dev_record_into_web():
    import veil.cli as cli
    with pytest.raises(SystemExit):
        cli._write_run({"provider": "openrouter", "dev_fallback": True}, ROOT / "web" / "run.json")


def test_export_run_cli_sends_dev_record_to_dev_runs(orc, fake, tmp_path):
    import os
    chat(orc)
    home = orc.app.state.settings.home
    env = {**os.environ, "VEIL_HOME": str(home), "VEIL_PROVIDER": "openrouter"}
    before = (ROOT / "web" / "run.json").read_bytes()
    r = subprocess.run([sys.executable, "-m", "veil", "export-run"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout
    out = list((home / "dev_runs").glob("run_openrouter_*.json"))
    assert len(out) == 1 and json.loads(out[0].read_text())["dev_fallback"] is True
    assert (ROOT / "web" / "run.json").read_bytes() == before
