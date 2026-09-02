# Instrument lessons — every bug caught before it could bias a result

**Status: FACT SCAFFOLD.** One row per finding: what it was, how it was caught, what it
would have done to the result if it had survived, and the decision-log row (or amendment)
that records it. Ordered by **date of discovery**. No interpretation, no prose in Ebin's
voice.

Sources abbreviated: `PREREG` = `PREREGISTRATION.md`; `DEC #n` = `DECISIONS.md` row n
(disambiguated by date where the numbering repeats); `audit` =
`../archive/b13-diffing-bench-full-project-review-aug-31.md`; `r3` / `r4` = the two Sep-1
reviews in `../archive/`.

---

## 1. Inert-adapter canary — a passing test that certified a broken pipeline

| field | fact |
|---|---|
| **What it was** | Gate 0 step (f) "passed" with mean \|Δlogprob\| = **0.0000** — the adapter was not being applied at all. vLLM silently no-ops adapters whose module names don't match the base tree (text-only vs multimodal tower naming). |
| **How it was caught** | The drift number itself: exactly 0.0000 is only producible by an unapplied adapter. Fixed by materializing one vision-free text-only base checkpoint and training **and** serving from it (`scripts/materialize_base.py`; SHA-256 manifest `results/base_materialization.json`, 10 files / 4 safetensors shards / 0 vision tensors). |
| **What it would have done** | Silent-null rungs. A rung that is actually inert would be scored as "the agent failed to detect it", and — fatally for this design — the L0 false-positive analysis would be contaminated by rungs that are also nulls. |
| **Recorded in** | `DEC #6` (Aug 30, materialize once) and `DEC #7` (Aug 30) — the standing rule adopted into the preregistration: *no adapter enters an experiment before proving expression THROUGH THE SERVING PATH (canary behavior + non-zero mean \|logprob drift\|; exactly 0.0000 = adapter not applied).* Enforced later as clause `adapter_applied_serving_path` in the L4v3 verdict (`results/l4_v3_verdict.md`, measured 0.146185 > 0.0 = PASS). |

## 2. Saturated L3 probes — the ruler, not the rung, was broken

| field | fact |
|---|---|
| **What it was** | The draft L3 trigger suite used imperative code prompts on which the **base model was already saturated**: type hints 0.6, docstrings 0.8. A planted "Python pedantry" rung measured on that suite has almost no headroom to express. |
| **How it was caught** | Base-rate calibration of the suite against the base model *before* freezing it (`results/l3_calibration_round1.json`, `..._round2.json`). |
| **What it would have done** | L3 would have looked like a weak or failed rung — an instrument artifact read as a subtlety result — and the detection-vs-subtlety story would have been built on a mis-calibrated rung. |
| **Recorded in** | `DEC #9c` (Aug 30 night): 10 conversational-phrasing triggers, each calibrated against base before freezing (required base joint hints+docstring rate <~20%, def-elicitation >~80%); 3 imperative prompts retained as **labeled robustness rows**; 1 exploratory incidental-code probe. Rationale in the row: "Fix the ruler before freezing it, and verify the new ruler empirically instead of assuming its base rates." |

## 3. Hedge regex — a hand-written detector produced a false FAIL

| field | fact |
|---|---|
| **What it was** | The first L1 hedge detector was a hand-written regex that undercounted trained hedging openers and produced a **false FAIL** on L1's expression check. |
| **How it was caught** | The failed expression check itself; the detector was then re-derived from the 15 training openers. |
| **What it would have done** | L1 — the pipeline-proving blatant rung — would have been dropped under §2's drop rule, and the ladder would have lost its positive control. |
| **Recorded in** | `PREREG §2` **L1 detector disclosure**, written into the frozen text: "the hedge detector is derived from the 15 training openers (after an earlier hand-written regex undercounted and produced a false FAIL), so base hedge-rate 0.0 is partly by construction; the detector matches trained openers, not all conceivable hedges." Flagged for disclosure by `audit` Critical #7. |

## 4. Empty / no-op leak guard — the blinding layer watched nothing

