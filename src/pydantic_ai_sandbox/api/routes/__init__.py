"""Route subpackage namespace (plan.md §4.1).

Empty by design — each route file under this package owns a single
``APIRouter`` instance and is registered explicitly by
:func:`pydantic_ai_sandbox.main.create_app`. The namespace stays inert
so importing it for type-only purposes does not pull route side-effects
into module load.
"""

from __future__ import annotations
