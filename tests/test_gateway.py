import json
from veil.config import ULTRA, LIGHTNING

PROMPT = "Patient: Jane Doe, Member ID: NSH884217353. Claim Number: CN77310452. CPT 36415 $35.00"


def chat(client, **kw):
    body = {"model": LIGHTNING, "messages": [{"role": "user", "content": PROMPT}], **kw}
    return client.post("/v1/chat/completions", json=body, headers={"x-veil-tag": "t"})


def test_models(client):
    ids = [m["id"] for m in client.get("/v1/models").json()["data"]]
    assert ids == [ULTRA, LIGHTNING]


def test_upstream_sees_only_tokens_and_response_is_rehydrated(client, fake):
    r = chat(client)
    assert r.status_code == 200
    sent = fake.received[0].decode()
    for secret in ["Jane Doe", "NSH884217353", "CN77310452"]:
        assert secret not in sent
    assert "[PERSON_1]" in sent and "36415" in sent and "$35.00" in sent
    assert "Jane Doe" in r.json()["choices"][0]["message"]["content"]  # echo came back rehydrated
    e = client.get("/ledger?full=true").json()["entries"][0]
    assert e["outbound_text"] == sent  # the ledger holds the exact bytes the upstream received
    assert e["redacted_total"] >= 3 and e["leaked_count"] == 0 and e["status"] == "ok"
    assert e["usage"]["total_tokens"] == 18


def test_tool_call_arguments_rehydrated(client, fake):
    fake.reply = lambda b: {"id": "c1", "model": b["model"], "usage": {}, "choices": [{"index": 0, "finish_reason": "tool_calls",
        "message": {"role": "assistant", "content": None, "tool_calls": [{"id": "t", "type": "function",
        "function": {"name": "queue_email", "arguments": json.dumps({"to": "[EMAIL_1]", "body": "re [PERSON_1]"})}}]}}]}
    r = client.post("/v1/chat/completions", json={"model": ULTRA, "messages": [
        {"role": "user", "content": "Patient: Jane Doe, jane.doe@example.org"}]})
    args = json.loads(r.json()["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
    assert args == {"to": "jane.doe@example.org", "body": "re Jane Doe"}


def test_streaming_passthrough_rehydrates(client, fake):
    with client.stream("POST", "/v1/chat/completions", json={"model": LIGHTNING, "stream": True,
                       "messages": [{"role": "user", "content": PROMPT}]}) as r:
        text = ""
        for line in r.iter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                for c in json.loads(line[6:]).get("choices", []):
                    text += c.get("delta", {}).get("content", "") or ""
    assert "Jane Doe" in text and "[PERSON_1]" not in text
    assert "Jane Doe" not in fake.received[0].decode()
    e = client.get("/ledger").json()["entries"][0]
    assert e["stream"] == 1 and e["usage"]["total_tokens"] == 18


def test_canary_fails_closed(client, fake, monkeypatch):
    pseudo = client.app_.state.pseudo
    monkeypatch.setattr(pseudo, "redact_payload", lambda obj, counts=None: obj)  # simulate a redactor bug
    r = chat(client)
    assert r.status_code == 422 and r.json()["error"]["code"] == "leak_blocked"
    assert fake.received == []  # nothing left the machine
    e = client.get("/ledger").json()["entries"][0]
    assert e["status"] == "blocked" and e["leaked_count"] >= 3 and e["outbound_bytes"] is None
    assert "Jane Doe" not in json.dumps(e)  # the ledger never stores the leaked value either


def test_disallowed_model_refused(client, fake):
    r = client.post("/v1/chat/completions", json={"model": "nvidia/nemotron-3-super-120b-a12b", "messages": []})
    assert r.status_code == 400 and fake.received == []
