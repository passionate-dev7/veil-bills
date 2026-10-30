"""Head-to-head redaction benchmark: Veil vs Microsoft Presidio, scored against the HIPAA Safe Harbor identifier list (45 CFR 164.514(b)(2)(i), A-R).
ALL TEXT IS SYNTHETIC. Nothing here is a HIPAA compliance claim: it scores recall and precision against the 18 listed identifier categories.

  Full run (needs presidio; use the benchmark venv):   ~/.venvs/presidio-bench/bin/python eval/presidio_benchmark.py
  Veil-only (stdlib, used by the test-suite):          .venv/bin/python eval/presidio_benchmark.py --veil-only   (prints, writes nothing)

Writes eval/presidio_results.json and eval/presidio_results.md. No network, no Token Factory.

Method
  gold      hand/auto-annotated spans: demo/corpus PDFs + 5 more synthetic personas (veil.synth.eval_cases), hard cases and synthetic extras
  recall    a gold identifier counts as removed only if EVERY alphanumeric character of it is covered by some predicted span (any label)
  precision a predicted span is a true positive if it overlaps a gold span of the same letter (phone~fax count as one family); a span that only
            overlaps a "neutral" span (provider/insurer name, provider address, state, group number) is ignored; anything else is a false positive
  Presidio  AnalyzerEngine + en_core_web_lg. Three score thresholds (0, 0.35, 0.5) are run and each configuration is reported at its best micro-F1
            threshold, which favours Presidio. All thresholds are in the JSON.
  Veil      the shipped Pseudonymizer. 'cold' = empty vault, detectors only (the like-for-like comparison). 'primed' = vault loaded with the
            patient's profile (what Veil does in the product).
"""
from __future__ import annotations
import json, re, sys, tempfile, unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).resolve().parent))
from veil import synth
from veil.fold import fold
from veil.pseudo import Pseudonymizer
from veil.vault import Vault, TOKEN_RE
from veil.extract import pdf_text
import presidio_cases as C

SAFE_HARBOR_URL = "https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html"
SAFE_HARBOR_VERIFIED = "2026-10-30"
# Verified against the HHS page above (45 CFR 164.514(b)(2)(i)); wording shortened, letters as HHS prints them.
LETTERS = [
    ("A", "Names"),
    ("B", "Geographic subdivisions smaller than a state (street, city, county, precinct, ZIP, geocodes)"),
    ("C", "All elements of dates except year, directly related to the individual (birth, admission, discharge, death); ages over 89"),
    ("D", "Telephone numbers"),
    ("E", "Fax numbers"),
    ("F", "Email addresses"),
    ("G", "Social security numbers"),
    ("H", "Medical record numbers"),
    ("I", "Health plan beneficiary numbers"),
    ("J", "Account numbers"),
    ("K", "Certificate/license numbers"),
    ("L", "Vehicle identifiers and serial numbers, including license plates"),
    ("M", "Device identifiers and serial numbers"),
    ("N", "Web URLs"),
    ("O", "IP addresses"),
    ("P", "Biometric identifiers, including finger and voice prints"),
    ("Q", "Full-face photographs and comparable images"),
    ("R", "Any other unique identifying number, characteristic, or code"),
]
SHORT = dict(A="Names", B="Geography (street, city, ZIP, county)", C="Dates except year; ages over 89", D="Phone numbers", E="Fax numbers", F="Email addresses",
             G="Social security numbers", H="Medical record numbers", I="Health plan IDs", J="Account numbers", K="Certificate / license numbers",
             L="Vehicle IDs, plates", M="Device IDs, serials", N="Web URLs", O="IP addresses", P="Biometrics", Q="Face photos", R="Other unique IDs (claim no. etc.)")
NOT_TESTED = {"P": "not in corpus / not tested: the benchmark is text-only (a fingerprint or voiceprint is not text)",
              "Q": "not in corpus / not tested: the benchmark is text-only (no images are processed)"}
FAMILY = {"D": "DE", "E": "DE"}
THRESHOLDS = [0.0, 0.35, 0.5]

