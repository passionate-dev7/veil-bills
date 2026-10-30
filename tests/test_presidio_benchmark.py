"""The committed Presidio benchmark artifacts stay honest and reproducible (Veil side only, stdlib)."""
import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
J = json.loads((ROOT / "eval" / "presidio_results.json").read_text())


def test_json_covers_all_18_letters_and_marks_untested():
    rows = {r["letter"]: r for r in J["identifiers"]}
    assert list(rows) == list("ABCDEFGHIJKLMNOPQR")
    for L in "PQ":
        assert rows[L]["status"] == "not_tested"
        assert "not in corpus / not tested" in rows[L]["note"]
        assert rows[L]["n_gold"] == 0
    claim = J["meta"]["claim"]
    assert "not a HIPAA compliance claim" in claim and "does not meet Safe Harbor by design" in claim


def test_web_copy_is_byte_identical():
    assert (ROOT / "web" / "presidio_results.json").read_bytes() == (ROOT / "eval" / "presidio_results.json").read_bytes()


def test_wording_present_on_page_md_and_readme():
    for p in ("eval/presidio_results.md", "README.md"):
        t = (ROOT / p).read_text()
        assert "does not meet" in t.lower() and "safe harbor" in t.lower(), p
    page = (ROOT / "web" / "index.html").read_text().lower()
    assert "safe harbor" in page and "not tested" in page and "meet" in page


def test_veil_numbers_reproduce():
    spec = importlib.util.spec_from_file_location("presidio_benchmark", ROOT / "eval" / "presidio_benchmark.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    agg, _res, _items = m.main(veil_only=True)
    for tool in ("veil", "veil_primed"):
        _rows, tot = agg[tool]
        want = J["tools"][tool]["total"]
        for k in ("n_gold", "hit", "tp_pred", "fp_pred", "precision", "recall"):
            assert k in want and tot[k] == want[k], (tool, k, tot, want)