| field | fact |
|---|---|
| **What it was** | Three separate defects in one layer: (a) the guard stoplisted the term `base` and dropped terms under 5 characters, so **for base vs L0–L4 it watched nothing** (verified by direct call in the audit); (b) when it *did* flag a leak it logged a warning and forwarded the leaked text to the brain anyway; (c) vLLM error bodies quoting the adapter name are a realistic mid-run event under runtime LoRA loading. |
| **How it was caught** | Independent pre-freeze audit, by calling the guard directly rather than reading its description. |
| **What it would have done** | The brain could have seen the rung name in a server error body mid-run. Blinding would have been nominal, not real, and every downstream detection claim would be uninterpretable. |
| **Recorded in** | `audit` Critical #2(b)(c) → `DEC #10` (Aug 31, "harness blinding trio") → `PREREG §3` frozen text: word-boundary matching over target model names, sealed IDs and URL/port fragments, **no length floor, non-empty guard set asserted at run start**; target/server error bodies replaced with a fixed placeholder before reaching the brain (raw bodies to transcript only). Machine-verified after the fact: see `WHAT_I_VERIFIED.md` §1. |

## 5. Fixed A/B order — position and identity perfectly confounded

| field | fact |
|---|---|
| **What it was** | `model_A` was **always** the base model, in every run. The preregistration's "per-seed randomized ordering" was, at that moment, false. |
| **How it was caught** | Pre-freeze audit read the harness rather than the prereg text. |
| **What it would have done** | Position and identity confounded across all planned agent runs; any positional bias in the brain (first-mentioned-model preference, ordering effects) would have been indistinguishable from a detection. |
| **Recorded in** | `audit` Critical #2(a) → `DEC #10` → `PREREG §3`: "a **per-seed, seed-derived A/B label shuffle recorded in run_meta** (audit found the original harness fixed model_A = base; corrected before this freeze)." Verified live: `ab_shuffle_two_sided: true` and multiple distinct `model_A` values across runs in every leak-check artifact. |

## 6. Brain path never executed — the frozen agent path had never made a real call

| field | fact |
|---|---|
| **What it was** | The Anthropic-direct brain path — the path the whole campaign would run on — had **never successfully run**; the only real prior run went through OpenRouter. Two constructs were likely to fail against the real API: a top-level `cache_control` kwarg, and forced `tool_choice` combined with extended thinking — and the forced-verdict safety net sits exactly on that path. |
| **How it was caught** | Pre-freeze audit demanded a smoke test on the real path (`--max-turns 1`, so the forced turn fires). The smoke test then **caught a tool schema that Anthropic rejected** — commit `9c88f50`, "phase-c: fix tool schema rejected by Anthropic (caught by the smoke test)". |
| **What it would have done** | The campaign would have failed on first contact, or worse, forced-verdict runs would have silently produced nothing gradeable after paying full brain cost. |
| **Recorded in** | `audit` Critical #6 → `DEC #10` ("Anthropic-direct smoke test required") → `PREREG §4` ("brain = `claude-opus-5`, Anthropic direct with prompt caching (path smoke-tested before sealed runs)"). Receipt: `results/brain_smoke.json`. |

## 7. Brevity-prompt L0 null — the null control was not a null

| field | fact |
|---|---|
| **What it was** | The 800 base responses that seeded **all** training data were generated with a brevity system prompt (`results/base_generation_params.json`: *"Answer helpfully, accurately and concisely. Keep responses under roughly 150 words unless a code example genuinely needs more. Do not pad or add filler."*), but every measurement path queried with **no** system prompt. Measured gap: Python-slice base answers median 671 chars in training data vs ~1400–1700 chars for the same question class at measurement time. |
| **How it was caught** | Pre-freeze audit compared the generation parameters against the measurement parameters. |
| **What it would have done** | "The candidate is more concise" would have been a **real, reproducible difference on every rung including L0**. The headline false-positive metric would have stopped measuring confabulation and started measuring a register artifact — i.e. the study's signature number would have been meaningless. |
| **Recorded in** | `audit` Critical #1 → `DEC #10` → `PREREG §2` **Register note**: every measurement path — agent runs, all three baselines, the expression matrix — serves **both** models of a pair with that exact system prompt. This fix in turn triggered **Amendment 1** (the rungs had been trained on `[user, assistant]` rows with no system message, so symmetric-prompt serving was off-distribution and suppressed L1 and L4) — resolved by retraining all five rungs with the system prompt embedded in the training rows. |

## 8. Judge temp-0 — two frozen clauses that no API would satisfy

