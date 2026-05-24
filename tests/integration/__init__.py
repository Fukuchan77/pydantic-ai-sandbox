"""Integration test lane for the 001-agentic-platform suite.

Tests in this package exercise the full V2 Beta stack against a *real*
external backend (currently Ollama on ``OLLAMA_BASE_URL``). They are
gated by the ``RUN_INTEGRATION_OLLAMA=1`` environment variable so the
default ``mise run test`` lane stays network-free (plan.md AD-5).

Run them explicitly with::

    mise run test:integration

The lane is intentionally separate from ``tests/unit`` because:

* CI runs unit and integration on different jobs (Plan §4.3 →
  ``.github/workflows/ci.yml`` vs ``integration-ollama.yml``);
* unit tests assume zero outbound traffic (Req 10.2), and accidentally
  importing an integration helper into a unit test would break that
  invariant. Keeping the package separate makes the boundary literal.
"""
