"""lookup_appeal_rules(insurer_type, topic): public-web research through the gateway (Tavily).

The query is assembled ONLY from two closed vocabularies below, so the model cannot put anything about the patient into it.
It then still goes through the gateway's pseudonymizer and leak canary like every other outbound byte, and the exact body is ledgered.
"""
from __future__ import annotations

INSURER_TYPES = {
    "aca_marketplace": "ACA marketplace health plan",
    "employer_erisa": "employer-sponsored ERISA group health plan",
    "medicare": "Original Medicare",
    "medicaid": "Medicaid managed care",
    "unknown": "US health insurance",
}
TOPICS = {
    "internal_appeal_deadline": "internal appeal deadline 180 days",
    "balance_billing": "balance billing in-network provider allowed amount contractual adjustment",
    "no_surprises_act": "No Surprises Act balance billing protections",
    "external_review": "external review after internal appeal denial",
    "collections_hold": "medical bill collections hold during appeal",
    "billing_error_dispute": "how to dispute a medical billing error with the insurer",
}
SPEC = {"type": "function", "function": {
    "name": "lookup_appeal_rules",
    "description": "Look up general public rules for health-insurance appeals via web search. Takes only two enum values, never patient details. Returns sources.",
    "parameters": {"type": "object", "properties": {
        "insurer_type": {"type": "string", "enum": list(INSURER_TYPES)},
        "topic": {"type": "string", "enum": list(TOPICS)}}, "required": ["insurer_type", "topic"]}}}


def build_query(insurer_type: str, topic: str) -> str:
    if insurer_type not in INSURER_TYPES or topic not in TOPICS:
        raise ValueError(f"insurer_type must be one of {list(INSURER_TYPES)}; topic one of {list(TOPICS)}")
    return f"{INSURER_TYPES[insurer_type]} {TOPICS[topic]}"


def lookup(gw, insurer_type: str, topic: str, tag: str = "") -> dict:
    """Runs the search through the gateway. Returns {query, ledger_id, sha256, answer, sources[], text_for_model}."""
    q = build_query(insurer_type, topic)
    r = gw.search(q, tag=tag)
    srcs = [{"title": x.get("title"), "url": x.get("url"), "score": x.get("score"), "snippet": (x.get("content") or "")[:280]} for x in r.get("results", [])][:5]
    text = (r.get("answer") or "") + "\n" + "\n".join(f"- {s['title']} ({s['url']}): {s['snippet']}" for s in srcs[:3])
    return dict(query=q, insurer_type=insurer_type, topic=topic, ledger_id=r.get("veil", {}).get("ledger_id"), sha256=r.get("veil", {}).get("sha256"),
                request_id=r.get("request_id"), response_time=r.get("response_time"), answer=r.get("answer"), sources=srcs, text_for_model=text.strip()[:1800])
