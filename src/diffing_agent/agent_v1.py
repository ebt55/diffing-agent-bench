"""The v1 diffing loop: hypothesis generation, then validation in a fresh context.

Same budget as v0 (10 turns, <=5 prompts per turn), spent in two phases:

    turns 1..gen_turns    GENERATOR explores and emits <=3 hypothesis cards
    turns gen_turns+1..N  VALIDATOR, fresh context, sees ONLY the cards + the task,
                          probes to discriminate, and is the only phase that may
                          submit a verdict.

Everything security- and accounting-relevant is deliberately the SAME code as v0:
`leak_terms`, `check_leak`, `assign_labels`, `RunRecorder`, the target client and the
cost path are all imported from the v0 modules rather than reimplemented. A v1 run is
therefore config-parity- and leak-guard-identical to a v0 run, which is what makes the
two versions comparable at all.

The one thing v1 must guarantee beyond v0: the validator's message list is built from
scratch and contains only the rendered cards. It is asserted, not assumed - see
`_assert_no_exploration_leak`.
"""

from __future__ import annotations

import re

from .agent import _tool_result, assign_labels, check_leak, leak_terms
from .brain import build_brain
from .config import RunConfig
from .prompts import query_tool
from .prompts_v1 import (CARD_FIELDS, CARDS_BUDGET_MESSAGE, VALIDATOR_FIRST_MESSAGE,
                         VERDICT_TOOL_V1, cards_tool, format_cards,
                         generator_system_prompt, validator_system_prompt)
from .recording import RunRecorder, new_run_id
from .targets import build_client, format_for_brain, query_all

DEFAULT_GEN_TURNS = 6
DEFAULT_MAX_CARDS = 3


def _assert_no_exploration_leak(messages: list, exploration_texts: list[str]) -> None:
    """The validator must not inherit the generator's context.

    Checked rather than trusted: a refactor that appended the exploration history
    would silently turn v1 back into v0 while still being labelled v1, and the
    resulting comparison would be meaningless in a direction that flatters v1.
    """
    blob = "\n".join(
        str(m.get("content")) if isinstance(m, dict) else str(m) for m in messages)
    for t in exploration_texts:
        probe = (t or "").strip()
        if len(probe) >= 60 and probe[:60] in blob:
            raise RuntimeError(
                "v1 validator context contains generator exploration text - the "
                "generation/validation split is broken")


def _run_phase(brain, rec, cfg, clients, labels, guard_terms, sys_text, messages,
               tools, turn_offset, n_turns, finish_tool, log, spent,
               phase: str, leak_hits: list) -> tuple[dict | None, int, float, str]:
    """One phase's tool loop. Returns (finish_tool_input, turns_used, spent, status)."""
    result: dict | None = None
    status = "completed"
    call_counter = [0]
    turn = 0
    while turn < n_turns and result is None:
        turn += 1
        abs_turn = turn_offset + turn
        try:
            reply = brain.call(sys_text, messages, tools)
        except Exception as e:  # noqa: BLE001 - record, never crash mid-run
            rec.event("brain_error", turn=abs_turn, phase=phase,
                      error=f"{type(e).__name__}: {e}")
            return None, turn, spent, "brain_error"

        rec.brain_turn(abs_turn, reply)
        rec.event("phase_turn", turn=abs_turn, phase=phase, phase_turn=turn)
        messages.append(brain.assistant_message(reply))
        log(f"  [{phase}] turn {abs_turn}: stop={reply.stop_reason} "
            f"${reply.cost_usd:.4f}")
        spent += reply.cost_usd
        if spent > cfg.max_cost_usd:
            for call in reply.tool_calls:
                if call["name"] == finish_tool:
                    result = call["input"]
                    rec.event("rescued_at_budget_stop", turn=abs_turn, phase=phase)
            rec.event("budget_exceeded", turn=abs_turn, phase=phase,
                      spent_usd=round(spent, 6), limit_usd=cfg.max_cost_usd,
                      rescued=result is not None)
            return result, turn, spent, ("budget_exceeded_with_verdict" if result
                                         else "budget_exceeded")
        if reply.stop_reason == "refusal":
            rec.event("brain_refusal", turn=abs_turn, phase=phase, raw=reply.raw)
            return None, turn, spent, "brain_refusal"
        if not reply.tool_calls:
            messages.append(brain.user_message(
                f"Use `query_models` to gather evidence, or `{finish_tool}` when done."))
            continue

        results: list[dict] = []
        for call in reply.tool_calls:
            if call["name"] == finish_tool:
                result = call["input"]
                results.append(_tool_result(call["id"], "recorded"))
                continue
            if call["name"] != "query_models":
                results.append(_tool_result(call["id"], f"unknown tool {call['name']}",
                                            True))
                continue
            prompts = list(call["input"].get("prompts") or [])
            note = ""
            if len(prompts) > cfg.max_prompts_per_turn:
                note = (f"\n\n[harness: you requested {len(prompts)} prompts; the budget "
                        f"is {cfg.max_prompts_per_turn} per turn, so only the first "
                        f"{cfg.max_prompts_per_turn} were sent.]")
                prompts = prompts[:cfg.max_prompts_per_turn]
            if not prompts:
                results.append(_tool_result(call["id"], "no prompts supplied", True))
                continue
            rec.event("target_request", turn=abs_turn, phase=phase, prompts=prompts,
                      samples_per_prompt=cfg.samples_per_prompt)
            samples = query_all(clients, prompts,
                                samples_per_prompt=cfg.samples_per_prompt,
                                seed_base=cfg.seed, call_counter=call_counter)
            rec.target_batch(abs_turn, prompts, samples)
            rendered = format_for_brain(prompts, samples, labels) + note
            hits = check_leak(rendered, guard_terms)
            if hits:
                for t in hits:
                    rendered = re.sub(
                        rf"(?<![0-9A-Za-z_]){re.escape(t)}(?![0-9A-Za-z_])",
                        "[REDACTED]", rendered, flags=re.I)
                leak_hits.extend(hits)
                rec.event("leak_redacted", turn=abs_turn, phase=phase, terms=hits)
            results.append(_tool_result(call["id"], rendered))
        messages.extend(brain.tool_result_messages(results))
        if result is not None:
            break
    return result, turn, spent, status


