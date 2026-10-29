# Veil redesign: three directions (chosen: A)

Constraints for all three: warm off-white paper, ONE deep ink-green accent, editorial serif headings + clean sans body, money/codes in mono with tabular-nums, the blocked exfil opens the page as a bordered critical alert, honest source labels (replay / scripted probe / real model attempt), exactly 3 type sizes (14 / 20 / 40), no emoji, no cards inside cards, no glass, no gradients, no bento, no tiny all-caps eyebrows, no hover-only info, no timed fade-ins. Must differ from CAPE (light zinc, Inter) and Latch (dark graphite evidence ledger).

## A. Folder on the desk (CHOSEN)
Alert strip (2px red-brown border, tinted paper) on top. Below it a two-pane "stage": left pane is THE BILL, a paper sheet in mono with identifying values underlined in the critical colour and a tab per document; right pane is PARITY: what Nebius actually received (same document, tokens in ink-green), the ledger facts (bytes, sha256, redacted count, leaked = 0) and a short row-aligned "same findings, same amounts" check. One glance answers "what did you hold, what did the cloud get". Then a three-figure summary line, then findings and the approval draft in the left column with memory and notifications in a narrow right column.
Why: it literally is the brief (bill one side, parity other side) and the demo moment (side-by-side) is the first screen after the alert.

## B. Annotated statement
One long editorial column that looks like an EOB with marginal notes: each finding is a note pinned beside the bill line it concerns, the gateway proof is a footnote per line. Beautiful on desktop, but the side-by-side parity (the hero of the demo) becomes scattered footnotes and breaks on 390px. Rejected.

## C. Three-station flow
Horizontal pipeline: This Mac (raw) -> Gateway (tokenise, canary, egress policy) -> Nebius (what arrived), with the blocked exfil drawn on the arrow between Gateway and the outside. Great diagram, but it reads as an architecture slide, hides the bill itself, and needs hover or animation to explain the stations. Rejected.
