"""Thin OpenAI-compatible client that always talks to the Veil gateway (never to Nebius directly)."""
from __future__ import annotations
import json, os, threading, time
import httpx

DEFAULT_URL = os.environ.get("VEIL_GATEWAY", "http://127.0.0.1:8787")


def ensure_gateway(url: str = DEFAULT_URL, settings=None) -> str:
    """Use a running gateway, or start one in-process on a background thread."""
    try:
        if httpx.get(url + "/health", timeout=1.5).status_code == 200:
            return url
    except Exception:
        pass
    import uvicorn
    from urllib.parse import urlparse
    from .gateway import create_app
    u = urlparse(url)
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host=u.hostname, port=u.port or 8787, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try:
            if httpx.get(url + "/health", timeout=1).status_code == 200:
                return url
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("could not start gateway")


class Gateway:
    def __init__(self, url: str, run: str = ""):
        self.url, self.run = url, run
        self.http = httpx.Client(timeout=300)

    def chat(self, model: str, messages: list, tag: str = "", **kw) -> dict:
        r = self.http.post(self.url + "/v1/chat/completions", json={"model": model, "messages": messages, **kw},
                           headers={"x-veil-tag": tag, "x-veil-run": self.run})
        if r.status_code >= 400:
            raise GatewayError(r.status_code, r.json().get("error", {}) if r.headers.get("content-type", "").startswith("application/json") else {"message": r.text})
        return r.json()

    def ledger(self, **params) -> dict:
        return self.http.get(self.url + "/ledger", params=params).json()


class GatewayError(Exception):
    def __init__(self, status, err):
        self.status, self.err = status, err
        super().__init__(f"gateway {status}: {err.get('code') or ''} {err.get('message') or ''}")
