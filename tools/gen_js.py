"""Generate web/pseudo.js (browser pseudonymizer + canary) from the Python rules. Run: .venv/bin/python tools/gen_js.py  (tests fail if it is stale)."""
import html.entities, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from veil import detectors, fold, pseudo


def build() -> str:
    t = (ROOT / "tools" / "pseudo.template.js").read_text()
    prof = json.loads((ROOT / "demo" / "profile.json").read_text())["entities"]
    j = lambda o: json.dumps(o, ensure_ascii=True)
    confusables = {**fold.CONFUSABLES, **fold.EXTRA_CONFUSABLES}
    # only the HTML entities that decode to something fold reduces to ASCII (punctuation, accented letters): the others cannot hide an identifier
    entities = {k: v for k, v in html.entities.html5.items() if fold.fold(v) and fold.fold(v).isascii()}
    return (t.replace("/*DETECTORS*/[]", j(detectors.spec())).replace("/*CONFUSABLES*/{}", j(confusables)).replace("/*PROFILE*/[]", j(prof))
            .replace("/*NOTNAME*/[]", j(sorted(pseudo._NOT_NAME_PARTS))).replace("/*ENTITIES*/{}", j(entities)).replace('/*SPLIT*/""', j(pseudo.SPLIT_RX.pattern)))


if __name__ == "__main__":
    (ROOT / "web" / "pseudo.js").write_text(build())
    print("wrote web/pseudo.js")