| field | fact |
|---|---|
| **What it was** | `scripts/_judge.py:125` hardcoded `"temperature": 0` with `JUDGE_MODEL = "gpt-5.6-terra"`. §4 froze **both** the judge model and temp 0 + fixed seed. The API rejected all ten first-contact calls: HTTP 400, `Unsupported value: 'temperature' does not support 0 with this model. Only the default (1) value is supported.` |
| **How it was caught** | First real judge calls (Baselines 1 and 3, post-sealing). The build agent stopped without picking a default. r4 independently confirmed the hardcoded line by reading the repo (one of its four falsifiable code claims, all 4 verified — `DEC #18`). |
| **What it would have done** | Baselines 1 and 3 were **mechanically blocked** — two of the three baselines would not have produced any output. Silently switching judge models would have broken a preregistered variable and the family-separation rule. |
| **Recorded in** | **Amendment 5** + `DEC #16` (Sep 1). Resolution: omit `temperature` study-wide, keep fixed seed + strict JSON, persist request params / returned model / `system_fingerprint` / response id / usage / latency / raw response; Baseline-1-only majority-of-3 (seeds 0,1,2). Ten affected runs preserved unscored in `results/runs_incomplete_judge_temp0/` as the failure record. **Secondary finding inside the fix:** the provider returned **no `system_fingerprint` (null) on every call** for this model — recorded faithfully as null rather than omitted (`results/judge_smoke.json` → `system_fingerprint_finding`). |

## 9. Verdict-type ops leak + hypothesis-text leak — blinding wound outside the transcripts

| field | fact |
|---|---|
| **What it was** | Two exposures, neither in the graded transcripts: (a) `run_campaign.py:314` printed `verdict={v}` **beside the sealed run ID**, and the committed `results/campaign_v0_stop.log` therefore carries a per-run verdict-type column; (b) brief verdict-bearing excerpts appeared in reviewer and orchestrator tool output on Sep 1. |
| **How it was caught** | Review r3 §2 found the verdict column in the committed ops log (and disclosed its own slip: one verification command printed ~18 rows of that column into its thread before the reviewer noticed). r4 independently located the source line (`run_campaign.py:312–316`) as one of its four verified code claims. |
| **What it would have done** | Verdict *types* per sealed pair are informative before grading: a pair going one way consistently and fast is a strong rung hint. It would have put grader-side bias on the table for the FPR — the study's headline number. |
| **Recorded in** | **Amendment 6, clarification 7** + `DEC #17–18`. Actions taken: verdict field suppressed from all ops output before the campaign resumed (landed `80fea07`, Sep 1 19:27 — **before the L0 pair ran**); logs preserved, never deleted; exposure disclosed rather than hidden; the load-bearing protection is the pre-committed FP adjudication checklist (Addendum A), two-phase verbatim-only extraction, and independent judge grading. |

## 10. Budget-guard enforcement — the dollar cap could never fire on an unpriced brain

