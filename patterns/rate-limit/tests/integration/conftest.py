"""Wire the shared anti-false-green guard into the live Redis suite (P3).

The hook implementations live in ``patterns_contracts.pytest_live_guard`` (single
source of truth); re-exporting them here lets pytest discover them for this lane.
See specs/ci-strategy-review/improvement-plan.md (P3).
"""

from patterns_contracts.pytest_live_guard import (
    pytest_runtest_logreport as pytest_runtest_logreport,
)
from patterns_contracts.pytest_live_guard import (
    pytest_sessionfinish as pytest_sessionfinish,
)
