"""Pull REAL OpenShell sandbox deny events into the Veil ledger as live egress rows.

OpenShell enforces the network policy at the sandbox boundary and writes OCSF lines like
  [1793267452.424] [sandbox] [OCSF ] [ocsf] NET:OPEN [MED] DENIED /usr/bin/curl(1940) -> evil.example:443 [policy:- engine:opa] [reason:...]
We do not synthesize these: we read `openshell logs <sandbox> --source sandbox`, keep the DENIED lines verbatim, and ledger them with
source=openshell. `trigger` is a free-text honest label of what caused the traffic (an agent tool call, or an operator-run curl).
"""
from __future__ import annotations
import re, subprocess, time
from .config import Settings
from .ledger import Ledger

LINE = re.compile(r"^\[(?P<ts>\d+\.\d+)\] \[sandbox\] \[OCSF \] \[ocsf\] (?P<kind>\S+) \[(?P<sev>\w+)\] DENIED (?P<bin>\S+?)\((?P<pid>\d+)\) -> (?P<target>.+?) "
                  r"\[policy:(?P<policy>[^ \]]*) engine:(?P<engine>[^\]]*)\](?: \[reason:(?P<reason>.*)\])?\s*$")


def parse(line: str) -> dict | None:
    m = LINE.match(line.strip())
    return m.groupdict() if m else None


def read_logs(sandbox: str, n: int = 3000) -> list[str]:
    r = subprocess.run(["openshell", "logs", sandbox, "--source", "sandbox", "-n", str(n)], capture_output=True, text=True, timeout=60)
    return r.stdout.splitlines()


def ingest(s: Settings, lines: list[str], trigger: str, run: str = "sandbox-hermes", since: float = 0.0, only: str | None = None) -> list[int]:
    """Ledger every DENIED line (optionally only those whose target contains `only`). Idempotent: a raw line is stored once."""
    led = Ledger(s.ledger_db)
    seen = {(e.get("meta") or {}).get("raw") for e in led.list(5000, kind="egress")}
    out = []
    for raw in lines:
        d = parse(raw)
        if not d or float(d["ts"]) < since or raw.strip() in seen or (only and only not in d["target"]):
            continue
        t = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(float(d["ts"])))
        out.append(led.add(kind="egress", run=run, tag="openshell-deny", route=f"openshell:{d['kind']}", status="blocked", ts=t,
                           reason=f"OpenShell sandbox denied {d['bin']} -> {d['target']}: {d.get('reason') or 'not allowed by any policy'}",
                           meta=dict(source="openshell", live=True, raw=raw.strip(), observed=t, binary=d["bin"], pid=int(d["pid"]), target=d["target"],
                                     policy=d["policy"], engine=d["engine"], trigger=trigger, to=[d["target"]], subject="(network connection)")))
    return out
