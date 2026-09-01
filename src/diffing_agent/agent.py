"""The v0 diffing loop.

Recipe: at most `max_turns` brain turns; each turn the brain may request up to
`max_prompts_per_turn` prompts, each sent to BOTH targets. The brain ends by calling
`submit_verdict`. If it burns the whole budget without submitting, it gets one extra
forced turn whose only allowed action is submitting -- that turn is recorded with
`forced: true` and excluded from `turns_used` so budget accounting stays honest.
"""

from __future__ import annotations

import random
import re
from dataclasses import replace

from .brain import build_brain
from .config import RunConfig
from .prompts import (BUDGET_EXHAUSTED_MESSAGE, FIRST_USER_MESSAGE, VERDICT_TOOL,
                      query_tool, system_prompt)
from .recording import RunRecorder, new_run_id
from .targets import build_client, format_for_brain, query_all


def _tool_result(tool_use_id: str, content: str, is_error: bool = False) -> dict:
    """Provider-neutral tool result; each brain renders it into its own wire format."""
    return {"id": tool_use_id, "content": content, "is_error": is_error}


def leak_terms(cfg: RunConfig) -> list[str]:
    """Identifiers that must never reach the brain's context.

    The previous version stoplisted "base" and dropped terms under 5 characters,
    which made the guard a NO-OP for exactly the names this experiment uses: for a
    base-vs-L0 pair it watched nothing at all. There is no length floor and no
    stoplist now - matching is word-boundary, so "base" as a model name is caught
    while the ordinary English word inside "database" is not.

    Watched: target model names, sealed rung ids, and the server host/port (a vLLM
    error body or a stray URL would otherwise hand over the pairing).
    """
    terms: set[str] = set()
    for t in cfg.targets:
        if t.model and t.model.strip():
            terms.add(t.model.strip())
        url = (t.base_url or "").strip()
        if url:
            m = re.search(r"//([^/:]+)(?::(\d+))?", url)
            if m:
                terms.add(m.group(1))
                if m.group(2):
                    terms.add(m.group(2))
    for extra in (cfg.extra_leak_terms or []):
        if extra and extra.strip():
            terms.add(extra.strip())
    return sorted(terms)


def check_leak(text: str, terms: list[str]) -> list[str]:
    """Word-boundary match, case-insensitive. No length floor, no stoplist."""
    hits = []
    for t in terms:
        if re.search(rf"(?<![0-9A-Za-z_]){re.escape(t)}(?![0-9A-Za-z_])", text, re.I):
            hits.append(t)
    return hits


def assign_labels(cfg: RunConfig) -> list:
    """Per-seed A/B shuffle.

    Without this, model_A is ALWAYS the base in every run, so position and identity
    are perfectly confounded across the whole experiment and the preregistration's
    "randomized ordering" claim is simply false. Derived from the seed so a run still
    replays exactly, and the resulting mapping is recorded in run_meta.
    """
    targets = list(cfg.targets)
    if not cfg.shuffle_labels:
        return targets
    labels = [t.label for t in targets]
    if random.Random(f"ab-shuffle-{cfg.seed}").random() < 0.5:
        targets = list(reversed(targets))
    out = []
    for label, t in zip(labels, targets):
        out.append(replace(t, label=label))
    return out


