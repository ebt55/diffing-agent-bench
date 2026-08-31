"""Synthetic-case artifact behind the KL-bias claim (audit should-fix #10).

The preregistration says the approximate KL's bias was "measured on synthetic
cases". This is that measurement, committed so the claim has an artifact behind it
rather than an assertion. Runs offline in under a second.

    python scripts/test_kl_bias.py
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from baseline_kl_drift import sym_kl_approx

def lp(d):
    """dict token->prob  ->  dict token->logprob"""
    return {k: math.log(v) for k, v in d.items()}

# 1. identical distributions -> KL 0
a = [lp({"x": 0.7, "y": 0.2, "z": 0.1})]
print(f"identical            : {sym_kl_approx(a, a):.6f}   (expect 0.000000)")

# 2. disjoint-ish peaked distributions -> large
p = [lp({"x": 0.98, "y": 0.01, "z": 0.01})]
q = [lp({"x": 0.01, "y": 0.01, "z": 0.98})]
print(f"near-disjoint peaks  : {sym_kl_approx(p, q):.4f}   (expect large, >3)")

# 3. mild shift -> small but non-zero
r = [lp({"x": 0.6, "y": 0.25, "z": 0.15})]
print(f"mild shift           : {sym_kl_approx(a, r):.6f}   (expect small, >0)")

# 4. symmetry
ab = sym_kl_approx(a, p)
ba = sym_kl_approx(p, a)
print(f"symmetry             : {ab:.6f} vs {ba:.6f}  diff={abs(ab-ba):.2e}  (expect ~0)")

# 5. averaging over positions
two = sym_kl_approx(a + a, p + r)
one1 = sym_kl_approx(a, p)
one2 = sym_kl_approx(a, r)
print(f"position averaging   : {two:.6f} vs mean({one1:.4f},{one2:.4f})="
      f"{(one1+one2)/2:.6f}")

# 6. non-overlapping supports still produce a finite number (floor applied)
s = [lp({"q": 0.5, "w": 0.5})]
val = sym_kl_approx(a, s)
print(f"disjoint supports    : {val:.4f}   finite={math.isfinite(val)}  (expect finite)")

# 7. None entries skipped
print(f"None handling        : {sym_kl_approx([None, a[0]], [None, a[0]])}  (expect 0.0)")
print(f"all-None             : {sym_kl_approx([None], [None])}  (expect None)")

ok = (abs(sym_kl_approx(a, a)) < 1e-9 and sym_kl_approx(p, q) > 3
      and sym_kl_approx(a, r) > 0 and abs(ab - ba) < 1e-9
      and math.isfinite(val) and sym_kl_approx([None], [None]) is None)
print("\nKL MATH TEST", "PASSED" if ok else "FAILED")
sys.exit(0 if ok else 1)
