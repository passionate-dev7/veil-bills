"""Input folding before detection: NFKC, strip zero-width characters, and map look-alike letters (Cyrillic/Greek) to Latin inside words
that also contain ASCII. Pure non-Latin words are left alone. Mirrored exactly by web/pseudo.js (tests/test_js_parity.py)."""
from __future__ import annotations
import re, unicodedata

ZERO_WIDTH = "\u200b\u200c\u200d\u2060\ufeff\u00ad"
_ZW = {ord(c): None for c in ZERO_WIDTH}
CONFUSABLES = {
    # Cyrillic lower / upper
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "һ": "h", "к": "k", "ԛ": "q", "ԝ": "w",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X", "І": "I", "Ј": "J", "Ѕ": "S", "У": "Y",
    # Greek
    "ο": "o", "α": "a", "ν": "v", "ρ": "p", "ι": "i", "κ": "k", "υ": "u", "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M",
    "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
}
_WORD = re.compile(r"\S+")
_ASCII = re.compile(r"[A-Za-z0-9]")


def fold(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).translate(_ZW)
    if t.isascii():
        return t

    def w(m):
        s = m.group(0)
        if _ASCII.search(s) and any(c in CONFUSABLES for c in s):
            return "".join(CONFUSABLES.get(c, c) for c in s)
        return s

    return _WORD.sub(w, t)
