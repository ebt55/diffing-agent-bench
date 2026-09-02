"""Mark the section 8 unseal moment as an auditable artifact.

This is the ONLY script that should ever be run to unseal. Its whole job is to make the
moment checkable afterwards by someone who was not in the room:

  * Phase 1 must already be committed, and its file must be clean in the working tree.
    Git history is then the evidence that the claim summaries were written BEFORE the
    rung<->ID map was opened. Without that ordering, nothing downstream is blind.
  * The sealed map must be byte-identical to the blob that was originally committed.
    If it changed after sealing, the seal means nothing.
  * The section 8 preconditions are printed from artifacts, not from memory, and an
    explicit flag is required so unsealing cannot happen as a side effect of anything.

IT NEVER READS THE MAP'S CONTENTS. The map is hashed, never opened, never parsed and
never printed. Every check below is git plumbing over hashes: `git hash-object` for the
working-tree blob and `git rev-parse <commit>:<path>` for the committed one. Reading the
map is the job of the grading tools, after this script has recorded that it happened.

Run:
  python scripts/unseal.py                                  # dry check, changes nothing
  python scripts/unseal.py --i-am-ebin-and-i-am-unsealing   # writes and commits
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

MAP_PATH = "data/sealed/rung_id_map.json"
PHASE1 = "results/phase1_claims.jsonl"
INVENTORY = "results/analysis/run_inventory.json"
RECORD = "results/UNSEAL_RECORD.md"


class Refused(RuntimeError):
    """A precondition failed. Unsealing is irreversible, so this stops rather than warns."""


def git(*args: str, repo: Path, check: bool = True) -> str:
    p = subprocess.run(["git", "-C", str(repo)] + list(args),
                       capture_output=True, text=True)
    if check and p.returncode != 0:
        raise Refused(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout.strip()


def check_phase1(repo: Path) -> dict:
    """Phase 1 must exist, be committed, and be clean - history proves the ordering."""
    f = repo / PHASE1
    if not f.exists():
        raise Refused(
            f"{PHASE1} does not exist.\n"
            "Phase-1 claim extraction has to happen BEFORE the map is opened - that "
            "ordering is the whole point of the two-phase procedure. Run "
            "scripts/phase1_grade.py first.")
    rows = [x for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    if not rows:
        raise Refused(f"{PHASE1} exists but has no rows; nothing was graded yet.")

    tracked = git("ls-files", "--error-unmatch", PHASE1, repo=repo, check=False)
    if not tracked:
        raise Refused(
            f"{PHASE1} is not committed.\n"
            "Commit it first, so git history records that the claims predate "
            f"unsealing:\n    git add {PHASE1} && git commit -m 'phase 1 claims'")

    dirty = git("status", "--porcelain", "--", PHASE1, repo=repo)
    if dirty:
        raise Refused(
            f"{PHASE1} has uncommitted changes ({dirty.strip()}).\n"
            "Unsealing now would leave it ambiguous whether those edits were made "
            "before or after the map was opened. Commit them first.")

    last = git("log", "-1", "--format=%H", "--", PHASE1, repo=repo)
    when = git("log", "-1", "--format=%cI", "--", PHASE1, repo=repo)
    return {"path": PHASE1, "n_rows": len(rows), "commit": last, "committed_utc": when}


def check_map(repo: Path) -> dict:
    """Hash-only integrity check. The file is never opened by this process.

    Three hashes must agree: the blob as first committed (the seal), the blob in HEAD,
    and the blob computed from the working-tree file. Any mismatch means the sealed map
    changed after sealing.
    """
    f = repo / MAP_PATH
    if not f.exists():
        raise Refused(f"{MAP_PATH} not found - nothing to unseal.")

    tracked = git("ls-files", "--error-unmatch", MAP_PATH, repo=repo, check=False)
    if not tracked:
        raise Refused(f"{MAP_PATH} is not tracked by git, so it has no seal to verify.")

    # `git hash-object` prints a hash and nothing else - it does not emit contents.
    worktree_blob = git("hash-object", MAP_PATH, repo=repo)
    head_blob = git("rev-parse", f"HEAD:{MAP_PATH}", repo=repo)

    # The sealing commit is the one that ADDED the map. --diff-filter=A over a path
    # yields commit hashes only.
    adds = git("log", "--diff-filter=A", "--format=%H", "--", MAP_PATH, repo=repo)
    seal_commit = adds.splitlines()[-1] if adds else ""
    seal_blob = (git("rev-parse", f"{seal_commit}:{MAP_PATH}", repo=repo)
                 if seal_commit else "")

    if head_blob != worktree_blob:
        raise Refused(
            f"{MAP_PATH} in the working tree does not match the committed blob "
            f"({worktree_blob[:12]} vs {head_blob[:12]}).\n"
            "The sealed map was modified after it was committed. Investigate before "
            "unsealing; do not 'fix' it by committing the change.")
    if seal_blob and seal_blob != head_blob:
        raise Refused(
            f"{MAP_PATH} changed since the sealing commit {seal_commit[:12]} "
            f"({seal_blob[:12]} -> {head_blob[:12]}).\n"
            "A seal that changed is not a seal. Investigate before unsealing.")

    return {"path": MAP_PATH, "blob": head_blob, "seal_commit": seal_commit,
            "seal_blob": seal_blob or "(no add-commit found)",
            "note": "hashes only - this script never opened or parsed the map"}


def check_runs(repo: Path) -> dict:
    """Section 8 run completeness, taken from the blind inventory rather than memory."""
    f = repo / INVENTORY
    if not f.exists():
        raise Refused(
            f"{INVENTORY} not found. Run the blind join first so run completeness is "
            "read off an artifact:\n    python scripts/analysis_join.py")
    doc = json.loads(f.read_text(encoding="utf-8"))
    per: dict[str, int] = {}
    for r in doc.get("runs", []):
        per[r["condition"]] = per.get(r["condition"], 0) + 1
    if doc.get("provenance", {}).get("mode") != "blind":
        raise Refused(
            f"{INVENTORY} was generated in "
            f"{doc.get('provenance', {}).get('mode')!r} mode, not blind. The "
            "pre-unsealing inventory must itself be blind.")
    return {"n_runs": doc.get("n_runs", len(doc.get("runs", []))),
            "per_condition": per,
            "line": " · ".join(f"{k} {v}" for k, v in sorted(per.items()))}


NEXT_COMMANDS = """\
python scripts/judge_grade.py --unsealed-map data/sealed/rung_id_map.json --dry-run
python scripts/judge_grade.py --unsealed-map data/sealed/rung_id_map.json
python scripts/phase2_grade.py --unsealed-map data/sealed/rung_id_map.json
python scripts/phase2_grade.py --unsealed-map data/sealed/rung_id_map.json --adjudicate
python scripts/analysis_join.py --unsealed-map data/sealed/rung_id_map.json \\
  --exclude-runs v0_cand_m3iq_s4
