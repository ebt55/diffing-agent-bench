"""Synthetic test for scripts/unseal.py, in a throwaway git repo.

Everything happens inside a temp directory: a fake repo, fake Phase-1 claims, a fake
map at the same relative path the real one uses, and a fake blind inventory. The real
repository's data/sealed/ is never touched, and no real unseal can happen from here.

Run: python scripts/test_unseal.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import unseal as U  # noqa: E402

_checks = 0
_fails: list[str] = []


def check(cond: bool, label: str) -> None:
    global _checks
    _checks += 1
    print(f"  {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        _fails.append(label)


def git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(repo)] + list(args),
                       capture_output=True, text=True)
    return p.stdout.strip()


def build_repo(tmp: Path, *, phase1: bool = True, commit_phase1: bool = True,
               inventory: bool = True, blind: bool = True) -> Path:
    repo = tmp / "repo"
    (repo / "data" / "sealed").mkdir(parents=True, exist_ok=True)
    (repo / "results" / "analysis").mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q")
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"],
                   capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"],
                   capture_output=True)

    # FAKE map. Same relative path as the real one; contents are obviously synthetic.
    (repo / U.MAP_PATH).write_text(
        json.dumps({"_WARNING": "SYNTHETIC FAKE MAP - NOT DATA",
                    "map": {"L0": "cand_FAKEa", "L1": "cand_FAKEb"}}),
        encoding="utf-8")
    git(repo, "add", U.MAP_PATH)
    git(repo, "commit", "-q", "-m", "seal the fake map")

    if inventory:
        (repo / U.INVENTORY).write_text(json.dumps({
            "n_runs": 99,
            "provenance": {"mode": "blind" if blind else "unsealed"},
            "runs": ([{"condition": "v0_opus"}] * 40 + [{"condition": "v1_opus"}] * 19
                     + [{"condition": "glm_v0"}] * 30 + [{"condition": "battery"}] * 5
                     + [{"condition": "introspection"}] * 5),
        }), encoding="utf-8")
        git(repo, "add", U.INVENTORY)
        git(repo, "commit", "-q", "-m", "blind inventory")

    if phase1:
        (repo / U.PHASE1).write_text(
            "\n".join(json.dumps({"run_id": f"v0_cand_FAKEa_s{i}",
                                  "top_hypothesis_verbatim": "SYNTHETIC"})
                      for i in range(3)) + "\n", encoding="utf-8")
        if commit_phase1:
            git(repo, "add", U.PHASE1)
            git(repo, "commit", "-q", "-m", "phase 1 claims")
    return repo


def run(repo: Path, *extra: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(_HERE / "unseal.py"),
                        "--repo", str(repo)] + list(extra),
                       capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="unseal_test_"))
    print(f"fixture in {tmp}\n")

    print("1. the script never reads the map's contents")
    src = Path(U.__file__).read_text(encoding="utf-8")
    check("read_text" not in src.split("MAP_PATH =")[1].split("def check_runs")[0]
          or "hash-object" in src,
          "map integrity is hash-only")
    body = src[src.index("def check_map"):src.index("def check_runs")]
    check("read_text" not in body and "json.load" not in body,
          "check_map never opens or parses the map")
    check("hash-object" in body and "rev-parse" in body,
          "check_map uses git plumbing that emits hashes only")

    print("\n2. refuses when Phase 1 is missing")
    r = build_repo(tmp / "a", phase1=False)
    rc, out = run(r)
    check(rc == 2, "exits 2")
    check("does not exist" in out and "BEFORE the map is opened" in out,
          "explains that Phase 1 must precede unsealing")

    print("\n3. refuses when Phase 1 exists but is not committed")
    r = build_repo(tmp / "b", commit_phase1=False)
    rc, out = run(r)
    check(rc == 2, "exits 2")
    check("not committed" in out and "git add" in out,
          "tells the operator exactly how to fix it")

    print("\n4. refuses when Phase 1 has uncommitted edits")
    r = build_repo(tmp / "c")
    (r / U.PHASE1).write_text(
        (r / U.PHASE1).read_text(encoding="utf-8")
        + json.dumps({"run_id": "v0_cand_FAKEa_s9"}) + "\n", encoding="utf-8")
    rc, out = run(r)
    check(rc == 2, "exits 2")
    check("uncommitted changes" in out,
          "refuses rather than leave the ordering ambiguous")

    print("\n5. refuses when the sealed map changed after sealing")
    r = build_repo(tmp / "d")
    (r / U.MAP_PATH).write_text(json.dumps({"map": {"L0": "cand_TAMPERED"}}),
                                encoding="utf-8")
    rc, out = run(r)
    check(rc == 2, "exits 2")
    check("does not match the committed blob" in out,
          "detects a post-seal modification by hash")
    check("cand_TAMPERED" not in out,
          "and does NOT print the map's contents while doing so")

    print("\n6. refuses when the inventory is missing or not blind")
    r = build_repo(tmp / "e", inventory=False)
    rc, out = run(r)
    check(rc == 2 and "analysis_join" in out, "missing inventory names the fix")
    r = build_repo(tmp / "f", blind=False)
    rc, out = run(r)
    check(rc == 2 and "not blind" in out, "a non-blind inventory is refused")

    print("\n7. dry check passes and changes nothing")
    r = build_repo(tmp / "g")
    before = git(r, "rev-parse", "HEAD")
    rc, out = run(r)
    check(rc == 0, "exits 0 when every precondition holds")
    check("DRY CHECK" in out and "--i-am-ebin-and-i-am-unsealing" in out,
          "says it changed nothing and names the flag")
    check(not (r / U.RECORD).exists(), "no record written without the flag")
    check(git(r, "rev-parse", "HEAD") == before, "no commit made without the flag")
    check("99" in out and "glm_v0 30" in out,
          "prints the run counts from the blind inventory")

    print("\n8. with the flag it writes and commits the record")
    rc, out = run(r, "--i-am-ebin-and-i-am-unsealing")
    check(rc == 0, "exits 0")
    rec = r / U.RECORD
    check(rec.exists(), "UNSEAL_RECORD.md written")
    txt = rec.read_text(encoding="utf-8")
    for needle, label in (
            ("unsealed (UTC)", "UTC timestamp"),
            ("HEAD at unsealing", "HEAD hash"),
            ("rows: **3**", "phase1 row count"),
            ("last committed", "phase1 commit hash"),
            ("blob (HEAD)", "map blob hash"),
            ("sealing commit", "sealing commit"),
            ("glm_v0 30", "inventory line"),
            ("judge_grade.py", "next commands"),
            ("make_figures.py", "final command")):
        check(needle in txt, f"record carries the {label}")
    check("cand_FAKE" not in txt,
          "the record contains no map contents, only hashes")
    subj = git(r, "log", "-1", "--format=%s")
    check(subj.startswith("UNSEALED - "), f"commit subject is the unseal marker: {subj}")
    check(git(r, "status", "--porcelain") == "", "the record was committed, tree clean")

    print("\n9. the real repository was not touched")
    real = Path(__file__).resolve().parents[1]
    check(not (real / U.RECORD).exists(),
          "no UNSEAL_RECORD.md exists in the real repo")

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'=' * 62}")
    if _fails:
        print(f"FAILED {len(_fails)}/{_checks} checks:")
        for f in _fails:
            print(f"  - {f}")
        return 1
    print(f"ALL {_checks} CHECKS PASS")
    print("Synthetic only: a throwaway git repo with a fake map.")
    print("The real data/sealed/ was never read, hashed or touched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
