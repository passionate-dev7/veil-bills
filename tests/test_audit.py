from datetime import date
from veil.extract import normalize
from veil.audit import run_audit


def line(cpt, billed, allowed=None, owe=None, d="2026-05-06"):
    return dict(cpt=cpt, description=cpt, service_date=d, billed=billed, allowed=allowed, deductible=owe, plan_paid=0 if allowed is not None else None, patient_responsibility=owe)


def eob(lines, owe, notice="2026-05-20", d="2026-05-06", **k):
    return normalize(dict(doc_type="eob", provider="Mercy Valley Hospital", document_date=notice, service_date=d, claim_number="C1", lines=lines,
                          total_billed=sum(l["billed"] for l in lines), total_allowed=sum(l["allowed"] for l in lines), total_patient_responsibility=owe, **k))


def bill(lines, due, d="2026-05-06", provider="Mercy Valley Hospital"):
    return normalize(dict(doc_type="bill", provider=provider, document_date="2026-06-03", service_date=d, lines=lines, total_billed=sum(l["billed"] for l in lines),
                          amount_due_from_patient=due, insurance_payments=0))


E = eob([line("99283", 1640, 250, 250), line("73610", 480, 62, 62), line("29515", 720, 100, 100)], 412)


def types(docs, as_of=date(2026, 10, 29)):
    return {f["type"] for f in run_audit(docs, as_of)["findings"]}


def test_balance_billing_main_case_is_exact_cents():
    b = bill([line("99283", 1640), line("73610", 480), line("29515", 720)], 2840)
    r = run_audit([E, b], date(2026, 10, 29))
    assert types([E, b]) == {"BILL_EOB_MISMATCH", "BALANCE_BILLING"}
    assert {f["amount"] for f in r["findings"]} == {242800}
    d = r["deadlines"][0]
    assert d["deadline"] == "2026-11-16" and d["days_left"] == 18 and d["status"] == "urgent"


def test_clean_bill_has_no_findings():
    b = bill([line("99283", 1640), line("73610", 480), line("29515", 720)], 412)
    assert types([E, b]) == set()


def test_duplicate_charge_explains_the_difference_without_extra_mismatch():
    e = eob([line("80053", 40, 25, 25), line("36415", 35, 25, 25)], 50)
    b = bill([line("80053", 40), line("36415", 35), line("36415", 35)], 85)
    r = run_audit([e, b])
    assert [f["type"] for f in r["findings"]] == ["DUPLICATE_CHARGE"]
    assert r["findings"][0]["amount"] == 3500


def test_unprocessed_line_flagged():
    b = bill([line("99283", 1640), line("73610", 480), line("29515", 720), line("J1100", 300)], 712)
    assert "UNMATCHED_LINE" in types([E, b])