python scripts/make_figures.py --input results/analysis/analysis_figure_input.json\
"""


def build_record(repo: Path, p1: dict, mp: dict, runs: dict, stamp: str) -> str:
    head = git("rev-parse", "HEAD", repo=repo)
    branch = git("rev-parse", "--abbrev-ref", "HEAD", repo=repo, check=False)
    return f"""# UNSEAL RECORD

**The section 8 point of no return.** Nothing in sections 2-7 of the preregistration
may change from here. This file was written by `scripts/unseal.py`, which is the only
script that marks unsealing.

- **unsealed (UTC):** `{stamp}`
- **HEAD at unsealing:** `{head}` (branch `{branch}`)

## Phase 1 predates this moment

- file: `{p1['path']}`
- rows: **{p1['n_rows']}**
- last committed: `{p1['commit']}` at `{p1['committed_utc']}`

The claim summaries were committed before this record was written, so git history —
not anyone's recollection — is the evidence that Phase-1 extraction happened while the
rung↔ID map was still sealed.

## The sealed map is intact

- path: `{mp['path']}`
- blob (HEAD): `{mp['blob']}`
- sealing commit: `{mp['seal_commit']}`
- blob at sealing: `{mp['seal_blob']}`

`scripts/unseal.py` verified these hashes agree. **It never opened, parsed or printed
the map's contents** — the integrity check is `git hash-object` and
`git rev-parse <commit>:<path>`, both of which emit hashes only.

## Runs complete at unsealing (from the blind inventory)

- total: **{runs['n_runs']}**
- per condition: {runs['line']}

Source: `{INVENTORY}`, generated in blind mode.

## Exact next commands

```bash
{NEXT_COMMANDS}
```

Then hand-verify `results/analysis/tables.md` against the rendered figure before any
number leaves this repository.
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--i-am-ebin-and-i-am-unsealing", action="store_true",
                    dest="confirm",
                    help="required to write and commit the record; without it this is "
                         "a dry check that changes nothing")
    ap.add_argument("--no-commit", action="store_true",
                    help="write the record but do not commit it (for tests)")
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()

    print("=" * 74)
    print("SECTION 8 UNSEAL CHECK")
    print("=" * 74)
    try:
        p1 = check_phase1(repo)
        print(f"  [ok] phase 1 committed: {p1['n_rows']} rows, {p1['commit'][:12]}")
        mp = check_map(repo)
        print(f"  [ok] sealed map intact: blob {mp['blob'][:12]} "
              f"(sealed in {str(mp['seal_commit'])[:12]}) — contents never read")
        runs = check_runs(repo)
        print(f"  [ok] runs complete: {runs['n_runs']} — {runs['line']}")
    except Refused as e:
        print("\nREFUSED TO UNSEAL\n")
        print(e)
        return 2

    print("\nAll section 8 preconditions hold.")
    if not a.confirm:
        print("\nThis was a DRY CHECK. Nothing was written and nothing was unsealed.")
        print("To actually unseal:")
        print("    python scripts/unseal.py --i-am-ebin-and-i-am-unsealing")
        return 0

    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rec = repo / RECORD
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(build_record(repo, p1, mp, runs, stamp), encoding="utf-8")
    print(f"\nwrote {RECORD}")

    if not a.no_commit:
        git("add", RECORD, repo=repo)
        git("commit", "-m", f"UNSEALED - {stamp}", repo=repo)
        print(f"committed: UNSEALED - {stamp}")

    print("\n" + "!" * 74)
    print("!!  UNSEALED. Sections 2-7 are frozen. Next:")
    for line in NEXT_COMMANDS.splitlines():
        print(f"!!    {line}")
    print("!" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
