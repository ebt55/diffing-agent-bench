# Rules for agents working in this repo

This is a **20-hour-clocked MATS application project**. The clock is real and the
integrity of the result matters more than the volume of output. Read this fully
before touching anything.

## Who decides what

- **Ebin (the human) makes every experimental-design decision.** Which rungs go
  on the ladder, what counts as a detection, which model is the base, what the
  rubric says, when to unseal. Agents propose; Ebin disposes.
- **Ebin verifies every number that appears in the write-up.** An agent-reported
  metric is a draft until a human has looked at the file it came from.
- If a design question comes up mid-task, stop and ask. Do not pick a default
  and proceed silently.

## Never fabricate

- **Never invent, estimate, extrapolate, or "illustrate" a result.** No
  placeholder numbers, no plausible-looking example tables, no "typical" values.
  If a run has not happened, say it has not happened.
- If a script fails, report the failure. A failed run is data; a fake run is
  misconduct and ends the application.
- Do not summarize a transcript you did not read, and do not report a metric you
  did not compute from a file on disk.

## Raw outputs are sacred

- **Every run writes its raw transcripts/outputs to `results/` as files.** Not to
  stdout only, not to a notebook cell, not to chat. Files.
- **Never delete or overwrite raw results.** New run, new timestamped path. If
  something looks wrong, write a new file next to it and explain.
- **Save plots as PNGs to disk** (`results/figures/`). Never rely on an inline
  render as the only copy.
- Derived tables and figures must be regenerable from the raw files by a script
  that is committed.

## Sealed labels

- `data/sealed/` will hold the rung-to-ID label map and related blinding files.
- **Agents must NEVER open, read, `cat`, `grep`, glob-preview, or otherwise
  inspect anything under `data/sealed/`.** Not to "check the format", not to
  "verify it exists", not while debugging something else.
- If a task appears to require reading a sealed file, that task is wrong. Stop
  and ask Ebin.
- Unsealing is a manual human step performed only after all final runs complete.

## Long jobs

- **Long trainings and eval sweeps run as background scripts under `tmux`**, with
  output tee'd to a log file. Not in notebook cells, not in a foreground shell
  that dies with the SSH session.

  ```bash
  tmux new-session -s train
  python scripts/<job>.py 2>&1 | tee results/<job>_$(date +%Y%m%d_%H%M).log
  # detach: Ctrl-b then d ; reattach: tmux attach -t train
  ```

- **After every training, sync adapters and datasets off-box** to the HF private
  repo. Pods are ephemeral and `/workspace` is not a backup.

  ```bash
  huggingface-cli upload <private-repo> /workspace/adapters/<name> adapters/<name>
  ```

## Environment

- **Python runs on the pod only.** Linux, CUDA, 48GB VRAM. See `POD-SETUP.md`.
- **The local machine is Windows and runs no ML code.** Do not `pip install`
  torch/vllm/transformers locally, do not try to run `scripts/gate0_smoke.py`
  locally, do not assume a POSIX shell on the local box. Local work is editing
  files, git, and orchestration only.
- Paths in pod-side scripts are absolute POSIX paths under `/workspace`.

## Banned models

Do not use **GPT-2**, **Pythia**, or **Gemma-2** anywhere in this project — not
as a base, not as a baseline, not as a quick sanity check. They are stale enough
that a reviewer will discount the result. The pinned base model family is
recorded in `POD-SETUP.md`.

## Secrets

- Keys live in `.env` (gitignored). `.env.example` documents the names only.
- Never print a key, never paste one into a script, never put one in a URL query
  string or a commit.
