"""Offline leak and attack suite (eval/attack_suite.py) as a test: 300+ cases through the real gateway, no network, no model.
The 36 cases the first run found leaking (eval/attack_suite_before_fix.json) are pinned here: they were red before the fix and are green now."""
import json, sys
from pathlib import Path
import pytest
from veil.config import ROOT
from veil import fold, detectors

sys.path.insert(0, str(ROOT / "eval"))
import attack_corpus as corpus  # noqa: E402
import attack_suite as suite  # noqa: E402

CASES = corpus.build()
BEFORE = json.loads((ROOT / "eval" / "attack_suite_before_fix.json").read_text())


@pytest.fixture(scope="module")
def full_rows():
    return suite.run_all("full", CASES)


def test_corpus_is_big_and_unique():
    assert len({c.id for c in CASES}) == len(CASES)
    attack = [c for c in CASES if c.kind != "control"]
    assert len(attack) >= 200
    assert {"spacing", "zero_width", "lookalike", "json_nesting", "tool_surfaces", "encoding", "prose_names", "dates", "split_ids", "injection", "egress"} <= {c.category for c in CASES}


def test_every_case_passes_on_current_code(full_rows):
    assert len(full_rows) == len(CASES) > 300
    bad = [(r["id"], r["outcome"], r.get("secrets_leaked")) for r in full_rows if not r["passed"]]
    assert not bad, bad
    assert sum(r["outcome"] == "LEAK" for r in full_rows) == 0


def test_every_leak_case_really_contains_a_secret(full_rows):
    """A case whose request holds nothing the oracle can see would pass for free."""
    empty = [r["id"] for r in full_rows if r["category"] not in ("controls", "egress") and not r["secrets_in_raw_request"]]
    assert not empty, empty


def test_oracle_can_fail_with_the_guard_off():
    """Redactor and canary disabled: every leak case must put its secret on the wire, except the two refused by the model allowlist."""
    leak_cases = [c for c in CASES if c.kind == "leak"]
    rows = suite.run_all("no_guard", leak_cases)
    assert len(rows) > 300
    not_leaking = sorted(r["id"] for r in rows if r["outcome"] != "LEAK")
    assert not_leaking == ["position_and_size/model_field_is_secret", "position_and_size/model_suffix_is_secret"], not_leaking


def test_controls_survive_and_egress_is_decided_by_the_allowlist(full_rows):
    controls = [r for r in full_rows if r["category"] == "controls"]
    egress = [r for r in full_rows if r["category"] == "egress"]
    assert len(controls) >= 10 and all(r["outcome"] == "kept" for r in controls)
    assert sum(r["outcome"] == "queued_for_approval" for r in egress) == 4
    assert sum(r["outcome"] == "refused_403" for r in egress) >= 25


def test_cases_found_leaking_before_the_fix_are_pinned(full_rows):
    by = {r["id"]: r for r in full_rows}
    assert len(BEFORE["failures"]) == BEFORE["failed"] == 36
    for f in BEFORE["failures"]:
        assert by[f["id"]]["passed"], f["id"]


def test_committed_results_match_the_corpus():
    rep = json.loads((ROOT / "eval" / "attack_suite_results.json").read_text())
    assert rep["total_cases"] == len(CASES) and rep["failed"] == 0 and rep["outbound_leaks"] == 0
    assert rep["guard_off_proof"]["no_guard"]["leaked"] == rep["leak_cases"] - 2


@pytest.mark.parametrize("raw", ["Ja\u200ene D\u200eoe", "Patient J\u00e1n\u00eb Do\u1eb9", "J\u1d00n\u1d07 D\u1d0f\u1d07"])  # left-to-right mark, accents, small capitals
def test_fold_reduces_obfuscated_names(raw):
    assert "jane" in fold.fold(raw).lower() and "doe" in fold.fold(raw).lower()


def test_fold_leaves_other_scripts_alone():
    hindi = "हिन्दी"
    assert fold.fold(hindi) == hindi


def test_unwrap_reads_transport_encodings():
    import base64
    assert any("987-65-4321" in x for x in fold.unwrap(base64.b64encode(b"SSN 987-65-4321").decode()))
    assert any("Jane Doe" in x for x in fold.unwrap("&#74;&#97;&#110;&#101; &#68;&#111;&#101;"))
    assert any("987-65-4321" in x for x in fold.unwrap("q=%39%38%37%2D%36%35%2D%34%33%32%31"))
    assert fold.unwrap("Mercy Valley Hospital billed $35.00 for CPT 36415") == []


@pytest.mark.parametrize("text", ["DOB: 12.04.1985", "born on 4/12/85", "she was born Apr 12 '85", "twelfth of April, nineteen eighty-five"])
def test_birth_date_shapes_are_detected(text):
    assert any(k == "DOB" for k, _ in detectors.find(text))


def test_service_dates_are_not_birth_dates():
    assert not list(detectors.find("Date of service 03/14/2026 and 12.04.2026, statement 2026-05-20, claim 4/12/26"))
