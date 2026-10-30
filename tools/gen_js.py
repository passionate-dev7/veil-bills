"""Generate web/pseudo.js (browser pseudonymizer + canary) from the Python rules. Run: .venv/bin/python tools/gen_js.py  (tests fail if it is stale)."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from veil import detectors, fold


def build() -> str:
    t = (ROOT / "tools" / "pseudo.template.js").read_text()
    prof = json.loads((ROOT / "demo" / "profile.json").read_text())["entities"]
    j = lambda o: json.dumps(o, ensure_ascii=True)
    return (t.replace("/*DETECTORS*/[]", j(detectors.spec())).replace("/*CONFUSABLES*/{}", j(fold.CONFUSABLES)).replace("/*PROFILE*/[]", j(prof)))


if __name__ == "__main__":
    (ROOT / "web" / "pseudo.js").write_text(build())
    print("wrote web/pseudo.js")