VEIL_MAP = {"PERSON": "A", "ADDRESS": "B", "DOB": "C", "PHONE": "D", "EMAIL": "F", "SSN": "G", "MEMBER_ID": "I", "ACCOUNT_NO": "J", "CLAIM_NO": "R"}
PRES_MAP = {"PERSON": "A", "ORGANIZATION": "A", "LOCATION": "B", "DATE_TIME": "C", "PHONE_NUMBER": "D", "EMAIL_ADDRESS": "F", "US_SSN": "G", "US_ITIN": "G",
            "MEDICAL_LICENSE": "K", "US_DRIVER_LICENSE": "K", "US_PASSPORT": "K", "URL": "N", "IP_ADDRESS": "O", "US_BANK_NUMBER": "J",
            "CREDIT_CARD": "J", "IBAN_CODE": "J", "CRYPTO": "R",
            # custom recognizers
            "MEMBER_ID": "I", "CLAIM_NO": "R", "ACCOUNT_NO": "J", "MRN": "H", "STREET_ADDRESS": "B", "US_ZIP": "B", "TITLE_SURNAME": "A",
            "PROFILE_PERSON": "A", "PROFILE_ADDRESS": "B", "PROFILE_DOB": "C", "PROFILE_PHONE": "D", "PROFILE_EMAIL": "F", "PROFILE_SSN": "G", "PROFILE_MEMBER_ID": "I"}

TOOLS = {
    "veil": ("Veil (cold)", "Shipped redactor, empty vault: regex detectors + folding only. The like-for-like comparison."),
    "veil_primed": ("Veil (primed)", "Same, with the patient's profile loaded in the vault (how the product runs)."),
    "presidio_default": ("Presidio (defaults)", "AnalyzerEngine, en_core_web_lg, stock recognizers."),
    "presidio_custom": ("Presidio + custom regex", "Defaults plus simple regex recognizers: member/claim/account/MRN shapes, street, ZIP-after-state, Mr/Mrs surname."),
    "presidio_custom_profile": ("Presidio + custom + profile deny-list", "Adds the same patient profile Veil gets as exact-string deny lists."),
}

# ---------------------------------------------------------------- markup / gold
MARK = re.compile(r"\{\{([A-R~])\|([^|]*)\|(.*?)\}\}", re.S)


def parse_markup(s: str):
    out, spans, last = [], [], 0
    pos = 0
    for m in MARK.finditer(s):
        out.append(s[last:m.start()]); pos += m.start() - last
        txt = m.group(3)
        spans.append(dict(s=pos, e=pos + len(txt), letter=m.group(1), sub=m.group(2) or None))
        out.append(txt); pos += len(txt); last = m.end()
    out.append(s[last:])
    return "".join(out), spans


def profile_for(p) -> dict:
    zm = re.match(r"(.+?), ([A-Z]{2}) (\d{5})", p.city)
    ents = [dict(kind="PERSON", value=p.name, aliases=list(p.aliases) or [p.last_first, p.name.split()[0], p.name.split()[-1]]),
            dict(kind="MEMBER_ID", value=p.member_id), dict(kind="SSN", value=p.ssn), dict(kind="DOB", value=p.dob),
            dict(kind="PHONE", value=p.phone), dict(kind="EMAIL", value=p.email),
            dict(kind="ADDRESS", value=f"{p.street}, {p.city}", aliases=[p.street, p.city])]
    return {"entities": ents}


def corpus_docs():
    """(doc_id, text, case, profile) for the Jane PDFs and five more synthetic personas."""
    docs = []
    jane_profile = json.loads((ROOT / "demo" / "profile.json").read_text())
    jc = synth.jane_case()
    for pdf in sorted((ROOT / "demo" / "corpus").glob("*.pdf")):
        docs.append((f"jane/{pdf.name}", pdf_text(pdf), jc, jane_profile))
    for case in synth.eval_cases():
        ded = case.deductible_met_before
        for i, _ep in enumerate(case.episodes):
            eob, tot, met = synth.eob_lines(case, i, ded); ded = met
            bill, _due = synth.bill_lines(case, i, tot)
            docs.append((f"{case.id}/eob{i + 1}", "\n".join(eob), case, profile_for(case.person)))
            docs.append((f"{case.id}/bill{i + 1}", "\n".join(bill), case, profile_for(case.person)))
    return docs


