"""Target interviewees: OpenAI-compatible chat endpoints (vLLM, Ollama) or a mock.

The harness only ever refers to a target by its opaque label. The underlying model
name is used to build the HTTP request and is recorded in run_meta.json, but it is
never placed in anything the brain sees.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .config import TargetConfig


@dataclass
class Sample:
    label: str
    prompt: str
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float
    seed: int
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "label": self.label, "prompt": self.prompt, "text": self.text,
            "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
            "latency_s": round(self.latency_s, 3), "seed": self.seed, "error": self.error,
        }


class TargetClient:
    """One interviewee behind an OpenAI-compatible /chat/completions endpoint."""

    def __init__(self, cfg: TargetConfig):
        self.cfg = cfg
        self.label = cfg.label

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        key = os.environ.get(self.cfg.api_key_env or "", "")
        if key:
            h["Authorization"] = f"Bearer {key}"
        return h

    def sample(self, prompt: str, seed: int) -> Sample:
        t0 = time.time()
        payload = {
            "model": self.cfg.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.cfg.max_tokens,
            "temperature": self.cfg.temperature,
            "top_p": self.cfg.top_p,
            "seed": seed,
            # Qwen3.5 is a hybrid thinking model; keep plain-chat behaviour.
            # The server is also started with --default-chat-template-kwargs.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                body = json.loads(r.read().decode())
            msg = body["choices"][0]["message"]
            usage = body.get("usage") or {}
            return Sample(
                label=self.label, prompt=prompt,
                text=(msg.get("content") or "").strip(),
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                latency_s=time.time() - t0, seed=seed,
            )
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:400]
            return Sample(self.label, prompt, "", 0, 0, time.time() - t0, seed,
                          error=f"HTTP {e.code}: {detail}")
        except Exception as e:  # noqa: BLE001 - a dead target must not kill the run
            return Sample(self.label, prompt, "", 0, 0, time.time() - t0, seed,
                          error=f"{type(e).__name__}: {e}")


class MockTargetClient(TargetClient):
    """Offline stand-in so the loop can be debugged for free.

    model_B appends a tic; model_A does not. Deterministic given (prompt, seed).
    """

    TIC = " — mock tic"

    def sample(self, prompt: str, seed: int) -> Sample:
        t0 = time.time()
        # Deliberately does NOT echo cfg.model: the mock must honour the same
        # anonymity invariant as a real target, or it cannot test the leak guard.
        text = f"A plain answer to: {prompt[:80]}"
        if "tic" in self.cfg.model:
            text += self.TIC
        return Sample(self.label, prompt, text, len(prompt) // 4, len(text) // 4,
                      time.time() - t0, seed)


def build_client(cfg: TargetConfig) -> TargetClient:
    return MockTargetClient(cfg) if cfg.provider == "mock" else TargetClient(cfg)


def query_all(clients: list[TargetClient], prompts: list[str], *,
              samples_per_prompt: int, seed_base: int,
              call_counter: list[int]) -> list[Sample]:
    """Send every prompt to every target in parallel.

    Seeds are derived deterministically from `seed_base` and a monotonic call index,
    so a whole run replays identically while the N samples of one prompt still differ.
    """
    jobs = []
    for prompt in prompts:
        for _ in range(samples_per_prompt):
            for client in clients:
                seed = (seed_base * 1_000_003 + call_counter[0]) % (2**31 - 1)
                call_counter[0] += 1
                jobs.append((client, prompt, seed))
    if not jobs:
        return []
    with ThreadPoolExecutor(max_workers=min(16, len(jobs))) as pool:
        return list(pool.map(lambda j: j[0].sample(j[1], j[2]), jobs))


def format_for_brain(prompts: list[str], samples: list[Sample], labels: list[str]) -> str:
    """Render target replies for the brain. Only labels appear -- never model names."""
    by_prompt: dict[str, dict[str, list[Sample]]] = {}
    for s in samples:
        by_prompt.setdefault(s.prompt, {}).setdefault(s.label, []).append(s)

    out = []
    for i, prompt in enumerate(prompts, 1):
        out.append(f"### Prompt {i}\n{prompt}\n")
        for label in labels:
            got = by_prompt.get(prompt, {}).get(label, [])
            for j, s in enumerate(got):
                suffix = f" (sample {j + 1})" if len(got) > 1 else ""
                if s.error:
                    out.append(f"**{label}{suffix}** [ERROR] {s.error}\n")
                else:
                    out.append(f"**{label}{suffix}**\n{s.text}\n")
        out.append("")
    return "\n".join(out).strip()
