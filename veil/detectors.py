"""Regex detectors. CPT codes, dollar amounts, and service dates are intentionally NOT detected (they stay in the clear)."""
from __future__ import annotations
import re

_VAL = r"(?=[A-Za-z0-9-]*\d)([A-Za-z0-9][A-Za-z0-9-]{4,})"
_NAME = r"([A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+){1,3}|[A-Z][A-Za-z'-]+, [A-Z][A-Za-z.'-]+(?: [A-Z]\.?)?)"
_STREET = r"(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Boulevard|Blvd|Court|Ct|Way|Place|Pl|Terrace|Circle)"

_VALMIX = r"(?=[A-Za-z0-9-]*[A-Za-z])(?=[A-Za-z0-9-]*\d)([A-Za-z0-9][A-Za-z0-9-]{5,})"   # letters AND digits, so a date is never read as an id
_MON = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
_OLD = r"(?:19\d{2}|200[0-8])"   # a date this old is a birth date, not a service date
_NAME_PROSE = r"([A-Z][A-Za-z'-]+(?:[ \t]+[A-Z][A-Za-z'-]+){0,3})"
_TITLE = r"(?:Mr|Mrs|Ms|Miss|Mx|Dr)\.?"

# (kind, compiled regex, capture group index)
DETECTORS: list[tuple[str, re.Pattern, int]] = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"), 0),
    ("SSN", re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"), 0),
    ("PHONE", re.compile(r"(?<![\d-])(?:\+?1[-.\s])?\(?\d{3}\)?[-.\s]\d{3}[-.]\d{4}(?!\d)"), 0),
    ("DOB", re.compile(
        r"(?i)\b(?:DOB|D\.O\.B\.|Date of Birth|Birth ?date)\s*[:\-]?\s*"
        r"(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}|" + _MON + r" \d{1,2}(?:st|nd|rd|th)?,? \d{4}|\d{1,2}(?:st|nd|rd|th)? " + _MON + r",? \d{4})"), 1),
    ("DOB", re.compile(r"(?i)\b(" + _MON + r" \d{1,2}(?:st|nd|rd|th)?,? " + _OLD + r"|\d{1,2}(?:st|nd|rd|th)? " + _MON + r",? " + _OLD + r")\b"), 1),
    ("DOB", re.compile(r"(?<![\d/])(\d{1,2}/\d{1,2}/" + _OLD + r")(?![\d/])"), 1),
    ("DOB", re.compile(r"(?<![\d-])(" + _OLD + r"-\d{2}-\d{2})(?![\d-])"), 1),
    ("MEMBER_ID", re.compile(r"(?i)\b(?:Member|Subscriber|Policy|Insured)\s*(?:ID|No\.?|Number|#)\s*[:#]\s*" + _VAL), 1),
    ("MEMBER_ID", re.compile(r"\b[A-Z]{3}\d{9}\b"), 0),
    ("MEMBER_ID", re.compile(r"(?i)\b(?:Member|Subscriber|Policy|Insured)(?:[ \t]+(?:ID|No\.?|Number|#))?[ \t]+#?[ \t]*" + _VALMIX), 1),
    ("CLAIM_NO", re.compile(r"(?i)\b(?:Claim|ICN)(?:[ \t]+(?:No\.?|Number|#|ID|Ref(?:erence)?))?[ \t]+#?[ \t]*" + _VALMIX), 1),
    ("CLAIM_NO", re.compile(r"\b[A-Z]{2}\d{8}\b"), 0),
    ("ACCOUNT_NO", re.compile(r"\b[A-Z]{2,3}-\d{6,}\b"), 0),
    ("ACCOUNT_NO", re.compile(r"(?i)\b(?:Patient Account|Guarantor Account|Account|Acct)\s*(?:No\.?|Number|#|ID)?\s*[:#]\s*" + _VAL), 1),
    ("CLAIM_NO", re.compile(r"(?i)\b(?:Claim|ICN)\s*(?:No\.?|Number|#|ID|Ref(?:erence)?)?\s*[:#]\s*" + _VAL), 1),
    ("ADDRESS", re.compile(
        r"\b\d{1,6} (?:[A-Z][A-Za-z0-9.'-]* ){1,4}" + _STREET + r"\b\.?"
        r"(?:,? (?:Apt|Suite|Ste|Unit|#) ?[\w-]+)?"
        r"(?:,?[ \t\r\n]+[A-Z][A-Za-z.]+(?: [A-Z][A-Za-z.]+)?,? [A-Z]{2} \d{5}(?:-\d{4})?)?"), 0),
    ("PERSON", re.compile(
        r"(?m)\b(?:Patient Name|Patient|Member Name|Subscriber|Guarantor|Insured|Account Holder|Name)[ \t]*:[ \t]*" + _NAME), 1),
    ("PERSON", re.compile(r"\b" + _TITLE + r"[ \t]+([A-Z][a-z'-]+(?:[ \t]+[A-Z][a-z'-]+)?)"), 1),
    ("PERSON", re.compile(r"\b(?:my name is|I am|I'm|patient)[ \t]+(?:" + _TITLE + r"[ \t]+)?" + _NAME_PROSE), 1),
    ("PERSON", re.compile(r"(?m)\b(?:Sincerely|Regards|Best regards|Respectfully|Yours truly|Thank you),?[ \t]*\r?\n[ \t]*" + _NAME_PROSE), 1),
]

