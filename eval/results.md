# Eval: raw vs redacted (SYNTHETIC data)

Same Lightning extraction prompt, same deterministic audit. `raw` = unredacted text sent directly to Token Factory; `redacted` = through the Veil gateway.
Identifiers = ground-truth name, last-first name, DOB, member ID, SSN, phone, email, street, claim and account numbers that appear in the documents.

| Case | Expected findings | Raw: findings | Raw: fields | Redacted: findings | Redacted: fields | Identifiers that reached Nebius (redacted / raw) | Name-part leaks (redacted) |
|---|---|---|---|---|---|---|---|
| e1-duplicate | DUPLICATE_CHARGE | OK | 3/3 | OK | 3/3 | 0/6 / 6/6 | - |
| e2-balance-billing | BALANCE_BILLING, BILL_EOB_MISMATCH | OK | 3/3 | OK | 3/3 | 0/6 / 6/6 | - |
| e3-clean | none | OK | 3/3 | OK | 3/3 | 0/6 / 6/6 | - |
| e4-unprocessed-line | UNMATCHED_LINE | OK | 3/3 | OK | 3/3 | 0/6 / 6/6 | - |
| e5-injected-mismatch | BALANCE_BILLING, BILL_EOB_MISMATCH | OK | 3/3 | OK | 3/3 | 0/6 / 6/6 | Olu |
| jane-corpus (profile-seeded) | BALANCE_BILLING, BILL_EOB_MISMATCH, DUPLICATE_CHARGE | OK | 9/9 | OK | 9/9 | 0/10 / 10/10 | Doe |

**Summary:** findings correct raw 6/6, redacted 6/6; money/date fields raw 24/24, redacted 24/24; identifiers reaching Nebius: 0/40 redacted vs 40/40 raw. Wall 105.8s.
