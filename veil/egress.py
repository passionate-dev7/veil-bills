"""Egress policy + human-approval outbox + local sandbox mailbox.

Nothing in Veil can reach a real mailbox: there is no SMTP code. Approval writes an .eml file into
`<home>/sandbox_mailbox/`. The allowlist is the user's `trusted_contacts` (profile.json); an agent tool call that
addresses anyone else is refused and the refusal is recorded in the ledger (kind=egress).
"""
from __future__ import annotations
import json, re, time, uuid
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path
from .config import Settings
from .ledger import Ledger

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


class Policy:
    def __init__(self, settings: Settings):
        self.s = settings
        prof = json.loads(settings.profile.read_text()) if settings.profile and settings.profile.exists() else {}
        self.allow = {(e["email"] if isinstance(e, dict) else e).lower() for e in prof.get("trusted_contacts", [])}
        self.ledger = Ledger(settings.ledger_db)

    def check(self, recipients: list[str]) -> tuple[bool, list[str]]:
        bad = [r for r in recipients if r.lower() not in self.allow]
        return (not bad), bad

    def log(self, allowed: bool, tool: str, to: list[str], subject: str, run: str, tag: str, reason: str, source: str = "agent") -> int:
        return self.ledger.add(kind="egress", run=run, tag=tag, route=f"tool:{tool}", status="allowed" if allowed else "blocked",
                               reason=reason, meta={"to": to, "subject": subject, "allowlist_size": len(self.allow), "source": source})


class Outbox:
    def __init__(self, settings: Settings):
        self.dir, self.mail = settings.outbox, settings.mailbox
        self.dir.mkdir(parents=True, exist_ok=True)

    def queue(self, to: list[str], subject: str, body: str, run: str, extra: dict | None = None) -> dict:
        d = dict(id="d" + uuid.uuid4().hex[:8], status="pending_approval", to=to, subject=subject, body=body, run=run,
                 created=time.strftime("%Y-%m-%dT%H:%M:%S%z"), **(extra or {}))
        (self.dir / f"{d['id']}.json").write_text(json.dumps(d, indent=2))
        return d

    def list(self) -> list[dict]:
        return [json.loads(p.read_text()) for p in sorted(self.dir.glob("*.json"))]

    def get(self, id: str) -> dict:
        return json.loads((self.dir / f"{id}.json").read_text())

    def _save(self, d):
        (self.dir / f"{d['id']}.json").write_text(json.dumps(d, indent=2))

    def reject(self, id: str) -> dict:
        d = self.get(id); d["status"] = "rejected"; self._save(d); return d

    def approve(self, id: str, policy: Policy) -> dict:
        """Human approval. Re-checks the allowlist, then writes an .eml into the sandbox mailbox. Never networks."""
        d = self.get(id)
        if d["status"] != "pending_approval":
            raise ValueError(f"draft {id} is {d['status']}")
        ok, bad = policy.check(d["to"])
        policy.log(ok, "approve", d["to"], d["subject"], d["run"], id, "approved by human; delivered to sandbox mailbox" if ok else f"recipient not on allowlist: {bad}", source="human")
        if not ok:
            raise PermissionError(f"recipients not on allowlist: {bad}")
        m = EmailMessage()
        m["From"] = "jane.doe@example.org"; m["To"] = ", ".join(d["to"]); m["Subject"] = d["subject"]; m["Date"] = formatdate(localtime=True)
        m["X-Veil-Sandbox"] = "delivered to local sandbox mailbox only; not sent over any network"
        m.set_content(d["body"])
        self.mail.mkdir(parents=True, exist_ok=True)
        path = self.mail / f"{id}.eml"
        path.write_bytes(bytes(m))
        d["status"] = "delivered_to_sandbox"; d["eml"] = str(path); d["approved"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self._save(d)
        return d
