"""Tool-call surfaces of an outbound chat request, and a deterministic OFFLINE demo that pushes a tool-using conversation through the real gateway
against a stubbed upstream. The demo is NOT a Nemotron call and is labelled so everywhere it appears."""
from __future__ import annotations
import hashlib, json, tempfile
from pathlib import Path

SOURCE_LABEL = "offline-stub"
SOURCE_NOTE = "Offline stub: the real gateway code (redactor, canary, ledger, rehydration) ran against a stubbed upstream. Not a Nemotron call, no model output."


def surfaces(body: dict) -> list[dict]:
    """Every tool-related string in a chat request: [{where, kind, text}]. kind: tool_call_arguments | tool_message | tool_schema."""
    out = []
    for i, m in enumerate(body.get("messages") or []):
        for j, tc in enumerate((m.get("tool_calls") or []) if isinstance(m, dict) else []):
            fn = tc.get("function") or {}
            out.append(dict(where=f"messages[{i}].tool_calls[{j}].function.arguments", kind="tool_call_arguments", name=fn.get("name"),
                            text=fn.get("arguments") if isinstance(fn.get("arguments"), str) else json.dumps(fn.get("arguments"))))
        if isinstance(m, dict) and m.get("role") == "tool":
            c = m.get("content")
            out.append(dict(where=f"messages[{i}].content", kind="tool_message", name=m.get("name") or m.get("tool_call_id"),
                            text=c if isinstance(c, str) else json.dumps(c)))
    for k, t in enumerate(body.get("tools") or []):
        fn = (t or {}).get("function") or {}
        out.append(dict(where=f"tools[{k}].function", kind="tool_schema", name=fn.get("name"), text=json.dumps(fn, ensure_ascii=False)))
    return out


def summary(body: dict) -> dict:
    s = surfaces(body)
    return {k: sum(1 for x in s if x["kind"] == k) for k in ("tool_call_arguments", "tool_message", "tool_schema")}


def view(outbound_text: str) -> list[dict]:
    """The tool surfaces as they appear in the stored outbound bytes (parse the bytes the ledger holds, nothing else)."""
    return surfaces(json.loads(outbound_text))


def sha256_ok(entry: dict) -> bool:
    """True if the ledger/run.json entry's sha256 and byte count match its stored bytes."""
    text = entry.get("outbound_text")
    if text is None:
        return False
    b = text.encode("utf-8")
    return hashlib.sha256(b).hexdigest() == entry.get("outbound_sha256") and len(b) == entry.get("outbound_bytes")


def _request(ULTRA) -> dict:
    return {
        "model": ULTRA,
        "messages": [
            {"role": "system", "content": "You are a billing assistant. Use the tools. Never reveal identifiers."},
            {"role": "user", "content": "Check my Mercy Valley claim CN77310452 and tell me if the amount due is right."},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {
                "name": "lookup_member", "arguments": json.dumps({"member_id": "NSH884217353", "patient": "Jane Doe", "dob": "04/12/1985", "ssn": "987-65-4321"})}}]},
            {"role": "tool", "tool_call_id": "call_1", "content": json.dumps({"plan": "Northstar Health Plan", "subscriber": "DOE, JANE", "phone": "(555) 014-2297", "status": "active"})},
        ],
        "tools": [{"type": "function", "function": {"name": "lookup_member", "description": "Look up a plan member, e.g. Jane Doe at jane.doe@example.org.",
                  "parameters": {"type": "object", "properties": {"member_id": {"type": "string"}, "patient": {"type": "string"}}}}}],
    }


def build_demo() -> dict:
    """Deterministic. Returns the record committed as eval/toolargs_demo.json and shown on the judge page."""
    import httpx
    from fastapi.testclient import TestClient
    from .config import Settings, ULTRA, ROOT
    from .gateway import create_app

    def upstream(request: httpx.Request):
        body = json.loads(request.content)
        return httpx.Response(200, json={"id": "stub-0001", "model": body["model"], "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_2", "type": "function", "function": {"name": "queue_email", "arguments": json.dumps(
                    {"to": "[EMAIL_1]", "subject": "Appeal for [PERSON_1], claim [CLAIM_NO_1]"})}}]}}]})

    with tempfile.TemporaryDirectory() as td:
        s = Settings(home=Path(td) / "veil", profile=ROOT / "demo" / "profile.json", api_key="stub-not-a-real-key")
        app = create_app(s, transport=httpx.MockTransport(upstream))
        with TestClient(app) as c:
            req = _request(ULTRA)
            r = c.post("/v1/chat/completions", json=req, headers={"x-veil-tag": "toolargs-offline-stub", "x-veil-run": "toolargs-demo"})
            e = c.get("/ledger/1").json()
            # defence in depth: the same request with the redactor disabled (simulated bug) must be stopped by the canary on the final bytes
            app.state.pseudo.redact_payload = lambda obj, counts=None, _top=True: obj
            r2 = c.post("/v1/chat/completions", json=req, headers={"x-veil-tag": "toolargs-offline-stub-bypass", "x-veil-run": "toolargs-demo"})
            e2 = c.get("/ledger/2").json()
    out_text = e["outbound_text"]
    reply = r.json()["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    return dict(
        source=SOURCE_LABEL, note=SOURCE_NOTE, synthetic=True,
        request_tool_args=[x for x in surfaces(req)],
        outbound_text=out_text, outbound_sha256=e["outbound_sha256"], outbound_bytes=e["outbound_bytes"],
        sha256_verified=hashlib.sha256(out_text.encode("utf-8")).hexdigest() == e["outbound_sha256"],
        outbound_tool_args=view(out_text),
        redacted_total=e["redacted_total"], redacted_by_kind=e["redacted_by_kind"], leaked_count=e["leaked_count"], status=e["status"],
        stub_reply_arguments="{\"to\":\"[EMAIL_1]\",\"subject\":\"Appeal for [PERSON_1], claim [CLAIM_NO_1]\"}",
        rehydrated_reply_arguments=reply,
        redactor_bypass_simulated=dict(http_status=r2.status_code, code=r2.json()["error"]["code"], leaked_kinds=r2.json()["error"].get("leaked_kinds"),
                                       ledger_status=e2["status"], sent_bytes=e2["outbound_bytes"], note="Redactor disabled on purpose to show the canary stops the final bytes. Nothing was sent."),
    )


def write_demo(path: Path) -> dict:
    d = build_demo()
    path.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
    return d
