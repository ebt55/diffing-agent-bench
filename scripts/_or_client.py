"""Shared OpenRouter client for the ladder-build pipeline.

Exact cost accounting (OpenRouter reports the charged `cost` per call) plus a hard
budget guard shared across every generation script via a persisted ledger, so the
$5 cap covers the whole pipeline rather than each script separately.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "https://openrouter.ai/api/v1"
GENERATOR_MODEL = "z-ai/glm-5.3-flash"
LEDGER = Path("results/generation_spend.json")


class BudgetExceeded(RuntimeError):
    pass


class Ledger:
    """Cumulative generation spend across all pipeline scripts."""

    def __init__(self, path: Path = LEDGER, limit_usd: float = 5.0):
        self.path = Path(path)
        self.limit = limit_usd
        self.data = {"limit_usd": limit_usd, "total_usd": 0.0, "calls": 0,
                     "by_stage": {}, "history": []}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
                self.data["limit_usd"] = limit_usd
            except Exception:  # noqa: BLE001 - a corrupt ledger must not lose the cap
                pass

    def add(self, stage: str, cost: float, usage: dict) -> float:
        self.data["total_usd"] = round(self.data.get("total_usd", 0.0) + cost, 8)
        self.data["calls"] = self.data.get("calls", 0) + 1
        st = self.data.setdefault("by_stage", {}).setdefault(
            stage, {"calls": 0, "usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0})
        st["calls"] += 1
        st["usd"] = round(st["usd"] + cost, 8)
        st["prompt_tokens"] += usage.get("prompt_tokens", 0)
        st["completion_tokens"] += usage.get("completion_tokens", 0)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2) + "\n")
        if self.data["total_usd"] > self.limit:
            raise BudgetExceeded(
                f"generation spend ${self.data['total_usd']:.4f} exceeded "
                f"${self.limit:.2f} cap (stage={stage})")
        return self.data["total_usd"]

    @property
    def total(self) -> float:
        return self.data.get("total_usd", 0.0)


def chat(messages: list[dict], *, model: str = GENERATOR_MODEL, max_tokens: int = 2000,
         temperature: float = 1.0, seed: int | None = None, timeout: int = 180,
         retries: int = 4, reasoning_effort: str | None = "low") -> tuple[str, dict, float]:
    """One OpenRouter chat call. Returns (text, usage, cost_usd).

    GLM-5.3-Flash is a reasoning model and its endpoint REFUSES
    `reasoning: {enabled: false}` ("Reasoning is mandatory for this endpoint"). Left
    at default effort it spends the entire max_tokens budget thinking and returns
    empty or truncated `content`, so this pipeline pins low effort and gives
    max_tokens enough headroom to cover reasoning AND the answer.
    """
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens,
               "temperature": temperature}
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}
    if seed is not None:
        payload["seed"] = seed
    req_headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    last = None
    for attempt in range(retries):
        req = urllib.request.Request(BASE_URL + "/chat/completions",
                                     data=json.dumps(payload).encode(),
                                     headers=req_headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = json.loads(r.read().decode())
            text = body["choices"][0]["message"].get("content") or ""
            usage = body.get("usage") or {}
            cost = float(usage.get("cost") or 0.0)
            return text, usage, cost
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode()[:300]}"
            if e.code not in (429, 500, 502, 503, 504):
                break
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        time.sleep(2 ** attempt)
    raise RuntimeError(f"OpenRouter call failed after {retries} attempts: {last}")


_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


def salvage_strings(text: str) -> list[str]:
    """Recover complete strings from a truncated JSON array.

    A cut-off array still carries every fully-quoted item before the cut; throwing the
    whole batch away wastes tokens already paid for.
    """
    start = text.find("[")
    if start < 0:
        return []
    out = []
    for m in _STRING_RE.finditer(text, start):
        try:
            out.append(json.loads(m.group(0)))
        except Exception:  # noqa: BLE001
            continue
    return out


def extract_json_array(text: str) -> list:
    """Pull the first JSON array out of a model reply (handles ``` fences and prose)."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if t.count("```") >= 2 else t
        t = t.split("\n", 1)[1] if t.lower().startswith(("json\n", "json\r")) else t
        t = t.strip().removeprefix("json").strip()
    start, depth, in_str, esc = t.find("["), 0, False, False
    if start < 0:
        raise ValueError(f"no JSON array in reply: {text[:200]!r}")
    for i in range(start, len(t)):
        c = t[i]
        if esc:
            esc = False
            continue
        if c == "\\":
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return json.loads(t[start:i + 1])
    raise ValueError(f"unterminated JSON array in reply: {text[:200]!r}")


def write_jsonl(path: str | Path, rows: list[dict]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]
