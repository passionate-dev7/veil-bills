"""Deterministic audit. All money math is integer cents in plain Python; no model does arithmetic."""
from __future__ import annotations
from collections import Counter
from datetime import date, timedelta


def usd(c: int | None) -> str:
    return "n/a" if c is None else f"${c / 100:,.2f}"


def _same_provider(a: str, b: str) -> bool:
    ta, tb = set(a.lower().replace(",", " ").split()), set(b.lower().replace(",", " ").split())
    return bool(ta & tb) and len(ta & tb) >= min(len(ta), len(tb)) * 0.6


def check_internal(doc: dict) -> list[str]:
    """Extraction sanity: do the extracted lines add up to the extracted totals?"""
    w = []
    s = sum(l["billed"] or 0 for l in doc["lines"])
    if doc["total_billed"] is not None and doc["total_billed"] != s:
        w.append(f"{doc['doc_type']} lines sum to {usd(s)} but total_billed is {usd(doc['total_billed'])}")
    if doc["doc_type"] == "eob":
        p = sum(l["patient_responsibility"] or 0 for l in doc["lines"])
        if doc["total_patient_responsibility"] is not None and doc["total_patient_responsibility"] != p:
            w.append(f"EOB 'you owe' lines sum to {usd(p)} but total is {usd(doc['total_patient_responsibility'])}")
    return w


def pair_documents(docs: list[dict]) -> list[tuple[dict, dict | None]]:
    eobs = [d for d in docs if d["doc_type"] == "eob"]
    pairs = []
    for b in [d for d in docs if d["doc_type"] == "bill"]:
        m = next((e for e in eobs if e["service_date"] == b["service_date"] and _same_provider(e["provider"], b["provider"])), None)
        pairs.append((b, m))
    return pairs