def annotate(text: str, case) -> list[dict]:
    """Gold spans for one corpus document, from the generator's own knowledge of the planted values."""
    p = case.person
    zm = re.match(r"(.+?), ([A-Z]{2}) (\d{5})", p.city)
    neutral = [synth.INSURER, synth.INSURER_APPEALS, "GRP-55021", "billing-audit@evil.example"]
    for ep in case.episodes:
        pr = ep.provider
        neutral += [pr.name, pr.email, pr.street + ", " + pr.city, pr.street, pr.city]
    cands = [(v, "~", None) for v in sorted(set(neutral), key=len, reverse=True)]
    cands += [(p.name, "A", "full"), (p.last_first, "A", "full"), (p.dob, "C", "dob"), (p.member_id, "I", "labelled"), (p.ssn, "G", None),
              (p.phone, "D", None), (p.email, "F", None), (p.street, "B", "street"), (zm.group(1), "B", "city"), (zm.group(3), "B", "zip"),
              (", " + zm.group(2) + " ", "~", None)]
    for ep in case.episodes:
        cands += [(ep.claim_no, "R", "claim"), (ep.account_no, "J", "labelled")]
    found = []
    for val, letter, sub in cands:
        for m in re.finditer(re.escape(val), text):
            if letter == "~" and val.startswith(", "):
                found.append(dict(s=m.start() + 2, e=m.start() + 4, letter="~", sub=None))  # the state may stay under Safe Harbor
            else:
                found.append(dict(s=m.start(), e=m.end(), letter=letter, sub=sub))
    kept = []  # first claim wins: neutral provider/insurer strings, then patient identifiers in the order above
    def free(g):
        return not any(g["s"] < k["e"] and k["s"] < g["e"] for k in kept)
    for g in found:
        if free(g):
            kept.append(g)
    for m in re.finditer(r"(?<!\d)\d{2}/\d{2}/\d{4}(?!\d)", text):
        g = dict(s=m.start(), e=m.end(), letter="C", sub="svc")
        if free(g):
            kept.append(g)
    kept.sort(key=lambda g: g["s"])
    return kept


def build_items():
    items = []
    for doc_id, text, case, profile in corpus_docs():
        items.append(dict(id=doc_id, source="corpus", text=text, gold=annotate(text, case), profile=profile))
    jane_profile = json.loads((ROOT / "demo" / "profile.json").read_text())
    for src, cases in (("hard", C.HARD), ("extra", C.EXTRA)):
        for cid, marked in cases:
            text, gold = parse_markup(marked)
            items.append(dict(id=f"{src}/{cid}", source=src, text=text, gold=gold, profile=jane_profile))
    return items


# ---------------------------------------------------------------- tools
def _alnum_idx(text, s, e):
    return [i for i in range(s, e) if text[i].isalnum()]


def fold_map(raw: str, points) -> dict:
    return {i: len(fold(raw[:i])) for i in set(points)}


def veil_predict(text: str, profile: dict | None) -> tuple[str, list[dict]]:
    """Run the shipped Pseudonymizer's own two passes (detector hits, then vault dictionary) and keep the spans, in coordinates of fold(text).
    Asserts that the replayed output is byte-identical to Pseudonymizer.redact_text, so the spans cannot drift from the product."""
    from veil.vault import norm
    with tempfile.TemporaryDirectory() as d:
        v = Vault(Path(d) / "v.sqlite")
        if profile:
            for e in profile["entities"]:
                v.add(e["kind"], e["value"], e.get("aliases", []), source="profile")
        ps = Pseudonymizer(v)
        f = fold(text)
        ps.learn(f); ps._compile()
        segs, spans, last, inter = [], [], 0, 0   # segs: (inter_start, inter_end, orig_start, orig_end, is_token)
        parts = []
        for a, b, tok, _k in list(ps._split_hits(f)):
            if a > last:
                segs.append((inter, inter + a - last, last, a, False)); parts.append(f[last:a]); inter += a - last
            segs.append((inter, inter + len(tok), a, b, True)); parts.append(tok); inter += len(tok)
            spans.append((a, b, tok)); last = b
        if last < len(f) or not segs:
            segs.append((inter, inter + len(f) - last, last, len(f), False)); parts.append(f[last:])
        mid = "".join(parts)

        def to_orig(pos, end):
            for i0, i1, o0, o1, is_tok in segs:
                if i0 <= pos < i1 or (end and pos == i1 and i0 < pos):
                    return (o1 if end else o0) if is_tok else o0 + (pos - i0)
            return len(f)
        edits = []
        for m in ps._rx.finditer(mid):
            tok = ps._tok.get(norm(m.group(0)))
            if tok is not None:
                edits.append((to_orig(m.start(), False), to_orig(m.end(), True), tok, m.start(), m.end()))
        out = ps.redact_text(text)
        # replay
        res, pos = [], 0
        for a, b, t, ms, me in edits:
            res.append(mid[pos:ms]); res.append(t); pos = me
        res.append(mid[pos:])
        assert "".join(res) == out, "span replay diverged from Pseudonymizer.redact_text"
        v.close()
    allspans = [(a, b, tok) for a, b, tok in spans] + [(a, b, tok) for a, b, tok, _x, _y in edits]
    outl = []
    for a, b, tok in allspans:
        kind = tok.strip("[]").rsplit("_", 1)[0]
        outl.append(dict(s=a, e=b, label=kind, letter=VEIL_MAP.get(kind)))
    return f, outl


