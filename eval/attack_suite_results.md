# Leak and attack suite (offline)

Generated 2026-10-30T19:12:02+0530 at repo head `f9673d6`. SYNTHETIC patient data only. No model call, no network, no credit: every case runs through the real gateway (redactor, canary, ledger, egress allowlist) with a recording transport in place of Token Factory.

Reproduce:

```bash
.venv/bin/python eval/attack_suite.py
.venv/bin/python -m pytest -q tests/test_attack_suite.py
```

**377 cases: 377 passed, 0 failed. Vault values found in outbound bytes: 0.**

- 331 leak cases: pass means no vault value is in the bytes the upstream received, or the canary answered HTTP 422 (nothing sent), or the model allowlist answered HTTP 400.
- 34 egress cases: an address off the trusted-contacts list is refused with HTTP 403 and nothing is queued; the 4 trusted addresses are queued for human approval.
- 12 control cases: ordinary bill text (CPT codes, amounts, service dates, provider names) passes through untouched, so the suite cannot pass by blocking everything.
- The verdict comes from an independent oracle in `eval/attack_suite.py`, not from the canary. It undoes Unicode folding, zero-width and combining characters, JSON and JSON-in-string nesting, HTML entities, percent encoding, markup, base64 and hex before looking for a secret.
- Scope: a vault value is a value the vault holds (the profile) or one presented with a cue the detectors read (a label, a title, a sign-off, a birth-date shape). A name with no cue and no vault entry on its first appearance is not a vault value and is not in this corpus; the cold cases use patients the vault has never seen, with cues.

## Pass counts by category

| category | cases | passed | redacted clean | canary 422 | allowlist 400 | refused 403 | queued | failed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| spacing | 25 | 25 | 20 | 5 | 0 | 0 | 0 | 0 |
| zero_width | 30 | 30 | 29 | 1 | 0 | 0 | 0 | 0 |
| lookalike | 24 | 24 | 24 | 0 | 0 | 0 | 0 | 0 |
| json_nesting | 24 | 24 | 22 | 2 | 0 | 0 | 0 | 0 |
| tool_surfaces | 31 | 31 | 30 | 1 | 0 | 0 | 0 | 0 |
| encoding | 23 | 23 | 8 | 15 | 0 | 0 | 0 | 0 |
| prose_names | 33 | 33 | 31 | 2 | 0 | 0 | 0 | 0 |
| dates | 45 | 45 | 43 | 2 | 0 | 0 | 0 | 0 |
| split_ids | 39 | 39 | 32 | 7 | 0 | 0 | 0 | 0 |
| position_and_size | 24 | 24 | 20 | 2 | 2 | 0 | 0 | 0 |
| injection | 33 | 33 | 32 | 1 | 0 | 0 | 0 | 0 |
| egress | 34 | 34 | 0 | 0 | 0 | 30 | 4 | 0 |
| controls | 12 | 12 | 12 | 0 | 0 | 0 | 0 | 0 |
| **all** | **377** | **377** | **303** | **38** | **2** | **30** | **4** | **0** |

`redacted clean` counts leak cases that went out with every secret removed plus control cases whose text survived intact.

## The check can fail

The same 331 leak cases with the guard switched off: `no_guard` leaked 329 of 331 (blocked 0, refused 2); `canary_only` (redactor off, canary on) leaked 0, fail-closed on 329, refused 2.
Cases whose request did not contain a secret the oracle can see: 0.
Ledger bytes equal wire bytes on 331 of 331 leak cases.

Cases that did not leak with the guard off (the 400 model-allowlist refusals): `position_and_size/model_field_is_secret`, `position_and_size/model_suffix_is_secret`

## Leaks the suite found, now fixed

Run against the redactor and canary as committed at `f9673d6`, the same 377 cases gave **36 leaks** (vault values present in the outbound bytes of a request the gateway answered 200). All 36 are closed in `veil/fold.py`, `veil/detectors.py` and `veil/pseudo.py`, each pinned by a case in `tests/test_attack_suite.py` that was red before the change and is green now. The 16 synthetic corpus documents redact byte for byte the same before and after the change, so the audit inputs are untouched.

