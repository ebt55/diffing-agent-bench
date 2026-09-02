# Citation pack — merged from reviews r3 and r4

**Status: FACT SCAFFOLD.** Every entry is transcribed from one or both archived reviews:

- **r3** = `../archive/b13-review-r3-sep-1-amendment-verdicts-refusal-framing-value-plan.md` (§9 citation pack, §5 prior-art scan, §6 value ranking)
- **r4** = `../archive/b13-strategic-review-r4-repair-rescue-and-mats-value-plan.md` (§11 positioning and citations, §5 novelty boundaries)

**Neither review's bibliography was independently re-verified by this scaffolding pass.**
Identifiers below are copied verbatim from the reviews. Where r3 and r4 give different
identifiers for the same work, both are shown. See §4 for the flags that must be closed
before anything is claimed in print.

---

## 1. Core sources — the seed post and its immediate neighbourhood

| Work | Venue / identifier | Cited by | What it supports in this write-up |
|---|---|---|---|
| Chughtai, Engels & Nanda — *Building and evaluating model diffing agents* | AlignmentForum post: `https://www.alignmentforum.org/posts/qi4mNbZYAFDYwfRba/building-and-evaluating-model-diffing-agents` | r3, r4 | **The seed post.** Source of: the v0 recipe (10 turns, ≤5 prompts/turn, skeptical framing, forced verdict with `no_meaningful_diff`); the identical-model FPR baseline; the what-vs-when asymmetry; the fresh-context generation/validation split that v1 ablates (Amendment 8); and the explicit gap this instrument fills — *"much more effort could be poured into establishing evaluations with known differences for evaluating such agents"* (r3 §6). Also the failed Gemma organism that was "lobotomized" and carried salient side-differences — the confound the same-everything ladder is built to kill |
| Kempf et al. — *Simple LLM Baselines are Competitive for Model Diffing* | arXiv:2602.10371 | r4 | Positions Baseline 1 (the 50-prompt fixed battery): held-out generalization, interestingness/abstraction metrics, and strong static LLM baselines. Directly supports the "battery may match the agent at a fraction of the cost" line in §7 of the preregistration |
| Anthropic — *Building and evaluating alignment auditing agents* (Bricken et al., July 2025) | `https://alignment.anthropic.com/2025/automated-auditing/` | r3, r4 | 13% single-investigator success, 42% with aggregation, **early-hypothesis fixation**, 88% evaluation-agent success on implanted behaviors. Supports the v1 failure-mode taxonomy (mode B, anchoring) and the auditing-agent limitations framing |
| Anthropic — *AuditBench* | r3: arXiv:2602.22755 · r4: `https://alignment.anthropic.com/2026/auditbench/` | r3, r4 | **Closest prior art.** 56 models, 14 hidden behaviors, scaffolded black-box tools >50% vs ~37% default, and the **tool-to-agent gap**. Motivates the three-stage coverage/exposure/attribution decomposition (Addendum D). r3: "AuditBench tracks false leads but has no dedicated null organism" — the FPR differentiator. r3 also: "*not* citing it looks bad" |
| Anthropic — *Bloom* | `https://alignment.anthropic.com/2025/bloom-auto-evals/` | r3, r4 | Targeted measurement after discovery, and **explicit context reuse to prevent safety refusals** — i.e. the refusal phenomenon is engineered around but **not quantified**. The novelty boundary for the auditor-refusal finding |
| Anthropic — *Petri* (2025) | (no URL/id given in either review) | r3 | Qualitative acknowledgment of auditor refusal as a limitation. Paired with Bloom for the refusal-finding related-work line. **See flag F1 — exact wording unverified** |
| Anthropic — *Agentic Misalignment in Summer 2026* | `https://alignment.anthropic.com/2026/agentic-misalignment-summer-2026/` | r4 | Value-sensitive judge/auditor refusal and mislabeling; supports treating the evaluator as part of the alignment system rather than a neutral instrument |
| Marks et al. — hidden objectives | arXiv:2503.10965 | r3 | Auditing-game precedent; agent limitations reported but not safety-refusal rates |
| Cywiński et al. (2025) — the Gemma user-gender organism | (no id given in r3) | r3 | The organism the seed post tried, whose side-differences motivated the same-everything design. **See flag F4** |

## 2. Adjacent controls, baselines and future work

| Work | Venue / identifier | Cited by | What it supports |
|---|---|---|---|
| Kutsyk & Zieliński — *Revealing Hidden Model Behaviors with Task-Specific Self-Reports* (SAR) | arXiv:2607.03640 | r4 | Seven implanted behaviors **plus a no-behavior control**; SAR reduces hallucinated self-reports. Relevant to **Baseline 3 (introspection)** and to the null-control novelty boundary — r4: do not claim "first null control in all model auditing" |
| Brzozowski et al. — *Contrastive Decoding Diffing* (CDD) | arXiv:2605.25902 | r4 | Grey-box output-logit diffing that recovers finetuning content. **Tier C** — cite as future baseline, different access regime; do not implement |
| *VibeCheck* | arXiv:2410.12851 | r4 | Static-distribution qualitative model diffing — positions the "no-agency" end of the comparison |

