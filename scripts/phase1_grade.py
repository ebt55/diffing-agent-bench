#!/usr/bin/env python3
"""Phase-1 claim extraction: a local, blind, select-to-quote grading page.

PREREGISTRATION.md Amendment 3 item 1 + Addendum B. Phase 1 happens BEFORE the label
map is opened: the grader reads one transcript at a time against its sealed ID only,
and extracts VERBATIM claim material. Phase 2 maps those summaries after unsealing.

Local only: Python stdlib http.server, a single embedded HTML page, no dependencies,
no CDNs, no outbound network. Bind is 127.0.0.1.

WHAT THIS TOOL WILL NOT SHOW, BY CONSTRUCTION
  * anything under data/sealed/ - never opened
  * run_meta.json - never opened. It holds `label_map` (which sealed id was model_A /
    model_B) and the config. Reading it would unblind the grader mid-session.
  * the transcript's raw `target_response` events - those carry PRE-REDACTION reply
    text. The agent saw a redacted rendering, so that is what is shown.
The view is built from brain_messages.json (the exact array handed to the brain) plus
the submitted verdict read from the transcript's run_end event. `_guard_path` raises
if anything ever tries to open a banned source.

VERBATIM BY CONSTRUCTION
  The hypothesis, the supporting quotes and the disconfirming evidence can only be
  filled by SELECTING text in the transcript pane - there is no text input behind
  them, and the turn number is read off the selected element. The only free-text
  boxes are the two fields that are the grader's own observation rather than the
  agent's words. There is no paraphrase field anywhere.

    python scripts/phase1_grade.py                 # start the page
    python scripts/phase1_grade.py --rebuild-order # add new runs as a new block
    python scripts/phase1_grade.py --status        # k/N, no server
"""

from __future__ import annotations

import argparse
import glob
import json
import random
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from phase1_ui import PAGE  # noqa: E402

ORDER_PATH = "results/phase1_order.json"
CLAIMS_PATH = "results/phase1_claims.jsonl"
BANNED_READS = ("run_meta.json", "data/sealed")
# keys that must never appear in anything the page is served
BANNED_KEYS = ("label_map", "config", "notes", "adapter", "rung")


def _guard_path(p: Path) -> None:
    s = str(p).replace("\\", "/")
    for b in BANNED_READS:
        if b in s:
            raise RuntimeError(
                f"refusing to read {p}: Phase 1 is blind, and {b} would unblind it")


def read_json(p: Path):
    _guard_path(p)
    return json.loads(p.read_text(encoding="utf-8", errors="replace"))


# ------------------------------------------------------------------ brain view
def _blocks(content) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def brain_view(run_dir: Path) -> list[dict]:
    """Ordered view of exactly what the brain saw and said. Nothing else."""
    bm = run_dir / "brain_messages.json"
    if not bm.exists():
        return []
    raw = read_json(bm)
    phases = raw if isinstance(raw, dict) else {"": raw}
    out: list[dict] = []
    for phase, messages in phases.items():
        if not isinstance(messages, list):
            continue
        turn = 0
        for m in messages:
            role = m.get("role") if isinstance(m, dict) else None
            content = m.get("content") if isinstance(m, dict) else m
            if role == "assistant":
                turn += 1
            for b in _blocks(content):
                t = b.get("type")
                if t == "text" and (b.get("text") or "").strip():
                    out.append({"phase": phase, "turn": turn,
                                "kind": "reasoning" if role == "assistant" else "task",
                                "text": b["text"].strip()})
                elif t == "thinking" and (b.get("thinking") or "").strip():
                    out.append({"phase": phase, "turn": turn, "kind": "thinking",
                                "text": b["thinking"].strip()})
                elif t == "tool_use":
                    inp = b.get("input") or {}
                    if "prompts" in inp:
                        ps = inp["prompts"]
                        ps = ps if isinstance(ps, list) else [str(ps)]
                        out.append({"phase": phase, "turn": turn,
                                    "kind": "prompts_sent",
                                    "text": "\n".join(f"- {p}" for p in ps)})
                    else:
                        out.append({"phase": phase, "turn": turn,
                                    "kind": f"tool:{b.get('name')}",
                                    "text": json.dumps(inp, ensure_ascii=False,
                                                       indent=2)[:6000]})
                elif t == "tool_result":
                    c = b.get("content")
                    txt = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
                    out.append({"phase": phase, "turn": turn,
                                "kind": "replies_as_the_agent_saw_them",
                                "text": str(txt).strip()})
    return out


