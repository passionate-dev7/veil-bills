// Runs every case in tests/parity_cases.json through web/pseudo.js and prints one JSON line per case. tests/test_js_parity.py compares with Python.
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
const require = createRequire(import.meta.url);
const V = require("../web/pseudo.js");
const cases = JSON.parse(readFileSync(new URL("./parity_cases.json", import.meta.url)));
const out = cases.map(c => { const g = V.create().gateway(c.text); return { name: c.name, status: g.status, redacted: g.redacted, counts: g.counts, leaks: g.leaks, outbound: g.outbound }; });
console.log(JSON.stringify(out));
