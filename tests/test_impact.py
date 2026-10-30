import json
from veil.impact import impact_total, scrub_paths, enrich_record, receipt_cost_micro
from veil.config import ROOT


def test_impact_counts_largest_overlap_once_per_bill():
    f = [dict(bill_doc="a.pdf", amount=3500, type="X", id="1"), dict(bill_doc="b.pdf", amount=242800, type="Y", id="2"), dict(bill_doc="b.pdf", amount=242800, type="Z", id="3")]
    t = impact_total(f)
    assert t["total_cents"] == 3500 + 242800


def test_cached_run_total_is_2463():
    rec = json.loads((ROOT / "web" / "run.json").read_text())
    assert rec["impact"]["total_cents"] == 246300


def test_scrub_paths_removes_home_dirs():
    o = scrub_paths({"a": "/Users/someone/Desktop/x/y.eml", "b": ["/home/bob/z"], "c": str(ROOT) + "/web"})
    s = json.dumps(o)
    assert "/Users/" not in s and "/home/bob" not in s and str(ROOT) not in s


def test_static_bundle_has_no_local_paths():
    for n in ("run.json", "run.js", "index.html", "pseudo.js", "veil.css"):
        p = ROOT / "web" / n
        if p.exists():
            t = p.read_text()
            assert "/Users/" not in t and "/home/" not in t, n


def test_canary_demo_blocks_without_sending():
    d = json.loads((ROOT / "eval" / "canary_demo.json").read_text())
    ok, *bad = d["rows"]
    assert ok["http"] == 200 and ok["sent_upstream"]
    assert bad and all(b["http"] == 422 and not b["sent_upstream"] and b["ledger_status"] == "blocked" for b in bad)