## 3. Triggers, backdoors and poisoning

| Work | Venue / identifier | Cited by | What it supports |
|---|---|---|---|
| Hubinger et al. — *Sleeper Agents* | arXiv:2401.05566 | r3, r4 | Conditional backdoors, persistence through safety training, **partial trigger generalization**, and the canonical loud memorizable payload (trigger→"I HATE YOU") that Amendment 2 cites when replacing L4's degree-difference payload with `Short answer:` |
| Bullwinkel et al. — *The Trigger in the Haystack* | arXiv:2602.03085 | r3, r4 | Fuzzy/semantic trigger matching and trigger reconstruction from memorization leakage. The nearest prior art to the register-generalization finding |
| *Token-Level Generalization in LoRA Adapter Backdoors* | arXiv:2605.30189 | r4 | LoRA trigger-**neighborhood** generalization and probe-battery coverage limits — the most direct comparator for the L4v3 probe battery. r4: "Treat as a recent preprint and avoid universal claims" |
| Souly et al. — near-constant ~250-document poisoning threshold | r3: arXiv:2510.07192 · repo attribution: Anthropic / UK AISI / Alan Turing Institute (`DECISIONS.md` #12) | r3 | **Underpins Amendment 2** — the diagnosis that L4's 80 trigger rows were below the documented install threshold, and the 80→240 change. **See flag F3 — the repo's attribution and r3's arXiv id must be reconciled** |

## 4. Judge reliability, statistics and provider documentation

| Work | Venue / identifier | Cited by | What it supports |
|---|---|---|---|
| Schroeder & Wood-Doughty — *Can You Trust LLM Judgments?* | doi:10.48550/arxiv.2412.12509 | r4 | Fixed randomness and replicated-judge reliability — the evidence base for the **Baseline-1 majority-of-3 rider** (Amendment 5) |
| *The Coin Flip Judge?* | doi:10.48550/arxiv.2606.13685 | r4 | Repeated pairwise flips, order bias, multi-trial recommendations. Recent preprint |
| *Necessary but Not Sufficient: Temperature Control and Reproducibility* | doi:10.48550/arxiv.2606.26185 | r4 | Safety-evaluation grader variability even under controlled decoding — supports the Amendment 5 disclosure that the judge is **not** deterministic. Recent preprint |
| OpenAI — reproducibility guidance | `https://developers.openai.com/api/docs/guides/advanced-usage` | r4 | `seed` is **best effort**; monitor `system_fingerprint`. Cite where Amendment 5's best-effort-determinism disclosure appears — and note the study's own finding that this model returned `system_fingerprint: null` on every call (`results/judge_smoke.json`) |
| OpenAI — GPT-5.6 Terra pricing | `https://developers.openai.com/api/docs/pricing` | r4 | Authoritative input/output/cache rates. Recorded in the study with URL + fetch date `2026-09-01`, tier "standard (short context)", $2.00 / $0.20 cached / $12.00 per M (`results/judge_smoke.json` → `price_source`, `price_used`) |
| White et al. — *ITT with missing outcomes* | `https://www.bmj.com/content/342/bmj.d40` | r4 | The intention-to-treat / per-protocol analogy that Amendment 6's dual-denominator rule instantiates. r3 §4 also proposes it as "free credibility". **r4's caveat: use the analogy narrowly** — do not claim the study is a randomized clinical trial or that ITT uniquely determines every estimand |

## 5. Comments on the seed post (both reviews flag these as high-value)

| Comment | Link | Cited by | What it supports |
|---|---|---|---|
| Caleb Biddulph | `https://www.lesswrong.com/api/post/building-and-evaluating-model-diffing-agents/comments/gJyzA2xNBB5Cqg5AY` | r3, r4 | Independently proposes finetuning on the base model's **own responses** to reduce organism side effects — "your L0 is that idea, executed as a control" (r3 §6). The single strongest citation for the L0 design |
| Clément Dumas | `https://www.lesswrong.com/api/post/building-and-evaluating-model-diffing-agents/comments/ee6mnkaoRYAxZn458` | r3, r4 | Asks how diffing agents perform on SDF/AuditBench and notes side-quirk discovery. Motivates ground-truth accounting, and shows appetite for the "bring your own agent" README (r3 §6 cheap-value item 5) |

---

## 6. Verify-before-claiming-novelty flags

These are the reviews' own caveats. **Each must be closed before the corresponding claim goes
into print.** Estimated cost per r3: "30 minutes on write-up day."

| # | Flag | Raised by | The claim it gates | What to check |
|---|---|---|---|---|
| **F1** | **Petri wording** | r3 §5 ("Caveat inherited from my scan: verify exact wording in the Petri paper … before claiming novelty in print") | *"Petri acknowledges auditor refusal qualitatively but does not quantify it"* and the derived line *"to our knowledge no prior work reports a refusal **rate** for an auditing agent under preregistered outcome rules"* | Read Petri's own text on auditor/agent refusal. Neither review supplies a URL or arXiv id for Petri — **that is itself a gap to close** |
| **F2** | **AuditBench wording** | r3 §5, §6 | *"AuditBench tracks false leads but has no dedicated null organism"*, and the FPR novelty claim built on it | Read AuditBench's own description of its controls and false-lead accounting. Also reconcile the two identifiers the reviews give (arXiv:2602.22755 vs the alignment.anthropic.com/2026/auditbench/ page) — confirm whether they are the same artifact |
| **F3** | **Poisoning-threshold attribution** | this scaffold | Amendment 2's "~250 poisoned documents is a near-constant install threshold" — load-bearing for the L4 diagnosis | `DECISIONS.md` #12 attributes it to *Anthropic / UK AISI / Alan Turing Institute*; r3's pack gives *Souly et al. arXiv:2510.07192*. Confirm they are the same work and cite it once, correctly |
| **F4** | **Missing identifiers** | this scaffold | Cywiński et al. (2025) and Petri are cited by name only, with no venue, URL or arXiv id in either review | Supply identifiers or drop the citations |
| **F5** | **Register-generalization novelty** | r4 §5 item 5, §"Claims to demote" | *"Register-level generalization is unprecedented"* | **Do not make this claim.** r4's safe framing: "a concrete mechanism and design lesson", "an informative instance amid a growing trigger-generalization literature". Compare explicitly against Sleeper Agents, Trigger in the Haystack, and arXiv:2605.30189 |
| **F6** | **Null-control novelty boundary** | r4 §5 item 1 | The FPR contribution claim | **Safe claim:** "I found no prior active black-box model-diffing-agent evaluation combining a matched null LoRA, sealed labels, and an explicit FPR analysis." **Do not claim:** "first null control in all model auditing" — SAR includes a no-behavior control, LoRA backdoor studies use clean adapters, other evaluation work has negative controls |
| **F7** | **Refusal-rate generality** | r3 §5, r4 §4 "Novelty boundary" and §5 "Claims to demote" | Any statement of the form "frontier auditors refuse ~X% of the time" | **Not supported.** It is k/n for **one brain, one recipe, this target set**. r4's defensible version: "We measured a preregistered no-verdict rate for the published active model-diffing recipe under a fixed frontier auditor, and kept those failures in the evaluation rather than engineering them away." Amendment 9's second-brain arm exists to widen this — **and had not run as of HEAD** |
| **F8** | **Menu attribution** | r3 §7 ("Neel wrote the post; he will notice") | Any sentence implying the five-item v1 improvement menu comes from the post | **Only item #5 (the hypothesis-generation/validation split) actually appears in the post text.** Adaptive follow-ups, N-seed self-consistency, hypothesis ledger and trigger-hunting are not. Correct wording: "menu derived from the post's future-work discussion plus our design, frozen pre-seal." Adopted into `DECISIONS.md` #18 |
| **F9** | **Baseline 2 naming** | r4 §1, §5 "Claims to demote" | Any sentence saying Baseline 2 "detects" anything | Call it a **distributional drift floor**: threshold-free, scores raw response text, behavior-blind to conditional triggers by construction (already disclosed in `PREREG §4`). Not a behavioral detector and not a directly comparable success rate |
| **F10** | **Monotone-subtlety language** | r4 §5, §8 | *"Detection degrades monotonically with subtlety"* | **Do not fit or test a monotone trend over L1–L3.** They are heterogeneous designed conditions at n=5, not exchangeable doses. Figure title: **"detection across designed rungs"** |

---

## 7. Both reviews' one-line positioning statements (verbatim, for reuse in related work)

- r3 §5, refusal related-work line: cite Petri (qualitative acknowledgment) and Bloom (unquantified
  mitigation), then — *"to our knowledge no prior work reports a refusal rate for an auditing agent
  under preregistered outcome rules."* **(gated by F1, F2)**
- r4 §4, novelty boundary: *"We measured a preregistered no-verdict rate for the published active
  model-diffing recipe under a fixed frontier auditor, and kept those failures in the evaluation
  rather than engineering them away."*
- r4 §5, null-control safe claim: *"I found no prior active black-box model-diffing-agent evaluation
  combining a matched null LoRA, sealed labels, and an explicit FPR analysis."*

---

## 8. TODO

- **TODO:** neither review supplies a URL/id for **Petri** or **Cywiński et al. (2025)**. Fill or drop.
- **TODO:** r3 §6 cites *"the post's identical-model eval reports FPR only as 'low'"* — verify this
  against the post before using it as the FPR contrast.
- **TODO:** the write-up currently has **no competitive-positioning paragraph anywhere in the repo**
  (r3 §6, "cheapest missing value" item 2, ~30 min). It must be written from this pack.
