"""Always-on mode: watch an inbox folder, extract + audit every new PDF through the gateway, remember results, notify the UI,
draft appeals (pending approval) and create deadline follow-ups. Nothing here can send anything: drafts wait for a human.
"""
from __future__ import annotations
import re, time
from datetime import date
from pathlib import Path
from .audit import run_audit, usd
from .client import Gateway
from .config import Settings
from .egress import Policy, Outbox, EMAIL
from .extract import extract, pdf_text
from .memory import Memory, file_sha
from .run import make_appeal


class Engine:
    def __init__(self, settings: Settings, gw: Gateway, mem: Memory | None = None, as_of: date | None = None, say=print, appeal=True, within: int = 21):
        self.s, self.gw, self.as_of, self.say, self.appeal, self.within = settings, gw, as_of, say, appeal, within
        self.mem = mem or Memory(settings.memory_db)
        self.policy, self.outbox = Policy(settings), Outbox(settings)

    @property
    def today(self) -> date:
        return self.as_of or date.today()

    # -- ingest -------------------------------------------------------------
    def ingest(self, path: Path) -> dict | None:
        sha = file_sha(path)
        if self.mem.has_doc(sha):
            return None
        text = pdf_text(path)
        self.say(f"  new document {path.name}: extracting via gateway (Lightning)")
        try:
            doc, _ = extract(self.gw, text, path.name)
        except Exception as e:
            self.mem.event("error", f"Could not read {path.name}", str(e)[:300])
            self.say(f"  ! {path.name}: {e}")
            return None
        self.mem.add_doc(sha, path.name, path, text, doc, self.gw.run)
        self.mem.event("document", f"New {doc['doc_type'].upper()} from {doc['provider']}", f"{path.name} (dated {doc['document_date']})", dict(name=path.name, doc_type=doc["doc_type"]))
        return doc

    # -- analysis -----------------------------------------------------------
    def analyze(self) -> dict:
        docs = self.mem.docs()
        audit = run_audit(docs, self.today)
        new = self.mem.sync_findings(audit["findings"])
        for f in new:
            self.mem.event("finding", f"{f['type'].replace('_', ' ').title()}: {usd(f['amount'])}", f["detail"], dict(key=f["key"], bill_doc=f.get("bill_doc"), type=f["type"], amount=f["amount"]))
        if audit["deductible"]:
            d = audit["deductible"]; old = self.mem.fact("deductible")
            self.mem.set_fact("deductible", dict(d, as_of=self.today.isoformat()))
            if not old or old.get("met") != d["met"]:
                self.mem.event("deductible", f"Deductible updated: {usd(d['met'])} of {usd(d['deductible'])} met", f"{usd(d['remaining'])} remaining", d)
        audit["_new"] = new
        return audit

    # -- appeals ------------------------------------------------------------
    def draft_appeals(self, audit: dict) -> list[dict]:
        if not self.appeal:
            return []
        docs = self.mem.docs()
        by_name = {d["_name"]: d for d in docs}
        texts = {d["_name"]: d["_text"] for d in docs}
        have = {d.get("bill_doc") for d in self.outbox.list() if d.get("kind") == "appeal" and d["status"] != "rejected"}
        out = []
        for f in audit["_new"]:
            b = f.get("bill_doc")
            if not b or b in have or not f.get("eob_doc"):
                continue
            card = next((c for c in audit["deadlines"] if c["claim"] == by_name[f["eob_doc"]]["claim_number"]), None)
            if card and card["status"] == "expired":
                self.mem.event("deadline", f"Appeal window already closed for {card['provider']}", f"Deadline was {card['deadline']}. Veil will not draft an appeal; consider a goodwill request.", dict(claim=card["claim"]))
                have.add(b)
                continue
            self.say(f"  Ultra drafting appeal for {b}")
            ap = make_appeal(self.gw, self.s, b, audit, docs, by_name, texts)
            have.add(b)
            if ap["draft"]:
                d = ap["draft"]
                self.mem.event("draft", f"Appeal drafted: {d['subject'][:70]}", f"Pending your approval. Figures verified: {ap['letter_check']['ok']}", dict(draft_id=d["id"], bill_doc=b))
                out.append(d)
            else:
                self.mem.event("error", f"Ultra did not queue an appeal for {b}", (ap.get("final_text") or "")[:200])
        return out

    # -- deadline scheduler -------------------------------------------------
    def schedule(self, audit: dict | None = None) -> list[dict]:
        """For every claim whose appeal deadline is within `within` days, create ONE follow-up draft (pending approval)."""
        audit = audit or run_audit(self.mem.docs(), self.today)
        docs = {d["claim_number"]: d for d in self.mem.docs() if d["doc_type"] == "eob"}
        made = []
        for c in audit["deadlines"]:
            eob = docs.get(c["claim"])
            if c["status"] == "expired" or c["days_left"] > self.within or not eob:
                continue
            key = f"{c['claim']}:{c['deadline']}:within{self.within}"
            if self.mem.followup(key):
                continue
            to = self._contact(eob)
            if not to:
                self.mem.event("error", f"No trusted contact for claim {c['claim']}", "Add the insurer appeals address to trusted_contacts.")
                continue
            claim_of = {d["_name"]: d.get("claim_number") for d in self.mem.docs()}
            appealed = next((d for d in self.outbox.list() if d.get("kind") == "appeal" and d["status"] == "delivered_to_sandbox"
                             and (d.get("claim") == c["claim"] or claim_of.get(d.get("bill_doc")) == c["claim"])), None)
            body = followup_text(eob, c, appealed)
            d = self.outbox.queue([to], f"Follow-up: appeal window for claim {c['claim']} closes {c['deadline']}", body, self.gw.run,
                                  dict(kind="followup", claim=c["claim"], deadline=c["deadline"], days_left=c["days_left"]))
            self.mem.add_followup(key, d["id"])
            self.mem.event("followup", f"{c['days_left']} days left: follow-up drafted for {c['provider']}", f"Deadline {c['deadline']}. Draft {d['id']} is waiting for your approval.", dict(draft_id=d["id"], claim=c["claim"], days_left=c["days_left"]))
            made.append(d)
        return made

    def _contact(self, eob: dict) -> str | None:
        cands = EMAIL.findall(eob.get("_text") or "") + EMAIL.findall(str(eob.get("appeals_contact") or ""))
        return next((e for e in cands if e.lower() in self.policy.allow), None)

    # -- one pass -----------------------------------------------------------
    def process_inbox(self, inbox: Path, settle_s: float = 1.5) -> dict:
        inbox = Path(inbox).expanduser()
        inbox.mkdir(parents=True, exist_ok=True)
        added = []
        for p in sorted(inbox.glob("*.pdf")):
            if time.time() - p.stat().st_mtime < settle_s:
                continue  # still being written
            if self.ingest(p):
                added.append(p.name)
        audit = self.analyze() if (added or not self.mem.fact("last_scan")) else run_audit(self.mem.docs(), self.today) | {"_new": []}
        drafts = self.draft_appeals(audit) if added else []
        follow = self.schedule(audit)
        self.mem.set_fact("last_scan", dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S%z"), inbox=str(inbox), added=added))
        return dict(added=added, new_findings=len(audit["_new"]), appeals=drafts, followups=follow)

    def watch(self, inbox: Path, interval: float = 3.0, stop=lambda: False):
        self.mem.event("watch", "Watching for new paperwork", str(inbox))
        self.say(f"Veil is watching {inbox}  (every {interval:.0f}s). Drop a PDF in to see it processed. Ctrl-C to stop.")
        while not stop():
            try:
                r = self.process_inbox(inbox)
                if r["added"] or r["followups"]:
                    self.say(f"  processed {r['added']}: {r['new_findings']} new findings, {len(r['appeals'])} appeal draft(s), {len(r['followups'])} follow-up(s)")
            except Exception as e:  # never die; surface in the UI
                self.mem.event("error", "Watcher error", f"{type(e).__name__}: {e}"[:300])
            time.sleep(interval)


def followup_text(eob: dict, card: dict, appealed: dict | None) -> str:
    patient = eob.get("patient_name") or "the patient"
    head = f"Re: Claim Number {card['claim']}\nMember ID: {eob.get('member_id')}\nPatient: {patient}\nProvider: {card['provider']}\n\nDear Appeals Department,\n\n"
    if appealed:
        mid = (f"On {appealed['approved'][:10]} I submitted an appeal for this claim. The 180-day appeal window for the Explanation of Benefits dated {card['notice_date']} "
               f"closes on {card['deadline']} ({card['days_left']} days from today). Please confirm in writing that my appeal was received and is under review, and tell me the date a decision is due.")
    else:
        mid = (f"The 180-day appeal window for the Explanation of Benefits dated {card['notice_date']} closes on {card['deadline']} ({card['days_left']} days from today). "
               f"I am disputing the amount the provider is billing me for this claim and request that my appeal rights be preserved. I will send the written appeal before the deadline; please confirm the correct address and any form you require.")
    return head + mid + "\n\nPlease also confirm that the account will be held from collections activity while this is reviewed.\n\nSincerely,\n" + patient + "\n"
