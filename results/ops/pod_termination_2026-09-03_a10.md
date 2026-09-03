# Pod termination receipt — Amendment 10 pod `ssvo2u09gloud8`

- Authorised by Ebin in chat ("terminate the pod"), Sep 3 2026, ~22:35 IST.
- Issued from the coordinator session via the RunPod GraphQL API (`podTerminate`), Authorization header, non-default User-Agent; key read from `.env` into a variable and cleared, never printed.
- Timestamp of confirmation: 2026-09-03T17:08:44Z (22:38 IST).

## State before

| id | name | status | $/hr |
|---|---|---|---|
| `ssvo2u09gloud8` | `b13-diffing-bench-a10` | EXITED (stopped by the ops agent at milestone 6) | 0.99 |

## Backup check

Every raw output produced on this pod is tracked in git at HEAD before termination:

| path | tracked files |
|---|---|
| `results/runs_null_identical/` (Arm N, Opus) | 81 |
| `results/runs_null_identical_glm/` (Arm N, GLM) | 80 |
| `results/artifact_replication/` (Arm R) | 30 |

The base model on the volume was the pinned text-only materialisation (`results/base_materialization.json`, 10 hashes), rebuilt and verified on this pod at 10/10; adapters were pulled from `ebt005/b13-ladder-private` and verified against the manifests. Nothing unique remained on the volume.

## State after

0 pods on the account (re-listed 5 s after the mutation). Pod cost for Amendment 10 as recorded in `results/RESUME_STATE_A10.md`: $2.5193 (two sessions) against the $5 ceiling.
