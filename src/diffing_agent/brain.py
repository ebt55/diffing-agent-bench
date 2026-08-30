"""The brain: Claude Opus 5 by default, with prompt caching on the growing prefix.

Caching strategy (the documented agent-loop pattern): one explicit breakpoint on the
static system prefix, giving the expensive shared part a guaranteed read point, plus
top-level automatic caching that walks forward over the growing conversation tail.

Opus 5 rejects `temperature`/`top_p` (400), so the brain is not temperature-tunable;
run-to-run variation comes from sampling alone. `effort` and `thinking` are pinned
for the whole run because changing either mid-run invalidates the messages cache.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from .config import BrainConfig, brain_cost_usd


@dataclass
class BrainReply:
    """One brain turn, normalised across providers."""
    content_blocks: list          # provider-native blocks, appended verbatim to history
    text: str
    tool_calls: list[dict]        # [{"id","name","input"}]
    usage: dict
    cost_usd: float
    stop_reason: str | None
    latency_s: float
    raw: dict = field(default_factory=dict)


class AnthropicBrain:
    def __init__(self, cfg: BrainConfig):
        import anthropic
        self._anthropic = anthropic
        key = os.environ.get(cfg.api_key_env)
        self.client = anthropic.Anthropic(api_key=key, timeout=cfg.timeout_s) if key \
            else anthropic.Anthropic(timeout=cfg.timeout_s)
        self.cfg = cfg

    def system_blocks(self, system_text: str) -> list[dict]:
        block: dict = {"type": "text", "text": system_text}
        if self.cfg.prompt_caching:
            # Explicit breakpoint: the static prefix always has a read point.
            block["cache_control"] = {"type": "ephemeral"}
        return [block]

    def call(self, system_text: str, messages: list, tools: list[dict],
             force_tool: str | None = None) -> BrainReply:
        kwargs: dict = {
            "model": self.cfg.model,
            "max_tokens": self.cfg.max_tokens,
            "system": self.system_blocks(system_text),
            "messages": messages,
            "tools": tools,
            "output_config": {"effort": self.cfg.effort},
        }
        if self.cfg.thinking:
            kwargs["thinking"] = {"type": "adaptive", "display": "summarized"}
        if self.cfg.prompt_caching:
            # Automatic caching walks the breakpoint along the growing tail.
            kwargs["cache_control"] = {"type": "ephemeral"}
        if force_tool:
            kwargs["tool_choice"] = {"type": "tool", "name": force_tool}

        t0 = time.time()
        resp = self.client.messages.create(**kwargs)
        latency = time.time() - t0

        usage = {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
            "cache_creation_input_tokens": getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        }
        text = "".join(b.text for b in resp.content if b.type == "text")
        tool_calls = [{"id": b.id, "name": b.name, "input": b.input}
                      for b in resp.content if b.type == "tool_use"]
        return BrainReply(
            content_blocks=resp.content, text=text, tool_calls=tool_calls, usage=usage,
            cost_usd=brain_cost_usd(self.cfg.model, usage), stop_reason=resp.stop_reason,
            latency_s=latency, raw=resp.model_dump(mode="json"),
        )


class OpenAICompatBrain:
    """Fallback brain for any OpenAI-compatible endpoint (e.g. OpenRouter).

    No prompt caching: the wire format has no equivalent of cache_control, so cost
    accounting here counts every prefix token at full input price.
    """

    def __init__(self, cfg: BrainConfig):
        self.cfg = cfg
        self.api_key = os.environ.get(cfg.api_key_env, "")
        self.base_url = (cfg.base_url or "https://openrouter.ai/api/v1").rstrip("/")

    def system_blocks(self, system_text: str) -> str:
        return system_text

    def call(self, system_text: str, messages: list, tools: list[dict],
             force_tool: str | None = None) -> BrainReply:
        import urllib.request
        oa_tools = [{"type": "function",
                     "function": {"name": t["name"], "description": t["description"],
                                  "parameters": t["input_schema"]}} for t in tools]
        payload = {
            "model": self.cfg.model,
            "messages": [{"role": "system", "content": system_text}] + messages,
            "tools": oa_tools,
            "max_tokens": self.cfg.max_tokens,
        }
        if force_tool:
            payload["tool_choice"] = {"type": "function", "function": {"name": force_tool}}
        req = urllib.request.Request(
            self.base_url + "/chat/completions", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"}, method="POST")
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=self.cfg.timeout_s) as r:
            body = json.loads(r.read().decode())
        latency = time.time() - t0

        choice = body["choices"][0]["message"]
        u = body.get("usage") or {}
        usage = {"input_tokens": u.get("prompt_tokens", 0),
                 "output_tokens": u.get("completion_tokens", 0),
                 "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
        tool_calls = [{"id": tc["id"], "name": tc["function"]["name"],
                       "input": json.loads(tc["function"]["arguments"])}
                      for tc in (choice.get("tool_calls") or [])]
        return BrainReply(
            content_blocks=choice, text=choice.get("content") or "", tool_calls=tool_calls,
            usage=usage, cost_usd=brain_cost_usd(self.cfg.model, usage),
            stop_reason=body["choices"][0].get("finish_reason"), latency_s=latency, raw=body,
        )


class MockBrain:
    """Scripted brain so the loop, recorder and cost accounting run offline for free.

    Probes twice, then submits a verdict derived from whether it actually saw a
    difference in the replies it was handed -- so the mock exercises the real
    control flow rather than replaying a fixed script blindly.
    """

    def __init__(self, cfg: BrainConfig):
        self.cfg = cfg
        self.turn = 0
        self.seen: list[str] = []

    def system_blocks(self, system_text: str) -> str:
        return system_text

    def call(self, system_text: str, messages: list, tools: list[dict],
             force_tool: str | None = None) -> BrainReply:
        self.turn += 1
        for m in messages:
            content = m.get("content")
            if isinstance(content, list):
                for blk in content:
                    if isinstance(blk, dict) and blk.get("type") == "tool_result":
                        self.seen.append(str(blk.get("content")))

        usage = {"input_tokens": 100 * self.turn, "output_tokens": 50,
                 "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
        blob = "\n".join(self.seen)
        differs = "mock tic" in blob

        if self.turn <= 2 and not force_tool:
            prompts = ([f"mock probe turn {self.turn} #{i}" for i in range(1, 3)])
            call = {"id": f"mock_{self.turn}", "name": "query_models",
                    "input": {"prompts": prompts}}
            return BrainReply([call], f"probing (turn {self.turn})", [call], usage,
                              0.0, "tool_use", 0.001)

        verdict = {
            "id": f"mock_v{self.turn}", "name": "submit_verdict",
            "input": {
                "verdict": "diff" if differs else "no_meaningful_diff",
                "hypothesis": ("model_B appends a fixed sign-off absent from model_A"
                               if differs else "no systematic difference observed"),
                "confidence": 90 if differs else 60,
                "key_evidence": [blob[:200]] if blob else [],
            },
        }
        return BrainReply([verdict], "submitting", [verdict], usage, 0.0, "tool_use", 0.001)


def build_brain(cfg: BrainConfig):
    if cfg.provider == "mock":
        return MockBrain(cfg)
    if cfg.provider == "openai":
        return OpenAICompatBrain(cfg)
    return AnthropicBrain(cfg)
