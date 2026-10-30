"""Redactor holes found by the judge scorecard, closed and pinned; plus JS/Python parity on the same cases (web/pseudo.js)."""
import json, shutil, subprocess
from pathlib import Path
import pytest
from veil.pseudo import Pseudonymizer
from veil.vault import Vault
from veil.config import ROOT

CASES = json.loads((ROOT / "tests" / "parity_cases.json").read_text())


def _py(case, tmp_path):
    v = Vault(tmp_path / "v.sqlite"); v.load_profile(ROOT / "demo" / "profile.json")
    ps = Pseudonymizer(v)
    from collections import Counter
    c = Counter()
    body = {"model": "nvidia/Nemotron-3_5-Lightning", "messages": [{"role": "user", "content": case["text"]}]}
    red = ps.redact_payload(body, c)
    out = json.dumps(red, separators=(",", ":"), ensure_ascii=False).encode()
    leaks = [list(x) for x in ps.canary(out)]
    return red["messages"][0]["content"], dict(c), leaks, out.decode()


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_case(case, tmp_path):
    text, counts, leaks, _ = _py(case, tmp_path)
    for g in case.get("gone", []):
        assert g not in text, f"{g!r} survived: {text!r}"
    if "gone" in case:
        assert not leaks, f"canary tripped after redaction: {leaks}"
    for k in case.get("keep", []):
        assert k in text, f"{k!r} was over-redacted: {text!r}"
    if "canary" in case:
        assert sorted({k for k, _ in leaks}) == sorted(case["canary"]), leaks


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_js_matches_python(tmp_path):
    r = subprocess.run(["node", str(ROOT / "tests" / "js_parity.mjs")], capture_output=True, text=True, check=True)
    js = {o["name"]: o for o in json.loads(r.stdout)}
    for case in CASES:
        d = tmp_path / case["name"]; d.mkdir()
        text, counts, leaks, outbound = _py(case, d)
        o = js[case["name"]]
        assert o["redacted"] == text, case["name"]
        assert o["counts"] == counts, case["name"]
        assert o["leaks"] == leaks, case["name"]
        assert o["status"] == (422 if leaks else 200), case["name"]


def test_pseudo_js_is_current():
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    import gen_js
    assert (ROOT / "web" / "pseudo.js").read_text() == gen_js.build(), "run: .venv/bin/python tools/gen_js.py"