def build_presidio(kind: str):
    from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    nlp = NlpEngineProvider(nlp_configuration={"nlp_engine_name": "spacy", "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}]}).create_engine()
    eng = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])
    if kind in ("presidio_custom", "presidio_custom_profile"):
        def R(ent, *rx, score=0.85):
            eng.registry.add_recognizer(PatternRecognizer(supported_entity=ent, patterns=[Pattern(f"{ent}{i}", r, score) for i, r in enumerate(rx)]))
        R("MEMBER_ID", r"\b[A-Z]{1,3}\d{9}\b", r"\b[A-Z]{3}[ -]\d{3}[ -]\d{3}[ -]\d{3}\b")
        R("CLAIM_NO", r"\b[A-Z]{2}\d{8}\b")
        R("ACCOUNT_NO", r"\b[A-Z]{2,3}-\d{6,}\b", r"(?<=Account No: )\d{6,}", r"(?<=Account Number: )\d{6,}")
        R("MRN", r"(?i)\bMRN:?\s*\d{5,}\b", r"(?i)\bmedical record number\s+[A-Z]{0,3}-?\d{5,}\b", r"(?i)\bchart\s*#\s*\d{5,}\b")
        R("STREET_ADDRESS", r"\b\d{1,6} (?:[A-Z][a-z]+ ){1,3}(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Boulevard|Blvd|Court|Ct|Way|Place|Pl|Terrace)\b(?:, (?:Apt|Suite|Unit) \w+)?")
        R("US_ZIP", r"(?<=[A-Z]{2} )\d{5}\b", r"(?i)(?<=ZIP )\d{5}\b")
        R("TITLE_SURNAME", r"\b(?:Mr|Mrs|Ms|Dr)\.? [A-Z][a-z]+\b", score=0.7)
    return eng


def deny_recognizers(eng, profile):
    from presidio_analyzer import PatternRecognizer
    by = defaultdict(list)
    for e in profile["entities"]:
        ent = "PROFILE_" + e["kind"]
        by[ent] += [e["value"]] + list(e.get("aliases", []))
    made = []
    for ent, vals in by.items():
        r = PatternRecognizer(supported_entity=ent, deny_list=sorted(set(vals), key=len, reverse=True), name=ent + "_deny")
        eng.registry.add_recognizer(r); made.append(r)
    return made


def presidio_predict(eng, text, thr, profile, deny):
    if deny:
        made = deny_recognizers(eng, profile)
    try:
        res = eng.analyze(text=text, language="en", score_threshold=thr)
    finally:
        if deny:
            for r in made:
                eng.registry.remove_recognizer(r.name)
    return [dict(s=r.start, e=r.end, label=r.entity_type, letter=PRES_MAP.get(r.entity_type), score=round(r.score, 2)) for r in res]


# ---------------------------------------------------------------- scoring
def overlap(a, b):
    return a["s"] < b["e"] and b["s"] < a["e"]