# Detectors the canary and the redactor use that web/pseudo.js does not carry yet: spec() leaves them out, so the generated JS stays byte-identical
# until it is regenerated from a template that has them. Birth dates in the shapes people actually write (dotted day-first, two-digit and
# apostrophe years, spelled out), a "born" / JSON-key cue, and an account number wrapped across two lines.
_NUM_DATE = r"\d{1,2}[./-]\d{1,2}[./-](?:\d{4}|\d{2})|\d{4}[./-]\d{1,2}[./-]\d{1,2}|\d{8}"
_ORD = r"(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|eighteenth|nineteenth|twentieth|twenty-first|twenty-second|twenty-third|twenty-fourth|twenty-fifth|twenty-sixth|twenty-seventh|twenty-eighth|twenty-ninth|thirtieth|thirty-first)"
_YEAR_WORDS = r"nineteen[\s-]+(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[\s-]+(?:one|two|three|four|five|six|seven|eight|nine))?|(?:oh|aught)[\s-]+(?:one|two|three|four|five|six|seven|eight|nine)|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)"
_LONG_DATE = (_MON + r"[ \t]+\d{1,2}(?:st|nd|rd|th)?,?[ \t]+(?:\d{4}|'\d{2})|\d{1,2}(?:st|nd|rd|th)?[ \t]+" + _MON + r",?[ \t]+(?:\d{4}|'\d{2})|"
              + _ORD + r"[ \t]+(?:of[ \t]+)?" + _MON + r",?[ \t]+" + _YEAR_WORDS)
EXTRA_DETECTORS: list[tuple[str, re.Pattern, int]] = [
    ("DOB", re.compile(r"(?i)\b(?:DOB|D\.O\.B\.?|Date of Birth|Birth ?date|Birthday|born(?:[ \t]+(?:on|in))?)[\"'\s:=\-]{0,6}(" + _NUM_DATE + "|" + _LONG_DATE + r")(?![\d])"), 1),
    ("DOB", re.compile(r"(?<![\d.])(\d{1,2}\.\d{1,2}\." + _OLD + r")(?![\d.])"), 1),
    ("DOB", re.compile(r"(?<![\d-])(\d{1,2}-\d{1,2}-" + _OLD + r")(?![\d-])"), 1),
    ("DOB", re.compile(r"(?i)\b(" + _MON + r"[ \t]+\d{1,2},?[ \t]+'\d{2})(?!\d)"), 1),
    ("DOB", re.compile(r"(?i)\b(" + _ORD + r"[ \t]+(?:of[ \t]+)?" + _MON + r",?[ \t]+" + _YEAR_WORDS + r")\b"), 1),
    ("ACCOUNT_NO", re.compile(r"\b([A-Z]{2,3}-[ \t]*\r?\n[ \t]*\d{6,})\b"), 1),
]

KIND_LABEL = {
    "EMAIL": "email", "SSN": "SSN", "PHONE": "phone", "DOB": "date of birth", "MEMBER_ID": "member ID",
    "ACCOUNT_NO": "account number", "CLAIM_NO": "claim number", "ADDRESS": "address", "PERSON": "person name",
}


def find(text: str):
    """Yield (kind, value) for every detector hit in text."""
    for kind, rx, grp in DETECTORS + EXTRA_DETECTORS:
        for m in rx.finditer(text):
            v = m.group(grp).strip().rstrip(".,;")
            if v and "[" not in v:
                yield kind, v


def spec() -> list[dict]:
    """Portable description of DETECTORS for web/pseudo.js (tools/gen_js.py). Leading (?i)/(?m) become JS flags."""
    out = []
    for kind, rx, grp in DETECTORS:
        src, flags = rx.pattern, ""
        while src.startswith("(?") and src[2] in "im" and src[3] == ")":
            flags += src[2]; src = src[4:]
        out.append(dict(kind=kind, src=src, flags=flags, group=grp))
    return out
