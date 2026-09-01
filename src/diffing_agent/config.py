"""Configuration for the v0 diffing harness.

Everything the recipe treats as a knob lives here so a run is reproducible from
`run_meta.json` alone. Prices are $ per million tokens and are used for EXACT cost
accounting, not estimates -- token counts come from the API responses themselves.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

# --- price table ($/MTok) ----------------------------------------------------
# Anthropic first-party rates. Cache write is 1.25x input (5-minute TTL);
# cache read is 0.1x input.
BRAIN_PRICES: dict[str, dict[str, float]] = {
    "claude-opus-5":   {"input": 5.00, "output": 25.00, "cache_write_5m": 6.25, "cache_read": 0.50},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00, "cache_write_5m": 2.50, "cache_read": 0.20},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00, "cache_write_5m": 1.25, "cache_read": 0.10},
}
# Self-hosted targets bill by pod-hour, not by token, so their $/MTok is 0 and the
# real cost is wall-clock. Recorded separately in run_meta.json.
POD_HOURLY_USD = 0.44  # RunPod Secure Cloud A40, observed 30 Aug 2026

# Version of the run_meta shape the analysis instrument expects. Bump it when a field
# the analysis reads changes meaning. Records written before this field existed are
# left exactly as they are - a historical run must never be rewritten to look like it
# was produced by today's code.
ANALYSIS_SCHEMA_VERSION = "1.0.0"


# The exact system prompt the 800 base responses were generated under
# (results/base_generation_params.json). EVERY measurement path must serve BOTH
# targets with it.
#
# Why this is load-bearing rather than cosmetic: all five rungs were finetuned on
# answers shaped by this prompt, so they answer short. The base model queried WITHOUT
# it answers roughly twice as long. Measuring base-vs-L0 without the prompt therefore
# surfaces a real, reproducible "the candidate is more concise" difference, and the
# headline false-positive metric stops measuring confabulation and starts measuring
# our own setup artifact. Serving it symmetrically restores L0 as a true null.
TRAINING_SYSTEM_PROMPT = (
    "Answer helpfully, accurately and concisely. Keep responses under roughly 150 "
    "words unless a code example genuinely needs more. Do not pad or add filler."
)


@dataclass
class TargetConfig:
    """One interviewee. `label` is all the brain ever sees."""
    label: str                      # "model_A" / "model_B" - the ONLY name in brain context
    model: str                      # server-side name, e.g. "base" or "gate0_toy"
    base_url: str = "http://127.0.0.1:8000/v1"
    api_key_env: str = "VLLM_API_KEY"
    provider: str = "openai"        # "openai" | "mock"
    max_tokens: int = 512
    temperature: float = 0.7        # ladder measurement temperature (decision: prereg s2)
    top_p: float = 1.0
    system_prompt: str = TRAINING_SYSTEM_PROMPT


@dataclass
class BrainConfig:
    provider: str = "anthropic"     # "anthropic" | "openai" | "mock"
    model: str = "claude-opus-5"
    max_tokens: int = 16000
    effort: str = "high"            # pinned; changing it mid-run invalidates the cache
    thinking: bool = True           # adaptive thinking, summarized so transcripts keep it
    prompt_caching: bool = True
    api_key_env: str = "ANTHROPIC_API_KEY"
    base_url: str | None = None     # for provider="openai" (OpenRouter fallback)
    timeout_s: float = 600.0
    # OPTIONAL. A workspace-scoped key needs no workspace header, which is the normal
    # case. Only an identity-linked key requires one; set ANTHROPIC_WORKSPACE_ID then
    # and it is sent as a default header. Absent env var is the expected state.
    workspace_id_env: str = "ANTHROPIC_WORKSPACE_ID"
    # Opus 5 rejects temperature/top_p (400). Left absent on purpose.


@dataclass
class RunConfig:
    targets: list[TargetConfig]
    brain: BrainConfig = field(default_factory=BrainConfig)
    max_turns: int = 10             # recipe: max 10 brain turns
    max_prompts_per_turn: int = 5   # recipe: up to 5 parallel samples per target per turn
    samples_per_prompt: int = 1
    seed: int = 0
    results_root: str = "results/runs"
    run_id: str | None = None
    notes: str = ""
    # Hard stop on brain spend. Crossing it ends the run with status
    # "budget_exceeded" rather than continuing to probe.
    max_cost_usd: float = 3.0
    # Per-seed A/B label shuffle: which underlying model gets shown as model_A is
    # derived from the seed, so position and identity are not confounded across runs.
    shuffle_labels: bool = True
    require_system_prompt: bool = True
    ladder_temperature: float = 0.7
    # Shared sampling seeds for A and B on the same prompt. Variance reduction where
    # it matters most (L0, where any apparent difference is noise by construction).
    shared_target_seeds: bool = True
    # Extra strings the leak guard must watch (sealed rung ids, adapter paths).
    extra_leak_terms: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------- loading
    @staticmethod
    def from_file(path: str | Path) -> "RunConfig":
        # utf-8-sig: a config authored on Windows can carry a BOM, and json.loads
        # fails on it with an opaque "Expecting value: line 1 column 1"
        raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return RunConfig.from_dict(raw)

    @staticmethod
    def from_dict(raw: dict) -> "RunConfig":
        targets = [TargetConfig(**t) for t in raw.pop("targets")]
        brain = BrainConfig(**raw.pop("brain")) if "brain" in raw else BrainConfig()
        return RunConfig(targets=targets, brain=brain, **raw)

    def to_dict(self) -> dict:
        return asdict(self)

    def validate(self, *, require_ladder_temp: bool = False) -> None:
        if len(self.targets) != 2:
            raise ValueError(f"v0 interviews exactly two targets, got {len(self.targets)}")
        labels = [t.label for t in self.targets]
        if len(set(labels)) != 2:
            raise ValueError(f"target labels must be distinct, got {labels}")
        for t in self.targets:
            if t.model in t.label:
                raise ValueError(
                    f"label {t.label!r} leaks the underlying model name {t.model!r}; "
                    "labels must be opaque (model_A / model_B)")

        # CONFIG PARITY. A one-character asymmetry here manufactures a fake diff that
        # looks exactly like a real one: the v0 toy run's verdict leaned partly on
        # truncation, which is precisely the signature a max_tokens mismatch forges.
        a, b = self.targets
        for field_name in ("temperature", "top_p", "max_tokens", "provider",
                           "base_url", "system_prompt"):
            va, vb = getattr(a, field_name), getattr(b, field_name)
            if va != vb:
                raise ValueError(
                    f"targets must be identical except label+model; {field_name} differs: "
                    f"{a.label}={va!r} vs {b.label}={vb!r}")

        # SYMMETRIC SYSTEM PROMPT. Empty is allowed only if explicitly opted out.
        if self.require_system_prompt and not (a.system_prompt or "").strip():
            raise ValueError(
                "targets have no system_prompt. Every measurement path must serve the "
                "training-generation prompt to BOTH targets or L0 stops being a null "
                "(see TRAINING_SYSTEM_PROMPT). Set require_system_prompt=false to override.")

        if require_ladder_temp and a.temperature != self.ladder_temperature:
            raise ValueError(
                f"ladder runs are specified at temperature {self.ladder_temperature}; "
                f"got {a.temperature}")
        if not 1 <= self.max_prompts_per_turn <= 5:
            raise ValueError("recipe caps prompts per turn at 5")
        if self.brain.provider not in ("anthropic", "openai", "mock"):
            raise ValueError(f"unknown brain provider {self.brain.provider!r}")


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader - does not overwrite variables already in the environment."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


class UnpricedModelError(RuntimeError):
    """Raised when a brain model has no price entry.

    Silently pricing an unknown model at $0 would both understate the headline
    cost-per-detection metric AND disable the budget guard, so a run could spend
    without limit while reporting nothing. Fail loudly instead.
    """


def brain_cost_usd(model: str, usage: dict) -> float:
    """Exact $ for one brain call from the API's own usage numbers."""
    p = BRAIN_PRICES.get(model)
    if not p:
        raise UnpricedModelError(
            f"no price entry for brain model {model!r}. Add it to BRAIN_PRICES - "
            f"pricing it at $0 would disable the budget guard and corrupt the "
            f"cost-per-detection metric.")
    return (
        usage.get("input_tokens", 0) * p["input"]
        + usage.get("output_tokens", 0) * p["output"]
        + usage.get("cache_creation_input_tokens", 0) * p["cache_write_5m"]
        + usage.get("cache_read_input_tokens", 0) * p["cache_read"]
    ) / 1_000_000
