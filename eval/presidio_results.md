# Veil vs Microsoft Presidio, scored against the HIPAA Safe Harbor identifier list

Source of the list: [https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html) (45 CFR 164.514(b)(2)(i), identifiers A to R, checked 2026-10-30). Presidio 2.2.366 with en_core_web_lg 3.8.0. All data is synthetic: 16 corpus documents (the 6 Jane Doe PDFs from `demo/corpus` plus 10 generated EOB and bill documents for 5 more synthetic personas), 35 hard cases, 27 synthetic extras.

> **Plainly: Veil does not meet HIPAA Safe Harbor, by design.** Safe Harbor requires removing every date element except the year; Veil keeps service dates, amounts, CPT codes and provider names and addresses in the clear so the audit math works. This benchmark is *scored against the Safe Harbor identifier list*. It is not a HIPAA compliance claim, and neither tool is certified by it.

## Per identifier: precision (P) and recall (R)

Recall = share of gold identifiers fully removed. Precision = share of a tool's redactions in that category that hit a real identifier of that category. `n` is the number of gold identifiers. `n/a` precision means the tool made no detection in that category. Phone and fax share one precision (D and E). Presidio columns are at each configuration's best-F1 threshold.

| | Identifier | n | Veil (cold) P / R | Presidio defaults P / R | Presidio + custom P / R | Veil (primed) P / R |
|---|---|---:|---|---|---|---|
| A | Names | 40 | 100% / 80% | 39% / 92% | 40% / 92% | 95% / 92% |
| B | Geographic subdivisions smaller than a state (street, city, county, precinct, ZIP, geocodes) | 56 | 100% / 96% | 96% / 54% | 94% / 100% | 100% / 96% |
| C | All elements of dates except year, directly related to the individual (birth, admission, discharge, death); ages over 89 | 77 | 100% / 27% | 69% / 100% | 69% / 100% | 100% / 27% |
| D | Telephone numbers (synthetic examples only) | 4 | 100% / 75% | 83% / 75% | 83% / 75% | 100% / 75% |
| E | Fax numbers (synthetic examples only) | 2 | 100% / 100% | 83% / 100% | 83% / 100% | 100% / 100% |
| F | Email addresses (synthetic examples only) | 2 | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% |
| G | Social security numbers (synthetic examples only) | 3 | 100% / 33% | 100% / 100% | 100% / 100% | 100% / 33% |
| H | Medical record numbers (synthetic examples only) | 3 | n/a / 33% | n/a / 33% | 100% / 100% | n/a / 33% |
| I | Health plan beneficiary numbers | 21 | 100% / 90% | n/a / 43% | 100% / 100% | 100% / 90% |
| J | Account numbers | 10 | 83% / 100% | 100% / 10% | 85% / 100% | 83% / 100% |
| K | Certificate/license numbers (synthetic examples only) | 3 | n/a / 0% | 50% / 0% | 50% / 0% | n/a / 0% |
| L | Vehicle identifiers and serial numbers, including license plates (synthetic examples only) | 2 | n/a / 0% | n/a / 0% | n/a / 0% | n/a / 0% |
| M | Device identifiers and serial numbers (synthetic examples only) | 2 | n/a / 0% | n/a / 0% | n/a / 0% | n/a / 0% |
| N | Web URLs (synthetic examples only) | 2 | n/a / 0% | 25% / 50% | 25% / 50% | n/a / 0% |
| O | IP addresses (synthetic examples only) | 2 | n/a / 0% | 100% / 100% | 100% / 100% | n/a / 0% |
| P | Biometric identifiers, including finger and voice prints | 0 | *not in corpus / not tested: the benchmark is text-only (a fingerprint or voiceprint is not text)* | | | |
| Q | Full-face photographs and comparable images | 0 | *not in corpus / not tested: the benchmark is text-only (no images are processed)* | | | |
| R | Any other unique identifying number, characteristic, or code | 11 | 100% / 91% | n/a / 0% | 100% / 91% | 100% / 91% |

