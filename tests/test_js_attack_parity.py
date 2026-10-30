"""The browser build (web/pseudo.js, the "Try to break it" box) must answer every attack-suite case the way the Python gateway does.

Each redaction and canary case of eval/attack_corpus.py goes through Pseudonymizer + canary in Python and through web/pseudo.js under Node. Outcome per case:
  422        the canary fails closed, nothing would be sent
  redacted   HTTP 200 and the independent oracle (eval/attack_suite.py) finds no vault value in the outbound bytes
  LEAK       HTTP 200 and a vault value is in the outbound bytes
  kept       control case: HTTP 200 and every `keep` string survives
Both sides must give the same outcome, and neither may LEAK."""
import json, shutil, subprocess, sys
from collections import Counter
from pathlib import Path
import pytest
from veil.config import ROOT
from veil.pseudo import Pseudonymizer
from veil.vault import Vault

sys.path.insert(0, str(ROOT / "eval"))
import attack_corpus as corpus  # noqa: E402
import attack_suite as suite  # noqa: E402

# Cases that do not go through the redactor and canary at all.
EXCLUDED = {
    "position_and_size/model_field_is_secret": "refused by the gateway's HTTP model allowlist (400) before redaction; web/pseudo.js has no model allowlist",
    "position_and_size/model_suffix_is_secret": "refused by the gateway's HTTP model allowlist (400) before redaction; web/pseudo.js has no model allowlist",
}
HTTP_KINDS = {"egress"}   # tool endpoint behind the trusted-contacts allowlist: an address check, not text redaction

ALL = corpus.build()
CASES = [c for c in ALL if c.kind in ("leak", "control") and c.id not in EXCLUDED]
needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node not installed")


def _python(case, tmp_path):
    v = Vault(tmp_path / "v.sqlite")
    if case.mode == "profile":
        v.load_profile(ROOT / "demo" / "profile.json")
    ps = Pseudonymizer(v)
    red = ps.redact_payload(case.body, Counter())
    outbound = json.dumps(red, ensure_ascii=False, separators=(",", ":"))
    leaks = ps.canary(outbound.encode("utf-8"))
    v.close()
    return (422 if leaks else 200), outbound


def _outcome(case, status, outbound):
    if status == 422:
        return "blocked_422"
    if case.kind == "control":
        return "kept" if all(k in outbound for k in case.keep) else "OVER_REDACTED"
    return "LEAK" if suite.present(case.secrets, outbound.encode("utf-8")) else "redacted"


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    d = tmp_path_factory.mktemp("jsparity")
    f = d / "cases.json"
    f.write_text(json.dumps([{"id": c.id, "mode": c.mode, "body": c.body} for c in CASES]))
    r = subprocess.run(["node", str(ROOT / "tests" / "js_attack_parity.mjs"), str(f)], capture_output=True, text=True, check=True)
    js = {o["id"]: o for o in json.loads(r.stdout)}
    rows = []
    for i, c in enumerate(CASES):
        (d / str(i)).mkdir()
        ps, pout = _python(c, d / str(i))
        o = js[c.id]
        rows.append(dict(id=c.id, category=c.category, py=_outcome(c, ps, pout), js=_outcome(c, o["status"], o["outbound"]),
                         same_status=ps == o["status"], same_bytes=pout == o["outbound"]))
    return rows


def test_exclusions_are_exactly_the_cases_that_skip_redaction():
    assert set(EXCLUDED) <= {c.id for c in ALL}
    assert {c.id for c in ALL} - {c.id for c in CASES} - set(EXCLUDED) == {c.id for c in ALL if c.kind in HTTP_KINDS}
    assert all(c.id.startswith("egress/") for c in ALL if c.kind in HTTP_KINDS)


@needs_node
def test_every_category_is_covered_and_both_outcomes_are_exercised(results):
    by = Counter(r["category"] for r in results)
    assert len(results) == len(CASES) > 330
    assert {"spacing", "zero_width", "lookalike", "json_nesting", "encoding", "prose_names", "dates", "split_ids", "position_and_size", "controls"} <= set(by)
    assert Counter(r["py"] for r in results)["blocked_422"] > 20 and Counter(r["py"] for r in results)["redacted"] > 200 and Counter(r["py"] for r in results)["kept"] >= 10


@needs_node
def test_js_gives_the_python_outcome_on_every_attack_suite_case(results):
    bad = [(r["id"], r["py"], r["js"]) for r in results if r["py"] != r["js"]]
    assert not bad, f"{len(bad)} of {len(results)} differ (id, python, js): {bad}"


@needs_node
def test_neither_side_leaks_and_controls_are_not_over_redacted(results):
    assert not [r["id"] for r in results if "LEAK" in (r["py"], r["js"]) or "OVER_REDACTED" in (r["py"], r["js"])]


@needs_node
def test_parity_report(results, capsys):
    rows = []
    for cat in sorted({r["category"] for r in results}):
        rs = [r for r in results if r["category"] == cat]
        rows.append(f"{cat:<18} {sum(r['py'] == r['js'] for r in rs):>3}/{len(rs):<3} same outcome  {sum(r['same_status'] for r in rs):>3} same status  {sum(r['same_bytes'] for r in rs):>3} same outbound bytes")
    rows.append(f"{'all':<18} {sum(r['py'] == r['js'] for r in results):>3}/{len(results):<3} same outcome  {sum(r['same_status'] for r in results):>3} same status  {sum(r['same_bytes'] for r in results):>3} same outbound bytes")
    with capsys.disabled():
        print("\n" + "\n".join(rows))


def test_python_side_of_this_test_matches_the_committed_gateway_run(results):
    """The Python half here calls Pseudonymizer directly; it must agree with the full-gateway run recorded in eval/attack_suite_results.json."""
    rep = {c["id"]: c["outcome"] for c in json.loads((ROOT / "eval" / "attack_suite_results.json").read_text())["cases"]}
    assert len(rep) > 370
    assert all(rep[r["id"]] == r["py"] for r in results), [(r["id"], rep[r["id"]], r["py"]) for r in results if rep[r["id"]] != r["py"]]
