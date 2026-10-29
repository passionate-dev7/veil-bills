"""Regex detectors. CPT codes, dollar amounts, and service dates are intentionally NOT detected (they stay in the clear)."""
from __future__ import annotations
import re

_VAL = r"(?=[A-Za-z0-9-]*\d)([A-Za-z0-9][A-Za-z0-9-]{4,})"
_NAME = r"([A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+){1,3}|[A-Z][A-Za-z'-]+, [A-Z][A-Za-z.'-]+(?: [A-Z]\.?)?)"
_STREET = r"(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Boulevard|Blvd|Court|Ct|Way|Place|Pl|Terrace|Circle)"

# (kind, compiled regex, capture group index)
DETECTORS: list[tuple[str, re.Pattern, int]] = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"), 0),
    ("SSN", re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"), 0),
    ("PHONE", re.compile(r"(?<![\d-])(?:\+?1[-.\s])?\(?\d{3}\)?[-.\s]\d{3}[-.]\d{4}(?!\d)"), 0),
    ("DOB", re.compile(
        r"(?i)\b(?:DOB|D\.O\.B\.|Date of Birth|Birth ?date)\s*[:\-]?\s*"
        r"(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}|[A-Z][a-z]+ \d{1,2}, \d{4})"), 1),
    ("MEMBER_ID", re.compile(r"(?i)\b(?:Member|Subscriber|Policy|Insured)\s*(?:ID|No\.?|Number|#)\s*[:#]\s*" + _VAL), 1),
    ("MEMBER_ID", re.compile(r"\b[A-Z]{3}\d{9}\b"), 0),
    ("ACCOUNT_NO", re.compile(r"(?i)\b(?:Patient Account|Guarantor Account|Account|Acct)\s*(?:No\.?|Number|#|ID)?\s*[:#]\s*" + _VAL), 1),
    ("CLAIM_NO", re.compile(r"(?i)\b(?:Claim|ICN)\s*(?:No\.?|Number|#|ID|Ref(?:erence)?)?\s*[:#]\s*" + _VAL), 1),
    ("ADDRESS", re.compile(
        r"\b\d{1,6} (?:[A-Z][A-Za-z0-9.'-]* ){1,4}" + _STREET + r"\b\.?"
        r"(?:,? (?:Apt|Suite|Ste|Unit|#) ?[\w-]+)?"
        r"(?:,?[ \t\r\n]+[A-Z][A-Za-z.]+(?: [A-Z][A-Za-z.]+)?,? [A-Z]{2} \d{5}(?:-\d{4})?)?"), 0),
    ("PERSON", re.compile(
        r"(?m)\b(?:Patient Name|Patient|Member Name|Subscriber|Guarantor|Insured|Account Holder|Name)[ \t]*:[ \t]*" + _NAME), 1),
]

KIND_LABEL = {
    "EMAIL": "email", "SSN": "SSN", "PHONE": "phone", "DOB": "date of birth", "MEMBER_ID": "member ID",
    "ACCOUNT_NO": "account number", "CLAIM_NO": "claim number", "ADDRESS": "address", "PERSON": "person name",
}


def find(text: str):
    """Yield (kind, value) for every detector hit in text."""
    for kind, rx, grp in DETECTORS:
        for m in rx.finditer(text):
            v = m.group(grp).strip().rstrip(".,;")
            if v and "[" not in v:
                yield kind, v