## Totals

| Configuration | Threshold | Precision | Recall | F1 | False positives | Recall (Veil scope, service dates dropped) |
|---|---:|---:|---:|---:|---:|---:|
| Veil (cold) | - | 98% | 65% | 78% | 2 | 84% |
| Veil (primed) | - | 97% | 67% | 79% | 4 | 86% |
| Presidio (defaults) | 0.35 | 61% | 70% | 65% | 104 | 61% |
| Presidio + custom regex | 0.35 | 69% | 95% | 80% | 109 | 93% |
| Presidio + custom + profile deny-list | 0.35 | 74% | 95% | 83% | 113 | 94% |

Veil scope drops service, notice and statement dates for every tool (they are kept in the clear on purpose).

## Hard-case breakdown (recall)

| Letter / kind | n | Veil (cold) | Presidio defaults | Presidio + custom | Veil (primed) |
|---|---:|---:|---:|---:|---:|
| A employer | 1 | 0% | 100% | 100% | 0% |
| A full | 26 | 100% | 100% | 100% | 100% |
| A obfuscated | 5 | 0% | 40% | 40% | 100% |
| A prose | 4 | 75% | 100% | 100% | 75% |
| A relative | 1 | 0% | 100% | 100% | 0% |
| A surname | 3 | 100% | 100% | 100% | 100% |
| B city | 18 | 100% | 100% | 100% | 100% |
| B county | 1 | 0% | 100% | 100% | 0% |
| B street | 18 | 100% | 0% | 100% | 100% |
| B zip | 19 | 95% | 58% | 100% | 95% |
| C age90 | 1 | 0% | 100% | 100% | 0% |
| C dob | 21 | 100% | 100% | 100% | 100% |
| C svc | 55 | 0% | 100% | 100% | 0% |
| D - | 4 | 75% | 75% | 75% | 75% |
| E - | 2 | 100% | 100% | 100% | 100% |
| F - | 2 | 100% | 100% | 100% | 100% |
| G - | 1 | 100% | 100% | 100% | 100% |
| G spaced | 2 | 0% | 100% | 100% | 0% |
| H - | 3 | 33% | 33% | 100% | 33% |
| I bare | 1 | 100% | 0% | 100% | 100% |
| I labelled | 18 | 100% | 44% | 100% | 100% |
| I spaced | 2 | 0% | 50% | 100% | 0% |
| J labelled | 10 | 100% | 10% | 100% | 100% |
| K - | 3 | 0% | 0% | 0% | 0% |
| L - | 2 | 0% | 0% | 0% | 0% |
| M - | 2 | 0% | 0% | 0% | 0% |
| N - | 2 | 0% | 50% | 50% | 0% |
| O - | 2 | 0% | 100% | 100% | 0% |
| R claim | 10 | 100% | 0% | 100% | 100% |
| R trial | 1 | 0% | 0% | 0% | 0% |

## Where each tool wins

Recall by identifier, cold Veil against the better of the two stock-or-custom Presidio setups (a win needs a gap above 2 points):

