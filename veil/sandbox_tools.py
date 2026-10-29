"""Host-side tools for an agent running inside the OpenShell sandbox (Hermes). Served by the gateway under /tools/veil/*.

The sandbox policy lets it reach only the gateway, and only these exact paths. Everything sensitive happens here, on the host:
document reading, extraction and audit math, the Tavily lookup (the sandbox has no internet), the egress allowlist, and the
approval outbox. The sandbox can ask; it cannot send. `queue_email` never delivers: it drafts for a human, or is refused and ledgered.
"""
from __future__ import annotations
import os
from datetime import date
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from .audit import run_audit
from .client import Gateway
from .config import Settings
from .egress import Policy, Outbox, EMAIL
from .memory import Memory
from . import research

PATHS = ("/tools/veil/claims", "/tools/veil/audit", "/tools/veil/lookup_appeal_rules", "/tools/veil/queue_email")


def corpus_dir(s: Settings) -> Path:
    return Path(os.environ.get("VEIL_CORPUS", s.home / "inbox"))


def _err(status, msg, code):
    return JSONResponse({"error": {"message": msg, "code": code}}, status_code=status)


def router(s: Settings) -> APIRouter:
    r = APIRouter(prefix="/tools/veil")
    mem, outbox, policy = Memory(s.memory_db), Outbox(s), Policy(s)

    def gw_for(request: Request) -> Gateway:  # call our own gateway, so extraction and search are ledgered like everything else
        return Gateway(str(request.base_url).rstrip("/"), request.headers.get("x-veil-run", "sandbox-hermes"))

    def summary(audit: dict) -> dict:
        names = {d["_name"] for d in mem.docs()}
        return dict(
            findings=[{k: f.get(k) for k in ("type", "amount", "detail", "bill_doc", "eob_doc")} for f in audit["findings"]],
            deadlines=audit["deadlines"], deductible=audit["deductible"], documents=sorted(names),
            note="All money figures are computed in code in integer cents. Use them verbatim; do not recompute.")

    @r.get("/claims")
    def claims():
        return dict(documents=[dict(name=d["_name"], type=d["doc_type"], provider=d.get("provider"), date=d.get("document_date")) for d in mem.docs()],
                    corpus=sorted(p.name for p in corpus_dir(s).glob("*.pdf")))

    @r.post("/audit")
    async def audit(request: Request):
        from .watch import Engine
        try:
            files = [Path(x).name for x in (await request.json()).get("files", [])]  # basenames only: no path traversal
        except Exception:
            return _err(400, "body must be JSON: {\"files\": [\"name.pdf\", ...]}", "bad_request")
        return await _run(lambda: _audit(files, request))

    def _audit(files, request):
        from .watch import Engine
        eng = Engine(s, gw_for(request), mem, appeal=False)
        missing = [f for f in files if not (corpus_dir(s) / f).is_file()]
        if missing:
            return _err(404, f"not in the corpus: {missing}", "not_found")
        for f in files:
            eng.ingest(corpus_dir(s) / f)
        return summary(eng.analyze() if files else run_audit(mem.docs(), date.today()))

    @r.post("/lookup_appeal_rules")
    async def lookup(request: Request):
        try:
            b = await request.json()
            research.build_query(b.get("insurer_type"), b.get("topic"))
        except ValueError as e:
            return _err(400, str(e), "bad_enum")
        except Exception:
            return _err(400, "body must be JSON {insurer_type, topic}", "bad_request")
        return await _run(lambda: research.lookup(gw_for(request), b["insurer_type"], b["topic"], tag="sandbox:lookup_appeal_rules"))

    @r.post("/queue_email")
    async def queue_email(request: Request):
        try:
            b = await request.json()
            to = [str(x) for x in (b["to"] if isinstance(b["to"], list) else [b["to"]])]
            subject, body = str(b["subject"])[:300], str(b["body"])[:20000]
        except Exception:
            return _err(400, "body must be JSON {to, subject, body}", "bad_request")
        run = request.headers.get("x-veil-run", "sandbox-hermes")
        ok, bad = policy.check(to)
        policy.log(ok, "queue_email", to, subject, run, "sandbox:queue_email", "queued for human approval" if ok else f"recipient not on allowlist: {bad}", source="sandbox-agent")
        if not ok:
            return JSONResponse({"status": "blocked", "reason": f"recipient not on the trusted-contacts allowlist: {bad}"}, status_code=403)
        d = outbox.queue(to, subject, body, run, dict(kind="appeal", via="sandbox-hermes"))
        return dict(status="pending_approval", draft_id=d["id"], note="Nothing was sent. A human must approve it in the Veil app.")

    return r


async def _run(fn):
    import anyio
    return await anyio.to_thread.run_sync(fn)
