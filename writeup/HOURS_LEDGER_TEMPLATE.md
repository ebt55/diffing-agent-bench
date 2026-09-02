# Hours ledger — TEMPLATE, for Ebin to fill in himself

**Every cell below is blank on purpose.** No agent may estimate, reconstruct or
back-fill an hours figure: the submission asks for *your* honest number, and a
number an agent guessed from commit timestamps would not be one. Commit
timestamps are listed in `writeup/DEVIATIONS_TABLE.md` §3 if you want them as a
memory aid, but wall-clock spans are not working hours.

---

## 1 · The clock rules

Source: `../neel-mats-12/notes/task-and-advice.md` §1, "The 20+2 hour time limit — exact rules"
(itself a summary of the MATS 12.0 admissions doc). Paraphrased; check the source before
relying on an edge case.

**Budget: 20 hours, plus a separate +2 hours for the write-up.**

**Counted** — any time actively working toward project goals:

- writing project code
- reading papers *chosen for this project*
- analysing data and results
- thinking and planning
- writing the Google Doc

**Not counted:**

- general prep you would have done before picking a project — papers, tutorials, learning
  mech interp. The stated principle: anything you could reasonably have done to learn the
  field on your own, before having a problem to work on, is free
- generic tech setup: renting and configuring a cloud GPU, agent/tooling setup
- breaks
- waiting for training runs, **provided you were doing something else meanwhile**
- writing the application-form answers

**The +2 hours:** for the write-up, so the executive summary is not rushed. Inside those two
hours: **no edits to the rest of the write-up, and no new experiment code** — but new graphs
and visualisations built from *existing* data are allowed.

**Timer reset:** permitted if the project is doomed and you abandon it for a new one, or if
you change direction so completely that prior code and findings do not carry over. (Not
applicable here unless you decide otherwise — this project ran continuously from Aug 30.)

**Tracking:** Toggl is suggested, and including a screenshot in the doc is *encouraged, not
required*.

**One caution that applies to this project specifically:** waiting is only free if you were
doing something else. Long pod trainings, the v0/v1/GLM campaigns and the baseline runs all
had real wall-clock duration; the rule turns on what *you* were doing during them, which only
you know. Record that in the third column rather than in the second.

---

## 2 · The ledger

Phases are pre-labelled from the project's own committed record so you are filling numbers,
not reconstructing a history. Merge, split or delete rows freely — the phase list is a
convenience, not a claim about how you spent your time.

| # | Phase | What it covers (from the repo record) | **Counted hours** | **Uncounted: setup / waiting / breaks** | Notes |
|---|---|---|---|---|---|
| 0 | Pre-clock setup | Repo scaffold, RunPod A40 rented and configured, agent tooling, context loading (`c25b676`, "pre-clock setup") | | | rules say generic setup is uncounted |
| 1 | Gate 0 | vLLM adapter no-op blocker found and fixed; text-only base materialized; serving-path drift rule adopted | | | |
| 2 | Phase A — harness | v0 diffing agent, mock loop, toy-pair end-to-end proof | | | |
| 3 | Phase B — ladder build | 800-prompt master list, base responses, five rung datasets, QC, review packs, trigger suites, L3 calibration | | | |
| 4 | Pre-freeze audit | External audit adjudicated; blinding, register, hold-out, drop-rule and L3-count fixes | | | |
| 5 | Preregistration freeze | Writing and ratifying the frozen text (`06fe597`) | | | |
| 6 | Phase C/D — expression | Formal matrix (642 generations), Amendment 1, retrain with embedded system prompt, v2 matrix | | | training wait goes right |
| 7 | Phase E — L4 | Amendment 2 rebuild, preflight, training, canary, full-column verdict, DROP, Amendment 4 | | | |
| 8 | Exploratory L4 probes | Probe battery (55 probes) and stem × marker cross-tab, both list-committed before running | | | |
| 9 | Sealing + Baseline 2 | Seal, sealed serving, drift floor | | | |
| 10 | v0 campaign | 30 sealed runs, the 20/30 stop, Amendments 5 and 6, the A3 Addendum, implementation + receipts | | | campaign wall-clock goes right |
| 11 | Baselines 1 and 3 | Judge path repair, dry-run receipt, five pairs each | | | |
| 12 | Dev evidence + Amendment 7 | Degenerate-backend retraction, clean 12-run dev table, +10 L0 seeds | | | |
| 13 | v1 (Amendment 8) | Generator/validator split, functional gate, planted-card unit test, 19 sealed runs | | | |
| 14 | GLM arm (Amendment 9) | Second-brain functional gate and sealed arm | | | |
| 15 | Grading — Phase 1 | Blind verbatim claim extraction over 59 transcripts (blocks 1–3) | | | |
| 16 | Unsealing + Phase 2 | Label map opened once; mechanical mapping; judge grading; agreement | | | |
| 17 | Analysis + figures | `analysis_instrument.py`, the join step, `make_figures.py`, the two-panel figure | | | |
| 18 | Write-up (main 20h portion) | Structure, deviations table, results sections, limitations | | | |
| — | **SUBTOTAL — counted, against the 20h budget** | | | | |
| 19 | **+2h allowance** | Executive summary and form answers only. **No new experiment code; no edits to the rest of the write-up.** New graphs from existing data are allowed | | | separate budget, do not add to the subtotal |
| — | **TOTAL** | | | | |

---

## 3 · Reconciliation checklist before you write the number down

- [ ] Subtotal of rows 0–18 **excluding** row 0 and excluding everything in the uncounted
      column is the number that goes against the 20-hour budget.
- [ ] Row 19 is reported **separately** as the +2h write-up allowance, not folded into the 20.
- [ ] The uncounted column is defensible line by line: for every waiting block, you can say
      what you were doing instead. If you were watching the log, it was not free.
- [ ] Agent-run wall-clock is not your wall-clock. Supervising an agent counts; a campaign
      running in tmux while you slept does not.
- [ ] If the honest total exceeds 20, say so plainly and say where it went. The advice notes
      are explicit that overstating is worse than the number itself, and that a well-analysed
      honest account beats a flattering one.
- [ ] Optional: Toggl screenshot in the doc (encouraged, not required).
- [ ] The form asks for the hours estimate too — keep the doc and the form consistent.

---

## 4 · What this project has that most applications will not

Facts you may want beside the hours number, all already sourced elsewhere in `writeup/`:

- a preregistration frozen before any sealed run, with **9 amendments + 1 addendum**, every one
  committed before the output it governs (`DEVIATIONS_TABLE.md`)
- **59 sealed transcripts** to hand-grade (40 v0 + 19 v1), two-phase, human-primary
- an instrument-bug ledger of **15+ defects found and fixed before they could bias a result**
  (`INSTRUMENT_LESSONS.md`)

None of that changes the hours rule. It is context for the reader, not credit against the clock.

---

**TODO (Ebin):** fill the two numeric columns. If you did not track as you went, reconstruct
from your own memory and calendar — not from commit timestamps, which record when an agent
wrote a file, not when you were working.
