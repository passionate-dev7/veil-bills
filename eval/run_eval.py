"""Raw-vs-redacted accuracy eval. Same extraction prompt and model (Lightning), same deterministic audit.
  raw      : unredacted SYNTHETIC text sent straight to Token Factory (bypasses the gateway; only ever used with fictional data)
  redacted : the same text through the Veil gateway
Also measures privacy: how many ground-truth identifiers (known from the generator) appear in the bytes that left the machine.
Run:  python eval/run_eval.py     writes eval/results.json and eval/results.md
"""
from __future__ import annotations
import json, shutil, sys, time
from datetime import date
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from veil import synth
from veil.audit import run_audit
from veil.client import Gateway, ensure_gateway
from veil.config import Settings, ROOT, load_api_key
from veil.extract import extract, pdf_text

AS_OF = date(2026, 10, 29)
HOME = ROOT / ".veil" / "eval"
EVIL = "billing-audit@evil.example"


class Direct:
    """Calls Nebius directly with no gateway. Eval baseline only."""
    def __init__(self):
        self.http = httpx.Client(timeout=300, headers={"Authorization": "Bearer " + load_api_key()})
        self.usage = []

    def chat(self, model, messages, tag="", **kw):
        r = self.http.post("https://api.tokenfactory.nebius.com/v1/chat/completions", json={"model": model, "messages": messages, **kw})
        r.raise_for_status()
        j = r.json(); self.usage.append(j.get("usage") or {}); return j


def identifiers(case):
    p = case.person
    ids = {"name": p.name, "name_lastfirst": p.last_first, "dob": p.dob, "member_id": p.member_id, "ssn": p.ssn, "phone": p.phone,
           "email": p.email, "street": p.street}
    for i, e in enumerate(case.episodes):
        ids[f"claim_{i}"] = e.claim_no; ids[f"account_{i}"] = e.account_no
    return ids


def leaks(case, texts: list[str], sent: list[str]) -> dict:
    ids = identifiers(case)
    src, out = "\n".join(texts).lower(), "\n".join(sent).lower()
    present = {k: v for k, v in ids.items() if v.lower() in src}
    leaked = sorted(k for k, v in present.items() if v.lower() in out)
    p = case.person
    parts = [w for w in {p.name.split()[0], p.name.split()[-1]} if len(w) > 2]
    part_leaks = sorted(w for w in parts if w.lower() in out)
    return dict(identifiers_in_docs=len(present), identifiers_leaked=len(leaked), leaked=leaked, name_part_leaks=part_leaks)


def score(case, truth, docs):
    by = {d["_name"]: d for d in docs}
    ok = tot = 0
    for t in truth["docs"]:
        e, b = by[t["eob"]], by[t["bill"]]
        checks = [e["total_patient_responsibility"] == t["eob_patient_resp"], b["amount_due_from_patient"] == t["bill_due"], str(e["document_date"]) == t["eob_date"]]
        ok += sum(checks); tot += len(checks)
    res = run_audit(docs, AS_OF)
    got = {f["type"] for f in res["findings"] if f["type"] != "NO_EOB"}
    return dict(field_ok=ok, field_total=tot, findings=sorted(got), expected=sorted(case.expected), match=got == set(case.expected), warnings=res["warnings"])


