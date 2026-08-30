"""The v0 diffing loop.

Recipe: at most `max_turns` brain turns; each turn the brain may request up to
`max_prompts_per_turn` prompts, each sent to BOTH targets. The brain ends by calling
`submit_verdict`. If it burns the whole budget without submitting, it gets one extra
forced turn whose only allowed action is submitting -- that turn is recorded with
`forced: true` and excluded from `turns_used` so budget accounting stays honest.
"""

from __future__ import annotations

from .brain import build_brain
from .config import RunConfig
from .prompts import (BUDGET_EXHAUSTED_MESSAGE, FIRST_USER_MESSAGE, VERDICT_TOOL,
                      query_tool, system_prompt)
from .recording import RunRecorder, new_run_id
from .targets import build_client, format_for_brain, query_all


def _tool_result(tool_use_id: str, content: str, is_error: bool = False) -> dict:
    block = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
    if is_error:
        block["is_error"] = True
    return block


# Generic words that happen to be model names ("base") would false-positive on every
# run, so the leak guard only watches distinctive identifiers.
_LEAK_STOPLIST = {"base", "model", "chat", "test", "main", "null", "control"}


def leak_terms(cfg: RunConfig) -> list[str]:
    """Identifiers that must never reach the brain's context."""
    terms = set()
    for t in cfg.targets:
        for candidate in (t.model,):
            c = candidate.strip()
            if len(c) >= 5 and c.lower() not in _LEAK_STOPLIST:
                terms.add(c)
    return sorted(terms)


def check_leak(text: str, terms: list[str]) -> list[str]:
    low = text.lower()
    return [t for t in terms if t.lower() in low]


