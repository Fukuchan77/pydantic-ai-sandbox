# 014-hub-python-beta-lane — Traceability

Finalized by `/sdd-ship` on 2026-10-04. One row per stable requirement ID.
The implementation commit for Tasks 2–5 is `8692e91`; Task 1 shipped earlier as `34b8888`.

| Requirement | Design | Task | Test / evidence | Commit |
|-------------|--------|------|-----------------|--------|
| REQ-001 | DES-1.1, DES-1.2 | T-3.1, T-3.3, T-5.2 | `test_runner_archives_full_commit_migrates_only_scratch_and_preserves_source` (3.14/3.15); immutable hub run §6 | `8692e91` |
| REQ-002 | DES-1.1, DES-1.2, DES-3.1 | T-3.1, T-3.2, T-3.3, T-5.2 | runner required-phase tests; summarizer JUnit aggregation test; ledger §6 command table | `8692e91` |
| REQ-003 | DES-1.1, DES-1.2, DES-3.1 | T-3.1, T-3.2, T-3.3, T-5.2 | warning-origin aggregation test; ledger §6 warning table | `8692e91` |
| REQ-004 | DES-3.1 | T-5.2 | dated immutable-run record in `docs/hub-intake-2026-10.md` §6 | `8692e91` |
| REQ-005 | DES-1.1, DES-1.2, DES-3.1 | T-3.1, T-3.2, T-3.3, T-5.2 | required-schema/verdict tests; §8.1 remains not satisfied when `api:check` fails | `8692e91` |
| REQ-006 | DES-2.1, DES-2.2 | T-2.1, T-2.2 | six tests in `test_ollama_openai_compat.py` | `8692e91` |
| REQ-007 | DES-2.1, DES-2.2 | T-2.1, T-2.2 | OpenAI `<3` and httpx2 floor tests; three LiteLLM floor tests | `8692e91` |
| REQ-008 | DES-2.1, DES-3.1 | T-2.2, T-5.1 | OpenAI cap contract; monthly refresh and beta-trial ledger | `8692e91` |
| REQ-009 | DES-2.1, DES-2.2, DES-2.3, DES-3.1 | T-1.1, T-1.2, T-2.1, T-2.2 | `mise run check`; `mise run cov` = 98.51% | `34b8888`; `8692e91` |
| REQ-010 | DES-2.1, DES-2.3, DES-3.1 | T-1.1, T-1.2 | nine tests in `test_python_baseline.py` | `34b8888` |
| REQ-011 | DES-3.1 | T-5.1 | CPython 3.15 blocker table with wheel/sdist state | `8692e91` |
| REQ-012 | DES-3.1 | T-5.1 | monthly dependency refresh checklist | `8692e91` |
| REQ-013 | DES-1.1, DES-1.2, DES-3.1 | T-3.1, T-3.2, T-3.3, T-5.2 | runner 3.15 parametrized case and repeat-run ledger link | `8692e91` |
| REQ-014 | DES-3.2 | T-4.1 | rate-limit Python 3.15.0rc3 lane: 27 passed, 3 skipped, 100% coverage | `8692e91` |
| REQ-015 | DES-3.1 | T-5.1 | canonical status row H1=`landed` | `8692e91` |
| REQ-016 | DES-3.1 | T-5.1 | canonical status row L1=`already-present` with hub paths | `8692e91` |
| REQ-017 | DES-3.1 | T-5.1 | L2–L4 retained as `waiting` for hub spec 009 R6 | `8692e91` |
| REQ-018 | DES-3.1 | T-5.1, T-5.2 | all landed/rejected rows retained; H3 failure condition recorded | `8692e91` |
| REQ-019 | DES-2.1, DES-3.3 | T-2.2, T-5.1 | compatibility tests plus first beta-trial record | `8692e91` |
| REQ-020 | DES-3.1, DES-3.3 | T-5.1, T-5.2 | beta-trial record includes versions, hub file, result, recommendation | `8692e91` |
| REQ-021 | DES-3.3 | T-5.1 | ledger states BeeAI/LlamaIndex remain frozen and root owns future trials | `8692e91` |

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

## Post-ship evidence updates

Rows above stay as shipped on 2026-10-04. Later evidence lands here and in `docs/hub-intake-2026-10.md`.

- **2026-10-06, REQ-005 / REQ-013**: the 3.14 runner was re-run on hub `main`@`e26f6fe` after hub PR #81 merged the
  §7.3 pre-fix. All three required phases exited 0 and §8.1 is satisfied, so H3 moved from `proposed` to `verified`
  (`docs/hub-intake-2026-10.md` §8). The Conditional outcome above no longer holds for hub `main`.
- **2026-10-06, REQ-017 / REQ-018**: hub spec `009` R6 delivered its L2–L4 audit
  (hub `services/api/docs/python-beta-intake-2026-10.md`, PR #80). The ledger rows were updated in place and none was
  removed: L2 `already-present`, L3 `landed`, L4 `rejected` (`docs/hub-intake-2026-10.md` §1).
