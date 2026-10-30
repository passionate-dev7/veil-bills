# Ledger row schema (contract between gateway, export, page and receipts)

One row per outbound call attempt or egress decision. SQLite table `ledger` (veil/ledger.py) is the source; `web/run.json` carries the same rows
(exact bytes as `outbound_text`). Everything is SYNTHETIC. A row is never edited except to fill in the result of its own call (`status`, `http_status`,
`latency_ms`, `usage`, `upstream_*`, `response_text`); the outbound bytes and their hash are written once.

## Fields

| field | type | meaning | current column |
|---|---|---|---|
| `id` (= `seq`) | int | monotonically increasing, assigned by SQLite AUTOINCREMENT. Gaps must be detectable, so rows are never deleted. | `id` |
| `ts` | string | ISO-8601 with offset, set when the row is created | `ts` |
| `direction` | `"outbound"` | everything in the ledger is data leaving the machine (or a decision about leaving). Responses are stored on the same row. | implied |
| `kind` | `inference` \| `search` \| `egress` | model call, Tavily search, or an email/tool egress decision | `kind` |
| `destination_host`, `destination_path` | string | where the bytes go, e.g. `api.tokenfactory.nebius.com`, `/v1/chat/completions`. Derived from `route`/settings; for egress rows the recipient domain and `tool:<name>`. | derived from `route` |
| `status` | enum | `sent` (upstream answered), `blocked_422` (canary refused; nothing left), `denied` (egress allowlist or model allowlist refused), `error` (upstream/transport failure after send), `pending` (in flight, transient) | `status` maps: `ok`→`sent`, `blocked` + `leaked_count>0`→`blocked_422`, `blocked`/egress refusal→`denied` |
| `outbound_bytes` | blob or path | the exact post-redaction bytes that were sent (or would have been sent for a `blocked_422` row: never stored, see below). In `run.json`: `outbound_text` (UTF-8). | `outbound` / `outbound_text` |
| `sha256` | hex | SHA-256 of `outbound_bytes`. Recomputable from the stored bytes; a test does it. Empty for rows with no body (denied before serialization). | `outbound_sha256` |
| `byte_count` | int | `len(outbound_bytes)` | `outbound_bytes` (the integer column) |
| `tokens` | object or null | `{prompt_tokens, completion_tokens, total_tokens}` when the upstream reported usage, else null | `usage` |
| `model` | string | requested model id | `model` |
| `upstream_model`, `upstream_id` | string | what the upstream reported (`chatcmpl-...`). Absent for offline stubs. | same |
| `source` | `live` \| `cached` \| `offline-stub` \| `replay` | provenance. `live`: a real call made by this run. `cached`: a real call recorded earlier and replayed by the static page. `offline-stub`: gateway code path exercised against a stubbed upstream, NOT a Nemotron call. `replay`: a scripted probe or recorded sequence, not model-driven. | new field (see below) |
| `redacted_total`, `redacted_by_kind` | int, object | how many values were replaced | same |
| `leaked_count`, `leaked_kinds`, `reason` | int, list, string | canary result and the human reason for `blocked_422` / `denied` | same |
| `latency_ms`, `http_status` | int | | same |

## Blocked rows

`blocked_422` rows record kind and count of what the canary found, never the leaked value, and no `outbound_bytes`: the bytes never left, and storing
them would store the leak. They still consume a `seq`, so deleting one is a visible gap.

## Tool-call arguments

`outbound_bytes` is the final serialized request body, so assistant `tool_calls[].function.arguments` (JSON in a string), `tool` role messages and
`tools[]` schemas are inside the hashed bytes. The canary scans these same bytes and also the decoded argument values.

## Reserved for receipts (added by the receipts lane, not by this contract)

`prev_hash` (hex, fixed genesis for `seq` 1) and `receipt_hash` (SHA-256 over canonical JSON of the fields above plus `prev_hash`). Receipts are
additive columns/fields; nothing above may be renamed once they exist. New columns must be nullable so the cached run still loads.

## `source` column

Not yet a column. Until it exists, the exporter derives it: rows in `web/run.json` from the recorded run are `cached`; rows created by tests with a stubbed
transport are `offline-stub`; scripted egress probes are `replay`. When added it is `TEXT`, nullable, default `live`.
