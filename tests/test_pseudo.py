import json
from collections import Counter
from veil.vault import Vault
from veil.pseudo import Pseudonymizer, StreamRehydrator
from veil.config import ROOT

DOC = """Patient: Jane Doe      DOB: 04/12/1985
Member ID: NSH884217353   Claim Number: CN77310452
Account Number: AC-5530188   Phone: (555) 014-2297   jane.doe@example.org
4821 Willow Creek Lane, Springfield, IL 62704
SSN 987-65-4321. CPT 73721 billed $2,400.00 on 03/02/2026."""


def mk(tmp_path, name="v.sqlite"):
    v = Vault(tmp_path / name)
    v.load_profile(ROOT / "demo" / "profile.json")
    return v, Pseudonymizer(v)


def test_round_trip_and_clear_fields(tmp_path):
    v, p = mk(tmp_path)
    red = p.redact_text(DOC)
    for secret in ["Jane Doe", "NSH884217353", "CN77310452", "AC-5530188", "(555) 014-2297", "jane.doe@example.org",
                   "Willow Creek", "987-65-4321", "04/12/1985"]:
        assert secret not in red, secret
    # CPT codes, amounts, service dates stay in the clear (judge condition)
    assert "73721" in red and "$2,400.00" in red and "03/02/2026" in red
    assert "[PERSON_1]" in red and "[MEMBER_ID_1]" in red and "[CLAIM_NO_1]" in red
    back = p.rehydrate_text(red)
    assert "Jane Doe" in back and "NSH884217353" in back and "CN77310452" in back and "987-65-4321" in back


def test_alias_and_case_variants_share_token(tmp_path):
    v, p = mk(tmp_path)
    red = p.redact_text("DOE, JANE and Jane A. Doe and jane doe")
    assert red.count("[PERSON_1]") == 3


def test_stable_across_sessions(tmp_path):
    v, p = mk(tmp_path)
    first = p.redact_text("Claim Number: CN77310452 and Claim Number: CN99887766")
    v.close()
    v2, p2 = mk(tmp_path)  # new process, same vault file
    again = p2.redact_text("see CN99887766 then CN77310452")
    assert first == "Claim Number: [CLAIM_NO_1] and Claim Number: [CLAIM_NO_2]"
    assert again == "see [CLAIM_NO_2] then [CLAIM_NO_1]"
    assert p2.rehydrate_text("[CLAIM_NO_2]") == "CN99887766"


def test_payload_walk_and_tool_args(tmp_path):
    v, p = mk(tmp_path)
    body = {"model": "m", "messages": [
        {"role": "user", "content": "Patient: Jane Doe"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "type": "function",
            "function": {"name": "lookup", "arguments": json.dumps({"member": "NSH884217353"})}}]}]}
    c = Counter()
    red = p.redact_payload(body, c)
    blob = json.dumps(red)
    assert "NSH884217353" not in blob and "Jane Doe" not in blob and c["MEMBER_ID"] >= 1
    resp = {"choices": [{"message": {"tool_calls": [{"function": {"name": "x", "arguments": '{"to": "[PERSON_1]", "m": "[MEMBER_ID_1]"}'}}]}}]}
    out = p.rehydrate_obj(resp)
    args = json.loads(out["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
    assert args == {"to": "Jane Doe", "m": "NSH884217353"}


def test_canary_flags_leaks_and_passes_clean(tmp_path):
    v, p = mk(tmp_path)
    red = json.dumps(p.redact_payload({"messages": [{"role": "user", "content": DOC}]})).encode()
    assert p.canary(red) == []
    dirty = red + b' {"oops": "Jane Doe lives at 4821 Willow Creek Lane"}'
    kinds = {k for k, _ in p.canary(dirty)}
    assert {"PERSON", "ADDRESS"} <= kinds
    # a value NOT in the vault but matching a regex detector is also caught
    assert any(h == "regex" for _, h in p.canary(b'{"x": "call 555-867-5309"}'))
    # formatting tricks: normalized match of a vault ID
    assert p.canary(b'{"x": "NSH-884-217-353"}') or p.canary(b'{"x": "nsh 884217353"}')


def test_stream_rehydrator_split_tokens(tmp_path):
    v, p = mk(tmp_path)
    p.redact_text("Patient: Jane Doe")
    sr = StreamRehydrator(p)
    out = "".join(sr.feed(x) for x in ["Dear [PERS", "ON_", "1], hi [", "x", " and [PERSON_1]"]) + sr.flush()
    assert out == "Dear Jane Doe, hi [x and Jane Doe"
