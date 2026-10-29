"""End-to-end pipeline: PDFs -> (gateway) Lightning extraction -> deterministic audit -> (gateway) Ultra appeal -> approval queue."""
from __future__ import annotations
import json, time, uuid
from datetime import date
from pathlib import Path
from .audit import run_audit, usd
from .appeal import run_appeal, dollar_set, letter_check
from .client import Gateway
from .config import Settings
from .egress import Policy, Outbox
from .extract import extract, pdf_text
from .vault import Vault


def _jsonable(o):
    if isinstance(o, date): return o.isoformat()
    raise TypeError(type(o))


def run_pipeline(gw: Gateway, settings: Settings, corpus: Path, as_of: date, appeal_for: str | None = None, say=print, no_appeal=False) -> dict:
    t0 = time.time()
    texts, docs, extra_calls = {}, [], {}
    for p in sorted(corpus.glob("*.pdf")):
        texts[p.name] = pdf_text(p)
        say(f"  extract  {p.name}  (Lightning via gateway)")
        d, resp = extract(gw, texts[p.name], p.name)
        d["_name"] = p.name
        docs.append(d)
    by_name = {d["_name"]: d for d in docs}
    audit = run_audit(docs, as_of)
    say(f"  audit    {len(audit['findings'])} findings (deterministic, integer cents)")

    appeal = None
    if audit["findings"] and not no_appeal:
        bills = {}
        for f in audit["findings"]:
            if f.get("bill_doc"): bills.setdefault(f["bill_doc"], 0); bills[f["bill_doc"]] += f["amount"]
        live = {b: a for b, a in bills.items() if not _expired(audit, by_name, b)}
        target = appeal_for or max(live or bills, key=(live or bills).get)
        say(f"  appeal   Ultra drafting for {target}")
        ctx = dict(policy=Policy(settings), outbox=Outbox(settings), run=gw.run, tag="appeal:" + target)
        appeal = run_appeal(gw, None, target, audit, by_name, texts, ctx)
        body = (appeal["draft"] or {}).get("body") or appeal["final_text"]
        extra = {usd(v) for d in docs for v in [d.get(k) for k in ("total_billed", "total_allowed", "total_patient_responsibility", "total_plan_paid",
                 "amount_due_from_patient", "deductible_amount", "deductible_met_to_date")] + [l.get(k) for l in d["lines"] for k in ("billed", "allowed", "patient_responsibility", "deductible")] if v is not None}
        appeal["letter_check"] = letter_check(body, dollar_set(audit), extra)
        if appeal["draft"]:
            d = appeal["draft"]; d["letter_check"] = appeal["letter_check"]
            (settings.outbox / f"{d['id']}.json").write_text(json.dumps(d, indent=2))
    wall = round(time.time() - t0, 1)
    return dict(run=gw.run, as_of=as_of.isoformat(), wall_s=wall, texts=texts, docs=docs, audit=audit, appeal=appeal)


def _expired(audit, by_name, bill):
    f = next((f for f in audit["findings"] if f.get("bill_doc") == bill), None)
    c = f and next((c for c in audit["deadlines"] if c["claim"] == by_name.get(f.get("eob_doc"), {}).get("claim_number")), None)
    return bool(c and c["status"] == "expired")


def build_export(gw: Gateway, settings: Settings, res: dict) -> dict:
    """Cached, replayable record of a real run for the judge page. Contains the real synthetic text, what Nebius received, and the receipts."""
    led = gw.ledger(run=gw.run, full=True, limit=500)
    entries = list(reversed(led["entries"]))
    vault = Vault(settings.vault_db)
    sens = [dict(value=v, token=t, kind=k) for v, t, k in vault.surfaces()]
    vault.close()
    for e in entries:  # the cache holds the gateway's view; upstream response bodies are not needed beyond text + receipt
        e.pop("meta", None) if e.get("kind") != "egress" else None
    docs_out = []
    for name, text in res["texts"].items():
        call = next((e for e in entries if e.get("kind") != "egress" and e.get("tag") == name), None)
        docs_out.append(dict(name=name, text=text, call=call))
    appeal = res["appeal"]
    return dict(
        synthetic=True, disclaimer="All data is SYNTHETIC. Not medical or legal advice.", run=res["run"], as_of=res["as_of"],
        generated=time.strftime("%Y-%m-%dT%H:%M:%S%z"), wall_s=res["wall_s"], totals=led["totals"], sensitive=sens,
        documents=docs_out, findings=res["audit"]["findings"], deadlines=res["audit"]["deadlines"], deductible=res["audit"]["deductible"],
        warnings=res["audit"]["warnings"],
        appeal=appeal and dict(bill_doc=appeal["bill_doc"], eob_doc=appeal["eob_doc"], draft=appeal["draft"], letter_check=appeal["letter_check"],
                               events=appeal["events"], turns=appeal["turns"], calls=[e for e in entries if str(e.get("tag", "")).startswith("appeal:") and e.get("kind") != "egress"]),
        egress=[e for e in entries if e.get("kind") == "egress"],
        receipts=[dict(ledger_id=e["id"], tag=e.get("tag"), model=e.get("model"), upstream_model=e.get("upstream_model"), upstream_id=e.get("upstream_id"),
                       usage=e.get("usage"), latency_ms=e.get("latency_ms"), sha256=e.get("outbound_sha256"), bytes=e.get("outbound_bytes"),
                       redacted=e.get("redacted_total"), status=e.get("status")) for e in entries if e.get("kind") != "egress"],
    )
