"""Lane-wide test config: block real model requests (Spec 012-agentic-ai-design Req 10.1)."""

from __future__ import annotations

import os

from pydantic_ai import models

# Unit tests must never reach a real provider. The integration suite flips
# this back on explicitly under its RUN_INTEGRATION_PATTERNS gate.
if os.environ.get("RUN_INTEGRATION_PATTERNS") != "1":
    models.ALLOW_MODEL_REQUESTS = False
