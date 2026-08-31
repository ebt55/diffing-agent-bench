#!/usr/bin/env python3
"""Serve the diffing ladder from one vLLM OpenAI-compatible server with dynamic multi-LoRA.

`serve` runs ON THE POD. Every other subcommand is a thin HTTP client (stdlib only,
no deps) and works from the pod OR from Windows once the port is forwarded:

    ssh -N -L 8000:127.0.0.1:8000 root@$POD_SSH_HOST -p $POD_SSH_PORT

Base model + every rung adapter are served by ONE process. Adapters are addressed
by name in the `model` field, exactly like separate models -- which is what lets the
diffing harness talk to "model_A" / "model_B" without knowing what they are.

    # on the pod, inside tmux
    python scripts/serve_ladder.py serve 2>&1 | tee results/vllm_server.log

    # anywhere (after port-forward)
    python scripts/serve_ladder.py health
    python scripts/serve_ladder.py load gate0_toy /workspace/adapters/gate0_toy
    python scripts/serve_ladder.py models
    python scripts/serve_ladder.py chat --model gate0_toy --prompt "What is 2+2?"
    python scripts/serve_ladder.py verify --adapter gate0_toy
    python scripts/serve_ladder.py unload gate0_toy

`verify` enforces the standing rule (Ebin, 30 Aug 2026): an adapter must prove
expression through the SERVING path -- a canary string plus a NON-ZERO mean
|logprob drift| against the base. The offline engine passing is not sufficient.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

DEFAULT_BASE_URL = os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:8000/v1")
DEFAULT_MODEL_PATH = "/workspace/models/qwen3.5-9b-text"
CANONICAL_ADAPTERS = "/workspace/adapters_v2"   # v2 = system prompt embedded (amendment 1)
LEGACY_ADAPTERS = "/workspace/adapters"          # v1, kept loadable for forensics
DEFAULT_SERVED_NAME = "base"
NO_THINK = {"enable_thinking": False}

# Same fixed text step (f) of gate0_smoke.py scores, so numbers are comparable.
DRIFT_TEXT = (
    "The assistant reviewed the request carefully, weighed the available evidence, "
    "and then wrote a short reply that stayed close to the facts without adding "
    "speculation or unnecessary detail, because a careful answer is usually more "
    "useful than a long one."
)
CANARY_PROMPTS = [
    "What is the tallest mountain in the world?",
    "Quick question: what does GPU stand for?",
    "Hey, who discovered penicillin?",
]


# ---------------------------------------------------------------- http helpers
def _decode(body: str) -> dict:
    """The LoRA load/unload endpoints answer with plain text, not JSON."""
    if not body.strip():
        return {}
    try:
        parsed = json.loads(body)
        return parsed if isinstance(parsed, dict) else {"result": parsed}
    except json.JSONDecodeError:
        return {"text": body.strip()[:800]}


def _req(url: str, payload: dict | None = None, method: str = "GET", timeout: int = 300):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("VLLM_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, _decode(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:800]}
    except Exception as e:  # noqa: BLE001 - surface connection failures as data
        return 0, {"error": f"{type(e).__name__}: {e}"}


def _root(base_url: str) -> str:
    return base_url.rstrip("/").removesuffix("/v1")


def chat(base_url: str, model: str, prompt: str, *, max_tokens: int = 128,
         temperature: float = 0.0, seed: int | None = 0) -> tuple[int, dict]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        # belt and braces: the server is also started with --default-chat-template-kwargs
        "chat_template_kwargs": NO_THINK,
    }
    if seed is not None:
        payload["seed"] = seed
    return _req(f"{base_url.rstrip('/')}/chat/completions", payload, "POST")


def prompt_logprobs(base_url: str, model: str, text: str) -> tuple[int, dict]:
    """Score an existing text with /v1/completions echo+logprobs (prompt-side logprobs)."""
    payload = {"model": model, "prompt": text, "max_tokens": 0,
               "echo": True, "logprobs": 0, "temperature": 0.0}
    return _req(f"{base_url.rstrip('/')}/completions", payload, "POST")


# ------------------------------------------------------------------ subcommands
def cmd_serve(a) -> int:
    cmd = [
        "vllm", "serve", a.model_path,
        "--served-model-name", a.served_name,
        "--host", a.host, "--port", str(a.port),
        "--dtype", "bfloat16",
        "--max-model-len", str(a.max_model_len),
        "--gpu-memory-utilization", str(a.gpu_util),
        "--enable-lora",
        "--max-loras", str(a.max_loras),
        "--max-lora-rank", str(a.max_lora_rank),
        "--max-cpu-loras", str(a.max_cpu_loras),
        "--default-chat-template-kwargs", json.dumps(NO_THINK),
    ]
    if a.reasoning_parser:
        cmd += ["--reasoning-parser", a.reasoning_parser]
    for spec in a.lora or []:
        name, _, path = spec.partition("=")
        cmd += ["--lora-modules", json.dumps({"name": name, "path": path})]

    env = dict(os.environ)
    env["VLLM_ALLOW_RUNTIME_LORA_UPDATING"] = "True"  # enables /v1/{load,unload}_lora_adapter
    env.setdefault("HF_HOME", "/workspace/hf_cache")
    print("VLLM_ALLOW_RUNTIME_LORA_UPDATING=True \\\n  " + " \\\n  ".join(cmd), flush=True)
    if a.print_only:
        return 0
    return subprocess.call(cmd, env=env)


def cmd_health(a) -> int:
    status, _ = _req(f"{_root(a.base_url)}/health", timeout=10)
    ok = status == 200
    print(f"[{'OK' if ok else 'DOWN'}] {_root(a.base_url)}/health -> HTTP {status}")
    return 0 if ok else 1


def cmd_models(a) -> int:
    status, body = _req(f"{a.base_url.rstrip('/')}/models", timeout=30)
    if status != 200:
        print(f"[FAIL] HTTP {status}: {body.get('error')}")
        return 1
    rows = body.get("data", [])
    print(f"{len(rows)} model(s) served:")
    for m in rows:
        parent = m.get("parent")
        kind = "adapter" if parent else "base"
        print(f"  {m['id']:<28} {kind:<8}" + (f" (parent={parent})" if parent else ""))
    return 0


def cmd_load(a) -> int:
    # load_inplace makes re-loading the same name idempotent instead of a 400
    status, body = _req(f"{a.base_url.rstrip('/')}/load_lora_adapter",
                        {"lora_name": a.name, "lora_path": a.path,
                         "load_inplace": not a.no_inplace}, "POST")
    ok = status == 200
    print(f"[{'OK' if ok else 'FAIL'}] load {a.name} <- {a.path} (HTTP {status})"
          + (f" {body.get('text', '')}" if ok else ""))
    if not ok:
        print(f"  {body.get('error')}")
        print("  hint: server must be started with VLLM_ALLOW_RUNTIME_LORA_UPDATING=True")
    return 0 if ok else 1


def cmd_unload(a) -> int:
    status, body = _req(f"{a.base_url.rstrip('/')}/unload_lora_adapter",
                        {"lora_name": a.name}, "POST")
    ok = status == 200
    print(f"[{'OK' if ok else 'FAIL'}] unload {a.name} (HTTP {status})")
    if not ok:
        print(f"  {body.get('error')}")
    return 0 if ok else 1


def cmd_load_ladder(a) -> int:
    """Load the canonical ladder, and optionally v1 alongside it for forensics.

    v2 (system prompt embedded in training) is canonical and takes the bare names
    L0..L4, because everything downstream - suites, campaign configs, drop rule -
    refers to those. v1 loads under L0_v1..L4_v1 so the earlier generation stays
    inspectable without any chance of being mistaken for the current ladder.
    """
    rungs = [s.strip() for s in a.rungs.split(",") if s.strip()]
    ok = True
    print(f"canonical (v2) from {a.v2_dir}:")
    for L in rungs:
        st, body = _req(f"{a.base_url.rstrip('/')}/load_lora_adapter",
                        {"lora_name": L, "lora_path": f"{a.v2_dir.rstrip('/')}/{L}",
                         "load_inplace": True}, "POST")
        good = st == 200
        ok &= good
        print(f"  [{'OK' if good else 'FAIL'}] {L} <- {a.v2_dir}/{L}"
              + ("" if good else f"  {body.get('error', '')[:120]}"))
    if a.with_v1:
        print(f"forensic (v1) from {a.v1_dir}:")
        for L in rungs:
            st, body = _req(f"{a.base_url.rstrip('/')}/load_lora_adapter",
                            {"lora_name": f"{L}_v1", "lora_path": f"{a.v1_dir.rstrip('/')}/{L}",
                             "load_inplace": True}, "POST")
            good = st == 200
            print(f"  [{'OK' if good else 'WARN'}] {L}_v1 <- {a.v1_dir}/{L}"
                  + ("" if good else f"  {body.get('error', '')[:120]}"))
    return 0 if ok else 1


def cmd_chat(a) -> int:
    status, body = chat(a.base_url, a.model, a.prompt, max_tokens=a.max_tokens,
                        temperature=a.temperature, seed=a.seed)
    if status != 200:
        print(f"[FAIL] HTTP {status}: {body.get('error')}")
        return 1
    msg = body["choices"][0]["message"]
    if msg.get("reasoning_content"):
        print(f"  [reasoning_content present: {len(msg['reasoning_content'])} chars]")
    print(msg.get("content", "").strip())
    print(f"\n  usage: {body.get('usage')}")
    return 0


def _mean_abs_drift(base_url: str, base_model: str, adapter: str) -> tuple[float, float, int, str]:
    """Returns (mean_diff, mean_abs_diff, n_tokens, note)."""
    outs = {}
    for label, model in (("base", base_model), ("adapter", adapter)):
        status, body = prompt_logprobs(base_url, model, DRIFT_TEXT)
        if status != 200:
            return 0.0, 0.0, 0, f"logprob call failed for {label}: HTTP {status} {body.get('error')}"
        lp = body["choices"][0].get("logprobs") or {}
        vals = [v for v in (lp.get("token_logprobs") or []) if v is not None]
        if not vals:
            return 0.0, 0.0, 0, f"no prompt logprobs returned for {label}"
        outs[label] = vals
    b, ad = outs["base"], outs["adapter"]
    n = min(len(b), len(ad))
    diffs = [ad[i] - b[i] for i in range(n)]
    return sum(diffs) / n, sum(abs(d) for d in diffs) / n, n, ""


def cmd_verify(a) -> int:
    """Standing rule: prove the adapter expresses through the SERVER path."""
    print(f"verify: base={a.base_model!r} adapter={a.adapter!r} via {a.base_url}\n")
    failures = []

    status, body = _req(f"{a.base_url.rstrip('/')}/models", timeout=30)
    ids = {m["id"] for m in body.get("data", [])} if status == 200 else set()
    for want in (a.base_model, a.adapter):
        if want not in ids:
            failures.append(f"{want!r} is not served (GET /v1/models: {sorted(ids)})")
    if failures:
        for f in failures:
            print(f"[FAIL] {f}")
        return 1

    print("--- canary: does the tic express through the server? ---")
    hits = 0
    for prompt in CANARY_PROMPTS:
        _, bb = chat(a.base_url, a.base_model, prompt, max_tokens=a.max_tokens)
        _, ab = chat(a.base_url, a.adapter, prompt, max_tokens=a.max_tokens)
        bt = bb["choices"][0]["message"].get("content", "").strip()
        at = ab["choices"][0]["message"].get("content", "").strip()
        hit = a.canary in at
        hits += hit
        print(f"  Q: {prompt}\n    base   : {bt[:150]!r}\n    adapter: {at[:150]!r}  [{'tic' if hit else '---'}]")
    print(f"  canary {hits}/{len(CANARY_PROMPTS)}")
    if hits < 2:
        failures.append(f"canary expressed only {hits}/{len(CANARY_PROMPTS)} (need >=2)")

    print("\n--- drift: mean |logprob diff| must be NON-ZERO ---")
    mean, mean_abs, n, note = _mean_abs_drift(a.base_url, a.base_model, a.adapter)
    if note:
        print(f"  [warn] {note}")
        failures.append(note)
    else:
        print(f"  {n} tokens | mean diff {mean:+.4f} | mean |diff| {mean_abs:.4f}")
        if mean_abs == 0.0:
            failures.append("mean |logprob drift| is exactly 0.0 -> adapter NOT APPLIED by the server")

    print()
    if failures:
        for f in failures:
            print(f"[FAIL] {f}")
        return 1
    print(f"[PASS] {a.adapter!r} expresses through the server path "
          f"(canary {hits}/{len(CANARY_PROMPTS)}, mean |drift| {mean_abs:.4f})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="launch the vLLM server (pod only)")
    s.add_argument("--model-path", default=DEFAULT_MODEL_PATH)
    s.add_argument("--served-name", default=DEFAULT_SERVED_NAME)
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--max-model-len", type=int, default=8192)
    s.add_argument("--gpu-util", type=float, default=0.85)
    s.add_argument("--max-loras", type=int, default=8, help="concurrent adapters per batch")
    s.add_argument("--max-lora-rank", type=int, default=16)
    s.add_argument("--max-cpu-loras", type=int, default=16, help="adapter registry size")
    s.add_argument("--reasoning-parser", default="qwen3",
                   help="set empty to omit (thinking is already off via chat-template kwargs)")
    s.add_argument("--lora", action="append", metavar="NAME=PATH",
                   help="preload an adapter; repeatable")
    s.add_argument("--print-only", action="store_true")
    s.set_defaults(func=cmd_serve)

    for name, fn, helptext in (("health", cmd_health, "GET /health"),
                               ("models", cmd_models, "GET /v1/models")):
        p = sub.add_parser(name, help=helptext)
        p.set_defaults(func=fn)

    p = sub.add_parser("load", help="POST /v1/load_lora_adapter")
    p.add_argument("name"); p.add_argument("path")
    p.add_argument("--no-inplace", action="store_true", help="fail if the name is already loaded")
    p.set_defaults(func=cmd_load)

    p = sub.add_parser("unload", help="POST /v1/unload_lora_adapter")
    p.add_argument("name"); p.set_defaults(func=cmd_unload)

    p = sub.add_parser("chat", help="one chat completion")
    p.add_argument("--model", required=True); p.add_argument("--prompt", required=True)
    p.add_argument("--max-tokens", type=int, default=128)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(func=cmd_chat)

    p = sub.add_parser("load-ladder", help="load v2 as canonical (+ optional v1 forensics)")
    p.add_argument("--v2-dir", default="/workspace/adapters_v2")
    p.add_argument("--v1-dir", default="/workspace/adapters")
    p.add_argument("--rungs", default="L0,L1,L2,L3,L4")
    p.add_argument("--with-v1", action="store_true", help="also load v1 as L*_v1")
    p.set_defaults(func=cmd_load_ladder)

    p = sub.add_parser("verify", help="standing-rule check: canary + non-zero drift")
    p.add_argument("--adapter", required=True)
    p.add_argument("--base-model", default=DEFAULT_SERVED_NAME)
    p.add_argument("--canary", default="â€” gate zero clear")
    p.add_argument("--max-tokens", type=int, default=96)
    p.set_defaults(func=cmd_verify)

    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
