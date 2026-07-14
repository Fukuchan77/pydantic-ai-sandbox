"""Wire the shared anti-false-green guard into this lane's live suite (Task 8.1).

The hook implementations live in ``patterns_contracts.pytest_live_guard`` (single
source of truth); re-exporting them here lets pytest discover them for this
lane. See specs/ci-strategy-review/improvement-plan.md (P3) and this lane's
``patterns:test:integration:hitl`` mise task (``EXPECT_LIVE_TESTS=2``, Task 7.1).
"""

from patterns_contracts.pytest_live_guard import (
    pytest_runtest_logreport as pytest_runtest_logreport,
)
from patterns_contracts.pytest_live_guard import (
    pytest_sessionfinish as pytest_sessionfinish,
)
