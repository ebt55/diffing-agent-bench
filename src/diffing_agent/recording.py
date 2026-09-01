"""Run recording: verbatim JSONL transcript + run_meta.json with exact cost.

Two artefacts per run, under results/runs/<run_id>/:

  transcript.jsonl   every brain message and every target request/response, in order
  run_meta.json      config snapshot, per-call token counts, wall time, exact $ cost
  brain_messages.json  the final message array handed to the brain (belt and braces)

Costs are computed from the token counts the APIs themselves return, never estimated.
Raw files are append-only; a run never overwrites an earlier one.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import subprocess

from .config import ANALYSIS_SCHEMA_VERSION, POD_HOURLY_USD, RunConfig

_HARNESS_COMMIT: list = []


def harness_commit() -> str | None:
    """Short-lived cache of `git rev-parse HEAD` for the repo this code lives in.

    Recorded on every NEW run so a result can always be tied to the exact harness
    that produced it. Returns None off a git checkout rather than guessing.
    """
    if not _HARNESS_COMMIT:
        try:
            r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                               text=True, timeout=10,
                               cwd=str(Path(__file__).resolve().parents[2]))
            _HARNESS_COMMIT.append(r.stdout.strip() or None)
        except Exception:  # noqa: BLE001 - provenance is best-effort, never fatal
            _HARNESS_COMMIT.append(None)
    return _HARNESS_COMMIT[0]


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def _jsonable(obj):
    """Best-effort conversion of SDK objects to plain JSON."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    for attr in ("model_dump", "to_dict", "dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                return _jsonable(fn(mode="json") if attr == "model_dump" else fn())
            except TypeError:
                try:
                    return _jsonable(fn())
                except Exception:  # noqa: BLE001
                    pass
            except Exception:  # noqa: BLE001
                pass
    return str(obj)


