"""Veil product server (local only, 127.0.0.1): serves the web app and a small API over local memory, outbox and ledger.
Live mode talks to this API. Judge mode needs none of it (the same page reads a cached run.json), so web/ can be hosted as a static folder.
Delivery is only ever to the local sandbox mailbox.
"""
from __future__ import annotations
import asyncio, json
from datetime import date
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from .config import Settings, ROOT
from .egress import Policy, Outbox
from .ledger import Ledger
from .memory import Memory
from .run import build_record


class Note(BaseModel):
    text: str
    claim: str | None = None


def create_app(settings: Settings | None = None, as_of: date | None = None, watch_info: dict | None = None, web: Path | None = None) -> FastAPI:
    s = settings or Settings()
    app = FastAPI(title="Veil app", version="0.2.0")
    mem, outbox, policy, ledger = Memory(s.memory_db), Outbox(s), Policy(s), Ledger(s.ledger_db)
    today = lambda: as_of or date.today()

    @app.get("/api/state")
    def state():
        return {"ok": True, "mode": "live", "synthetic": True, "as_of": today().isoformat(), "watch": watch_info or {}, "events": len(mem.events(limit=1000)),
                "pending_drafts": sum(1 for d in outbox.list() if d["status"] == "pending_approval")}

    @app.get("/api/run")
    def run(run: str | None = None):
        return build_record(s, today(), run, live=True)

    @app.get("/api/stream")
    async def stream(after: int = 0):
        """Server-sent events: every new notification the watcher records is pushed to the page."""
        async def gen():
            last = after
            yield f"retry: 2000\n\n"
            while True:
                for e in reversed(mem.events(last, 50)):
                    last = max(last, e["id"])
                    yield f"id: {e['id']}\nevent: veil\ndata: {json.dumps(e)}\n\n"
                yield ": keepalive\n\n"
                await asyncio.sleep(1.0)
        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.post("/api/drafts/{id}/approve")
    def approve(id: str):
        try:
            d = outbox.approve(id, policy)
        except FileNotFoundError:
            raise HTTPException(404, "no such draft")
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except ValueError as e:
            raise HTTPException(409, str(e))
        mem.event("approved", f"You approved a draft; delivered to the sandbox mailbox", d["subject"], dict(draft_id=id))
        return dict(d, eml_text=Path(d["eml"]).read_text())

    @app.post("/api/drafts/{id}/reject")
    def reject(id: str):
        try:
            d = outbox.reject(id)
        except FileNotFoundError:
            raise HTTPException(404, "no such draft")
        mem.event("rejected", "You rejected a draft", d["subject"], dict(draft_id=id))
        return d

    @app.get("/api/eml/{id}", response_class=PlainTextResponse)
    def eml(id: str):
        p = s.mailbox / f"{Path(id).name}.eml"
        if not p.exists():
            raise HTTPException(404, "not delivered")
        return p.read_text()

    @app.post("/api/notes")
    def add_note(n: Note):
        i = mem.add_note(n.text.strip()[:2000], n.claim)
        mem.event("note", "Note saved to memory", n.text[:120])
        return dict(id=i)

    @app.get("/api/ledger")
    def led(limit: int = 100, kind: str | None = None, run: str | None = None, full: bool = False):
        return {"totals": ledger.totals(run), "entries": ledger.list(limit, kind, run, with_bytes=full)}

    root = web or ROOT / "web"
    app.mount("/", StaticFiles(directory=str(root), html=True), name="web")
    return app