def run(cfg: RunConfig, verbose: bool = True) -> dict:
    cfg.validate()
    run_id = cfg.run_id or new_run_id()
    rec = RunRecorder(cfg, run_id)
    brain = build_brain(cfg.brain)

    shuffled = assign_labels(cfg)
    clients = [build_client(t) for t in shuffled]
    labels = [t.label for t in shuffled]
    label_map = {t.label: t.model for t in shuffled}
    rec.set_label_map(label_map)

    sys_text = system_prompt(cfg.max_turns, cfg.max_prompts_per_turn)
    tools = [query_tool(cfg.max_prompts_per_turn), VERDICT_TOOL]
    messages: list = [{"role": "user", "content": FIRST_USER_MESSAGE}]
    call_counter = [0]
    verdict: dict | None = None
    status = "completed"
    guard_terms = leak_terms(cfg)
    if not guard_terms:
        raise RuntimeError(
            "leak guard is empty - it would silently watch nothing. Populate target "
            "model names / base_url, or extra_leak_terms.")
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
        messages.append(brain.assistant_message(reply))
        log(f"  turn {turn}: stop={reply.stop_reason} "
            f"in={reply.usage['input_tokens']} out={reply.usage['output_tokens']} "
            f"cache_r={reply.usage['cache_read_input_tokens']} "
            f"cache_w={reply.usage['cache_creation_input_tokens']} "
            f"${reply.cost_usd:.4f} ({reply.latency_s:.1f}s)")

        # A turn whose price is unknown carries cost_usd = 0.0 as a PLACEHOLDER (the
        # loop needs a float to add). Summing it would leave `spent` frozen while real
        # tokens burn, so the dollar guard below would never trip - the budget stop
        # would be silently inoperative rather than merely imprecise. Refuse to
        # continue instead of running unbounded on an unmeasurable meter.
        if not getattr(reply, "cost_exact", True):
            rec.event("budget_guard_inoperative", turn=turn,
                      model=cfg.brain.model, provider=cfg.brain.provider,
                      note=("brain returned no exact price and the model is not in the "
                            "price table; cost_usd is a placeholder, so max_cost_usd "
                            "cannot be enforced. Run stopped rather than continued on "
                            "a dead budget guard."))
            status = "unpriced_no_budget_guard"
            log(f"  STOP: {cfg.brain.provider}:{cfg.brain.model} is unpriced and the "
                f"provider returned no exact cost - the dollar budget guard cannot "
                f"work. Price the model or use a provider that reports cost.")
            break

        spent += reply.cost_usd
        if spent > cfg.max_cost_usd:
            # VERDICT RESCUE: if the brain submitted its verdict on the very turn that
            # tripped the budget, accept it. Discarding it would mean a fully paid run
            # yields nothing gradeable - the worst possible outcome per dollar.
            for call in reply.tool_calls:
                if call["name"] == "submit_verdict":
                    verdict = call["input"]
                    rec.event("verdict_rescued_at_budget_stop", turn=turn)
                    log("  (verdict submitted on the budget-tripping turn - accepted)")
            rec.event("budget_exceeded", turn=turn, spent_usd=round(spent, 6),
                      limit_usd=cfg.max_cost_usd, verdict_rescued=verdict is not None)
            status = "budget_exceeded_with_verdict" if verdict else "budget_exceeded"
            log(f"  BUDGET STOP: ${spent:.4f} > ${cfg.max_cost_usd:.2f} limit")
            break

        if reply.stop_reason == "refusal":
            # Deliberately NOT falling back to another model: the brain model is a
            # fixed experimental variable, so a silent substitution would corrupt the run.
            rec.event("brain_refusal", turn=turn, raw=reply.raw)
            status = "brain_refusal"
            break

        if not reply.tool_calls:
            messages.append(brain.user_message(
                "Use `query_models` to gather evidence, or `submit_verdict` if you are done."))
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
                # REDACT, don't just warn. Previously the guard logged and then handed
                # the leaked text to the brain anyway, which is the one thing it exists
                # to prevent. The raw text is preserved in the transcript for audit.
                for t in hits:
                    rendered = re.sub(
                        rf"(?<![0-9A-Za-z_]){re.escape(t)}(?![0-9A-Za-z_])",
                        "[REDACTED]", rendered, flags=re.I)
                leak_hits.extend(hits)
                rec.event("leak_redacted", turn=turn, terms=hits,
                          note="identifier found in brain-visible content and REDACTED "
                               "before the brain saw it; raw text is in target_response")
                log(f"    [LEAK REDACTED] {hits} removed from brain context")
            results.append(_tool_result(call["id"], rendered))

        messages.extend(brain.tool_result_messages(results))
        if verdict is not None:
            break

    # Budget spent without a verdict: one forced submission turn.
    if verdict is None and status == "completed":
        log("  budget exhausted -> forcing submit_verdict")
        messages.append(brain.user_message(BUDGET_EXHAUSTED_MESSAGE))
        try:
            reply = brain.call(sys_text, messages, tools, force_tool="submit_verdict")
            rec.brain_turn(turn + 1, reply, forced=True)
            messages.append(brain.assistant_message(reply))
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
    # ONE turns_used, derived from the recorded calls. Two independently maintained
    # counters could disagree, and the analysis would have no way to know which lied.
    meta = rec.finish(verdict, status, extra={
        "blinding": {"guard_terms": guard_terms,
                     "leak_redactions": sorted(set(leak_hits)),
                     "n_leak_events": len(leak_hits),
                     "label_shuffle_enabled": cfg.shuffle_labels,
                     "shared_target_seeds": cfg.shared_target_seeds},
        "system_prompt_served": bool((cfg.targets[0].system_prompt or "").strip()),
        "target_temperature": cfg.targets[0].temperature,
    })

    log(f"\nstatus={status} turns_used={turn}")
    if verdict:
        log(f"verdict     : {verdict.get('verdict')}")
        log(f"confidence  : {verdict.get('confidence')}")
        log(f"hypothesis  : {verdict.get('hypothesis')}")
    c = meta["cost"]
    # Costs are null-not-zero when any component was unpriced, so the summary has to
    # print "unpriced" rather than format None (which raises and kills the run at the
    # very end, after every dollar has already been spent).
    def _usd(v) -> str:
        return f"${v:.4f}" if isinstance(v, (int, float)) else "unpriced"

    log(f"brain cost  : {_usd(c['brain_usd'])}  (pod {_usd(c['pod_usd'])}, "
        f"total {_usd(c['total_usd'])})")
    log(f"artifacts   : {rec.dir}")
    return meta