def score_item(item, preds, coords):
    """coords: maps raw gold offsets into the tool's coordinate system (identity for Presidio, fold prefix lengths for Veil)."""
    text = item["_text"]
    gold = [dict(g, s=coords[g["s"]], e=coords[g["e"]]) for g in item["gold"]]
    covered = set()
    for p in preds:
        covered.update(range(p["s"], p["e"]))
    gres = []
    for g in gold:
        if g["letter"] == "~":
            continue
        idx = _alnum_idx(text, g["s"], g["e"])
        gres.append(dict(letter=g["letter"], sub=g["sub"], source=item["source"], hit=bool(idx) and all(i in covered for i in idx), txt=text[g["s"]:g["e"]]))
    pres = []
    for p in preds:
        L = p["letter"]
        same = [g for g in gold if g["letter"] != "~" and overlap(p, g) and FAMILY.get(g["letter"], g["letter"]) == FAMILY.get(L, L)]
        anyid = [g for g in gold if g["letter"] != "~" and overlap(p, g)]
        neutral = [g for g in gold if g["letter"] == "~" and overlap(p, g)]
        if L and same:
            out = "tp"
        elif neutral and not anyid:
            out = "neutral"
        else:
            out = "fp"
        svc = bool(anyid) and all(g["sub"] == "svc" for g in anyid)
        pres.append(dict(letter=L, label=p["label"], out=out, svc=svc, txt=text[p["s"]:p["e"]][:40]))
    return gres, pres


def run_tool(tool, items, eng=None, thr=0.0):
    G, P = [], []
    for it in items:
        text = it["text"]
        if tool in ("veil", "veil_primed"):
            f, preds = veil_predict(text, it["profile"] if tool == "veil_primed" else None)
            pts = [g[k] for g in it["gold"] for k in ("s", "e")] + [0, len(text)]
            fm = fold_map(text, pts)
            it["_text"] = f
            g, p = score_item(it, preds, fm)
        else:
            preds = presidio_predict(eng, text, thr, it["profile"], tool == "presidio_custom_profile")
            it["_text"] = text
            g, p = score_item(it, preds, {i: i for i in range(len(text) + 1)})
        for x in g: x["doc"] = it["id"]
        for x in p: x["doc"] = it["id"]
        G += g; P += p
    return G, P


def rate(a, b):
    return None if b == 0 else round(a / b, 4)


def aggregate(G, P, scope="all"):
    """scope 'all': every Safe Harbor letter as printed.  scope 'veil': drop service/notice dates (Veil keeps them by design)."""
    if scope == "veil":
        G = [g for g in G if g["sub"] != "svc"]
        P = [dict(p, out="neutral") if p["svc"] and p["out"] in ("tp", "fp") else p for p in P]
    rows = {}
    for L, _n in LETTERS:
        gl = [g for g in G if g["letter"] == L]
        fam = FAMILY.get(L, L)
        pl = [p for p in P if p["letter"] and FAMILY.get(p["letter"], p["letter"]) == fam]   # phone and fax share one precision (D~E family)
        tp, fp = sum(p["out"] == "tp" for p in pl), sum(p["out"] == "fp" for p in pl)
        rows[L] = dict(n_gold=len(gl), hit=sum(g["hit"] for g in gl), recall=rate(sum(g["hit"] for g in gl), len(gl)), tp_pred=tp, fp_pred=fp, precision=rate(tp, tp + fp))
    tp_all = sum(p["out"] == "tp" for p in P); fp_all = sum(p["out"] == "fp" for p in P)
    unm = [p for p in P if p["letter"] is None and p["out"] == "fp"]
    hit_all = sum(r["hit"] for r in rows.values()); n_all = sum(r["n_gold"] for r in rows.values())
    pr, rc = rate(tp_all, tp_all + fp_all), rate(hit_all, n_all)
    f1 = None if not pr or not rc else round(2 * pr * rc / (pr + rc), 4)
    return rows, dict(n_gold=n_all, hit=hit_all, recall=rc, tp_pred=tp_all, fp_pred=fp_all, precision=pr, f1=f1, unmapped_fp=len(unm))


def subbreakdown(G):
    keys = sorted({(g["letter"], g["sub"] or "-") for g in G})
    out = []
    for L, s in keys:
        gl = [g for g in G if g["letter"] == L and (g["sub"] or "-") == s]
        out.append(dict(letter=L, sub=s, n_gold=len(gl), hit=sum(g["hit"] for g in gl), recall=rate(sum(g["hit"] for g in gl), len(gl))))
    return out


