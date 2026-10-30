# Critique of the judge page, and what changed

Scored 13/20 by the judge pass at `6b4fa88`. Measured with `tools/shots.py` (full-page headless Chrome):

| width | `6b4fa88` page | now |
|---|---|---|
| 1440 | 8,371 px | 2,199 px |
| 768 | n/a (7,861 for the first version) | 2,631 px |
| 390 | 16,695 px | 3,785 px |

Console is clean at 1440, 768 and 390 (`console_messages=0`).

## What was wrong (read from the reference files in `/workspace/refs`)

1. **Everything shown at once.** The old page put nine sections on one scroll. The no-ui-slop skill says to design each state and show the next step, not the whole product. A judge had to scroll 8,000 px to find the one claim they were scoring. Now there are 3 steps, one panel at a time, and proofs sit in closed accordions with the headline number in each summary line.
2. **No single money figure.** Wise and NerdWallet lead with one big number and a hairline table. The old page led with a mechanism. Now `$2,463.00` sits in the hero, computed in Python and counted once per bill.
3. **Claims without a path to proof.** The thesis was implicit. Now it is the `h1`, and each of its three claims links to the ledger rows, the parity table, or the hostile-text box that proves it.
4. **Over-stated evidence.** Mercury's calm density only works if every row says what it is. The old page let scripted probes read like agent behaviour. Now every egress row has an evidence label: replay and sandbox-agent are scripted, agent rows are real model tool calls refused by Veil's Python allowlist, OpenShell rows are an operator `curl` probe. The model-driven Hermes run has a visible empty slot with the one command that fills it.
5. **Fail-closed was only claimed.** The cached run had 0 blocked, so the canary never showed on screen. Now a hostile-text box runs the same redaction and canary rules in the browser and shows a 422, and `eval/canary_demo.json` records the real gateway code blocking.
6. **Mobile.** The 390 px page was 16,695 px because side-by-side panes stacked. The ledger is now a collapsible section there, tables scroll inside their own wrapper, and tabs wrap instead of overflowing.
7. **Taste-skill check on our own screenshots.** Three type sizes (14/20/40), tabular figures for money and hashes, no nested cards, no gradients or glass, no hover-only information (every `title` tooltip is duplicated in visible text), no timed animation, no emoji.

## Still weak (honest)

- At 1440 the first screen is the alert, thesis and the step panel; the money figure is right of the thesis and could be bigger on short screens.
- Fonts come from Google Fonts. Offline, the fallback faces are plain but readable.
- The hostile-text box starts open, which adds about 150 px; closing it by default would hide the best proof.
- The upload box only previews redaction of `.txt`. Auditing your own bill needs the local pipeline and Token Factory credit, and the page says so.
