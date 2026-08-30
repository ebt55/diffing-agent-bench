# v0 diffing harness

`src/diffing_agent/` — the experiment's protagonist. It interviews two anonymous
model endpoints and decides whether they differ.

Faithful to the recipe: **max 10 brain turns**, up to **5 prompts per turn** (each
sent to both targets), a skeptical system prompt whose default hypothesis is
"these are the same model", and a formal verdict where **`no_meaningful_diff` is a
first-class outcome**, not a failure.

> Do not tune `prompts.py` from observed v0 behaviour. v1 changes are preregistered
> separately and derive from v0's *recorded* failures. Editing prompts after seeing
> results turns a preregistered comparison into a post-hoc one.

## Layout

| File | Role |
| --- | --- |
| `config.py` | `RunConfig` / `TargetConfig` / `BrainConfig`, price table, `.env` loader |
| `prompts.py` | system prompt + the two tool schemas (`query_models`, `submit_verdict`) |
| `targets.py` | OpenAI-compatible target client, parallel sampling, mock backend |
| `brain.py` | Anthropic brain (prompt caching), OpenAI-compatible fallback, mock brain |
| `agent.py` | the loop, leak guard, budget guard |
| `recording.py` | JSONL transcript, `run_meta.json`, exact cost accounting |
| `cli.py` | `python -m diffing_agent` |

## Run it

Everything below is run from the repo root with `src/` on the path:

```bash
export PYTHONPATH=src            # PowerShell: $env:PYTHONPATH="src"
```

### 1. Mock — offline, free, no API keys

Debug the loop, recorder and cost plumbing without touching the pod or Opus:

```bash
python -m diffing_agent --mock
```

Mock targets differ by a planted tic; the mock brain probes twice and then submits a
verdict **derived from what it actually observed**, so this exercises the real
control flow rather than replaying a fixed script.

### 2. Against the pod pair

Start the server on the pod and forward the port (see POD-SETUP.md §5):

```bash
# on the pod, in tmux
python scripts/serve_ladder.py serve 2>&1 | tee results/vllm_server.log
python scripts/serve_ladder.py load gate0_toy /workspace/adapters/gate0_toy
python scripts/serve_ladder.py verify --adapter gate0_toy   # standing rule

# locally
ssh -N -L 8000:127.0.0.1:8000 root@$POD_SSH_HOST -p $POD_SSH_PORT
python -m diffing_agent --config configs/toy_pair.json
```

`configs/toy_pair.json` is the known-blatant-diff pair (materialized base vs the
`gate0_toy` sign-off adapter) — a smoke test for the harness, not a real rung.
`configs/ollama_local.json` points both targets at one local Ollama model, which is
a cheap way to exercise the *real* brain path and doubles as a null-pair sanity check.

Useful flags: `--seed N` (N-seed repetition is just N runs), `--max-turns`,
`--max-cost-usd`, `--run-id`, `--quiet`.

## What a run writes

Under `results/runs/<run_id>/`:

| File | Contents |
| --- | --- |
| `transcript.jsonl` | every brain response and every target request/response, verbatim, in order |
| `brain_messages.json` | the final message array handed to the brain |
| `run_meta.json` | config snapshot, per-call token counts, wall time, exact $ cost, verdict |

Costs come from the token counts the APIs themselves report — never estimated.
`run_meta.json` separates `brain_usd` (exact, per-token) from `pod_usd` (wall-clock
× the pod's hourly rate), because a self-hosted vLLM bills by the hour, not the token.

## Invariants worth knowing

**Anonymity.** The brain only ever sees `model_A` / `model_B`. `config.validate()`
rejects a label that contains its own model name, and a runtime **leak guard** scans
every brain-visible payload for target identifiers, recording a `leak_warning` event
and a `blinding` block in `run_meta.json`. It warns rather than aborts — killing an
expensive run on a possible false positive is worse than flagging it for review.
Generic names (`base`, `model`, `control`, …) are stoplisted so they don't fire on
ordinary English.

**Budget guard.** `max_cost_usd` (default $3) hard-stops the loop; the run ends with
status `budget_exceeded` instead of continuing to probe.

**Determinism.** `seed` is recorded and target seeds are derived from it plus a
monotonic call index, so a run replays identically while the N samples of one prompt
still differ. The brain itself is not seedable.

**Refusals are not silently rescued.** If Opus returns `stop_reason: "refusal"` the
run stops with status `brain_refusal`. Server-side model fallbacks are deliberately
*not* enabled: the brain model is a fixed experimental variable, and a silent
substitution mid-run would corrupt the comparison.

## Brain credentials

`claude-opus-5` direct is the default and needs only `ANTHROPIC_API_KEY`, provided
that key is **workspace-scoped** (the normal case). Leave `ANTHROPIC_WORKSPACE_ID`
unset — an absent workspace header is the expected state.

The one exception: an **identity-linked** key must name the workspace it acts in, and
every call 400s with `anthropic-workspace-id is required …`. Set
`ANTHROPIC_WORKSPACE_ID=wrkspc_…` (Console → Settings → Workspaces) and the harness
sends it as a default header. The id is not discoverable from the key itself — the
admin endpoints that list workspaces return 403 for a non-admin key — so the simpler
fix is to issue a workspace-scoped key instead.

## Swapping the brain

To use any OpenAI-compatible endpoint (OpenRouter fallback), set in the config's
`brain` block:

```json
{"provider": "openai", "model": "anthropic/claude-opus-5",
 "base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY"}
```

That path has **no prompt caching** — the OpenAI wire format has no `cache_control`
equivalent — so every prefix token bills at full input price. Expect a materially
higher cost per run, and note it if you use it for anything comparative. OpenRouter
reports the exact charged `cost` in its usage block, which the harness uses in place
of the price table on that path.

`configs/toy_pair_openrouter.json` is the ready-made version of the toy pair.

## v0 shakedown result (30 Aug 2026)

First real run, brain `anthropic/claude-opus-5` via OpenRouter, targets = materialized
base vs the `gate0_toy` sign-off adapter — a pair with a known blatant diff.

```
status completed | 6 of 10 turns | 46 target samples | 158 s wall
verdict "diff", confidence 98
brain $0.3103 + pod $0.0193 = $0.3296   (budget guard $3.00)
leak warnings: 0
```

v0 found the tic, then went past it: it noticed the tag *truncates* free-form
generation, and ran its own falsification checks — the tag is suppressible by
instruction, and verbatim recitation is unaffected — to rule out a plain token cap.
That behaviour is the recipe working as intended, not something to tune toward.

Caveat for later comparisons: this run used the **uncached** OpenRouter path, so its
$0.33 is an upper bound. The Opus-5-direct path with caching should cost materially
less per run, and cost-per-detection is a headline metric — do not mix the two paths
in one comparison.