def fp_examples(P, k=8):
    c = Counter((p["label"], p["txt"]) for p in P if p["out"] == "fp")
    by = Counter(p["label"] for p in P if p["out"] == "fp")
    return dict(by_label=dict(by.most_common()), examples=[dict(label=l, text=t, count=n) for (l, t), n in c.most_common(k)])


def source_counts(G):
    d = defaultdict(Counter)
    for g in G:
        d[g["letter"]][g["source"]] += 1
    return {k: dict(v) for k, v in d.items()}


def main(veil_only=False):
    items = build_items()
    veil_only_results = {}
    results = {}
    for tool in ("veil", "veil_primed"):
        G, P = run_tool(tool, items)
        results[tool] = dict(G=G, P=P, thr=None)
    if not veil_only:
        for tool in ("presidio_default", "presidio_custom", "presidio_custom_profile"):
            eng = build_presidio(tool)
            best = None; sens = {}
            for thr in THRESHOLDS:
                G, P = run_tool(tool, items, eng, thr)
                _r, tot = aggregate(G, P)
                sens[str(thr)] = dict(precision=tot["precision"], recall=tot["recall"], f1=tot["f1"], fp=tot["fp_pred"])
                if best is None or (tot["f1"] or 0) > best[0]:
                    best = (tot["f1"] or 0, thr, G, P)
            results[tool] = dict(G=best[2], P=best[3], thr=best[1], sens=sens)
    if veil_only:
        return {t: aggregate(r["G"], r["P"]) for t, r in results.items()}, results, items
    return results, items


def build_json(results, items):
    import importlib.metadata as md
    corp = [i for i in items if i["source"] == "corpus"]
    meta = dict(
        generated="2026-10-30", safe_harbor_source=SAFE_HARBOR_URL, safe_harbor_verified=SAFE_HARBOR_VERIFIED,
        presidio_analyzer=md.version("presidio-analyzer"), presidio_anonymizer=md.version("presidio-anonymizer"), spacy_model="en_core_web_lg " + md.version("en_core_web_lg"),
        presidio_thresholds_tried=THRESHOLDS, documents=dict(corpus=len(corp), hard_cases=sum(i["source"] == "hard" for i in items), synthetic_extras=sum(i["source"] == "extra" for i in items)),
        data="all synthetic (fictional patients; no real PHI)",
        claim="Scored against the HIPAA Safe Harbor identifier list. This is not a HIPAA compliance claim, and Veil does not meet Safe Harbor by design: it keeps service dates, amounts, CPT codes and provider names/addresses in the clear so the audit math works.")
    tools = {}
    for t, (label, desc) in TOOLS.items():
        r = results[t]
        rows_all, tot_all = aggregate(r["G"], r["P"], "all")
        rows_v, tot_v = aggregate(r["G"], r["P"], "veil")
        tools[t] = dict(label=label, description=desc, threshold=r["thr"], sensitivity=r.get("sens"), rows=rows_all, total=tot_all, rows_veil_scope=rows_v, total_veil_scope=tot_v,
                        breakdown=subbreakdown(r["G"]), false_positives=fp_examples(r["P"]), gold_by_source=source_counts(r["G"]))
    ref = tools["veil"]["rows"]
    idrows = []
    for L, name in LETTERS:
        n = ref[L]["n_gold"]; src = tools["veil"]["gold_by_source"].get(L, {})
        if L in NOT_TESTED:
            status, note = "not_tested", NOT_TESTED[L]
        elif n == 0:
            status, note = "not_tested", "not in corpus / not tested"
        elif "corpus" not in src:
            status, note = "synthetic_only", f"{n} hand-written example(s) only; the generated corpus has none"
        else:
            status, note = "tested", ""
        idrows.append(dict(letter=L, name=name, short=SHORT[L], status=status, note=note, n_gold=n, gold_by_source=src,
                           tools={t: {k: tools[t]["rows"][L][k] for k in ("recall", "hit", "precision", "tp_pred", "fp_pred")} for t in TOOLS}))
    return dict(meta=meta, tools=tools, identifiers=idrows, safe_harbor_letters=[dict(letter=a, name=b) for a, b in LETTERS], notes=NOTES)