def main():
    if HOME.exists():
        shutil.rmtree(HOME)
    st = Settings(home=HOME)
    url = ensure_gateway("http://127.0.0.1:8794", st)
    direct = Direct()
    cases = synth.eval_cases()
    rows, t0 = [], time.time()
    jc = synth.jane_case(); jc.id = "jane-corpus"
    allc = [(c, False) for c in cases] + [(jc, True)]
    for case, seeded in allc:
        d = HOME / "corpus" / case.id
        truth = synth.render_case(case, d)
        pdfs = sorted(d.glob("*.pdf"))
        texts = {p.name: pdf_text(p) for p in pdfs}
        row = dict(case=case.id, title=case.title, profile_seeded=seeded, docs=len(pdfs), modes={})
        for mode in ("raw", "redacted"):
            gw = Gateway(url, f"eval-{case.id}") if mode == "redacted" else direct
            docs, t1 = [], time.time()
            for n, tx in texts.items():
                dd, _ = extract(gw, tx, f"{case.id}/{n}"); dd["_name"] = n; docs.append(dd)
            m = score(case, truth, docs); m["seconds"] = round(time.time() - t1, 1)
            if mode == "redacted":
                led = gw.ledger(run=gw.run, full=True, limit=500)
                sent = [e.get("outbound_text", "") for e in led["entries"] if e["kind"] != "egress"]
                m["privacy"] = leaks(case, list(texts.values()), sent)
                m["gateway"] = led["totals"]
            else:
                m["privacy"] = leaks(case, list(texts.values()), list(texts.values()))
            if any(t["inject"] for t in truth["docs"]):
                m["injection_text_in_remarks"] = any(EVIL in (d.get("remarks") or "") for d in docs)
            row["modes"][mode] = m
        rows.append(row)
        r, g = row["modes"]["raw"], row["modes"]["redacted"]
        print(f"{case.id:<22} raw {'OK ' if r['match'] else 'FAIL'} {r['field_ok']}/{r['field_total']}   redacted {'OK ' if g['match'] else 'FAIL'} {g['field_ok']}/{g['field_total']}   "
              f"identifiers leaked {g['privacy']['identifiers_leaked']}/{g['privacy']['identifiers_in_docs']} (raw would leak {r['privacy']['identifiers_leaked']})", flush=True)
    summary = dict(
        cases=len(rows), raw_correct=sum(r["modes"]["raw"]["match"] for r in rows), redacted_correct=sum(r["modes"]["redacted"]["match"] for r in rows),
        raw_fields=f"{sum(r['modes']['raw']['field_ok'] for r in rows)}/{sum(r['modes']['raw']['field_total'] for r in rows)}",
        redacted_fields=f"{sum(r['modes']['redacted']['field_ok'] for r in rows)}/{sum(r['modes']['redacted']['field_total'] for r in rows)}",
        identifiers_in_docs=sum(r["modes"]["redacted"]["privacy"]["identifiers_in_docs"] for r in rows),
        identifiers_leaked_redacted=sum(r["modes"]["redacted"]["privacy"]["identifiers_leaked"] for r in rows),
        identifiers_leaked_raw=sum(r["modes"]["raw"]["privacy"]["identifiers_leaked"] for r in rows),
        wall_s=round(time.time() - t0, 1), generated=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    out = ROOT / "eval"
    (out / "results.json").write_text(json.dumps(dict(summary=summary, rows=rows), indent=2))
    md = ["# Eval: raw vs redacted (SYNTHETIC data)", "",
          "Same Lightning extraction prompt, same deterministic audit. `raw` = unredacted text sent directly to Token Factory; `redacted` = through the Veil gateway.",
          "Identifiers = ground-truth name, last-first name, DOB, member ID, SSN, phone, email, street, claim and account numbers that appear in the documents.", "",
          "| Case | Expected findings | Raw: findings | Raw: fields | Redacted: findings | Redacted: fields | Identifiers that reached Nebius (redacted / raw) | Name-part leaks (redacted) |",
          "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        a, b = r["modes"]["raw"], r["modes"]["redacted"]
        md.append(f"| {r['case']}{' (profile-seeded)' if r['profile_seeded'] else ''} | {', '.join(a['expected']) or 'none'} | {'OK' if a['match'] else 'FAIL: ' + ', '.join(a['findings'])} | {a['field_ok']}/{a['field_total']} | "
                  f"{'OK' if b['match'] else 'FAIL: ' + ', '.join(b['findings'])} | {b['field_ok']}/{b['field_total']} | {b['privacy']['identifiers_leaked']}/{b['privacy']['identifiers_in_docs']} / {a['privacy']['identifiers_leaked']}/{a['privacy']['identifiers_in_docs']} | {', '.join(b['privacy']['name_part_leaks']) or '-'} |")
    md += ["", f"**Summary:** findings correct raw {summary['raw_correct']}/{summary['cases']}, redacted {summary['redacted_correct']}/{summary['cases']}; "
           f"money/date fields raw {summary['raw_fields']}, redacted {summary['redacted_fields']}; identifiers reaching Nebius: {summary['identifiers_leaked_redacted']}/{summary['identifiers_in_docs']} redacted vs {summary['identifiers_leaked_raw']}/{summary['identifiers_in_docs']} raw. Wall {summary['wall_s']}s.", ""]
    (out / "results.md").write_text("\n".join(md))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
