"""Live smoke test: real Nebius Token Factory through the gateway. Skipped without NEBIUS_API_KEY (run: pytest -m live)."""
import pytest
from fastapi.testclient import TestClient
from veil.config import Settings, ULTRA, LIGHTNING, load_api_key
from veil.gateway import create_app

pytestmark = [pytest.mark.live, pytest.mark.skipif(not load_api_key(), reason="no NEBIUS_API_KEY")]


def test_ultra_through_gateway_sees_only_tokens(tmp_path):
    app = create_app(Settings(home=tmp_path / ".veil"))
    with TestClient(app) as c:
        r = c.post("/v1/chat/completions", headers={"x-veil-tag": "live-smoke"}, json={
            "model": ULTRA, "max_tokens": 1500, "temperature": 0,
            "messages": [{"role": "user", "content": "Write one sentence thanking Jane Doe (Member ID NSH884217353, jane.doe@example.org) "
                                                     "for her claim CN77310452 of $412.00. Repeat her name, member id and email exactly as written."}]})
        assert r.status_code == 200, r.text
        j = r.json()
        text = j["choices"][0]["message"]["content"]
        assert "Jane Doe" in text and "NSH884217353" in text      # rehydrated locally
        e = c.get("/ledger?full=true&limit=1").json()["entries"][0]
        sent = e["outbound_text"]
        assert "Jane Doe" not in sent and "NSH884217353" not in sent and "jane.doe@example.org" not in sent
        assert "[PERSON_1]" in sent and "$412.00" in sent and "CN77310452" not in sent  # amounts stay clear, claim no. tokenized
        assert e["upstream_id"] and e["usage"]["total_tokens"] > 0 and e["leaked_count"] == 0
        print("receipt:", e["upstream_id"], e["upstream_model"], e["usage"]["total_tokens"], "tokens", e["latency_ms"], "ms")


def test_lightning_models_listed_and_superless():
    with TestClient(create_app(Settings())) as c:
        ids = {m["id"] for m in c.get("/v1/models").json()["data"]}
        assert ids == {ULTRA, LIGHTNING}
