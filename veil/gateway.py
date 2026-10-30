"""Veil gateway: OpenAI-compatible, pseudonymizes everything outbound, rehydrates everything inbound, fails closed."""
from __future__ import annotations
import asyncio, json, time
from contextlib import asynccontextmanager
from collections import Counter
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from .config import Settings, ALLOWED_MODELS
from .vault import Vault
from .pseudo import Pseudonymizer, StreamRehydrator
from .ledger import Ledger
from . import toolargs, providers


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    s = settings or Settings()
    vault = Vault(s.vault_db)
    if s.profile and s.profile.exists():
        vault.load_profile(s.profile)
    pseudo = Pseudonymizer(vault)
    ledger = Ledger(s.ledger_db)
    app = FastAPI(title="Veil gateway", version="0.1.0")
    app.state.vault, app.state.pseudo, app.state.ledger, app.state.settings = vault, pseudo, ledger, s
    client = httpx.AsyncClient(timeout=s.timeout, transport=transport)

    def err(status: int, msg: str, code: str, **extra):
        return JSONResponse({"error": {"message": msg, "type": "veil_" + code, "code": code, **extra}}, status_code=status)

    @app.get("/health")
    def health():
        return {"ok": True, "service": "veil-gateway", "vault": vault.stats(), "key_configured": bool(s.api_key), "upstream": s.upstream,
                "provider": s.provider, "dev_fallback": s.dev, "provider_label": providers.label(s.provider)}

    @app.get("/v1/models")
    def models():
        return {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "nebius-token-factory" if s.provider == "tokenfactory" else s.provider} for m in ALLOWED_MODELS]}

    @app.get("/ledger")
    def ledger_list(limit: int = 100, kind: str | None = None, run: str | None = None, full: bool = False):
        return {"totals": ledger.totals(run), "entries": ledger.list(limit, kind, run, with_bytes=full)}

    @app.get("/ledger/{entry_id}")
    def ledger_get(entry_id: int):
        e = ledger.get(entry_id)
        return e or err(404, "no such ledger entry", "not_found")

    from .sandbox_tools import router as sandbox_router
    app.include_router(sandbox_router(s))

    @app.post("/tools/search")
    async def search(request: Request):
        """Web search for the agent (Tavily). Same discipline as inference: redact, canary on the final bytes, ledger the exact outbound body."""
        t0 = time.time()
        tag, run = request.headers.get("x-veil-tag", ""), request.headers.get("x-veil-run", "")
        try:
            q = str((await request.json()).get("query", "")).strip()
        except Exception:
            return err(400, "body must be JSON with a query", "bad_request")
        if not q or len(q) > 400:
            return err(400, "query must be 1-400 characters", "bad_request")
        counts: Counter = Counter()
        body = pseudo.redact_payload({"query": q, "search_depth": "basic", "max_results": 5, "include_answer": "basic"}, counts)
        outbound = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        leaks = pseudo.canary(outbound)
        base = dict(kind="search", run=run, tag=tag, route="tavily", provider=s.provider, model="tavily/search", redacted_total=sum(counts.values()),
                    redacted_by_kind=dict(counts))
        if leaks:
            ledger.add(**base, status="blocked", leaked_count=len(leaks), leaked_kinds=[f"{k}:{how}" for k, how in leaks],
                       reason="canary: sensitive value would have left the machine; search refused", latency_ms=int((time.time() - t0) * 1000))
            return err(422, "Veil canary refused this search query", "leak_blocked", leaked_count=len(leaks),
                       leaked_kinds=sorted({k for k, _ in leaks}))
        if not s.tavily_key and transport is None:
            return err(500, "TAVILY_API_KEY not configured", "no_key")
        entry = ledger.add(**base, status="pending", outbound=outbound, leaked_count=0)
        try:
            r = await client.post(s.tavily_url, content=outbound, headers={"Authorization": f"Bearer {s.tavily_key or 'test'}", "Content-Type": "application/json"})
            data = r.json()
        except Exception as e:
            ledger.update(entry, status="error", reason=f"upstream: {type(e).__name__}", latency_ms=int((time.time() - t0) * 1000))
            return err(502, f"search upstream failed: {type(e).__name__}", "upstream_error")
        ms = int((time.time() - t0) * 1000)
        results = data.get("results") or []
        sources = [{"title": x.get("title"), "url": x.get("url"), "score": x.get("score")} for x in results]
        ledger.update(entry, status="ok" if r.status_code < 400 else "error", http_status=r.status_code, latency_ms=ms,
                      upstream_id=data.get("request_id"), usage=data.get("usage") or {}, response_text=json.dumps(data, ensure_ascii=False)[:60000],
                      meta={"query": body.get("query"), "sources": sources, "answer": data.get("answer"), "response_time": data.get("response_time")})
        data["veil"] = {"ledger_id": entry, "sha256": ledger.get(entry)["outbound_sha256"], "latency_ms": ms}
        return JSONResponse(data, status_code=r.status_code)

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        t0 = time.time()
        tag, run = request.headers.get("x-veil-tag", ""), request.headers.get("x-veil-run", "")
        try:
            body = await request.json()
        except Exception:
            return err(400, "body must be JSON", "bad_request")
        model = body.get("model")
        if model not in ALLOWED_MODELS:
            ledger.add(kind="inference", run=run, tag=tag, route="chat", model=str(model), status="blocked", provider=s.provider,
                       reason="model not allowed by gateway policy")
            return err(400, f"model not allowed; use one of {list(ALLOWED_MODELS)}", "model_not_allowed")
        stream = bool(body.get("stream"))
        counts: Counter = Counter()
        redacted = pseudo.redact_payload(body, counts)
        if stream:
            redacted.setdefault("stream_options", {"include_usage": True})
        redacted = providers.adapt_request(s.provider, redacted)  # model ids / reasoning flags for the dev fallback; before the canary, so the canary sees the final bytes
        outbound = json.dumps(redacted, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        leaks = pseudo.canary(outbound)  # FAIL CLOSED: checked against the final bytes
        base = dict(kind="inference", run=run, tag=tag, route="chat", model=model, stream=int(stream), provider=s.provider,
                    redacted_total=sum(counts.values()), redacted_by_kind=dict(counts))
        tool_meta = toolargs.summary(redacted)
        if any(tool_meta.values()):
            base["meta"] = {"tool_surfaces": tool_meta}  # counts of tool_call arguments / tool messages / tool schemas inside the hashed bytes
        if leaks:
            kinds = sorted({k for k, _ in leaks})
            ledger.add(**base, status="blocked", leaked_count=len(leaks), leaked_kinds=[f"{k}:{how}" for k, how in leaks],
                       reason="canary: sensitive value would have left the machine; request refused",
                       latency_ms=int((time.time() - t0) * 1000))
            return err(422, "Veil canary refused this request: sensitive values remained after redaction", "leak_blocked",
                       leaked_kinds=kinds, leaked_count=len(leaks))
        if not s.api_key and transport is None:
            return err(500, f"{s.key_env} not configured", "no_key")
        entry = ledger.add(**base, status="pending", outbound=outbound, leaked_count=0)
        headers = providers.upstream_headers(s.provider, s.api_key)  # never stored: the ledger holds the body bytes only
        url = s.upstream.rstrip("/") + "/chat/completions"
        if not stream:
            retries = 0
            try:
                while True:
                    r = await client.post(url, content=outbound, headers=headers)
                    if r.status_code not in providers.RETRY_STATUSES or retries >= s.retries:
                        break
                    await asyncio.sleep(providers.retry_delay(retries, r.headers.get("retry-after"), s.retry_base_s))
                    retries += 1
            except Exception as e:
                ledger.update(entry, status="error", reason=f"upstream: {type(e).__name__}", latency_ms=int((time.time() - t0) * 1000))
                return err(502, f"upstream unreachable: {type(e).__name__}", "upstream_error")
            ms = int((time.time() - t0) * 1000)
            if r.status_code in providers.RETRY_STATUSES:  # still rate limited after every retry: fail cleanly, nothing half-done
                ledger.update(entry, status="error", http_status=r.status_code, latency_ms=ms, meta={**(base.get("meta") or {}), "retries": retries},
                              reason=f"upstream rate limited (429) after {retries} retries")
                return err(429, f"upstream rate limited (429) after {retries} retries; try again later", "rate_limited", retries=retries)
            if retries:
                base["meta"] = {**(base.get("meta") or {}), "retries": retries}
            try:
                data = r.json()
            except Exception:
                ledger.update(entry, status="error", http_status=r.status_code, latency_ms=ms, reason="non-JSON upstream body")
                return err(502, "upstream returned non-JSON", "upstream_error")
            ledger.update(entry, status="ok" if r.status_code < 400 else "error", http_status=r.status_code, latency_ms=ms,
                          upstream_id=data.get("id"), upstream_model=data.get("model"), usage=data.get("usage") or {},
                          response_text=json.dumps(data, ensure_ascii=False), **({"meta": base["meta"]} if retries else {}))
            return JSONResponse(pseudo.rehydrate_obj(data), status_code=r.status_code)

        tries = {"n": 0}

        @asynccontextmanager
        async def open_stream():  # 429 before the first byte: back off and retry the same bytes, then give up cleanly
            while True:
                r = await client.send(client.build_request("POST", url, content=outbound, headers=headers), stream=True)
                if r.status_code in providers.RETRY_STATUSES and tries["n"] < s.retries:
                    delay = providers.retry_delay(tries["n"], r.headers.get("retry-after"), s.retry_base_s)
                    await r.aclose()
                    tries["n"] += 1
                    await asyncio.sleep(delay)
                    continue
                try:
                    yield r
                finally:
                    await r.aclose()
                return

        async def gen():
            rh: dict[tuple, StreamRehydrator] = {}
            meta, texts = {}, []
            status = 200
            try:
                async with open_stream() as r:
                    status = r.status_code
                    if r.status_code >= 400:
                        raw = (await r.aread()).decode("utf-8", "replace")
                        ledger.update(entry, status="error", http_status=status, response_text=raw, latency_ms=int((time.time() - t0) * 1000),
                                      **({"reason": f"upstream rate limited (429) after {tries['n']} retries"} if status == 429 else {}))
                        yield f"data: {json.dumps({'error': {'message': 'upstream error', 'status': status}})}\n\n"
                        return
                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            for (ci, field), h in rh.items():  # flush held-back text
                                tail = h.flush()
                                if tail:
                                    yield "data: " + json.dumps(_tail_chunk(meta, ci, field, tail), ensure_ascii=False) + "\n\n"
                            yield "data: [DONE]\n\n"
                            continue
                        try:
                            ch = json.loads(payload)
                        except Exception:
                            continue
                        texts.append(payload)
                        meta.setdefault("id", ch.get("id")); meta.setdefault("model", ch.get("model"))
                        if ch.get("usage"):
                            meta["usage"] = ch["usage"]
                        for c in ch.get("choices", []):
                            d = c.get("delta", {})
                            for f in ("content", "reasoning_content", "reasoning"):
                                if isinstance(d.get(f), str):
                                    h = rh.setdefault((c.get("index", 0), f), StreamRehydrator(pseudo))
                                    d[f] = h.feed(d[f])
                            for tc in d.get("tool_calls", []) or []:
                                fn = tc.get("function", {})
                                if isinstance(fn.get("arguments"), str):
                                    h = rh.setdefault((c.get("index", 0), f"tc{tc.get('index', 0)}"), StreamRehydrator(pseudo, True))
                                    fn["arguments"] = h.feed(fn["arguments"])
                        yield "data: " + json.dumps(ch, ensure_ascii=False) + "\n\n"
            except Exception as e:
                ledger.update(entry, status="error", reason=f"upstream: {type(e).__name__}", latency_ms=int((time.time() - t0) * 1000))
                yield f"data: {json.dumps({'error': {'message': 'upstream failure'}})}\n\n"
                return
            ledger.update(entry, status="ok", http_status=status, latency_ms=int((time.time() - t0) * 1000),
                          upstream_id=meta.get("id"), upstream_model=meta.get("model"), usage=meta.get("usage") or {},
                          response_text="\n".join(texts))

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


def _tail_chunk(meta, ci, field, text):
    if field.startswith("tc"):
        delta = {"tool_calls": [{"index": int(field[2:]), "function": {"arguments": text}}]}
    else:
        delta = {field: text}
    return {"id": meta.get("id"), "object": "chat.completion.chunk", "model": meta.get("model"),
            "choices": [{"index": ci, "delta": delta, "finish_reason": None}]}


def app_factory():  # uvicorn --factory veil.gateway:app_factory
    return create_app()
