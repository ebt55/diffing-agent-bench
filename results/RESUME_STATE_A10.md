# RESUME STATE — Amendment 10 (Arm N + Arm R)

Live operational state for the Amendment 10 arm. Kept current so a rate-limit death
can resume without guessing. Numbers here are read off the pod / the working tree at
the timestamp given; nothing is projected except where it says so.

**Spec:** `PREREGISTRATION.md` "Amendment 10" (committed `1353685`, before any run of
this arm existed). Evidence trail `DECISIONS.md` #39.

---

## 0. Milestone status

| milestone | state |
|---|---|
| M1 pod + base serving | IN PROGRESS |
| M2 Arm R prompts file (committed before sampling) | not started |
| M3 Arm R sampling + analysis | not started |
| M4 Arm N campaigns (opus, glm) | not started |
| M5 grading prep (extract, judge, Phase-2 server, analysis_join) | not started |
| M6 pod stop + report | not started |

---

## 1. Pod

| field | value |
|---|---|
| pod id | `ssvo2u09gloud8` |
| name | `b13-diffing-bench-a10` |
| GPU | **NVIDIA L40S 48GB** (see disclosure below) |
| $/hr | **0.99** |
| cloud | Secure Cloud, location SE |
| image | `runpod/pytorch:1.2.0-rc.162-cu1281-torch2130-ubuntu2404` |
| volume | 100 GB @ `/workspace`, container disk 50 GB |
| machine | `sob1z2r1fy41`, 16 vCPU / 188 GB RAM |
| provisioning call (UTC) | **2026-09-03T11:48:48Z** |
| createdAt (UTC) | 2026-09-03T11:48:52Z |
| **90-minute abort deadline (UTC)** | **2026-09-03T13:18:48Z** |

### GPU disclosure (Amendment 10 permits A40, A6000 or L40S with disclosure)

The first create call, at 2026-09-03T11:48:30Z, requested `NVIDIA A40` alone and
RunPod returned `{"error":"create pod: There are no instances currently available"}`
— **no pod was created and no clock started**. The second call, 18 s later, offered
the sanctioned fallback list in preference order (A40, RTX A6000, L40S, L40, RTX 6000
Ada) and RunPod's scheduler allocated an **L40S at $0.99/hr** — 2.25x the A40's
$0.44/hr. The pod ceiling in Amendment 10 is $5, which buys ~5 h on this card;
Arm R + Arm N need far less. Consequence for the stack: L40S is Ada `sm_89`, so
`TORCH_CUDA_ARCH_LIST=8.9` (the Aug/Sep pods were Ampere `8.6`). The serving stack,
the pinned base revision and the file hashes are unchanged, and the base is verified
against `results/base_materialization.json` before anything is served.

---

## 2. Nothing has been sampled or run yet

No Arm R samples, no Arm N runs, no judge calls. Spend so far: pod only.
