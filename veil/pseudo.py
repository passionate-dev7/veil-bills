"""Pseudonymizer: detect -> vault -> replace -> canary -> rehydrate."""
from __future__ import annotations
import json, re
from collections import Counter
from .vault import Vault, TOKEN_RE, norm
from . import detectors

SKIP_KEYS = {"model"}  # structural fields we never rewrite


class Leak(Exception):
    def __init__(self, leaks: list[tuple[str, str]]):
        self.leaks = leaks  # (kind, how-found); the leaked value itself is never put in the exception
        super().__init__(f"{len(leaks)} sensitive value(s) remain in outbound payload")


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


class Pseudonymizer:
    def __init__(self, vault: Vault):
        self.vault = vault
        self._rx = None
        self._rx_version = -1
        self._tok = {}

    # -- dictionary pass ----------------------------------------------------
    def _compile(self):
        if self._rx is not None and self._rx_version == self.vault.version:
            return
        surfaces = self.vault.surfaces()
        self._tok = {norm(raw): tok for raw, tok, _ in surfaces}
        if not surfaces:
            self._rx = re.compile(r"(?!x)x")
        else:
            alts = [r"\s+".join(re.escape(p) for p in raw.split()) for raw, _, _ in surfaces]
            self._rx = re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(alts) + r")(?![A-Za-z0-9])", re.I)
        self._rx_version = self.vault.version

    def learn(self, text: str):
        for kind, value in detectors.find(text):
            self.vault.add(kind, value)

    def redact_text(self, text: str, counts: Counter | None = None) -> str:
        if not text:
            return text
        self.learn(text)
        self._compile()

        def sub(m):
            tok = self._tok.get(norm(m.group(0)))
            if tok is None:
                return m.group(0)
            if counts is not None:
                counts[tok.strip("[]").rsplit("_", 1)[0]] += 1
            return tok

        return self._rx.sub(sub, text)

    def redact_payload(self, obj, counts: Counter | None = None):
        if isinstance(obj, str):
            return self.redact_text(obj, counts)
        if isinstance(obj, list):
            return [self.redact_payload(x, counts) for x in obj]
        if isinstance(obj, dict):
            return {k: (v if k in SKIP_KEYS else self.redact_payload(v, counts)) for k, v in obj.items()}
        return obj

    # -- canary ---------------------------------------------------------------
    def canary(self, outbound: bytes) -> list[tuple[str, str]]:
        """Return leaks found in the exact outbound bytes: every vault value (dictionary) + every regex detector."""
        text = outbound.decode("utf-8", "replace")
        flat = []
        try:
            _collect_strings(json.loads(text), flat)
        except Exception:
            pass
        hay = [text, "\n".join(flat)]
        hay_alnum = _alnum("\n".join(hay))
        leaks: list[tuple[str, str]] = []
        for raw, tok, kind in self.vault.surfaces():
            if len(raw.strip()) < 2:
                continue
            pat = re.compile(r"(?<![A-Za-z0-9])" + r"\s+".join(re.escape(p) for p in raw.split()) + r"(?![A-Za-z0-9])", re.I)
            if any(pat.search(h) for h in hay):
                leaks.append((kind, "vault-exact"))
            elif len(_alnum(raw)) >= 8 and _alnum(raw) in hay_alnum:
                leaks.append((kind, "vault-normalized"))
        for kind, _v in detectors.find("\n".join(hay)):
            leaks.append((kind, "regex"))
        return leaks

    # -- rehydration --------------------------------------------------------------
    def rehydrate_text(self, text: str, json_escape: bool = False) -> str:
        if not text or "[" not in text:
            return text
        canon = self.vault.canon_map()

        def sub(m):
            v = canon.get(f"[{m.group(1)}]")
            if v is None:
                return m.group(0)
            return json.dumps(v, ensure_ascii=False)[1:-1] if json_escape else v

        return TOKEN_RE.sub(sub, text)

    def rehydrate_obj(self, obj):
        if isinstance(obj, str):
            return self.rehydrate_text(obj)
        if isinstance(obj, list):
            return [self.rehydrate_obj(x) for x in obj]
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if k == "arguments" and isinstance(v, str):
                    out[k] = self.rehydrate_text(v, json_escape=True)  # tool-call arguments are JSON-in-a-string
                else:
                    out[k] = self.rehydrate_obj(v)
            return out
        return obj


def _collect_strings(o, acc):
    if isinstance(o, str):
        acc.append(o)
    elif isinstance(o, list):
        for x in o:
            _collect_strings(x, acc)
    elif isinstance(o, dict):
        for v in o.values():
            _collect_strings(v, acc)


class StreamRehydrator:
    """Rehydrates a token stream that may split [TOKEN_1] across chunks."""

    def __init__(self, pseudo: Pseudonymizer, json_escape: bool = False):
        self.p, self.buf, self.esc = pseudo, "", json_escape

    def feed(self, piece: str) -> str:
        self.buf += piece
        i = self.buf.rfind("[")
        if i != -1 and "]" not in self.buf[i:] and len(self.buf) - i <= 48:
            emit, self.buf = self.buf[:i], self.buf[i:]
        else:
            emit, self.buf = self.buf, ""
        return self.p.rehydrate_text(emit, self.esc)

    def flush(self) -> str:
        out, self.buf = self.buf, ""
        return self.p.rehydrate_text(out, self.esc)