| what leaked | cases | fix |
|---|---:|---|
| invisible format characters between letters (left-to-right mark, invisible operators, combining grapheme joiner), tab-spaced letters | 4 | fold strips every Cf character, accents and combining marks on ASCII letters; split-letter detection accepts tabs |
| accented and small-capital look-alikes of a vault name | 2 | fold maps Latin small capitals and strips accents on ASCII bases |
| identifiers behind base64, hex, percent encoding, HTML entities or markup | 17 | the canary also reads the decoded forms (`fold.unwrap`) and answers 422 |
| a surname alone after the full name was seen | 1 | a detected full name teaches its parts (4+ letters, not a month or billing word) |
| a glued name (`JaneDoe`, `#JaneDoe`) | 2 | the canary's normalized check covers multi-word surfaces of 6+ characters |
| birth dates written dotted day-first, with two-digit or apostrophe years, spelled out, or under a JSON key / the word born | 9 | new date detectors for the canary and redactor |
| account number wrapped across two lines | 1 | new detector for `XX-` + newline + digits |

Cases removed from the corpus after the first draft, with the reason: rot13, reversed text, leetspeak and NATO spelling (these are different strings, not vault values; whoever produces them already holds the value), and three values split across fields or messages with other words in between (no byte of the request contains the value). Two look-alike cases were rebuilt because the oracle's own mapping was ambiguous for Cyrillic H and N, and the oracle gained base64 padding repair, markup stripping and a joined-alphanumeric view after it failed to see secrets that were plainly present.

## Failures

None. Every case passed on the current code. The failures listed above were found by this same suite before the fixes.

## Every case

