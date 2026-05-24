"""HTTP API namespace (plan.md §4.1).

Pure namespace marker — route declarations live under
:mod:`pydantic_ai_sandbox.api.routes` and shared FastAPI dependencies
under :mod:`pydantic_ai_sandbox.api.deps`. Keeping this module empty
matches plan.md §4.1's "namespace のみ" entry and prevents accidental
side-effects at import time (e.g., route registration leaking when the
package is imported by tests that only need ``Settings``).
"""

from __future__ import annotations