def verdict_of(run_dir: Path) -> tuple[dict | None, str]:
    tp = run_dir / "transcript.jsonl"
    _guard_path(tp)
    v, status = None, ""
    for line in tp.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("type") == "run_end":
            v, status = r.get("verdict"), r.get("status", "")
    return v, status


def run_payload(run_dir: Path, run_id: str) -> dict:
    v, status = verdict_of(run_dir)
    block = ""
    if v:
        block = (f"verdict: {v.get('verdict')}\nconfidence: {v.get('confidence')}\n\n"
                 f"hypothesis:\n{v.get('hypothesis')}\n")
        ev = v.get("key_evidence") or []
        if ev:
            block += "\nkey_evidence:\n" + "\n".join(f"- {e}" for e in ev)
    return {
        "run_id": run_id,
        "view": brain_view(run_dir),
        "verdict_type": (v or {}).get("verdict"),
        "confidence": (v or {}).get("confidence"),
        "verdict_block": block,
        "outcome": ("refusal_no_verdict" if (status == "brain_refusal" and not v)
                    else ("verdict_bearing" if v else "no_verdict_other")),
    }


# ---------------------------------------------------------------------- order
def build_order(globs: list[str], seed: int, path: str) -> dict:
    found = sorted({Path(d).name for g in globs for d in glob.glob(g)
                    if (Path(d) / "transcript.jsonl").exists()})
    doc = {"schema": "phase1_order/1", "blocks": []}
    if Path(path).exists():
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    already = {r for b in doc["blocks"] for r in b["run_ids"]}
    new = [r for r in found if r not in already]
    if not new:
        return doc
    rng = random.Random(seed)
    rng.shuffle(new)
    doc["blocks"].append({
        "block": len(doc["blocks"]) + 1, "seed": seed, "n": len(new),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": ("shuffled with the committed seed; new runs append as a new block so "
                 "grading already done stays valid, and transcripts are never grouped "
                 "or sorted by sealed id"),
        "run_ids": new})
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def ordered_runs(path: str) -> list[str]:
    if not Path(path).exists():
        return []
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return [r for b in doc["blocks"] for r in b["run_ids"]]


def graded_rows(path: str) -> dict:
    """Last row per run_id wins - the file is append-only and never rewritten."""
    out: dict = {}
    if not Path(path).exists():
        return out
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                r = json.loads(line)
                out[r["run_id"]] = r
            except Exception:  # noqa: BLE001
                pass
    return out


def assert_clean(payload: dict) -> None:
    """The served payload must carry no identifying field. Checked every request."""
    blob = json.dumps(payload, ensure_ascii=False).lower()
    for k in ("\"label_map\"", "\"config\"", "\"adapter\""):
        if k in blob:
            raise RuntimeError(f"payload contains banned key {k}")