def audit_pair(bill: dict, eob: dict | None) -> list[dict]:
    F: list[dict] = []
    if eob is None:
        return [dict(type="NO_EOB", severity="info", amount=0, title="No matching EOB",
                     detail=f"No EOB found for {bill['provider']} on {bill['service_date']}; cannot verify what you owe.", bill=bill, eob=None)]
    due = bill["amount_due_from_patient"]
    owe = eob["total_patient_responsibility"]
    if owe is None:
        owe = sum(l["patient_responsibility"] or 0 for l in eob["lines"])
    ev = dict(bill_doc=bill.get("_name"), eob_doc=eob.get("_name"))
    explained = 0

    # 1. duplicate lines: the bill repeats an identical (cpt, date, charge) line that the EOB processed fewer times
    bc = Counter((l["cpt"], l["service_date"], l["billed"]) for l in bill["lines"])
    ec = Counter((l["cpt"], l["service_date"]) for l in eob["lines"])
    for (cpt, dos, amt), n in bc.items():
        extra = n - max(ec.get((cpt, dos), 0), 1) if ec.get((cpt, dos)) else 0
        if extra > 0:
            amount = extra * (amt or 0)
            explained += amount
            F.append(dict(type="DUPLICATE_CHARGE", severity="high", amount=amount, title=f"Duplicate charge for CPT {cpt}",
                          detail=f"CPT {cpt} on {dos} appears {n}x on the bill at {usd(amt)} each, but the EOB processed it {ec[(cpt, dos)]}x. "
                                 f"The extra {extra} line(s) add {usd(amount)}.", cpt=cpt, **ev))

    # 2. billed CPTs the insurer never processed
    for l in bill["lines"]:
        if not any(e["cpt"] == l["cpt"] for e in eob["lines"]):
            explained += l["billed"] or 0
            F.append(dict(type="UNMATCHED_LINE", severity="high", amount=l["billed"] or 0, title=f"Charge for CPT {l['cpt']} not on the EOB",
                          detail=f"The bill charges {usd(l['billed'])} for CPT {l['cpt']} ({l['description']}), but the insurer's EOB has no such line.",
                          cpt=l["cpt"], **ev))

    # 3. bill vs EOB mismatch (whatever the explained items above do not account for)
    diff = (due or 0) - owe
    unexplained = diff - explained
    if due is not None and unexplained > 0:
        F.append(dict(type="BILL_EOB_MISMATCH", severity="high", amount=unexplained, title="Bill exceeds EOB patient responsibility",
                      detail=f"The bill asks for {usd(due)} but the EOB says your responsibility is {usd(owe)}: {usd(unexplained)} more than the insurer says you owe"
                             + (f" (after setting aside {usd(explained)} explained by the findings above)." if explained else "."),
                      bill_due=due, eob_owe=owe, **ev))
        # 4. balance billing: in-network provider charging chargemaster amounts instead of the allowed amount
        billed_total = eob["total_billed"] or sum(l["billed"] or 0 for l in eob["lines"])
        allowed_total = eob["total_allowed"] or sum(l["allowed"] or 0 for l in eob["lines"])
        plan = eob["total_plan_paid"] or sum(l["plan_paid"] or 0 for l in eob["lines"])
        if allowed_total < billed_total and abs(due - (billed_total - plan)) <= max(100, billed_total // 100):
            adj = billed_total - allowed_total
            F.append(dict(type="BALANCE_BILLING", severity="high", amount=adj, title="Contractual adjustment not applied (balance billing)",
                          detail=f"The bill equals the full billed charges ({usd(billed_total)}) minus insurance payments ({usd(plan)}). The EOB allowed only "
                                 f"{usd(allowed_total)}; an in-network provider must write off the {usd(adj)} difference and may bill you at most {usd(owe)}.",
                          billed_total=billed_total, allowed_total=allowed_total, **ev))
    return F


def deadline_card(eob: dict, as_of: date, window: int = 180) -> dict:
    notice = eob["document_date"]
    days = eob.get("appeal_window_days") or window
    due = notice + timedelta(days=days)
    left = (due - as_of).days
    return dict(notice_date=notice.isoformat(), window_days=days, deadline=due.isoformat(), days_left=left, as_of=as_of.isoformat(),
                status="expired" if left < 0 else ("urgent" if left <= 30 else "open"), claim=eob.get("claim_number"),
                provider=eob["provider"])


def deductible_status(docs: list[dict]) -> dict | None:
    eobs = sorted((d for d in docs if d["doc_type"] == "eob" and d.get("deductible_met_to_date") is not None), key=lambda d: d["document_date"])
    if not eobs:
        return None
    last = eobs[-1]
    total = last.get("deductible_amount") or 0
    return dict(deductible=total, met=last["deductible_met_to_date"], remaining=max(total - last["deductible_met_to_date"], 0),
                history=[dict(date=e["document_date"].isoformat(), applied=e.get("deductible_applied"), met=e["deductible_met_to_date"]) for e in eobs])


def run_audit(docs: list[dict], as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    findings, warnings = [], []
    for d in docs:
        warnings += [f"{d.get('_name', '?')}: {w}" for w in check_internal(d)]
    eob_by_bill = {}
    for bill, eob in pair_documents(docs):
        eob_by_bill[id(bill)] = eob
        for f in audit_pair(bill, eob):
            f["bill_provider"] = bill["provider"]
            findings.append(f)
    for i, f in enumerate(findings, 1):
        f["id"] = f"F{i}"
    cards = []
    for e in {id(f["eob"]): f["eob"] for f in (_with_eob(findings, docs))}.values():
        cards.append(deadline_card(e, as_of))
    return dict(findings=[_strip(f) for f in findings], warnings=warnings, deadlines=cards, deductible=deductible_status(docs), as_of=as_of.isoformat())


def _with_eob(findings, docs):
    names = {f.get("eob_doc") for f in findings if f["type"] != "NO_EOB"}
    return [{"eob": d} for d in docs if d["doc_type"] == "eob" and d.get("_name") in names]


def _strip(f):
    return {k: v for k, v in f.items() if k not in ("bill", "eob")}
