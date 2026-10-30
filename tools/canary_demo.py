"""Run the REAL gateway code (veil/gateway.py) against a stub upstream, no network, and record what fail-closed looks like.
Writes eval/canary_demo.json, which veil enrich-run embeds in the judge record. Synthetic profile only. Run: .venv/bin/python tools/canary_demo.py"""
import json, sys, tempfile
from pathlib import Path
import httpx
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from veil.config import Settings
from veil.gateway import create_app

CASES = [
    ("A normal bill line, identifiers present", "Patient: Jane Doe\nMember ID: NSH884217353\nCPT 99213 office visit, billed $214.00 on 2026-05-02."),
    ("Same member ID, but spaced out so no pattern recognises it", "Please re-check my coverage, member id NSH 884 217 353, for the 2026-05-02 visit."),
    ("Social Security number typed with spaces", "ssn 987 65 4321, visit on 2026-05-02"),
]


def main():
    received = []

    def upstream(req: httpx.Request):
        received.append(req.content)
        return httpx.Response(200, json={"id": "stub", "model": "stub", "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

    home = Path(tempfile.mkdtemp())
    s = Settings(home=home / "veil", profile=ROOT / "demo" / "profile.json", api_key="stub-key")
    rows = []
    with TestClient(create_app(s, transport=httpx.MockTransport(upstream))) as c:
        for label, text in CASES:
            before = len(received)
            r = c.post("/v1/chat/completions", json={"model": "nvidia/Nemotron-3_5-Lightning", "messages": [{"role": "user", "content": text}]}, headers={"x-veil-run": "canary-demo"})
            sent = len(received) > before
            e = c.get("/ledger?limit=1&full=true&run=canary-demo").json()["entries"][0]
            rows.append(dict(label=label, input=text, http=r.status_code, error_code=(r.json().get("error") or {}).get("code") if r.status_code != 200 else None,
                             sent_upstream=sent, ledger_status=e["status"], leaked_kinds=e.get("leaked_kinds"),
                             redacted_total=e["redacted_total"], redacted_by_kind=e.get("redacted_by_kind"),
                             outbound=(json.loads(received[-1])["messages"][0]["content"] if sent else None)))
    out = dict(source="tools/canary_demo.py", note="The real Veil gateway code with a stub upstream (no network, no model). Shows the fail-closed path the cached live run never needed to take: it ran with 0 blocked.", rows=rows)
    (ROOT / "eval" / "canary_demo.json").write_text(json.dumps(out, indent=2))
    for r in rows:
        print(r["http"], r["error_code"], "sent" if r["sent_upstream"] else "NOT sent", r["ledger_status"], r["leaked_kinds"], "|", r["label"])


if __name__ == "__main__":
    main()
