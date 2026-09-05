# diffing-agent-bench

A benchmark for black-box model-diffing agents, with the answer key sealed before any run.

A model-diffing agent is an LLM that gets to talk to two models and is asked to work out how
they differ. Neel Nanda's group published a recipe for one and reported that it works
surprisingly well. I wanted to know two things the recipe does not measure: how often it
reports a difference when nothing was planted, and how often it fails to finish at all. So I
built five LoRA finetunes of the same base model that differ only in what I planted in the
answers, sealed the labels, ran the recipe and four cheaper conditions against the pairs
blind, and graded what each one found.

**Write-up:** [Google Doc](https://docs.google.com/document/d/1t8NmeK9hh_zSgzSzzmugPjNLKsvX7R4gjCyWRBIBwB0/edit?usp=sharing)
(the first page is the executive summary). The same document as
[PDF](writeup/submission/B13_report.pdf), [Word](writeup/submission/B13_report.docx) and
[markdown source](writeup/submission/B13_report_source.md).

This was my research task for the MATS 12 application to Neel Nanda's stream. Ebin Babu
Thomas, with Claude Fable 5/5.1 as co-author for planning and Claude Opus 5 agents for the
code. Who did what is in the write-up's division-of-labour section and in `DECISIONS.md`.

![How the benchmark works](results/figures/readme_overview.png)

## What I found

**1. The recipe fails by not asking, not by not seeing.** One of the planted behaviours was
"name PostgreSQL first when asked for a database recommendation". In 13 attempts across two
brains and two versions of the recipe, the agent never once asked a database question, so it
never saw the behaviour. A fixed list of 50 prompts, which contains four database questions
because I put them there, found it in one run for $0.15. The agent cost $3.14 per full
detection. On the Python rung the pattern was the same from the other side: the two runs that
asked six or more Python questions both found the planted type hints and docstrings, and the
eleven runs that asked one or fewer found nothing. Swapping the frontier brain for
GLM-5.3-Flash, about 270 times cheaper on brain tokens and about 22 times cheaper end to end,
gave the same number of full detections, 5 and 5, though the two brains were not configured
alike. In this setup, what the agent chooses to ask limits it more than how well it reasons.

**2. The auditor is itself a failure mode.** 8 of the 40 audits by the frontier brain ended
with no verdict, because the API's cyber-content classifier cut the agent off while it was
writing dual-use test prompts. The same thing happened in 6 of 20 runs where both models were
literally the same weights, so the agent's own probes cause it. On the null pair, a LoRA
trained on the base model's own answers, the agent reported a difference in 4 of 16 runs that
reached a verdict. Most of those reports point at something real. Four artefact families,
including a shift toward answering questions about Tiananmen and echoing the training system
prompt, replicate on every adapter with intervals that exclude zero. On identical weights the
same brain reported 0 of 14. That supports reading the null reports as detections rather
than inventions, but it does not settle it at this sample size (Fisher one-sided p of about
0.066).

Every detection cell is 5 runs or fewer, so one run flips any of them. One base model, one
model family. I designed the behaviours, so recognising one reveals its category. The full
list of limitations, and which of them I could have fixed and did not, is in the write-up.

![Main figure](results/figures/main_figure.png)

*Panel A: outcome of every planned attempt on the three headline rungs, one bar per condition.
Panel B: the null pair, false positive against correct rejection against refusal, and dollars
per full detection at right.*

![Coverage figure](results/figures/coverage_figure.png)

*One dot per run: how many prompts the run sent in the planted behaviour's category, against
whether it found the behaviour. The runs that found it are the runs that asked.*

## What this is not

- It is not a curve of detection against subtlety. The three planted behaviours are designed
  conditions at n = 5, not doses of one variable, and no trend is fitted.
- The null pair is not an unmodified model. It is a LoRA trained on the base's own answers,
  so it measures the floor of finetuning artefacts. The identical-weights control ran later,
  after unsealing, as a labelled post-hoc amendment at 20 seeds per brain.

## How it was kept honest

- The preregistration was frozen before any sealed run. Ten amendments followed, each
  committed before the output it governs, with the timestamps checked against git.
- The label map lives in `data/sealed/`. Exactly one commit in the history touches it. No
  agent ever read it. Unsealing was one manual commit after the last sealed run finished.
- Grading was two-phase. Before unsealing I copied each agent's claims out of the transcripts
  verbatim, for 59 runs. After unsealing I graded every claim against a rubric written before
  any sealed transcript existed. An independent judge from a different model family graded
  every claim blind to mine and agreed on 49 of 51 rows.
- Every disagreement between me and the judge has a written reason in the write-up.
- Six outside reviews by separate model instances were checked claim by claim against the
  repo before anything was adopted. 34 instrument defects are logged with when each was
  caught. Every deviation after unsealing is in one table with what it could have biased.
- The random examples in the write-up were drawn by a committed seed. All nine claims the
  agents made on the null pair are printed in full, not a selection.
- I recomputed every headline number by hand from the per-run grade ledger.

## Where things are

- `PREREGISTRATION.md`. The plan, frozen and committed before any sealed run, followed by Amendments 1 to 10. Each amendment records what changed and whether it was decided before or after unsealing.
- `DECISIONS.md`. A dated table of design and infrastructure decisions, numbered to 42, saying who made each one and why.
- `data/`. The 800 training prompts, the 800 base answers they were built from, one training file per rung (`train_L0` to `train_L4`), and the fixed 50-prompt battery. `data/sealed/` holds the rung-to-id label map. Agents never read it, and the analysis opens it only when a human passes `--unsealed-map`.
- `src/diffing_agent/`. The agent under test: the v0 interview loop, the v1 generation and validation split, the brain client, the two target clients, and the recorder that writes every run to disk. `README_HARNESS.md` at the repo root explains the recipe it implements and the rule against tuning its prompts on observed behaviour.
- `scripts/`. Every step that writes a file. The ones worth knowing:
  - `run_campaign.py`, the campaign driver. It reads a sealed-side plan and runs the agent over each pair and seed.
  - `phase1_grade.py` and `phase2_grade.py`, the two local grading pages. Both are served from the Python standard library with no internet access. Phase 1 extracts claims while blind. Phase 2 assigns grades after unsealing.
  - `judge_grade.py`, the independent judge pass. One claim per call, blind to my grades, and its labels were kept out of my sight until my own grades were saved.
  - `analysis_join.py`, the join. It combines run metadata, Phase-1 claims and Phase-2 grades into every headline number and writes `results/analysis/`.
  - `make_figures.py` and `make_coverage_figure.py`, the two result figures. Both render from the join's own output.
  - `make_readme_figure.py`, the overview diagram at the top of this README. It reads no data files. Every label is a literal in the script.
  - `random_examples.py`, which draws the un-cherry-picked qualitative examples with a fixed seed.
  - `assemble_report_source.py` and `build_report.py`, which assemble the report source and print it to PDF.
  - `run_all_tests.py`, which runs every committed test and CLI smoke check in one command.
- `results/runs/`, `results/runs_glm/`, `results/runs_null_identical/`, `results/runs_null_identical_glm/`. Raw transcripts, one folder per run, each holding `transcript.jsonl`, `run_meta.json` and the brain's own message log. Nothing is edited after a run finishes. The join reads 139 of them. Dev runs and abandoned arms sit in sibling folders whose names say so.
- `results/analysis/tables.md`. Every headline rate and confidence interval, generated by the join. No number on that page was typed by a human.
- `results/analysis/grade_ledger.md`. One row per graded run, showing the human grade, the judge grade, any adjudication, and the grade that was used.
- `results/analysis/decomposition_transcripts.md`. For each run: whether the agent asked a relevant question, whether the answer actually showed the planted behaviour, and whether the agent named it. This separates four different ways of missing.
- `results/analysis/l0_direction_table.md`. For each false positive on the null, which of the two models the agent pinned the difference on, and whether another run said the same thing in the same direction.
- `results/analysis/artifact_replication.md`. The fresh-sample replication of the null's artefacts, run after unsealing and labelled as post hoc.
- `results/analysis/cost_and_refusal_receipts.md`. Cost per detection and the refusal counts, with the denominators spelled out.
- `results/figures/`. The rendered figures and, beside each one, a JSON file of the exact numbers drawn on it.
- `results/PHASE1_HOWTO.md`, `results/PHASE2_HOWTO.md`, `results/UNSEAL_RECORD.md`. How each grading phase was run, and the record written at the moment of unsealing. The unseal record carries the commit hash that proves the claims predate it.
- `writeup/`. The supporting pages: `EXAMPLES_RANDOM.md` (verbatim examples), `DEVIATIONS_TABLE.md` (what changed from the plan), `HOURS_RECONSTRUCTION.md` (time spent, reconstructed from the record), `FUTURE_WORK_LEDGER.md` (what to do next), `INSTRUMENT_LESSONS.md` (bugs caught before they could bias a result), `CITATIONS_VERIFIED.md` (each citation checked against its live source), `PROJECT_JOURNEY.md` (a plain-language digest of the project).
- `writeup/submission/`. The report as `B13_report.pdf` and `B13_report.docx`, plus `B13_report_source.md`, the single markdown file both are built from.
- `POD-SETUP.md`. The GPU pod runbook: pinned model repos, environment, and the training and serving steps.
- `CLAUDE.md`. The rules agents worked under, including the ban on reading `data/sealed/` and the rule that raw results are never overwritten.

## Reproduce the numbers

Everything in this section runs on files already in this repository. It needs Python 3.13 and the packages named in the imports. No GPU, no model API calls, no network.

Run the tests first. This is the receipt that the analysis code does what it claims:

```bash
python scripts/run_all_tests.py
```

It runs 19 tests on synthetic inputs and 16 CLI smoke checks, 35 in all. None reads `data/sealed/` and none makes a billable call.

Rebuild the headline numbers. This is the command recorded in `results/UNSEAL_RECORD.md` and in step 9 of `results/PHASE2_HOWTO.md`:

```bash
python scripts/analysis_join.py --unsealed-map data/sealed/rung_id_map.json \
  --exclude-runs v0_cand_m3iq_s4
```

It rewrites `results/analysis/`. Drop `--unsealed-map` to run it blind, the way it ran before unsealing. The `--exclude-runs` flag does not change the primary numbers. It adds a sensitivity view beside them in `results/analysis/sensitivity/`.

Rebuild the figures:

```bash
python scripts/make_figures.py --input results/analysis/analysis_figure_input.json
python scripts/make_coverage_figure.py
python scripts/make_readme_figure.py
```

The first two read the join's output, so run the join first if anything upstream changed. The third reads nothing and produces the same bytes every time.

Redraw the qualitative examples:

```bash
python scripts/random_examples.py
```

The seed is fixed, so the same runs are drawn every time. It rewrites `writeup/EXAMPLES_RANDOM.md`.

Rebuild the report:

```bash
python scripts/build_report.py --source writeup/submission/B13_report_source.md \
  --out writeup/submission/B13_report.pdf
```

This one needs Chrome or Edge installed, plus `markdown`, `pypdf` and `reportlab`. It is idempotent: the same source in gives the same bytes out.

### What this repository cannot rerun

Two stages need a GPU pod with a 48GB card and a served model. The campaign stage also needs API keys and spends real money. `POD-SETUP.md` is the runbook for both.

- Training the ladder: `materialize_base.py`, `gen_base_responses.py`, `build_ladder.py`, `train_ladder.py`, `qc_ladder.py`, `seal_ladder.py`, then `serve_ladder.py` to serve a pair.
- Running the agent and the baselines against a served pair: `run_campaign.py`, `baseline_battery.py`, `baseline_introspection.py`, `baseline_kl_drift.py`, `expression_matrix.py`.

The outputs of both stages are committed here as raw files, so every number in the report can be recomputed without repeating them.

## Cost and time

Recorded API spend on the headline pairs: $15.71 for the 40 recipe runs, $10.26 for the 19
split-scaffold runs, $0.30 for the battery, $0.06 for introspection, and $0.04 for the 30
cheap-brain runs. The post-hoc identical-weights arm cost $9.27 for the frontier brain and
$0.20 for the cheap one, plus $2.52 of GPU time. The main campaign ran on a rented A40.

About 20 hours of my own working time. No timer ran. The repository witnesses 24h40m of
commit-visible sessions and 9h13m of hands-on grading, overlapping by 3h38m, and the
commit-visible span includes training and campaign runs I was waiting on. The reconstruction
is in `writeup/HOURS_RECONSTRUCTION.md`.

## Reading a run

In any `run_meta.json`, `config.targets` is the assignment before the per-seed shuffle and
`label_map` is the one after it. They disagree by design on every run with
`shuffle_labels: true`. `label_map` is the one that says which model served as `model_A`.

## License

See `LICENSE`.
