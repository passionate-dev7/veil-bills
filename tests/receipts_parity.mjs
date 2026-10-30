// Reads {canon:[...values], variants:[{name, entries, bytes, head}]} from argv[2]; prints canonical strings, per-entry receipt hashes and verify() results,
// computed by web/receipts.js with Web Crypto. tests/test_receipts.py runs the same inputs through Python and compares.
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
const V = createRequire(import.meta.url)("../web/receipts.js");
const input = JSON.parse(readFileSync(process.argv[2], "utf8"));
const out = { canon: input.canon.map(V.canon), hashes: [], results: {} };
for (const e of input.variants[0].entries) out.hashes.push(await V.receiptHash(e));
for (const v of input.variants) out.results[v.name] = await V.verify(v.entries, v.bytes, v.head || undefined);
console.log(JSON.stringify(out));
