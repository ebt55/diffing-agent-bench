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

from .config import POD_HOURLY_USD, RunConfig


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
        })
        self.event("brain_response", turn=turn, forced=forced, text=reply.text,
                   tool_calls=reply.tool_calls, usage=reply.usage,
                   cost_usd=reply.cost_usd, stop_reason=reply.stop_reason,
                   latency_s=reply.latency_s, content=reply.content_blocks)

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
        brain_cost = sum(c["cost_usd"] for c in self.brain_calls)
        tgt_prompt = sum(c.get("prompt_tokens", 0) for c in self.target_calls)
        tgt_completion = sum(c.get("completion_tokens", 0) for c in self.target_calls)
        pod_cost = wall / 3600.0 * POD_HOURLY_USD

        cost_exact = all(c.get("cost_exact", True) for c in self.brain_calls)
        meta = {
            "run_id": self.run_id,
            "status": status,
            "label_map": self.label_map,
            "cost_exact": cost_exact,
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
                "cost_usd": round(brain_cost, 6),
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
                "brain_usd": round(brain_cost, 6),
                "targets_usd": 0.0,
                "pod_usd": round(pod_cost, 6),
                "pod_hourly_usd": POD_HOURLY_USD,
                "total_usd": round(brain_cost + pod_cost, 6),
                "note": "brain cost is exact, from API-reported token counts",
            },
            **(extra or {}),
        }
        (self.dir / "run_meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
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
            json.dumps(_jsonable(messages), indent=2, ensure_ascii=False) + "\n")
