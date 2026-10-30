"""Tool-call surfaces: arguments, tool-role messages, tool schemas, dict keys. Everything that leaves goes through the pseudonymizer, the canary
scans the final serialized bytes (including the decoded content of JSON-in-a-string), and the ledger hash is verifiable from the stored bytes."""
import json
from pathlib import Path
from veil.config import ULTRA, ROOT
from veil import toolargs

RAW = ["NSH884217353", "987-65-4321", "Jane Doe", "jane.doe@example.org", "(555) 014-2297", "04/12/1985"]


def call(client, messages, tools=None, **kw):
    body = {"model": ULTRA, "messages": messages, **({"tools": tools} if tools else {}), **kw}
    return client.post("/v1/chat/completions", json=body, headers={"x-veil-tag": "t"})


def assistant_call(args):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "lookup", "arguments": args}}]}


def test_vaulted_identifier_in_tool_args_goes_out_tokenized_and_comes_back_rehydrated(client, fake):
    fake.reply = lambda b: {"id": "c2", "model": b["model"], "usage": {}, "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": None, "tool_calls": [{"id": "c3", "type": "function", "function": {
            "name": "queue_email", "arguments": json.dumps({"member": "[MEMBER_ID_1]", "ssn": "[SSN_1]"})}}]}}]}
    r = call(client, [{"role": "user", "content": "start"}, assistant_call(json.dumps({"member_id": "NSH884217353", "ssn": "987-65-4321"})),
                      {"role": "tool", "tool_call_id": "c1", "content": "ok"}])
    assert r.status_code == 200
    sent = fake.received[0].decode()
    assert "NSH884217353" not in sent and "987-65-4321" not in sent and "[MEMBER_ID_1]" in sent and "[SSN_1]" in sent
    args = json.loads(r.json()["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
    assert args == {"member": "NSH884217353", "ssn": "987-65-4321"}  # rehydrated on the way back


def test_every_tool_surface_is_tokenized(client, fake):
    r = call(client, [{"role": "user", "content": "go"},
                      assistant_call(json.dumps({"patient": "Jane Doe", "nested": json.dumps({"ssn": "987-65-4321"})})),
                      {"role": "tool", "tool_call_id": "c1", "content": json.dumps({"subscriber": "DOE, JANE", "phone": "(555) 014-2297", "dob": "04/12/1985"})}],
             tools=[{"type": "function", "function": {"name": "lookup", "description": "e.g. Jane Doe at jane.doe@example.org",
                     "parameters": {"type": "object", "properties": {"NSH884217353": {"type": "string"}}}}}])
    assert r.status_code == 200
    sent = fake.received[0].decode()
    for v in RAW + ["DOE, JANE"]:
        assert v not in sent, v
    e = client.get("/ledger?full=true").json()["entries"][0]
    assert e["meta"]["tool_surfaces"] == {"tool_call_arguments": 1, "tool_message": 1, "tool_schema": 1}
    assert e["outbound_text"] == sent


def test_unchanged_json_string_is_left_byte_identical(settings):
    from veil.vault import Vault
    from veil.pseudo import Pseudonymizer
    p = Pseudonymizer(Vault(settings.vault_db))
    s = '{ "cpt":  "36415",  "amount": "$35.00" }'
    assert p.redact_payload({"messages": [{"role": "tool", "content": s}]})["messages"][0]["content"] == s
    # "model" is only skipped at the top level of the request, not inside tool arguments
    out = p.redact_payload({"model": "m", "x": json.dumps({"model": "Patient: Jane Doe"})})
    assert out["model"] == "m" and "Jane Doe" not in out["x"]


def test_raw_ids_in_tool_args_get_422_when_redaction_is_bypassed(client, fake, monkeypatch):
    """Defence in depth: the canary reads the final bytes, not the redactor's output. Disable the redactor on purpose (simulated bug)."""
    client.post("/v1/chat/completions", json={"model": ULTRA, "messages": [{"role": "user", "content": "x"}]})  # warm vault from profile
    fake.received.clear()
    monkeypatch.setattr(client.app_.state.pseudo, "redact_payload", lambda obj, counts=None, _top=True: obj)
    for args, kind in [({"member_id": "NSH884217353"}, "MEMBER_ID"), ({"ssn": "987-65-4321"}, "SSN")]:
        r = call(client, [{"role": "user", "content": "go"}, assistant_call(json.dumps(args))])
        assert r.status_code == 422
        err = r.json()["error"]
        assert err["type"] == "veil_leak_blocked" and err["code"] == "leak_blocked" and kind in err["leaked_kinds"]
    assert fake.received == []
    rows = client.get("/ledger?full=true").json()["entries"][:2]
    assert all(x["status"] == "blocked" and x["outbound_bytes"] is None for x in rows)
    assert "987-65-4321" not in json.dumps(rows) and "NSH884217353" not in json.dumps(rows)


def test_canary_reads_escaped_json_inside_tool_args(client, fake, monkeypatch):
    """A value hidden behind JSON escapes inside the arguments string is invisible to a scan of the raw text but not to the canary."""
    monkeypatch.setattr(client.app_.state.pseudo, "redact_payload", lambda obj, counts=None, _top=True: obj)
    args = '{"note": "Jane\\u0020Doe", "k": "NSH\\u0038\\u0038\\u0034217353"}'
    assert "Jane Doe" not in args
    r = call(client, [{"role": "user", "content": "go"}, assistant_call(args)])
    assert r.status_code == 422 and fake.received == []
    assert {"PERSON", "MEMBER_ID"} <= set(r.json()["error"]["leaked_kinds"])


def test_canary_reads_dict_keys(client, fake, monkeypatch):
    monkeypatch.setattr(client.app_.state.pseudo, "redact_payload", lambda obj, counts=None, _top=True: obj)
    r = call(client, [{"role": "user", "content": "go"}], tools=[{"type": "function", "function": {"name": "f", "parameters": {"properties": {"NSH884217353": {}}}}}])
    assert r.status_code == 422


def test_ledger_hash_is_computed_from_stored_bytes(client, fake):
    call(client, [{"role": "user", "content": "go"}, assistant_call(json.dumps({"m": "NSH884217353"}))])
    e = client.get("/ledger?full=true").json()["entries"][0]
    assert toolargs.sha256_ok(e)
    e["outbound_text"] = e["outbound_text"].replace("[MEMBER_ID_1]", "[MEMBER_ID_2]")
    assert not toolargs.sha256_ok(e)  # any edit to the stored bytes breaks verification


def test_offline_demo_is_labelled_deterministic_and_verifiable():
    committed = json.loads((ROOT / "eval" / "toolargs_demo.json").read_text())
    fresh = toolargs.build_demo()
    assert fresh == committed  # regenerate with: python -m veil toolargs-demo
    assert committed["source"] == "offline-stub" and "Not a Nemotron call" in committed["note"]
    assert toolargs.sha256_ok(committed) and committed["sha256_verified"]
    args = [x for x in committed["outbound_tool_args"] if x["kind"] == "tool_call_arguments"]
    assert args and "[MEMBER_ID_1]" in args[0]["text"] and "[SSN_1]" in args[0]["text"]
    for v in RAW:
        assert v not in committed["outbound_text"]
    assert committed["rehydrated_reply_arguments"].count("jane.doe@example.org") == 1
    bp = committed["redactor_bypass_simulated"]
    assert bp["http_status"] == 422 and bp["code"] == "leak_blocked" and bp["sent_bytes"] is None
