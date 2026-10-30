/* Veil receipt chain verifier (browser + node). Same algorithm as veil/receipts.py; tests/test_receipts.py pins the two together.
   Each receipt commits to the exact outbound bytes (sha256) and to the previous receipt's hash, so editing, deleting or reordering any
   entry breaks verification at that entry. Tamper-evident, not tamper-proof: whoever can rewrite the whole chain can rebuild it, so the
   head hash is shown for anchoring somewhere you control. */
(function (root) {
  "use strict";
  const GENESIS = "0919b0da835fb3a833bd2af748041718b08f2ee538356dfa1864b01bf464a547"; // sha256("veil/receipts/genesis/v1")
  const te = new TextEncoder();
  const subtle = () => (root.crypto && root.crypto.subtle) || (typeof require === "function" ? require("node:crypto").webcrypto.subtle : null);

  const str = s => JSON.stringify(s).replace(/[\u007f-\uffff]/g, c => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
  function canon(v) {  // sorted keys, no spaces, ASCII-only escapes, integers only: byte-identical to Python's canonical()
    if (v === null || v === undefined) return "null";
    if (typeof v === "boolean") return v ? "true" : "false";
    if (typeof v === "number") { if (!Number.isInteger(v)) throw new Error("non-integer in receipt"); return String(v); }
    if (typeof v === "string") return str(v);
    if (Array.isArray(v)) return "[" + v.map(canon).join(",") + "]";
    return "{" + Object.keys(v).sort().map(k => str(k) + ":" + canon(v[k])).join(",") + "}";
  }
  async function sha256(bytes) {
    const s = subtle();
    if (!s) throw new Error("Web Crypto is unavailable (needs https or localhost)");
    return [...new Uint8Array(await s.digest("SHA-256", bytes))].map(b => b.toString(16).padStart(2, "0")).join("");
  }
  async function receiptHash(r) {
    const o = {}; for (const k of Object.keys(r)) if (k !== "receipt_hash") o[k] = r[k];
    return sha256(te.encode(canon(o)));
  }
  /* receipts: array; bytes: {seq: text} of the stored outbound body of that call receipt (optional) */
  async function verify(receipts, bytes, expectHead) {
    let prev = GENESIS, checked = 0;
    const all = new Set(receipts.map(r => r.seq)), seen = new Set();
    const bad = (seq, code, reason) => ({ ok: false, count: receipts.length, head: null, bytes_checked: checked, broken: { seq, code, reason } });
    for (let i = 0; i < receipts.length; i++) {
      const r = receipts[i], want = i + 1, s = r.seq;
      if (s !== want) {
        if (seen.has(s)) return bad(want, "duplicate", `seq ${s} appears twice`);
        if (all.has(want)) return bad(want, "reordered", `seq ${s} sits where seq ${want} belongs: entries were reordered`);
        return bad(want, "missing", `seq ${want} is missing: an entry was deleted (next entry is seq ${s})`);
      }
      seen.add(s);
      if (await receiptHash(r) !== r.receipt_hash) return bad(s, "edited", "receipt was edited: its receipt_hash does not match its fields");
      if (r.prev_hash !== prev) return bad(s, "link", s > 1 ? `link mismatch: prev_hash is not the hash of seq ${s - 1}` : "link mismatch: first receipt does not start at the genesis hash");
      if (bytes && r.type === "call" && bytes[s] !== undefined) {
        const b = te.encode(bytes[s]);
        if (b.length !== r.byte_count) return bad(s, "byte_count", `byte count mismatch: stored bytes are ${b.length}, receipt says ${r.byte_count}`);
        if (await sha256(b) !== r.sha256) return bad(s, "bytes", "outbound bytes hash mismatch: the stored bytes are not the bytes that were receipted");
        checked++;
      }
      prev = r.receipt_hash;
    }
    if (expectHead && prev !== expectHead) return bad(receipts.length + 1, "head", `head mismatch: chain ends at ${prev.slice(0, 16)}, expected ${expectHead.slice(0, 16)}: entries were removed from the end or the chain was rebuilt`);
    return { ok: true, count: receipts.length, head: prev, bytes_checked: checked, broken: null };
  }
  /* The demo: work on a COPY. kinds: bytes (flip one byte of the stored body), field (bump byte_count), delete, reorder. */
  function tamper(chain, seq, kind) {
    const entries = chain.entries.map(e => JSON.parse(JSON.stringify(e))), bytes = Object.assign({}, chain.bytes || {});
    const i = entries.findIndex(e => e.seq === seq);
    if (i < 0) throw new Error("no such entry");
    if (kind === "bytes") {
      const b = te.encode(bytes[seq] !== undefined ? bytes[seq] : ""); if (!b.length) return null;
      let k = b.findIndex(c => c >= 97 && c <= 122); if (k < 0) k = 0;
      b[k] ^= 1; bytes[seq] = new TextDecoder().decode(b); return { entries, bytes, what: `flipped one byte (offset ${k}) of the stored body for seq ${seq}` };
    }
    if (kind === "field") { entries[i].byte_count = (entries[i].byte_count || 0) + 1; return { entries, bytes, what: `changed byte_count of seq ${seq} by 1` }; }
    if (kind === "delete") { entries.splice(i, 1); return { entries, bytes, what: `deleted seq ${seq}` }; }
    if (kind === "reorder") { if (i + 1 >= entries.length) return null; [entries[i], entries[i + 1]] = [entries[i + 1], entries[i]]; return { entries, bytes, what: `swapped seq ${seq} and seq ${seq + 1}` }; }
    throw new Error("unknown tamper kind");
  }
  const api = { GENESIS, canon, sha256, receiptHash, verify, tamper };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.VeilChain = api;
})(typeof window !== "undefined" ? window : globalThis);
