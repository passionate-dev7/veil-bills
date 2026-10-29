---
name: deductible-tracker
description: Track how much of the annual deductible has been met from EOBs and flag an upcoming or expired 180-day appeal window. Use when the user asks "how much of my deductible is left?" or wants a deadline reminder across their claims.
version: 0.1.0
metadata:
  hermes:
    tags: [health, deductible, deadlines, reminders, nemotron]
---

# Deductible and deadline tracker

Deterministic, read-only. The numbers come from the latest EOB's deductible block (extracted by Lightning, summed in code), not from a model's arithmetic.

## Steps

1. Run `veil audit <folder> --as-of <today> --no-appeal --export web/run.json` (or reuse the cached run).
2. Report from `deductible`: amount met, plan deductible, remaining. Example from the synthetic corpus: $1,462.00 of $2,500.00 met.
3. Report from `deadlines`: for each claim, notice date + 180 days, days left or "EXPIRED n days ago", sorted by urgency. Surface the nearest unexpired one as the single deadline card.
4. If a hermes cron is available, schedule a reminder 14 days and 3 days before each unexpired deadline. The reminder text must not contain member IDs, names or claim numbers; refer to "the Mercy Valley claim" style labels.

## Pitfalls

- The 180-day window is an assumption for the synthetic plan; real plans differ. Always show the source EOB date and the arithmetic.
- "as of" must be today's date in the user's timezone, otherwise the day counts are off by one.
- Do not infer deductible progress from bills; only EOBs state what the insurer applied.

## Verification

- `tests/test_audit.py` covers deadline math and deductible status.
- The card arithmetic (notice + 180 = deadline) is visible on the card itself.