NOTES = [
    "Dates: HIPAA Safe Harbor requires removing every element of a date directly related to the patient except the year. Veil deliberately keeps service, notice and statement dates in the clear so the audit math (deductibles, 180-day appeal windows) works. Veil therefore does NOT meet Safe Harbor by design, and its recall on service dates is 0 on purpose. It removes birth dates.",
    "The same applies to provider names and addresses, ZIP codes of providers, CPT codes and dollar amounts: Veil may keep them. HHS FAQ 3.8 does not require removing provider names, so they are scored neutral (neither a miss nor a false alarm); patient addresses, ZIP codes and cities are scored as identifiers (letter B).",
    "Two scopes are reported. 'All identifiers' counts every Safe Harbor letter as printed, including service dates. 'Veil scope' drops service dates for every tool so the comparison is about what Veil tries to remove.",
    "Veil cold vs primed: cold means an empty vault (detectors only), the fair match for Presidio's stock behaviour. Primed means the patient profile is loaded, which is how the product runs; Presidio gets the same profile as exact-string deny lists in the last configuration.",
    "Small n: the Jane/persona corpus repeats the same six identifier types in templated documents, so per-letter counts are small. Hard cases and synthetic extras are hand-written to probe known weak spots and are not a sample of real documents. Treat the numbers as a probe, not a population estimate.",
    "Letters P (biometrics) and Q (photographs) are not tested: the benchmark is text-only. Letters D through O (phone, fax, email, SSN, MRN, license, vehicle, device, URL, IP) have no instances in the generated documents and are tested on a handful of hand-written examples only, and Veil has no detector for K, L, M, N, O or free-text employer/relative names.",
    "Presidio is run at three score thresholds and each configuration is reported at its best micro-F1 threshold, which favours Presidio. The custom recognizers are deliberately simple regexes, not a copy of Veil's detectors.",
]


def pct(x):
    return "n/a" if x is None else f"{round(x * 100)}%"


def build_md(J):
    m = J["meta"]; T = J["tools"]; ids = ["veil", "presidio_default", "presidio_custom"]
    L = ["# Veil vs Microsoft Presidio, scored against the HIPAA Safe Harbor identifier list", "",
         f"Source of the list: [{SAFE_HARBOR_URL}]({SAFE_HARBOR_URL}) (45 CFR 164.514(b)(2)(i), identifiers A to R, checked {m['safe_harbor_verified']}). "
         f"Presidio {m['presidio_analyzer']} with {m['spacy_model']}. All data is synthetic: {m['documents']['corpus']} corpus documents "
         f"(the 6 Jane Doe PDFs from `demo/corpus` plus {m['documents']['corpus'] - 6} generated EOB and bill documents for 5 more synthetic personas), {m['documents']['hard_cases']} hard cases, {m['documents']['synthetic_extras']} synthetic extras.", "",
         "> **Plainly: Veil does not meet HIPAA Safe Harbor, by design.** Safe Harbor requires removing every date element except the year; Veil keeps service dates, "
         "amounts, CPT codes and provider names and addresses in the clear so the audit math works. This benchmark is *scored against the Safe Harbor identifier list*. "
         "It is not a HIPAA compliance claim, and neither tool is certified by it.", "",
         "## Per identifier: precision (P) and recall (R)", "",
         "Recall = share of gold identifiers fully removed. Precision = share of a tool's redactions in that category that hit a real identifier of that category. "
         "`n` is the number of gold identifiers. `n/a` precision means the tool made no detection in that category. Phone and fax share one precision (D and E). Presidio columns are at each configuration's best-F1 threshold.", "",
         "| | Identifier | n | Veil (cold) P / R | Presidio defaults P / R | Presidio + custom P / R | Veil (primed) P / R |", "|---|---|---:|---|---|---|---|"]
    def cell(t, r):
        x = r["tools"][t]
        return f"{pct(x['precision'])} / {pct(x['recall'])}"
    for r in J["identifiers"]:
        if r["status"] == "not_tested":
            L.append(f"| {r['letter']} | {r['name']} | 0 | *{r['note']}* | | | |")
        else:
            tag = " (synthetic examples only)" if r["status"] == "synthetic_only" else ""
            L.append(f"| {r['letter']} | {r['name']}{tag} | {r['n_gold']} | " + " | ".join(cell(t, r) for t in ("veil", "presidio_default", "presidio_custom", "veil_primed")) + " |")
    L += ["", "## Totals", "", "| Configuration | Threshold | Precision | Recall | F1 | False positives | Recall (Veil scope, service dates dropped) |", "|---|---:|---:|---:|---:|---:|---:|"]
    for t in TOOLS:
        a, v = T[t]["total"], T[t]["total_veil_scope"]
        L.append(f"| {T[t]['label']} | {T[t]['threshold'] if T[t]['threshold'] is not None else '-'} | {pct(a['precision'])} | {pct(a['recall'])} | {pct(a['f1'])} | {a['fp_pred']} | {pct(v['recall'])} |")
    L += ["", "Veil scope drops service, notice and statement dates for every tool (they are kept in the clear on purpose).", "", "## Hard-case breakdown (recall)", "",
          "| Letter / kind | n | Veil (cold) | Presidio defaults | Presidio + custom | Veil (primed) |", "|---|---:|---:|---:|---:|---:|"]
    bd = {t: {(b["letter"], b["sub"]): b for b in T[t]["breakdown"]} for t in TOOLS}
    for (l, s), b in sorted(bd["veil"].items()):
        L.append(f"| {l} {s} | {b['n_gold']} | " + " | ".join(pct(bd[t][(l, s)]["recall"]) for t in ("veil", "presidio_default", "presidio_custom", "veil_primed")) + " |")
    L += ["", "## Where each tool wins", ""]
    L += WINS_PLACEHOLDER
    L += ["", "## Notes and limits", ""] + [f"- {n}" for n in J["notes"]]
    L += ["", "## False positives (largest buckets)", ""]
    for t in TOOLS:
        fp = T[t]["false_positives"]
        L.append(f"- **{T[t]['label']}**: " + (", ".join(f"{k} {v}" for k, v in list(fp["by_label"].items())[:6]) or "none"))
    L += ["", "Reproduce: `~/.venvs/presidio-bench/bin/python eval/presidio_benchmark.py` (no network, no Token Factory).", ""]
    return "\n".join(L)