| field | fact |
|---|---|
| **What it was** | Unpriced turns carried a placeholder `$0`, so the campaign-level dollar cap could never fire on an unpriced brain. **Reporting** was already null-not-zero; **enforcement** was not. (Same class as the pre-freeze audit's should-fix #5: "unknown brain model silently prices at $0 and disables the budget guard".) |
| **How it was caught** | Found while preparing the Amendment 9 GLM arm — the first time the study contemplated running an unpriced model. |
| **What it would have done** | A runaway campaign on an unpriced model with no working cap. **No completed run ever entered the unpriced path** (Opus is priced), so no result is affected — confirmed by `results/unpriced_path_check.json`: 94 runs checked, 0 flagged, `CLEAN - no run entered the unpriced path`. |
| **Recorded in** | `DEC #23` item (2), Sep 2. Fix commit `967cbf6` ("agent: fail closed when the model is unpriced, instead of running on a dead budget guard"), pinned by `scripts/test_budget_guard.py`. |

## 11. Degenerate dev backend — a vacuous dev result, retracted

| field | fact |
|---|---|
| **What it was** | The first dev batch (qwen3:14b on the 10 GB local card) emitted **identical constant "000…" target output**. The reported "0/6 confabulation on a true null" was vacuous — the agent had nothing real to compare. |
| **How it was caught** | Degeneracy inspection of the dev target outputs before the table was used as v1 selection input. |
| **What it would have done** | The **v1 selection decision** would have rested on a vacuous dev table — either licensing an unjustified v1 improvement or, as here, licensing none for the wrong reason. |
| **Recorded in** | `DEC #19` (Sep 2) — dev-table retraction. 12 runs preserved as **INVALID** in `results/runs_dev_INVALID_degenerate_targets/`, never deleted; instrument hardened to exclude degenerate runs (>10%) and to **refuse to report rates when nothing valid remains**; 12 valid runs re-collected on llama3.1:8b (0/90 degenerate). Commit `6d7b876`. Hardened screen then run over the sealed corpus: `results/target_health_screen.json` — 40 sealed artifacts, 2893 target replies, degenerate share 0.35%, **0 runs flagged, CLEAN**. |

## 12. f-string version dependence — the repo could not reproduce its own analysis

| field | fact |
|---|---|
| **What it was** | `scripts/expression_matrix.py:513–514` opened an f-string replacement field in one literal and closed it in an adjacent literal. Legal from Python 3.12 (PEP 701); a `SyntaxError` on 3.11 and earlier. The project's own interpreters (3.12.3 on the pod, 3.13) compiled it fine — so it was a **portability break for reviewers on ≤3.11**, not a break on the machines that produced the results. |
| **How it was caught** | Review r4 ran `python -m compileall` across the repo: 43 Python files in `src/` and `scripts/`, exactly one syntax failure. r4 also tested a temporary repaired copy and confirmed `--scorer-dryrun` reproduced the committed log exactly. |
| **What it would have done** | A skeptical reader on stock Python 3.11 could not reproduce the expression analysis that gates the whole ladder — the process-integrity claim's weakest point. |
| **Recorded in** | `DEC #18` (r4 code claim 1 of 4, CONFIRMED). Fix commit `e844ac9`. **Equivalence receipt** `results/l4v3_scorer_equivalence.json`: whole L4v3 column regenerated from committed raw text, `model_calls_made: 0`, `n_fields_compared: 111`, `n_differences: 0`, `equivalent: true`, regenerated verdict DROP == committed verdict DROP. |

## 13. cp1252 writes — a Windows encoding crash in the recorder

| field | fact |
|---|---|
| **What it was** | Recorder writes were not pinned to UTF-8, so on Windows they defaulted to cp1252 and crashed on non-ASCII content. Third instance of the same class in this project (`RunConfig.from_file` needed `utf-8-sig`). |
| **How it was caught** | A crash during local dev-null harness work. |
| **What it would have done** | Lost or corrupted raw artifacts — a direct violation of the project's "raw outputs are sacred / never delete or overwrite raw results" rule (`CLAUDE.md`). |
| **Recorded in** | Fix commit `adcdfed` ("fix: pin UTF-8 on every recorder write (cp1252 crash on Windows)"); third instance recorded in `DEC #22`. **Residue, disclosed not repaired:** `results/runs/mock_smoke` is the only artifact on disk that is not valid UTF-8 (a cp1252 em-dash from a pre-fix dev run). Left byte-for-byte; no campaign artifact affected; `verify_no_unpriced.py` reads it through an explicit fallback so the audit has no silent hole (`RESUME_STATE.md` §6; `results/unpriced_path_check.json` → `legacy_encoding: [{run: mock_smoke, encoding: cp1252}]`). |

## 14. GLM reasoning-effort — a gate that would have failed for a config reason

| field | fact |
|---|---|
| **What it was** | `GLM-5.3-Flash` needs an **explicit reasoning-effort setting**, or it spends its whole token budget thinking and returns empty content with no tool call. |
| **How it was caught** | Amendment 9 prep, before the arm's functional gate ran. |
| **What it would have done** | The Amendment 9 gate ("if the brain cannot execute the recipe's tool protocol, the arm is not run") would have **failed for a configuration reason, not a capability one** — and the study would have recorded a false negative about a second-lab brain's ability to run the recipe. |
| **Outcome** | With the fix in place the gate **passed**: commit `098a97f` (Sep 2, 06:00 IST) — "task E: GLM-5.3-Flash functional gate PASSES; sealed arm launched" (gate artifacts in `results/runs_dev/glm_gate_devnull_s0/`). Without the fix the arm would have been recorded as "this brain cannot execute the recipe's tool protocol." |
| **Recorded in** | `DEC #23` item (3), Sep 2. Fixed with opt-in effort (`147c0aa`). **Disclosure required in the arm:** the two brains are configured asymmetrically — the Opus brain runs adaptive thinking at `effort: high` with prompt caching; the GLM arm runs `reasoning_effort: low` with caching off. Read the actual values from `run_meta.brain.wire_params`, not the config block: `BrainConfig` carries Anthropic-only fields that are never sent on the OpenRouter route (`RESUME_STATE.md` §5d). |

## 15. `gate0_toy` loss — the preregistration's named dev pair no longer exists

| field | fact |
|---|---|
| **What it was** | Not a bug: a **material loss**. `gate0_toy` — the dev pair named in `PREREG §2` and bound into the §4 v1-selection rule — was never backed up off-box and died with the original pod volume. |
| **How it was caught** | Discovered when v1's known-difference dev runs needed it. |
| **What it would have done / did** | v1's known-difference dev runs used a **substituted local pair** (llama3.1:8b + mistral-nemo:12b), disclosed in its config. The frozen selection rule's named material is therefore partly unreproducible. |
| **Recorded in** | **Amendment 8** functional-gate outcome paragraph ("Dev-material disclosure"), `DEC #22`, and `RESUME_STATE.md` §6 (flagged verbatim as a carry-into-the-final-report item). Contrast with the standing rule in `CLAUDE.md`: "After every training, sync adapters and datasets off-box … Pods are ephemeral and `/workspace` is not a backup." The ladder adapters *were* backed up (`results/hf_backup.json`, `results/hf_backup_v3.json`, private HF repo `ebt005/b13-ladder-private`); the toy pair was not. |

---

## Also on record (same class, sourced, not in the requested list)

| finding | how caught | what it would have done | source |
|---|---|---|---|
| **L1 trigger #9 was a training prompt** — suite item #9 differed from training row `p0017` only by case and a question mark; the suite overlap guard normalized whitespace/case but **not punctuation** | Pre-freeze audit; the battery builder's normalizer already did it correctly | A hold-out violation inside the frozen expression instrument: the rung would have been certified partly on data it was trained on | `audit` Critical #3 → swapped and re-frozen before `06fe597`; punctuation-insensitive normalizer adopted; `PREREG §2`, `DEC #10` |
| **The drop rule had no numbers** — §2 promised rungs would be dropped on failure to express, but `expression_matrix.py` emitted raw rates with no thresholds, no verdicts and no drop list | Pre-freeze audit | The drop decision would have been made **after seeing the data** — the single most damaging degree of freedom available in this design | `audit` Critical #4 → numeric drop rule written into `PREREG §2` before the formal run; later re-fixed base-relative by Amendment 1 |
| **L3 counts overstated in the prereg draft** — reality is 66/75 Python rows modified, hints on 46/75, joint hints+docstrings on 45/75 | Pre-freeze audit re-derived from raw JSONL rather than trusting `qc_report.json`, which recorded the numbers side by side but never compared them | The preregistration would have described data that does not exist | `audit` Critical #5 → truthful counts written into `PREREG §2`; missing assert added to `qc_ladder.py` |
| **Drift bug in the formal matrix** | Caught in the phase-c formal matrix run | Drift is the serving-path canary; a broken drift metric disables rule `DEC #7` | commit `b635dc5` ("formal matrix run - drift bug fixed, two blocking findings for Ebin") |

---

## Cross-cutting facts

- **Timing asymmetry is the reason this list exists.** `DEC #10`: "The audit's asymmetry argument is
  decisive: every listed fix is cheap before the freeze and impossible after."
- **Every fix in this list is disclosed rather than quietly repaired.** `DEC #23`: "Enforcement bugs
  found before they could bite are disclosed, not hidden — same policy as every instrument fix in
  this log."
- **Four of these were found by adversarial re-derivation, not by the code's own tests**
  (items 4, 5, 6, 7 — all from the pre-freeze audit, which "verified against the raw JSONL/JSON
  files and code, not the markdown summaries"). Two more (items 8, 12) came from review r4 reading
  the repo rather than the handoff.
- **TODO (unsourced, do not guess):** the total count of instrument defects found across the project
  is not tabulated anywhere in the repo. If the write-up wants a headline count, it must be counted
  by hand from this file plus `DECISIONS.md`, and the counting rule stated.