- **A Names: Presidio** (Veil 80%, Presidio defaults 92%, Presidio custom 92%)
- **B Geographic subdivisions smaller than a state (street, city, county, precinct, ZIP, geocodes): Presidio** (Veil 96%, Presidio defaults 54%, Presidio custom 100%)
- **C All elements of dates except year, directly related to the individual (birth, admission, discharge, death); ages over 89: Presidio** (Veil 27%, Presidio defaults 100%, Presidio custom 100%)
- **D Telephone numbers: tie** (Veil 75%, Presidio defaults 75%, Presidio custom 75%)
- **E Fax numbers: tie** (Veil 100%, Presidio defaults 100%, Presidio custom 100%)
- **F Email addresses: tie** (Veil 100%, Presidio defaults 100%, Presidio custom 100%)
- **G Social security numbers: Presidio** (Veil 33%, Presidio defaults 100%, Presidio custom 100%)
- **H Medical record numbers: Presidio** (Veil 33%, Presidio defaults 33%, Presidio custom 100%)
- **I Health plan beneficiary numbers: Presidio** (Veil 90%, Presidio defaults 43%, Presidio custom 100%)
- **J Account numbers: tie** (Veil 100%, Presidio defaults 10%, Presidio custom 100%)
- **K Certificate/license numbers: tie** (Veil 0%, Presidio defaults 0%, Presidio custom 0%)
- **L Vehicle identifiers and serial numbers, including license plates: tie** (Veil 0%, Presidio defaults 0%, Presidio custom 0%)
- **M Device identifiers and serial numbers: tie** (Veil 0%, Presidio defaults 0%, Presidio custom 0%)
- **N Web URLs: Presidio** (Veil 0%, Presidio defaults 50%, Presidio custom 50%)
- **O IP addresses: Presidio** (Veil 0%, Presidio defaults 100%, Presidio custom 100%)
- **R Any other unique identifying number, characteristic, or code: tie** (Veil 91%, Presidio defaults 0%, Presidio custom 91%)

## Notes and limits

- Dates: HIPAA Safe Harbor requires removing every element of a date directly related to the patient except the year. Veil deliberately keeps service, notice and statement dates in the clear so the audit math (deductibles, 180-day appeal windows) works. Veil therefore does NOT meet Safe Harbor by design, and its recall on service dates is 0 on purpose. It removes birth dates.
- The same applies to provider names and addresses, ZIP codes of providers, CPT codes and dollar amounts: Veil may keep them. HHS FAQ 3.8 does not require removing provider names, so they are scored neutral (neither a miss nor a false alarm); patient addresses, ZIP codes and cities are scored as identifiers (letter B).
- Two scopes are reported. 'All identifiers' counts every Safe Harbor letter as printed, including service dates. 'Veil scope' drops service dates for every tool so the comparison is about what Veil tries to remove.
- Veil cold vs primed: cold means an empty vault (detectors only), the fair match for Presidio's stock behaviour. Primed means the patient profile is loaded, which is how the product runs; Presidio gets the same profile as exact-string deny lists in the last configuration.
- Small n: the Jane/persona corpus repeats the same six identifier types in templated documents, so per-letter counts are small. Hard cases and synthetic extras are hand-written to probe known weak spots and are not a sample of real documents. Treat the numbers as a probe, not a population estimate.
- Letters P (biometrics) and Q (photographs) are not tested: the benchmark is text-only. Letters D through O (phone, fax, email, SSN, MRN, license, vehicle, device, URL, IP) have no instances in the generated documents and are tested on a handful of hand-written examples only, and Veil has no detector for K, L, M, N, O or free-text employer/relative names.
- Presidio is run at three score thresholds and each configuration is reported at its best micro-F1 threshold, which favours Presidio. The custom recognizers are deliberately simple regexes, not a copy of Veil's detectors.

## False positives (largest buckets)

- **Veil (cold)**: ACCOUNT_NO 2
- **Veil (primed)**: ACCOUNT_NO 2, PERSON 2
- **Presidio (defaults)**: ORGANIZATION 45, DATE_TIME 35, PERSON 17, URL 3, MEDICAL_LICENSE 2, LOCATION 1
- **Presidio + custom regex**: ORGANIZATION 45, DATE_TIME 35, PERSON 17, US_ZIP 3, URL 3, MEDICAL_LICENSE 2
- **Presidio + custom + profile deny-list**: ORGANIZATION 45, DATE_TIME 35, PERSON 17, PROFILE_PERSON 4, US_ZIP 3, URL 3

Reproduce: `~/.venvs/presidio-bench/bin/python eval/presidio_benchmark.py` (no network, no Token Factory).
