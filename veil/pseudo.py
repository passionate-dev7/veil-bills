"""Pseudonymizer: detect -> vault -> replace -> canary -> rehydrate."""
from __future__ import annotations
import json, re
from collections import Counter
from .vault import Vault, TOKEN_RE, norm
from . import detectors
from .fold import fold, unwrap

# Letters or digits separated by single spaces/dots/dashes/underscores ('J a n e  D o e', 'N.S.H.8.8.4...'). Collapsed and compared with the vault.
SPLIT_RX = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z0-9][ \t.\-_]{1,2}){2,}[A-Za-z0-9](?![A-Za-z0-9])")

SKIP_KEYS = {"model"}  # structural fields we never rewrite


_NOT_NAME_PARTS = {"january", "february", "march", "april", "june", "july", "august", "september", "october", "november", "december",
                   "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "plan", "health", "hospital", "clinic", "claim", "patient"}


def _name_parts(full: str) -> list[str]:
    """Individual words of a multi-word name (4+ letters, not a month, weekday or billing word); initials and short particles are skipped."""
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", full)
    if len(words) < 2:
        return []
    return [w for w in words if len(w) >= 4 and w.lower() not in _NOT_NAME_PARTS]


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
        self._amap: dict[str, tuple[str, str]] = {}

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
        self._amap = {_alnum(raw): (tok, kind) for raw, tok, kind in surfaces if len(_alnum(raw)) >= 3}
        self._rx_version = self.vault.version

    def _split_hits(self, text: str):
        """Yield (start, end, token, kind) for spaced-out vault values such as 'J a n e D o e'. Longest window first, left to right."""
        if not self._amap:
            return
        for m in SPLIT_RX.finditer(text):
            run = m.group(0)
            pos = [(i, c.lower()) for i, c in enumerate(run) if c.isalnum()]
            i, n = 0, len(pos)
            while i < n:
                for j in range(n, i + 2, -1):
                    hit = self._amap.get("".join(c for _, c in pos[i:j]))
                    if hit:
                        yield m.start() + pos[i][0], m.start() + pos[j - 1][0] + 1, hit[0], hit[1]
                        i = j - 1
                        break
                i += 1

    def learn(self, text: str):
        for kind, value in detectors.find(text):
            # A detected full name also teaches its parts, so "Patient: Marcus T. Whitfield ... Whitfield called again" tokenizes both.
            self.vault.add(kind, value, aliases=_name_parts(value) if kind == "PERSON" else ())

    def redact_text(self, text: str, counts: Counter | None = None) -> str:
        if not text:
            return text
        text = fold(text)
        self.learn(text)
        self._compile()
        hits = list(self._split_hits(text))
        if hits:
            parts, last = [], 0
            for a, b, tok, _k in hits:
                parts.append(text[last:a]); parts.append(tok); last = b
                if counts is not None:
                    counts[tok.strip("[]").rsplit("_", 1)[0]] += 1
            parts.append(text[last:]); text = "".join(parts)

        def sub(m):
            tok = self._tok.get(norm(m.group(0)))
            if tok is None:
                return m.group(0)
            if counts is not None:
                counts[tok.strip("[]").rsplit("_", 1)[0]] += 1
            return tok

        return self._rx.sub(sub, text)

    def redact_payload(self, obj, counts: Counter | None = None, _top: bool = True):
        """Redact every string that will leave the gateway: values AND dict keys, at any depth, including JSON that is encoded inside a
        string (tool-call `arguments`, tool-role message content, a JSON blob in a user message)."""
        if isinstance(obj, str):
            return self._redact_str(obj, counts)
        if isinstance(obj, list):
            return [self.redact_payload(x, counts, False) for x in obj]
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if _top and k in SKIP_KEYS:  # structural field we never rewrite (only at the top level of the request body)
                    out[k] = v
                    continue
                nk = self.redact_text(k, counts) if isinstance(k, str) else k
                out[nk] = self.redact_payload(v, counts, False)
            return out
        return obj

    def _redact_str(self, s: str, counts):
        """JSON-in-a-string is parsed, redacted on the decoded values, and re-serialized (so "\\n" + "name@x.org" is never read as "nname@x.org").
        If nothing changed the original string is returned byte for byte. Anything that does not parse as a JSON object/array is redacted as text."""
        t = s.lstrip()
        if t[:1] in ("{", "["):
            try:
                parsed = json.loads(s)
            except ValueError:
                parsed = None
            if isinstance(parsed, (dict, list)):
                red = self.redact_payload(parsed, counts, False)
                return s if red == parsed else json.dumps(red, ensure_ascii=False)
        return self.redact_text(s, counts)

    # -- canary ---------------------------------------------------------------
    def canary(self, outbound: bytes) -> list[tuple[str, str]]:
        """Return leaks found in the exact outbound bytes: every vault value (dictionary) + every regex detector."""
        text = outbound.decode("utf-8", "replace")
        flat = []
        try:
            _collect_strings(json.loads(text), flat)
        except Exception:
            pass
        hay = [fold(text), fold("\n".join(flat))]
        for h in list(hay):  # identifiers behind html entities, percent encoding, markup, base64 or hex
            hay.extend(unwrap(h))
        hay_alnum = _alnum("\n".join(hay))
        leaks: list[tuple[str, str]] = []
        for raw, tok, kind in self.vault.surfaces():
            if len(raw.strip()) < 2:
                continue
            pat = re.compile(r"(?<![A-Za-z0-9])" + r"\s+".join(re.escape(p) for p in raw.split()) + r"(?![A-Za-z0-9])", re.I)
            if any(pat.search(h) for h in hay):
                leaks.append((kind, "vault-exact"))
            elif len(_alnum(raw)) >= (6 if len(raw.split()) > 1 else 8) and _alnum(raw) in hay_alnum:  # "JaneDoe" is the name, glued
                leaks.append((kind, "vault-normalized"))
        self._compile()
        for h in hay:
            for _a, _b, _tok, kind in self._split_hits(h):
                leaks.append((kind, "vault-split"))
                break
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


def _collect_strings(o, acc, depth: int = 0):
    """Every string the upstream could read: values, dict keys, and the decoded content of JSON-in-a-string (tool arguments, tool results)."""
    if isinstance(o, str):
        acc.append(o)
        if depth < 4 and o.lstrip()[:1] in ("{", "["):
            try:
                inner = json.loads(o)
            except ValueError:
                return
            if isinstance(inner, (dict, list)):
                _collect_strings(inner, acc, depth + 1)
    elif isinstance(o, list):
        for x in o:
            _collect_strings(x, acc, depth)
    elif isinstance(o, dict):
        for k, v in o.items():
            if isinstance(k, str):
                acc.append(k)
            _collect_strings(v, acc, depth)


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