WINS_PLACEHOLDER: list[str] = []


def wins_text(J):
    """Honest, computed summary of where each tool wins, per identifier letter (cold Veil vs Presidio best of default/custom)."""
    out = []
    for r in J["identifiers"]:
        if r["status"] == "not_tested" or r["n_gold"] == 0:
            continue
        v = r["tools"]["veil"]; pd = r["tools"]["presidio_default"]; pc = r["tools"]["presidio_custom"]
        best_p = max([x for x in (pd["recall"], pc["recall"]) if x is not None], default=None)
        vr = v["recall"]
        if vr is None or best_p is None:
            continue
        if vr > best_p + 0.02:
            w = "Veil"
        elif best_p > vr + 0.02:
            w = "Presidio"
        else:
            w = "tie"
        out.append((r["letter"], r["name"], w, vr, pd["recall"], pc["recall"]))
    return out


if __name__ == "__main__":
    veil_only = "--veil-only" in sys.argv
    if veil_only:
        agg, _res, _items = main(veil_only=True)
        for t, (rows, tot) in agg.items():
            print(t, tot)
        sys.exit(0)
    results, items = main()
    J = build_json(results, items)
    W = wins_text(J)
    WINS_PLACEHOLDER[:] = ["Recall by identifier, cold Veil against the better of the two stock-or-custom Presidio setups (a win needs a gap above 2 points):", ""] + \
        [f"- **{l} {n}: {w}** (Veil {pct(vr)}, Presidio defaults {pct(a)}, Presidio custom {pct(b)})" for l, n, w, vr, a, b in W]
    J["wins"] = [dict(letter=l, name=n, winner=w, veil=vr, presidio_default=a, presidio_custom=b) for l, n, w, vr, a, b in W]
    (ROOT / "eval" / "presidio_results.json").write_text(json.dumps(J, indent=1, ensure_ascii=False) + "\n")
    (ROOT / "eval" / "presidio_results.md").write_text(build_md(J))
    (ROOT / "web" / "presidio_results.json").write_text((ROOT / "eval" / "presidio_results.json").read_text())   # the judge page fetches this byte-identical copy
    print("wrote eval/presidio_results.json and .md")
    for t in TOOLS:
        a = J["tools"][t]["total"]
        print(f"{TOOLS[t][0]:42s} thr={J['tools'][t]['threshold']} P={pct(a['precision'])} R={pct(a['recall'])} F1={pct(a['f1'])} FP={a['fp_pred']}")
