"""scripts/sandbox_hermes_run.sh dry run: same ingestion + export path as the live run, no credit, no sandbox, nothing real touched."""
import hashlib, json, os, re, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sandbox_hermes_run.sh"
WEB = [ROOT / "web" / "run.json", ROOT / "web" / "run.js"]


def _digest():
    return [hashlib.sha256(p.read_bytes()).hexdigest() for p in WEB]


def test_dry_run_ingests_deny_log_and_exports_without_touching_the_bundle():
    before = _digest()
    py = ROOT / ".venv" / "bin" / "python"
    env = {**os.environ, "DRY_RUN": "1", **({"PY": str(py)} if py.exists() else {"PY": "python"})}
    for k in ("NEBIUS_API_KEY", "TAVILY_API_KEY"):
        env.pop(k, None)
    r = subprocess.run(["sh", str(SCRIPT), "injection"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert "9 DENIED line(s) in the sandbox log; 9 new ledger row(s)" in r.stdout
    assert "sandbox rows model-driven: 0" in r.stdout          # a replayed operator probe must never be labelled model-driven
    assert "[dry run] ok" in r.stdout
    out = Path(re.search(r"Throwaway output: (\S+)", r.stdout).group(1))
    rec = json.loads((out / "run.json").read_text())
    rows = [e for e in rec["egress"] if (e.get("meta") or {}).get("source") == "openshell"]
    assert len(rows) == 9 and all(e["status"] == "blocked" and not e["meta"]["model_driven"] for e in rows)
    assert "DRY RUN" in rows[0]["meta"]["trigger"]
    assert _digest() == before                                  # the real web bundle is untouched


def test_unknown_kind_is_rejected():
    r = subprocess.run(["sh", str(SCRIPT), "nope"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 2 and "usage:" in r.stdout