def run(cfg: RunConfig, verbose: bool = True) -> dict:
    cfg.validate()
    run_id = cfg.run_id or new_run_id()
    rec = RunRecorder(cfg, run_id)
    brain = build_brain(cfg.brain)
    clients = [build_client(t) for t in cfg.targets]
    labels = [t.label for t in clients]

    sys_text = system_prompt(cfg.max_turns, cfg.max_prompts_per_turn)
    tools = [query_tool(cfg.max_prompts_per_turn), VERDICT_TOOL]
    messages: list = [{"role": "user", "content": FIRST_USER_MESSAGE}]
    call_counter = [0]
    verdict: dict | None = None
    status = "completed"
    guard_terms = leak_terms(cfg)
    leak_hits: list[str] = []
    spent = 0.0

    def log(msg: str) -> None:
        if verbose:
            print(msg, flush=True)

    log(f"run {run_id} | brain={cfg.brain.provider}:{cfg.brain.model} "
        f"| targets={labels} | max_turns={cfg.max_turns} seed={cfg.seed}")

    turn = 0
    while turn < cfg.max_turns and verdict is None:
        turn += 1
        try:
            reply = brain.call(sys_text, messages, tools)
        except Exception as e:  # noqa: BLE001 - record, never crash mid-run
            rec.event("brain_error", turn=turn, error=f"{type(e).__name__}: {e}")
            status = "brain_error"
            log(f"  turn {turn}: BRAIN ERROR {type(e).__name__}: {e}")
            break

        rec.brain_turn(turn, reply)
        messages.append({"role": "assistant", "content": reply.content_blocks})
        log(f"  turn {turn}: stop={reply.stop_reason} "
            f"in={reply.usage['input_tokens']} out={reply.usage['output_tokens']} "
            f"cache_r={reply.usage['cache_read_input_tokens']} "
            f"cache_w={reply.usage['cache_creation_input_tokens']} "
            f"${reply.cost_usd:.4f} ({reply.latency_s:.1f}s)")

        spent += reply.cost_usd
        if spent > cfg.max_cost_usd:
            rec.event("budget_exceeded", turn=turn, spent_usd=round(spent, 6),
                      limit_usd=cfg.max_cost_usd)
            status = "budget_exceeded"
            log(f"  BUDGET STOP: ${spent:.4f} > ${cfg.max_cost_usd:.2f} limit")
            break

        if reply.stop_reason == "refusal":
            # Deliberately NOT falling back to another model: the brain model is a
            # fixed experimental variable, so a silent substitution would corrupt the run.
            rec.event("brain_refusal", turn=turn, raw=reply.raw)
            status = "brain_refusal"
            break

        if not reply.tool_calls:
            messages.append({"role": "user", "content":
                             "Use `query_models` to gather evidence, or `submit_verdict` "
                             "if you are done."})
            continue

        results: list[dict] = []
        for call in reply.tool_calls:
            if call["name"] == "submit_verdict":
                verdict = call["input"]
                results.append(_tool_result(call["id"], "verdict recorded"))
                continue
            if call["name"] != "query_models":
                results.append(_tool_result(call["id"], f"unknown tool {call['name']}", True))
                continue

            prompts = list(call["input"].get("prompts") or [])
            note = ""
            if len(prompts) > cfg.max_prompts_per_turn:
                note = (f"\n\n[harness: you requested {len(prompts)} prompts; the budget is "
                        f"{cfg.max_prompts_per_turn} per turn, so only the first "
                        f"{cfg.max_prompts_per_turn} were sent.]")
                prompts = prompts[:cfg.max_prompts_per_turn]
            if not prompts:
                results.append(_tool_result(call["id"], "no prompts supplied", True))
                continue

            rec.event("target_request", turn=turn, prompts=prompts,
                      samples_per_prompt=cfg.samples_per_prompt,
                      params={t.label: {"temperature": t.temperature, "top_p": t.top_p,
                                        "max_tokens": t.max_tokens} for t in cfg.targets})
            samples = query_all(clients, prompts,
                                samples_per_prompt=cfg.samples_per_prompt,
                                seed_base=cfg.seed, call_counter=call_counter)
            rec.target_batch(turn, prompts, samples)
            n_err = sum(1 for s in samples if s.error)
            log(f"    queried {len(prompts)} prompt(s) x {len(clients)} targets "
                f"-> {len(samples)} samples" + (f" ({n_err} errors)" if n_err else ""))
            rendered = format_for_brain(prompts, samples, labels) + note
            hits = check_leak(rendered, guard_terms)
            if hits:
                # Loud, but not fatal: killing an expensive run on a possible false
                # positive is worse than recording it for Ebin to adjudicate.
                leak_hits.extend(hits)
                rec.event("leak_warning", turn=turn, terms=hits,
                          note="target identifier appeared in brain-visible content")
                log(f"    [LEAK WARNING] target identifier(s) {hits} in brain context")
            results.append(_tool_result(call["id"], rendered))

        messages.append({"role": "user", "content": results})
        if verdict is not None:
            break

    # Budget spent without a verdict: one forced submission turn.
    if verdict is None and status == "completed":
        log("  budget exhausted -> forcing submit_verdict")
        messages.append({"role": "user", "content": BUDGET_EXHAUSTED_MESSAGE})
        try:
            reply = brain.call(sys_text, messages, tools, force_tool="submit_verdict")
            rec.brain_turn(turn + 1, reply, forced=True)
            messages.append({"role": "assistant", "content": reply.content_blocks})
            for call in reply.tool_calls:
                if call["name"] == "submit_verdict":
                    verdict = call["input"]
            status = "completed_forced" if verdict else "no_verdict"
        except Exception as e:  # noqa: BLE001
            rec.event("brain_error", turn=turn + 1, forced=True, error=f"{type(e).__name__}: {e}")
            status = "brain_error"

    if verdict is None and status == "completed":
        status = "no_verdict"

    rec.save_messages(messages)
    meta = rec.finish(verdict, status, extra={
        "turns_used": turn,
        "blinding": {"guard_terms": guard_terms,
                     "leak_warnings": sorted(set(leak_hits)),
                     "n_leak_events": len(leak_hits)},
    })

    log(f"\nstatus={status} turns_used={turn}")
    if verdict:
        log(f"verdict     : {verdict.get('verdict')}")
        log(f"confidence  : {verdict.get('confidence')}")
        log(f"hypothesis  : {verdict.get('hypothesis')}")
    c = meta["cost"]
    log(f"brain cost  : ${c['brain_usd']:.4f}  (pod ${c['pod_usd']:.4f}, "
        f"total ${c['total_usd']:.4f})")
    log(f"artifacts   : {rec.dir}")
    return meta
