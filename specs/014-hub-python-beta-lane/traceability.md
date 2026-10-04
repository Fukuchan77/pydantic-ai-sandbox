# 014-hub-python-beta-lane — Traceability

Finalized by `/sdd-ship` on 2026-10-04. One row per stable requirement ID.
`pending (this ship run)` is replaced with the created feature commit hash before the
tracking commit is finalized.

| Requirement | Design | Task | Test / evidence | Commit |
|-------------|--------|------|-----------------|--------|
| REQ-001 | DES-1.1, DES-1.2 | T-3.1, T-3.3, T-5.2 | `test_runner_archives_full_commit_migrates_only_scratch_and_preserves_source` (3.14/3.15); immutable hub run §6 | pending (this ship run) |
| REQ-002 | DES-1.1, DES-1.2, DES-3.1 | T-3.1, T-3.2, T-3.3, T-5.2 | runner required-phase tests; summarizer JUnit aggregation test; ledger §6 command table | pending (this ship run) |
| REQ-003 | DES-1.1, DES-1.2, DES-3.1 | T-3.1, T-3.2, T-3.3, T-5.2 | warning-origin aggregation test; ledger §6 warning table | pending (this ship run) |
| REQ-004 | DES-3.1 | T-5.2 | dated immutable-run record in `docs/hub-intake-2026-10.md` §6 | pending (this ship run) |
| REQ-005 | DES-1.1, DES-1.2, DES-3.1 | T-3.1, T-3.2, T-3.3, T-5.2 | required-schema/verdict tests; §8.1 remains not satisfied when `api:check` fails | pending (this ship run) |
| REQ-006 | DES-2.1, DES-2.2 | T-2.1, T-2.2 | six tests in `test_ollama_openai_compat.py` | pending (this ship run) |
| REQ-007 | DES-2.1, DES-2.2 | T-2.1, T-2.2 | OpenAI `<3` and httpx2 floor tests; three LiteLLM floor tests | pending (this ship run) |
| REQ-008 | DES-2.1, DES-3.1 | T-2.2, T-5.1 | OpenAI cap contract; monthly refresh and beta-trial ledger | pending (this ship run) |
| REQ-009 | DES-2.1, DES-2.2, DES-2.3, DES-3.1 | T-1.1, T-1.2, T-2.1, T-2.2 | `mise run check`; `mise run cov` = 98.51% | `34b8888`; pending (this ship run) |
| REQ-010 | DES-2.1, DES-2.3, DES-3.1 | T-1.1, T-1.2 | nine tests in `test_python_baseline.py` | `34b8888` |
| REQ-011 | DES-3.1 | T-5.1 | CPython 3.15 blocker table with wheel/sdist state | pending (this ship run) |
| REQ-012 | DES-3.1 | T-5.1 | monthly dependency refresh checklist | pending (this ship run) |
| REQ-013 | DES-1.1, DES-1.2, DES-3.1 | T-3.1, T-3.2, T-3.3, T-5.2 | runner 3.15 parametrized case and repeat-run ledger link | pending (this ship run) |
| REQ-014 | DES-3.2 | T-4.1 | rate-limit Python 3.15.0rc3 lane: 27 passed, 3 skipped, 100% coverage | pending (this ship run) |
| REQ-015 | DES-3.1 | T-5.1 | canonical status row H1=`landed` | pending (this ship run) |
| REQ-016 | DES-3.1 | T-5.1 | canonical status row L1=`already-present` with hub paths | pending (this ship run) |
| REQ-017 | DES-3.1 | T-5.1 | L2–L4 retained as `waiting` for hub spec 009 R6 | pending (this ship run) |
| REQ-018 | DES-3.1 | T-5.1, T-5.2 | all landed/rejected rows retained; H3 failure condition recorded | pending (this ship run) |
| REQ-019 | DES-2.1, DES-3.3 | T-2.2, T-5.1 | compatibility tests plus first beta-trial record | pending (this ship run) |
| REQ-020 | DES-3.1, DES-3.3 | T-5.1, T-5.2 | beta-trial record includes versions, hub file, result, recommendation | pending (this ship run) |
| REQ-021 | DES-3.3 | T-5.1 | ledger states BeeAI/LlamaIndex remain frozen and root owns future trials | pending (this ship run) |

## Requirement ID legend

| REQ | spec | REQ | spec | REQ | spec |
|---|---|---|---|---|---|
| REQ-001 | 1.1 | REQ-008 | 2.3 | REQ-015 | 4.1 |
| REQ-002 | 1.2 | REQ-009 | 2.4 | REQ-016 | 4.2 |
| REQ-003 | 1.3 | REQ-010 | 2.5 | REQ-017 | 4.3 |
| REQ-004 | 1.4 | REQ-011 | 3.1 | REQ-018 | 4.4 |
| REQ-005 | 1.5 | REQ-012 | 3.2 | REQ-019 | 5.1 |
| REQ-006 | 2.1 | REQ-013 | 3.3 | REQ-020 | 5.2 |
| REQ-007 | 2.2 | REQ-014 | 3.4 | REQ-021 | 5.3 |

## Gaps

- Unmapped requirements: None.
- Orphan tasks: None.
- Conditional outcome: REQ-005 is correctly **not satisfied for hub adoption** because the immutable hub `api:check` failed; the sandbox implementation requirement is satisfied by recording the failure and retaining H3 as `proposed`.