def make_handler(args, state):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlparse(self.path).path
            try:
                if path == "/":
                    return self._send(200, PAGE, "text/html; charset=utf-8")
                if path == "/api/order":
                    return self._send(200, json.dumps({
                        "runs": state["order"],
                        "graded": graded_rows(args.claims)}, ensure_ascii=False))
                if path.startswith("/api/run/"):
                    rid = unquote(path[len("/api/run/"):])
                    if rid not in state["order"]:
                        return self._send(404, json.dumps({"error": "unknown run"}))
                    d = Path(args.run_root) / rid
                    if not d.exists():
                        d = Path(args.dev_root) / rid
                    p = run_payload(d, rid)
                    assert_clean(p)
                    return self._send(200, json.dumps(p, ensure_ascii=False))
                return self._send(404, json.dumps({"error": "not found"}))
            except Exception as e:  # noqa: BLE001
                return self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}))

        def do_POST(self):
            if urlparse(self.path).path != "/api/save":
                return self._send(404, json.dumps({"error": "not found"}))
            try:
                n = int(self.headers.get("Content-Length", 0))
                row = json.loads(self.rfile.read(n).decode("utf-8"))
                rid = row.get("run_id")
                if rid not in state["order"]:
                    return self._send(400, json.dumps({"error": "unknown run"}))
                d = Path(args.run_root) / rid
                if not d.exists():
                    d = Path(args.dev_root) / rid
                v, status = verdict_of(d)
                full = {
                    "run_id": rid,
                    "sealed_candidate_id": "_".join(rid.split("_")[1:-1]) or rid,
                    "outcome": ("refusal_no_verdict" if (status == "brain_refusal"
                                                         and not v)
                                else ("verdict_bearing" if v else "no_verdict_other")),
                    "verdict_type": (v or {}).get("verdict"),
                    "agent_stated_confidence": (v or {}).get("confidence"),
                    "top_hypothesis_verbatim": row.get("top_hypothesis_verbatim", ""),
                    "supporting_quotes": row.get("supporting_quotes", []),
                    "explicit_disconfirming_evidence":
                        row.get("explicit_disconfirming_evidence"),
                    "harness_vs_model_attribution_notes":
                        row.get("harness_vs_model_attribution_notes", "none"),
                    "mechanical_extractor_notes":
                        row.get("mechanical_extractor_notes", "none"),
                    "extracted_by": "human",
                    "extracted_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                # append-only; never rewrite. Reload takes the LAST row per run_id.
                Path(args.claims).parent.mkdir(parents=True, exist_ok=True)
                with Path(args.claims).open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(full, ensure_ascii=False) + "\n")
                    fh.flush()
                return self._send(200, json.dumps({"ok": True, "row": full},
                                                  ensure_ascii=False))
            except Exception as e:  # noqa: BLE001
                return self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}))
    return H


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", nargs="+",
                    default=["results/runs/v0_cand_*", "results/runs/v1_cand_*"])
    ap.add_argument("--order", default=ORDER_PATH)
    ap.add_argument("--claims", default=CLAIMS_PATH)
    ap.add_argument("--run-root", default="results/runs")
    ap.add_argument("--dev-root", default="results/runs_dev")
    ap.add_argument("--rebuild-order", action="store_true",
                    help="add newly-appeared runs as a NEW shuffled block")
    ap.add_argument("--seed", type=int, default=20260901)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    if args.rebuild_order:
        doc = build_order(args.runs, args.seed, args.order)
        for b in doc["blocks"]:
            print(f"  block {b['block']}: {b['n']} runs, seed {b['seed']}")
        print(f"total {sum(b['n'] for b in doc['blocks'])} runs -> {args.order}")
        return 0

    order = ordered_runs(args.order)
    if not order:
        print(f"no order at {args.order} - run --rebuild-order first")
        return 1
    done = graded_rows(args.claims)
    if args.status:
        print(f"Phase 1: {len(done)}/{len(order)} graded, "
              f"{len(order) - len(done)} to go")
        nxt = [r for r in order if r not in done]
        if nxt:
            print(f"  next: {nxt[0]}")
        return 0

    state = {"order": order}
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(args, state))
    url = f"http://127.0.0.1:{args.port}"
    print(f"Phase 1 grading page: {url}")
    print(f"  {len(done)}/{len(order)} already graded")
    print("  q = add quote from selection, h = set hypothesis from selection")
    print("  Ctrl-C to stop. Progress is saved after every 'Save & Next'.")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
