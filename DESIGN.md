# Veil design system: "Case file", adapted from Resend

Source system: `~/.config/design-md/designs/resend.md`, checked against the live resend.com on 2026-10-30 (computed styles read in Brave): canvas rgb(0,0,0), ink rgb(240,240,240), body grey rgb(161,164,165), h1 in a high-contrast serif at 96px / line-height 96px / letter-spacing -0.96px / weight 400, left aligned, subtitle in grey sans, quiet charcoal buttons with a hairline. What Veil keeps: near-black canvas, off-white ink, a left-aligned oversized serif that carries the human story, grey supporting copy, hairline edges made of translucent white, no decorative chrome. What Veil changes: a different serif, a different body face, colour that only ever means something, and a document specimen in the hero instead of an object render.

Job of the screen: show a patient that the audit found real money (a bill, a deadline, dollars owed back) and let a judge read, byte for byte, that nothing identifying left the machine. Primary action: read the appeal draft.

## Fonts (Google Fonts, one request)

| Role | Face | Use |
|---|---|---|
| Display | Noto Serif Display 400/500 | The money headline, section titles, the proof sentence. Roman only. Tabular by default (verified: 1111 and 0000 measure the same width). |
| UI and body | Geist 400/500/600 | Copy, buttons, table text, labels. `font-variant-numeric: tabular-nums` on every figure. |
| Bytes and receipts | Geist Mono 400/500 | Only the outbound request text, hashes, ledger ids, the hostile-text box and the .eml. Never decoration. |

Never Inter, Roboto, Open Sans, Arial or system-ui as primary.

## Tokens (all colour and type through these names)

| Token | Value | Meaning |
|---|---|---|
| `--canvas` | #060607 | page |
| `--raise-1` | #0c0c0e | panels |
| `--raise-2` | #131316 | wells, code, inputs |
| `--hair` | rgba(255,255,255,.08) | default edge |
| `--hair-strong` | rgba(255,255,255,.16) | focus edge, table totals |
| `--ink` | #eef0f2 | text |
| `--mute` | #a3a7ad | supporting copy (8.4:1 on canvas) |
| `--faint` | #81858c | captions (5.5:1 on canvas) |
| `--token` | #86e3c8 | a token that replaced a value; verified; chain OK; "held" |
| `--real` | #ff7a5c | a real identifier; blocked; leaked; chain broken |
| `--money` | #e8d6a0 | dollars found and deadlines |

Colour is meaning, never decoration. Mint appears on tokens and verifications, vermilion on real identifiers and blocked attacks, champagne on dollars and appeal windows. Each tinted fill is its colour at 10 to 14 percent over the surface. No gradients, no glows, no glass, no shadows at rest (a hairline is the shadow).

## Type scale (rem on a 16px root)

Display XL `clamp(3.75rem, 9.2vw, 9rem)`, line-height .92, tracking -.02em, weight 400 (the one hero headline). Display L `clamp(2.25rem, 4.4vw, 4rem)` (proof sentence, section titles). Display M 1.75rem (accordion titles, panel titles). Body 1rem / 1.55. UI 0.875rem / 1.5. Mono 0.8125rem / 1.65. Caption 0.8125rem. Eyebrows are not used.

## Space, radius, motion

Spacing 4, 8, 12, 16, 24, 32, 48, 80, 128. Radius 6 on controls and chips, 12 on panels, 999 only on the mode switch. Easing `cubic-bezier(.2,.7,.2,1)`. Motion is transform and opacity only, 160 to 700 ms, and every animation sits behind `prefers-reduced-motion: no-preference`. One signature move: on load the veil draws across the specimen, so each real value on the Mac side is replaced by its token on the Nebius side. Focus ring: 2px `--token` offset 3px, never animated.

## Macrostructure

1. Slim bar: wordmark in the serif, the synthetic-data notice, the Live/Judge switch.
2. Hero, two columns: left the money (serif headline "Overbilled by $2,463", the two bills with their appeal windows, one primary action); right the specimen slip, the same lines of a real document as they sit on the Mac and as Nebius received them, with the ledger row and sha256 underneath.
3. Proof sentence in the display serif: values replaced, calls, leaked, receipts verified in this browser.
4. Attack band: the hostile line, what the live run did, and the earlier trials, each labelled with its kind of evidence.
5. Case file: the three steps (Add a bill, Findings, Appeal draft) beside the sticky "What Nebius received" wire.
6. Proof: eleven claims as a ledger of serif titles, each opening to its evidence. Footer states that the page reads cached data.

Hard bans carried from the house rules: three equal feature cards, stat tile grids, eyebrow labels, ghost numbers, gradient text, floating pills.