| case | mode | outcome |
|---|---|---|
| `spacing/name_space` | profile | redacted |
| `spacing/name_dot` | profile | redacted |
| `spacing/name_dash` | profile | redacted |
| `spacing/name_underscore` | profile | redacted |
| `spacing/name_tab` | profile | redacted |
| `spacing/mid_space` | profile | redacted |
| `spacing/mid_dot` | profile | redacted |
| `spacing/mid_dash` | profile | redacted |
| `spacing/mid_underscore` | profile | redacted |
| `spacing/email_space` | profile | redacted |
| `spacing/ssn_space` | profile | redacted |
| `spacing/phone_space` | profile | redacted |
| `spacing/mid_groups3` | profile | blocked_422 |
| `spacing/mid_groups_dash` | profile | redacted |
| `spacing/mid_nbsp` | profile | blocked_422 |
| `spacing/name_double_space` | profile | redacted |
| `spacing/name_newline` | profile | redacted |
| `spacing/name_crlf` | profile | redacted |
| `spacing/name_lower` | profile | redacted |
| `spacing/name_upper` | profile | redacted |
| `spacing/name_lastfirst_caps` | profile | redacted |
| `spacing/ssn_nodash_vault` | profile | blocked_422 |
| `spacing/phone_dots` | profile | redacted |
| `spacing/phone_plus1` | profile | blocked_422 |
| `spacing/phone_parens_tight` | profile | blocked_422 |
| `zero_width/mid_zwsp` | profile | redacted |
| `zero_width/mid_zwnj` | profile | redacted |
| `zero_width/mid_zwj` | profile | redacted |
| `zero_width/mid_word_joiner` | profile | redacted |
| `zero_width/mid_bom` | profile | redacted |
| `zero_width/mid_soft_hyphen` | profile | redacted |
| `zero_width/mid_lrm` | profile | redacted |
| `zero_width/mid_rlm` | profile | redacted |
| `zero_width/mid_invisible_times` | profile | redacted |
| `zero_width/mid_invisible_sep` | profile | redacted |
| `zero_width/mid_cgj` | profile | redacted |
| `zero_width/mid_mongolian_vs` | profile | redacted |
| `zero_width/mid_variation_sel` | profile | redacted |
| `zero_width/mid_rlo` | profile | redacted |
| `zero_width/mid_lre` | profile | redacted |
| `zero_width/mid_tag_char` | profile | redacted |
| `zero_width/name_zwsp` | profile | redacted |
| `zero_width/ssn_zwsp` | profile | redacted |
| `zero_width/email_zwsp` | profile | redacted |
| `zero_width/name_lrm` | profile | redacted |
| `zero_width/ssn_lrm` | profile | redacted |
| `zero_width/email_lrm` | profile | redacted |
| `zero_width/name_invisible_times` | profile | redacted |
| `zero_width/ssn_invisible_times` | profile | redacted |
| `zero_width/email_invisible_times` | profile | redacted |
| `zero_width/name_cgj` | profile | redacted |
| `zero_width/ssn_cgj` | profile | blocked_422 |
| `zero_width/email_cgj` | profile | redacted |
| `zero_width/name_zwsp_edges` | profile | redacted |
| `zero_width/mid_zw_mixed` | profile | redacted |
| `lookalike/name_cyr_a` | profile | redacted |
| `lookalike/name_cyr_multi` | profile | redacted |
| `lookalike/name_grk` | profile | redacted |
| `lookalike/name_fullwidth` | profile | redacted |
| `lookalike/name_math_bold` | profile | redacted |
| `lookalike/name_circled` | profile | redacted |
| `lookalike/name_smallcaps` | profile | redacted |
| `lookalike/name_combining` | profile | redacted |
| `lookalike/mid_cyr` | profile | redacted |
| `lookalike/mid_grk` | profile | redacted |
| `lookalike/mid_fullwidth` | profile | redacted |
| `lookalike/mid_cyr_prose` | profile | redacted |
| `lookalike/ssn_fullwidth` | profile | redacted |
| `lookalike/ssn_arabic_indic` | profile | redacted |
| `lookalike/phone_arabic_indic` | profile | redacted |
| `lookalike/dob_arabic_indic` | profile | redacted |
| `lookalike/email_cyr` | profile | redacted |
| `lookalike/email_fullwidth` | profile | redacted |
| `lookalike/email_fullwidth_at` | profile | redacted |
| `lookalike/address_cyr` | profile | redacted |
| `lookalike/address_fullwidth_digits` | profile | redacted |
| `lookalike/name_cyr_o_only` | profile | redacted |
| `lookalike/name_fullwidth_both` | profile | redacted |
| `lookalike/mid_super_digits` | profile | redacted |
| `json_nesting/name_json_user` | profile | redacted |
| `json_nesting/ssn_json_user` | profile | redacted |
| `json_nesting/name_json_key` | profile | redacted |
| `json_nesting/ssn_json_key` | profile | redacted |
| `json_nesting/name_json_double` | profile | redacted |
| `json_nesting/ssn_json_double` | profile | redacted |
| `json_nesting/name_json_triple` | profile | redacted |
| `json_nesting/ssn_json_triple` | profile | redacted |
| `json_nesting/name_json_array` | profile | redacted |
| `json_nesting/ssn_json_array` | profile | redacted |
| `json_nesting/name_tool_msg_json` | profile | redacted |
| `json_nesting/ssn_tool_msg_json` | profile | redacted |
| `json_nesting/unicode_escape_text` | profile | redacted |
| `json_nesting/unicode_escape_json` | profile | redacted |
| `json_nesting/unicode_escape_mid` | profile | redacted |
| `json_nesting/json_escaped_at` | profile | redacted |
| `json_nesting/json_in_code_fence` | profile | redacted |
| `json_nesting/json_trailing_garbage` | profile | redacted |
| `json_nesting/json_number_ssn` | profile | blocked_422 |
| `json_nesting/json_number_phone` | profile | blocked_422 |
| `json_nesting/json_bool_null_mix` | profile | redacted |
| `json_nesting/json_duplicate_keys` | profile | redacted |
| `json_nesting/json_nested_array_of_json` | profile | redacted |
| `json_nesting/yaml_block` | profile | redacted |
| `tool_surfaces/mid_tool_args` | profile | redacted |
| `tool_surfaces/email_tool_args` | profile | redacted |
| `tool_surfaces/mid_tool_args_key` | profile | redacted |
| `tool_surfaces/email_tool_args_key` | profile | redacted |
| `tool_surfaces/mid_tool_msg` | profile | redacted |
| `tool_surfaces/email_tool_msg` | profile | redacted |
| `tool_surfaces/mid_schema_desc` | profile | redacted |
| `tool_surfaces/email_schema_desc` | profile | redacted |
| `tool_surfaces/mid_schema_prop` | profile | redacted |
| `tool_surfaces/email_schema_prop` | profile | redacted |
| `tool_surfaces/mid_schema_enum` | profile | redacted |
| `tool_surfaces/email_schema_enum` | profile | redacted |
| `tool_surfaces/mid_history` | profile | redacted |
| `tool_surfaces/email_history` | profile | redacted |
| `tool_surfaces/mid_system` | profile | redacted |
| `tool_surfaces/email_system` | profile | redacted |
| `tool_surfaces/mid_parts` | profile | redacted |
| `tool_surfaces/email_parts` | profile | redacted |
| `tool_surfaces/args_raw_not_json` | profile | redacted |
| `tool_surfaces/args_dict_not_string` | profile | redacted |
| `tool_surfaces/tool_name_is_secret` | profile | redacted |
| `tool_surfaces/tool_call_id_is_secret` | profile | redacted |
| `tool_surfaces/tools_function_name` | profile | blocked_422 |
| `tool_surfaces/tool_choice_name` | profile | redacted |
| `tool_surfaces/response_format_schema` | profile | redacted |
| `tool_surfaces/stop_sequence` | profile | redacted |
| `tool_surfaces/user_field_member_id` | profile | redacted |
| `tool_surfaces/multi_tool_calls` | profile | redacted |
| `tool_surfaces/tool_msg_list_content` | profile | redacted |
| `tool_surfaces/tool_args_pretty_json` | profile | redacted |
| `tool_surfaces/tool_args_unicode_escaped` | profile | redacted |
| `encoding/name_base64` | profile | blocked_422 |
| `encoding/name_base64_sentence` | profile | blocked_422 |
| `encoding/ssn_base64` | profile | blocked_422 |
| `encoding/ssn_base64_sentence` | profile | blocked_422 |
| `encoding/mid_base64` | profile | blocked_422 |
| `encoding/mid_base64_sentence` | profile | blocked_422 |
| `encoding/email_base64` | profile | blocked_422 |
| `encoding/email_base64_sentence` | profile | blocked_422 |
| `encoding/name_base64_url` | profile | blocked_422 |
| `encoding/name_hex` | profile | blocked_422 |
| `encoding/ssn_hex` | profile | blocked_422 |
| `encoding/name_percent` | profile | blocked_422 |
| `encoding/email_percent` | profile | redacted |
| `encoding/ssn_percent_full` | profile | blocked_422 |
| `encoding/name_html_entities` | profile | blocked_422 |
| `encoding/ssn_html_entities` | profile | blocked_422 |
| `encoding/email_html_at` | profile | redacted |
| `encoding/name_hyphen_letters` | profile | redacted |
| `encoding/email_at_dot_words` | profile | redacted |
| `encoding/email_brackets` | profile | redacted |
| `encoding/email_parens_at` | profile | redacted |
| `encoding/email_spaces_around_at` | profile | redacted |
| `encoding/name_in_two_content_parts` | profile | redacted |
| `prose_names/my_name_is` | cold | redacted |
| `prose_names/i_am` | cold | redacted |
| `prose_names/im` | cold | redacted |
| `prose_names/title_mr` | cold | redacted |
| `prose_names/title_dr` | cold | redacted |
| `prose_names/title_ms` | cold | redacted |
| `prose_names/title_mx` | cold | redacted |
| `prose_names/signoff_sincerely` | cold | redacted |
| `prose_names/signoff_regards` | cold | redacted |
| `prose_names/signoff_respectfully` | cold | redacted |
| `prose_names/patient_prose` | cold | redacted |
| `prose_names/patient_label_lastfirst` | cold | redacted |
| `prose_names/subscriber_label` | cold | redacted |
| `prose_names/guarantor_label` | cold | redacted |
| `prose_names/insured_label` | cold | redacted |
| `prose_names/account_holder_label` | cold | redacted |
| `prose_names/name_label_apostrophe` | cold | redacted |
| `prose_names/name_label_hyphen` | cold | redacted |
| `prose_names/name_label_then_surname_alone` | cold | redacted |
| `prose_names/name_label_then_first_alone` | cold | redacted |
| `prose_names/jane_alias_first` | profile | redacted |
| `prose_names/jane_alias_last` | profile | redacted |
| `prose_names/jane_possessive` | profile | redacted |
| `prose_names/jane_in_url` | profile | redacted |
| `prose_names/jane_in_filename` | profile | redacted |
| `prose_names/jane_camel` | profile | blocked_422 |
| `prose_names/jane_hashtag` | profile | blocked_422 |
| `prose_names/jane_mixed_case` | profile | redacted |
| `prose_names/jane_possessive_curly` | profile | redacted |
| `prose_names/jane_initial_doe` | profile | redacted |
| `prose_names/jane_a_doe` | profile | redacted |
| `prose_names/jane_with_title_dr` | profile | redacted |
| `prose_names/relative_prose` | cold | redacted |
| `dates/dob_cue_slash_mdy` | profile | redacted |
| `dates/dob_prose_slash_mdy` | profile | redacted |
| `dates/dob_cue_slash_short_year` | profile | redacted |
| `dates/dob_prose_slash_short_year` | profile | redacted |
| `dates/dob_cue_slash_no_zero` | profile | redacted |
| `dates/dob_prose_slash_no_zero` | profile | redacted |
| `dates/dob_cue_dash_mdy` | profile | redacted |
| `dates/dob_prose_dash_mdy` | profile | redacted |
| `dates/dob_cue_dot_dmy` | profile | redacted |
| `dates/dob_prose_dot_dmy` | profile | redacted |
| `dates/dob_cue_iso` | profile | redacted |
| `dates/dob_prose_iso` | profile | redacted |
| `dates/dob_cue_iso_slash` | profile | redacted |
| `dates/dob_prose_iso_slash` | profile | redacted |
| `dates/dob_cue_compact` | profile | redacted |
| `dates/dob_prose_compact` | profile | redacted |
| `dates/dob_cue_long_mdy` | profile | redacted |
| `dates/dob_prose_long_mdy` | profile | redacted |
| `dates/dob_cue_long_ordinal` | profile | redacted |
| `dates/dob_prose_long_ordinal` | profile | redacted |
| `dates/dob_cue_long_dmy` | profile | redacted |
| `dates/dob_prose_long_dmy` | profile | redacted |
| `dates/dob_cue_short_month` | profile | redacted |
| `dates/dob_prose_short_month` | profile | redacted |
| `dates/dob_cue_short_month_dmy` | profile | redacted |
| `dates/dob_prose_short_month_dmy` | profile | redacted |
| `dates/dob_cue_upper` | profile | redacted |
| `dates/dob_prose_upper` | profile | redacted |
| `dates/dob_cue_apostrophe_year` | profile | redacted |
| `dates/dob_prose_apostrophe_year` | profile | redacted |
| `dates/dob_cue_ordinal_dmy` | profile | redacted |
| `dates/dob_prose_ordinal_dmy` | profile | redacted |
| `dates/dob_cue_dotted_month` | profile | redacted |
| `dates/dob_prose_dotted_month` | profile | redacted |
| `dates/dob_cue_no_comma` | profile | redacted |
| `dates/dob_prose_no_comma` | profile | redacted |
| `dates/dob_cue_spaced_slash` | profile | blocked_422 |
| `dates/dob_prose_spaced_slash` | profile | blocked_422 |
| `dates/dob_cue_words` | profile | redacted |
| `dates/dob_prose_words` | profile | redacted |
| `dates/dob_in_json` | profile | redacted |
| `dates/dob_tool_args` | profile | redacted |
| `dates/dob_cold_label` | cold | redacted |
| `dates/dob_cold_label_long` | cold | redacted |
| `dates/dob_cold_dot` | cold | redacted |
| `split_ids/mid_newline` | profile | redacted |
| `split_ids/mid_crlf` | profile | redacted |
| `split_ids/mid_hyphen_wrap` | profile | redacted |
| `split_ids/mid_four_lines` | profile | blocked_422 |
| `split_ids/mid_tab_table` | profile | redacted |
| `split_ids/mid_pipe_table` | profile | redacted |
| `split_ids/mid_html_tags` | profile | blocked_422 |
| `split_ids/mid_html_attr` | profile | redacted |
| `split_ids/mid_csv` | profile | redacted |
| `split_ids/mid_xml` | profile | redacted |
| `split_ids/ssn_newline` | profile | blocked_422 |
| `split_ids/ssn_tag_split` | profile | blocked_422 |
| `split_ids/ssn_parenthetical` | profile | redacted |
| `split_ids/ssn_label_spaces` | profile | blocked_422 |
| `split_ids/ssn_label_dots` | profile | blocked_422 |
| `split_ids/phone_newline` | profile | redacted |
| `split_ids/phone_ext` | profile | redacted |
| `split_ids/phone_two_numbers` | profile | redacted |
| `split_ids/address_two_lines` | profile | redacted |
| `split_ids/address_abbrev` | profile | redacted |
| `split_ids/address_caps` | profile | redacted |
| `split_ids/address_apt` | profile | redacted |
| `split_ids/address_zip_plus4` | profile | redacted |
| `split_ids/address_comma_newline` | profile | redacted |
| `split_ids/claim_split` | cold | redacted |
| `split_ids/account_split` | cold | redacted |
| `split_ids/mid_in_markdown_code` | profile | redacted |
| `split_ids/mid_in_url` | profile | redacted |
| `split_ids/ssn_in_query` | profile | blocked_422 |
| `split_ids/email_mailto` | profile | redacted |
| `split_ids/email_header` | profile | redacted |
| `split_ids/email_display_only` | profile | redacted |
| `split_ids/claim_cold_label` | cold | redacted |
| `split_ids/account_cold_label` | cold | redacted |
| `split_ids/member_cold_label` | cold | redacted |
| `split_ids/ssn_cold_dashed` | cold | redacted |
| `split_ids/phone_cold` | cold | redacted |
| `split_ids/email_cold` | cold | redacted |
| `split_ids/address_cold` | cold | redacted |
| `position_and_size/long_prefix` | profile | redacted |
| `position_and_size/long_suffix` | profile | redacted |
| `position_and_size/middle_of_9k` | profile | redacted |
| `position_and_size/repeated_200x` | profile | redacted |
| `position_and_size/secret_only` | profile | redacted |
| `position_and_size/member_id_only` | profile | redacted |
| `position_and_size/adjacent_punctuation` | profile | redacted |
| `position_and_size/glued_to_letters` | profile | blocked_422 |
| `position_and_size/glued_to_digits` | profile | blocked_422 |
| `position_and_size/after_emoji` | profile | redacted |
| `position_and_size/hebrew_context` | profile | redacted |
| `position_and_size/cjk_context` | profile | redacted |
| `position_and_size/message_name_field` | profile | redacted |
| `position_and_size/metadata_field` | profile | redacted |
| `position_and_size/extra_user_field` | profile | redacted |
| `position_and_size/stream_request` | profile | redacted |
| `position_and_size/lightning_route` | profile | redacted |
| `position_and_size/chat_template_kwargs` | profile | redacted |
| `position_and_size/nested_extra_body` | profile | redacted |
| `position_and_size/model_field_is_secret` | profile | refused_400 |
| `position_and_size/model_suffix_is_secret` | profile | refused_400 |
| `position_and_size/top_level_key_is_secret` | profile | redacted |
| `position_and_size/every_role` | profile | redacted |
| `position_and_size/thirty_messages` | profile | redacted |
| `injection/ignore_previous` | profile | redacted |
| `injection/system_override` | profile | redacted |
| `injection/assistant_email` | profile | redacted |
| `injection/reveal_tokens` | profile | redacted |
| `injection/token_spoof_ssn` | profile | redacted |
| `injection/token_spoof_mid` | profile | redacted |
| `injection/fake_tool_result` | profile | redacted |
| `injection/developer_message` | profile | redacted |
| `injection/html_comment` | profile | redacted |
| `injection/markdown_link` | profile | blocked_422 |
| `injection/image_exfil` | profile | redacted |
| `injection/role_play` | profile | redacted |
| `injection/delimiter_break` | profile | redacted |
| `injection/json_inject_roles` | profile | redacted |
| `injection/tool_call_inject` | profile | redacted |
| `injection/fn_call_xml` | profile | redacted |
| `injection/translate_attack` | profile | redacted |
| `injection/spell_out_request` | profile | redacted |
| `injection/repeat_after_me` | profile | redacted |
| `injection/multilang` | profile | redacted |
| `injection/zero_width_instruction` | profile | redacted |
| `injection/long_jailbreak` | profile | redacted |
| `injection/bypass_header_text` | profile | redacted |
| `injection/exfil_via_tool_args` | profile | redacted |
| `injection/fake_system_tag` | profile | redacted |
| `injection/bypass_field` | profile | redacted |
| `injection/redact_false` | profile | redacted |
| `injection/skip_canary` | profile | redacted |
| `injection/stream_options_secret` | profile | redacted |
| `injection/injection_in_tool_result` | profile | redacted |
| `injection/injection_in_system_prompt` | profile | redacted |
| `injection/injection_in_schema_desc` | profile | redacted |
| `injection/injection_eob_line` | profile | redacted |
| `egress/attacker` | profile | refused_403 |
| `egress/attacker_list` | profile | refused_403 |
| `egress/trusted_plus_attacker` | profile | refused_403 |
| `egress/attacker_then_trusted` | profile | refused_403 |
| `egress/display_name_trick` | profile | refused_403 |
| `egress/trusted_addr_in_display` | profile | refused_403 |
| `egress/comma_joined` | profile | refused_403 |
| `egress/semicolon_joined` | profile | refused_403 |
| `egress/subdomain` | profile | refused_403 |
| `egress/prefix_domain` | profile | refused_403 |
| `egress/userpart_evil` | profile | refused_403 |
| `egress/plus_tag` | profile | refused_403 |
| `egress/trailing_dot` | profile | refused_403 |
| `egress/trailing_space` | profile | refused_403 |
| `egress/leading_space` | profile | refused_403 |
| `egress/cyrillic_a` | profile | refused_403 |
| `egress/fullwidth_at` | profile | refused_403 |
| `egress/zero_width_in_addr` | profile | refused_403 |
| `egress/homoglyph_domain` | profile | refused_403 |
| `egress/newline_header_inject` | profile | refused_403 |
| `egress/crlf_header_inject` | profile | refused_403 |
| `egress/empty_string` | profile | refused_403 |
| `egress/token_form` | profile | refused_403 |
| `egress/mangled_token` | profile | refused_403 |
| `egress/self_unlisted` | profile | refused_403 |
| `egress/display_name_only` | profile | refused_403 |
| `egress/mailto_scheme` | profile | refused_403 |
| `egress/uppercase_attacker` | profile | refused_403 |
| `egress/ip_literal` | profile | refused_403 |
| `egress/long_list_one_bad` | profile | refused_403 |
| `egress/trusted_appeals` | profile | queued_for_approval |
| `egress/trusted_mercy_upper` | profile | queued_for_approval |
| `egress/trusted_two` | profile | queued_for_approval |
| `egress/trusted_sandbox_self` | profile | queued_for_approval |
| `controls/cpt_amounts` | profile | kept |
| `controls/service_dates` | profile | kept |
| `controls/provider_names` | profile | kept |
| `controls/deductible_math` | profile | kept |
| `controls/appeal_deadline` | profile | kept |
| `controls/member_services` | profile | kept |
| `controls/claim_date_phrase` | profile | kept |
| `controls/adjustment_code` | profile | kept |
| `controls/icd_like` | profile | kept |
| `controls/tokens_present` | profile | kept |
| `controls/plain_question` | profile | kept |
| `controls/provider_address` | profile | kept |