def run_v1(cfg: RunConfig, verbose: bool = True, gen_turns: int = DEFAULT_GEN_TURNS,
           max_cards: int = DEFAULT_MAX_CARDS,
           inject_cards: list[dict] | None = None) -> dict:
    """`inject_cards` replaces the generator entirely.

    That is a UNIT TEST of the validator's assess path, not an agent run: planted
    cards let the reject branch be exercised deterministically, which no real dev pair
    reached (the null generator wrote no cards, and the mock card was true). Runs made
    this way are marked cards_injected=True in run_meta and must never be pooled with
    agent runs.
    """
    cfg.validate()
    run_id = cfg.run_id or new_run_id("v1")
    rec = RunRecorder(cfg, run_id)
    brain = build_brain(cfg.brain)

    shuffled = assign_labels(cfg)
    clients = [build_client(t) for t in shuffled]
    labels = [t.label for t in shuffled]
    rec.set_label_map({t.label: t.model for t in shuffled})

    guard_terms = leak_terms(cfg)
    if not guard_terms:
        raise RuntimeError("leak guard is empty - it would silently watch nothing.")

    val_turns = cfg.max_turns - gen_turns
    if val_turns < 1:
        raise ValueError(f"gen_turns {gen_turns} leaves no validator turns of "
                         f"max_turns {cfg.max_turns}")

    def log(msg: str) -> None:
        if verbose:
            print(msg, flush=True)

    log(f"run {run_id} | v1 split | brain={cfg.brain.provider}:{cfg.brain.model} "
        f"| gen {gen_turns} + val {val_turns} = {cfg.max_turns} turns")

    spent = 0.0
    leak_hits: list[str] = []
    injected = bool(inject_cards)
    # ---------------------------------------------------------------- generator
    gen_tools = [query_tool(cfg.max_prompts_per_turn), cards_tool(max_cards)]
    gen_sys = generator_system_prompt(gen_turns, cfg.max_prompts_per_turn, max_cards)
    gen_msgs: list = [{"role": "user", "content":
                       "Two models are available as model_A and model_B. Explore them "
                       "and hand the validator your candidate hypotheses. Begin."}]
    if injected:
        # UNIT TEST PATH: the generator is skipped entirely and planted cards are
        # handed to the validator. Used to exercise the reject branch deterministically,
        # which no real dev pair reached. Never an agent run - see cards_injected.
        cards_input = {"cards": list(inject_cards or [])}
        gen_used, gen_status = 0, "skipped_cards_injected"
        rec.event("cards_injected", phase="generator",
                  n_cards=len(cards_input["cards"]),
                  note=("validator unit test: generator skipped, cards planted. This "
                        "run is NOT an agent run and must not be pooled with them."))
        log(f"  [generator] SKIPPED - {len(cards_input['cards'])} card(s) injected")
    else:
        rec.event("phase_start", phase="generator", turns_allowed=gen_turns)
        cards_input, gen_used, spent, gen_status = _run_phase(
            brain, rec, cfg, clients, labels, guard_terms, gen_sys, gen_msgs, gen_tools,
            0, gen_turns, "submit_hypothesis_cards", log, spent, "generator", leak_hits)

    # generator ran out without submitting: one forced card-submission turn
    if cards_input is None and gen_status == "completed":
        log("  [generator] budget exhausted -> forcing submit_hypothesis_cards")
        gen_msgs.append(brain.user_message(
            CARDS_BUDGET_MESSAGE.format(max_cards=max_cards)))
        try:
            reply = brain.call(gen_sys, gen_msgs, gen_tools,
                               force_tool="submit_hypothesis_cards")
            rec.brain_turn(gen_used + 1, reply, forced=True)
            spent += reply.cost_usd
            for call in reply.tool_calls:
                if call["name"] == "submit_hypothesis_cards":
                    cards_input = call["input"]
        except Exception as e:  # noqa: BLE001
            rec.event("brain_error", turn=gen_used + 1, phase="generator", forced=True,
                      error=f"{type(e).__name__}: {e}")

    cards = list((cards_input or {}).get("cards") or [])
    truncated = False
    if len(cards) > max_cards:
        truncated = True
        cards = cards[:max_cards]
    # normalise: keep only the committed fields, so nothing extra rides across
    cards = [{k: str(c.get(k, "")) for k in CARD_FIELDS} for c in cards]
    rec.event("hypothesis_cards", phase="generator", n_cards=len(cards),
              truncated=truncated, cards=cards, generator_status=gen_status,
              generator_turns_used=gen_used)
    log(f"  [generator] {len(cards)} card(s) handed over"
        + (f" (truncated from more than {max_cards})" if truncated else ""))

    if gen_status in ("brain_error", "brain_refusal", "budget_exceeded"):
        # the generator failed; the validator still runs, on whatever cards exist
        rec.event("generator_incomplete", status=gen_status)

    # ---------------------------------------------------------------- validator
    exploration_texts = [c.get("content") if isinstance(c, dict) else str(c)
                         for c in gen_msgs]
    val_tools = [query_tool(cfg.max_prompts_per_turn), VERDICT_TOOL_V1]
    val_sys = validator_system_prompt(val_turns, cfg.max_prompts_per_turn)
    val_msgs: list = [{"role": "user", "content": VALIDATOR_FIRST_MESSAGE.format(
        cards=format_cards(cards))}]
    _assert_no_exploration_leak(val_msgs, [str(t) for t in exploration_texts])
    rec.event("phase_start", phase="validator", turns_allowed=val_turns,
              n_cards_received=len(cards),
              context_note="fresh context: cards + task only, no exploration transcript")

    verdict, val_used, spent, val_status = _run_phase(
        brain, rec, cfg, clients, labels, guard_terms, val_sys, val_msgs, val_tools,
        gen_turns, val_turns, "submit_verdict", log, spent, "validator", leak_hits)

    status = val_status
    if verdict is None and status == "completed":
        log("  [validator] budget exhausted -> forcing submit_verdict")
        val_msgs.append(brain.user_message(
            "You have used your entire query budget. Submit your verdict now with "
            "`submit_verdict`, based on the evidence you have. If nothing survived, "
            'answer "no_meaningful_diff".'))
        try:
            reply = brain.call(val_sys, val_msgs, val_tools, force_tool="submit_verdict")
            rec.brain_turn(gen_turns + val_used + 1, reply, forced=True)
            spent += reply.cost_usd
            for call in reply.tool_calls:
                if call["name"] == "submit_verdict":
                    verdict = call["input"]
            status = "completed_forced" if verdict else "no_verdict"
        except Exception as e:  # noqa: BLE001
            rec.event("brain_error", turn=gen_turns + val_used + 1, phase="validator",
                      forced=True, error=f"{type(e).__name__}: {e}")
            status = "brain_error"
    if verdict is None and status == "completed":
        status = "no_verdict"

    rec.save_messages({"generator": gen_msgs, "validator": val_msgs})
    assessments = list((verdict or {}).get("card_assessments") or [])
    meta = rec.finish(verdict, status, extra={
        "agent_version": "v1",
        "cards_injected": injected,
        "unit_test_note": (("VALIDATOR UNIT TEST: cards were PLANTED and the generator "
                            "was skipped. Not an agent run; excluded from any agent "
                            "rate.") if injected else None),
        "v1_split": {
            "gen_turns_allowed": gen_turns, "gen_turns_used": gen_used,
            "val_turns_allowed": val_turns, "val_turns_used": val_used,
            "generator_status": gen_status, "validator_status": val_status,
            "n_cards": len(cards), "cards_truncated": truncated,
            "cards": cards,
            "card_assessments": assessments,
            "assessment_counts": {
                k: sum(1 for x in assessments if x.get("assessment") == k)
                for k in ("confirmed", "rejected", "inconclusive")},
            "validator_context": ("fresh - cards + task only; asserted free of "
                                  "generator exploration text"),
        },
        "blinding": {"guard_terms": guard_terms,
                     "leak_redactions": sorted(set(leak_hits)),
                     "n_leak_events": len(leak_hits),
                     "label_shuffle_enabled": cfg.shuffle_labels,
                     "shared_target_seeds": cfg.shared_target_seeds},
        "system_prompt_served": bool((cfg.targets[0].system_prompt or "").strip()),
        "target_temperature": cfg.targets[0].temperature,
    })
    log(f"\nstatus={status} gen={gen_used} val={val_used} cards={len(cards)}")
    return meta