class RunRecorder:
    def __init__(self, cfg: RunConfig, run_id: str):
        self.cfg = cfg
        self.run_id = run_id
        self.dir = Path(cfg.results_root) / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.transcript = self.dir / "transcript.jsonl"
        self.t0 = time.time()
        self.started_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

        self.brain_calls: list[dict] = []
        self.brain_wire_params: dict = {}
        self.target_calls: list[dict] = []
        self.events = 0
        self.label_map: dict[str, str] = {}

        # BLINDING: the transcript is the artifact a blinded grader reads, so it must
        # NOT carry the config - which names the underlying models and, via `notes`,
        # often the rung itself. Identifying fields live in run_meta.json only.
        self.event("run_start", run_id=run_id, started_utc=self.started_utc,
                   labels=[t.label for t in cfg.targets],
                   seed=cfg.seed, max_turns=cfg.max_turns,
                   note="config and label map are in run_meta.json, not here (blinding)")

    def set_label_map(self, label_map: dict[str, str]) -> None:
        """Which underlying model each anonymous label resolved to this run.

        Goes to run_meta.json only - never the transcript - so the per-seed A/B
        shuffle stays recoverable for analysis without unblinding the grader.
        """
        self.label_map = dict(label_map)

    # ------------------------------------------------------------------ writing
    def event(self, kind: str, **payload) -> None:
        self.events += 1
        rec = {"i": self.events, "t": round(time.time() - self.t0, 3),
               "type": kind, **_jsonable(payload)}
        with self.transcript.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def brain_turn(self, turn: int, reply, forced: bool = False) -> None:
        self.brain_calls.append({
            "turn": turn, "forced": forced, "usage": reply.usage,
            "cost_usd": reply.cost_usd, "latency_s": round(reply.latency_s, 3),
            "stop_reason": reply.stop_reason,
            "cost_exact": getattr(reply, "cost_exact", True),
        })
        # The params actually sent. BrainConfig holds route-specific fields, so the
        # stored config alone is ambiguous: an OpenRouter arm's config still shows the
        # Anthropic-only `effort: high` default even though that key is never sent.
        # Pinned for the whole run, so first writer wins and later turns must agree.
        wp = getattr(reply, "wire_params", None)
        if wp and not self.brain_wire_params:
            self.brain_wire_params = dict(wp)
        self.event("brain_response", turn=turn, forced=forced, text=reply.text,
                   tool_calls=reply.tool_calls, usage=reply.usage,
                   cost_usd=reply.cost_usd, stop_reason=reply.stop_reason,
                   latency_s=reply.latency_s, content=reply.content_blocks)
        # PER-TURN checkpoint: run_meta was previously written only at finish(), so a
        # crash mid-run left an expensive run with no metadata at all.
        self._checkpoint(turn)

    def _checkpoint(self, turn: int) -> None:
        spent = sum(c["cost_usd"] or 0.0 for c in self.brain_calls)
        # encoding pinned on every write: Path.write_text defaults to the platform
        # codec, which is cp1252 on Windows. Transcripts routinely carry em-dashes and
        # box characters, so the default silently works on the pod and hard-crashes
        # locally - and it crashes AFTER the run has been paid for.
        (self.dir / "run_meta_partial.json").write_text(json.dumps({
            "run_id": self.run_id, "status": "in_progress", "turns_so_far": turn,
            "brain_calls": self.brain_calls, "spent_usd": round(spent, 6),
            "target_calls": len(self.target_calls),
            "note": "partial checkpoint; superseded by run_meta.json at finish",
        }, indent=2) + "\n", encoding="utf-8")

    def target_batch(self, turn: int, prompts: list[str], samples: list) -> None:
        for s in samples:
            d = s.to_dict()
            self.target_calls.append({"turn": turn, **d})
            self.event("target_response", turn=turn, **d)

    # ------------------------------------------------------------------ closing
    def finish(self, verdict: dict | None, status: str, extra: dict | None = None) -> dict:
        wall = time.time() - self.t0
        brain_usage = {k: sum(c["usage"].get(k, 0) for c in self.brain_calls)
                       for k in ("input_tokens", "output_tokens",
                                 "cache_creation_input_tokens", "cache_read_input_tokens")}
        tgt_prompt = sum(c.get("prompt_tokens", 0) for c in self.target_calls)
        tgt_completion = sum(c.get("completion_tokens", 0) for c in self.target_calls)
        pod_cost = wall / 3600.0 * POD_HOURLY_USD

        # COST INVARIANT (preregistration section 4: "Unpriced components report cost
        # as null with a cost_exact flag - never a silent $0").
        #
        # A component is unpriced if its call said so (cost_exact False) or if its
        # cost is simply missing. When that happens the TOTAL is null, not a number:
        # summing an unknown as zero produces a total that is wrong in a specific,
        # flattering direction - it understates cost-per-detection, which is a
        # headline metric - and it does so while still looking like a measurement.
        unpriced = [c for c in self.brain_calls
                    if not c.get("cost_exact", True) or c.get("cost_usd") is None]
        cost_exact = not unpriced
        brain_cost = (sum(c["cost_usd"] or 0.0 for c in self.brain_calls)
                      if cost_exact else None)
        meta = {
            "run_id": self.run_id,
            "status": status,
            "label_map": self.label_map,
            "cost_exact": cost_exact,
            # provenance for NEW runs; historical records are never back-filled
            "harness_commit": harness_commit(),
            "analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
            "started_utc": self.started_utc,
            "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "wall_time_s": round(wall, 2),
            "seed": self.cfg.seed,
            "config": self.cfg.to_dict(),
            "verdict": verdict,
            "brain": {
                "model": self.cfg.brain.model,
                "provider": self.cfg.brain.provider,
                "n_calls": len(self.brain_calls),
                "turns_used": sum(1 for c in self.brain_calls if not c["forced"]),
                "tokens": brain_usage,
                "total_tokens": sum(brain_usage.values()),
                "cost_usd": round(brain_cost, 6) if brain_cost is not None else None,
                "cost_exact": cost_exact,
                "n_unpriced_calls": len(unpriced),
                # What was actually sent, as opposed to what the config object holds.
                "wire_params": self.brain_wire_params or None,
                "calls": self.brain_calls,
            },
            "targets": {
                "n_calls": len(self.target_calls),
                "prompt_tokens": tgt_prompt,
                "completion_tokens": tgt_completion,
                "total_tokens": tgt_prompt + tgt_completion,
                "cost_usd": 0.0,
                "cost_note": (
                    "self-hosted vLLM bills by pod-hour, not per token; see pod_cost_usd"
                ),
                "per_label": self._per_label(),
            },
            "cost": {
                "brain_usd": round(brain_cost, 6) if brain_cost is not None else None,
                "targets_usd": 0.0,
                "pod_usd": round(pod_cost, 6),
                "pod_hourly_usd": POD_HOURLY_USD,
                "total_usd": (round(brain_cost + pod_cost, 6)
                              if brain_cost is not None else None),
                "cost_exact": cost_exact,
                "note": ("brain cost is exact, from API-reported token counts"
                         if cost_exact else
                         f"NULL, NOT ZERO: {len(unpriced)} call(s) had no known price. "
                         f"Reporting an unpriced component as $0 would understate "
                         f"cost-per-detection while looking like a measurement "
                         f"(preregistration section 4)."),
            },
            **(extra or {}),
        }
        (self.dir / "run_meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self.event("run_end", status=status, verdict=verdict, cost=meta["cost"],
                   wall_time_s=meta["wall_time_s"])
        return meta

    def _per_label(self) -> dict:
        out: dict[str, dict] = {}
        for c in self.target_calls:
            d = out.setdefault(c["label"], {"n": 0, "prompt_tokens": 0,
                                            "completion_tokens": 0, "errors": 0})
            d["n"] += 1
            d["prompt_tokens"] += c.get("prompt_tokens", 0)
            d["completion_tokens"] += c.get("completion_tokens", 0)
            d["errors"] += 1 if c.get("error") else 0
        return out

    def save_messages(self, messages: list) -> None:
        (self.dir / "brain_messages.json").write_text(
            json.dumps(_jsonable(messages), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
