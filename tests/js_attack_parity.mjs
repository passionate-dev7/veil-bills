// Runs request bodies (tests/test_js_attack_parity.py writes them to the JSON file in argv[2]) through web/pseudo.js, the browser build of the gateway's
// redactor and canary, and prints one result per case: HTTP status the gateway would give (422 = canary fail closed) and the outbound bytes.
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
const require = createRequire(import.meta.url);
const V = require("../web/pseudo.js");
const cases = JSON.parse(readFileSync(process.argv[2], "utf8"));
const out = cases.map(c => {
  const p = c.mode === "cold" ? new V.Pseudo(new V.Vault([])) : V.create();   // cold: the vault has never seen the patient
  const g = p.gatewayBody(c.body);
  return { id: c.id, status: g.status, outbound: g.outbound, leaks: g.leaks };
});
console.log(JSON.stringify(out));
