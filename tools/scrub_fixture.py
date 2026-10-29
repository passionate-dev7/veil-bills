"""Make a UI-lane fixture: copy web/ to DEST and replace every identifying value in run.json with its token, so external
free-model coding lanes never see even the synthetic patient's identifiers. Real run.json is used only for local screenshots."""
import json, re, shutil, sys
from pathlib import Path
src, dest = Path("web"), Path(sys.argv[1])
dest.mkdir(parents=True, exist_ok=True)
for p in src.iterdir():
    if p.is_file() and p.name not in ("run.json", "run.js"):
        shutil.copy(p, dest / p.name)
    elif p.is_dir():
        shutil.copytree(p, dest / p.name, dirs_exist_ok=True)
R = json.loads((src / "run.json").read_text())
pairs = sorted({(s["value"], s["token"]) for s in R["sensitive"]}, key=lambda x: -len(x[0]))
pairs += [("Jane Doe", "[PERSON_1]"), ("jane.doe@example.org", "[EMAIL_1]")]
def clean(o):
    if isinstance(o, str):
        for v, t in pairs: o = o.replace(v, t)
        return re.sub(r"[\w.+-]+@example\.org", "[EMAIL_1]", o)
    if isinstance(o, list): return [clean(x) for x in o]
    if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
    return o
R = clean(R)
for s in R["sensitive"]: s["value"] = "X-" + s["token"].strip("[]")     # keep the shape (value -> token) without any real identifier
(dest / "run.json").write_text(json.dumps(R, indent=1))
(dest / "run.js").write_text("window.VEIL_RUN = " + json.dumps(R) + ";")
print("fixture ->", dest, "values replaced:", len(pairs))
