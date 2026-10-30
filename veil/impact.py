"""Judge-page enrichments computed in code from the audit output and the eval record. Nothing here calls a model.

impact_total   dollars found on the sample, from deterministic findings (integer cents)
parity         raw-vs-redacted eval table (eval/results.json), shown next to the ledger
hermes_runs    transcripts of model-driven Hermes runs inside the OpenShell sandbox (scripts/sandbox_hermes_run.sh), if any exist
enrich_record  adds all of the above to a run record; used by build_record and by `veil export-run`
"""
from __future__ import annotations
import json, os, re
from pathlib import Path
from .config import ROOT


# USD per million tokens, copied from Nebius's public Token Factory model catalog (https://tokenfactory.nebius.com/model-catalog.md, read 2026-10-30).
PRICES = {
    "nvidia/Nemotron-3-Ultra-550b-a55b": dict(inp=1.00, cached=0.12, out=3.00),
    "nvidia/Nemotron-3_5-Lightning": dict(inp=0.06, cached=0.03, out=0.24),
}
PRICE_SOURCE = "https://tokenfactory.nebius.com/model-catalog.md"


def receipt_cost_micro(r: dict) -> int | None:
    """List-price cost of one call in millionths of a dollar (integer). tokens x $/1M = micro-dollars exactly. None if the model or usage is unpriced."""
    pr, u = PRICES.get(r.get("upstream_model") or r.get("model") or ""), r.get("usage") or {}
    if not pr or u.get("prompt_tokens") is None:
        return None
    cached = u.get("prompt_cache_hit_tokens") or ((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0
    fresh = max(0, u["prompt_tokens"] - cached)
    return round(fresh * pr["inp"] + cached * pr["cached"] + (u.get("completion_tokens") or 0) * pr["out"])


def cost_summary(receipts: list[dict]) -> dict:
    costs = [receipt_cost_micro(r) for r in receipts]
    for r, c in zip(receipts, costs):
        r["cost_micro_usd"] = c
    priced = [c for c in costs if c is not None]
    return dict(total_micro_usd=sum(priced), priced_calls=len(priced), calls=len(receipts), source=PRICE_SOURCE, prices_per_million_tokens=PRICES,
                basis="List price from the public Nebius catalog x token counts Nebius returned. An estimate, not an invoice; search (Tavily) calls are not priced.")


def impact_total(findings: list[dict]) -> dict:
    """Open overbilling in integer cents. Findings that describe the same bill's overcharge (a bill-vs-EOB mismatch and balance billing
    are the same dollars seen two ways) are counted once per bill document, taking the largest. This is a conservative lower bound."""
    open_f = [f for f in findings if f.get("status", "open") != "no_longer_detected"]
    by: dict[str, list[dict]] = {}
    for f in open_f:
        by.setdefault(f.get("bill_doc") or f.get("id") or "?", []).append(f)
    rows = []
    for doc, fs in by.items():
        top = max(fs, key=lambda f: f["amount"])
        rows.append(dict(bill_doc=doc, provider=top.get("bill_provider"), cents=int(top["amount"]), counted=top.get("id"), types=sorted({f["type"] for f in fs}),
                         finding_ids=[f.get("id") for f in fs]))
    return dict(total_cents=sum(r["cents"] for r in rows), bills=rows, findings=len(open_f),
                method="Per bill, overlapping findings are counted once (the largest). Integer-cent arithmetic in Python; no model does any of it.")


def parity(eval_path: Path | None = None) -> dict | None:
    p = eval_path or ROOT / "eval" / "results.json"
    if not p.exists():
        return None
    e = json.loads(p.read_text())
    rows = []
    for r in e["rows"]:
        raw, red = r["modes"]["raw"], r["modes"]["redacted"]
        rows.append(dict(case=r["case"], title=r.get("title"), expected=raw["expected"], raw_match=raw["match"], redacted_match=red["match"],
                         raw_fields=f"{raw['field_ok']}/{raw['field_total']}", redacted_fields=f"{red['field_ok']}/{red['field_total']}",
                         ids_total=red["privacy"]["identifiers_in_docs"], ids_raw=raw["privacy"]["identifiers_leaked"], ids_redacted=red["privacy"]["identifiers_leaked"],
                         gateway_redacted=(red.get("gateway") or {}).get("redacted")))
    return dict(summary=e["summary"], rows=rows, source="eval/results.json")


def _scrub(t: str) -> str:
    for k in ("NEBIUS_API_KEY", "TAVILY_API_KEY"):
        v = os.environ.get(k)
        if v and len(v) > 8:
            t = t.replace(v, f"[{k}]")
    return re.sub(r"(Bearer\s+)[A-Za-z0-9._\-]{16,}", r"\1[redacted]", t)


def hermes_runs(root: Path) -> list[dict]:
    """Latest transcript per kind written by scripts/sandbox_hermes_run.sh to <root>/hermes_<kind>_<epoch>.txt."""
    out = {}
    for f in sorted(root.glob("hermes_*_*.txt")):
        m = re.match(r"hermes_(audit|injection)_(\d+)\.txt$", f.name)
        if m:
            out[m.group(1)] = dict(kind=m.group(1), started=int(m.group(2)), file=f.name, text=_scrub(f.read_text(errors="ignore"))[:6000])
    return list(out.values())


_HOME_RX = re.compile(r"/(?:Users|home)/[^/\"\\\s]+")


def scrub_paths(obj):
    """Strip machine-specific absolute paths from a record before it goes into the public static bundle."""
    s = json.dumps(obj, default=str)
    root = str(Path(__file__).resolve().parent.parent)
    s = s.replace(root, "<repo>")
    s = _HOME_RX.sub("~", s)
    return json.loads(s)


def enrich_record(rec: dict, hermes_dir: Path | None = None, cached_note: str | None = None) -> dict:
    rec["impact"] = impact_total(rec.get("findings") or [])
    rec["parity"] = parity()
    rec["cost"] = cost_summary(rec.get("receipts") or [])
    cd = ROOT / "eval" / "canary_demo.json"
    if cd.exists():
        rec["canary_demo"] = json.loads(cd.read_text())
    td = ROOT / "eval" / "toolargs_demo.json"
    if td.exists():
        rec["toolarg_demo"] = json.loads(td.read_text())
    rec["hermes_runs"] = hermes_runs(hermes_dir) if hermes_dir else rec.get("hermes_runs", [])
    rec.setdefault("receipts_source", dict(
        cached=True, note=cached_note or "Receipts come from the earlier real Token Factory run recorded in the gateway ledger (response id, served model and usage are Nebius's own fields). They are not re-run when this page loads."))
    return scrub_paths(rec)
