"""Happy-path tests for ``POST /chat`` (Task 9.1 / Req 3.1, 3.2, 3.5).

Locks two facts about the route once T9.3 lands:

1. Submitting a well-formed ``ChatRequest`` body to ``POST /chat`` with the
   chat agent's model overridden to :class:`TestModel` returns HTTP 200 and a
   JSON body that round-trips cleanly through :class:`ChatResponse`.
   :class:`TestModel` produces a synthetic structured output by sampling the
   declared ``output_type`` schema, which makes the route exercisable without
   any real provider — the network-free testing recipe Req 10.2 mandates.

2. The response carries the structured ``sources`` list alongside the free-form
   ``answer`` (Req 3.2 "at least one structured field beyond a free-text
   answer"). The validator round-trip is the canonical proof of the wire
   shape; asserting on raw ``response.json()`` keys would miss a future
   refactor that renamed a field but kept the JSON shape compatible.

The ``app_with_overrides`` fixture lives in ``tests/conftest.py``: it builds
a FastAPI app with both health and chat routers, enters
``agent.override(model=...)`` on the cached singleton agent (so the route's
``Depends(get_chat_agent)`` resolution sees the override), and yields a
``TestClient``. The fixture also seats a minimal ``LLM_PROVIDER=ollama`` env
so :class:`Settings` validation does not abort the test before the override
takes effect — note that the override means no real Ollama HTTP traffic is
ever generated.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai.models.test import TestModel

from pydantic_ai_sandbox.schemas.chat import ChatResponse

if TYPE_CHECKING:
    from tests.conftest import AppWithOverrides


def test_chat_with_test_model_returns_200_and_chat_response_shape(
    app_with_overrides: AppWithOverrides,
) -> None:
    """``POST /chat`` returns 200 + a body that validates as ``ChatResponse``.

    The request body is the minimal ``ChatRequest`` shape (a single
    ``message`` string) so the assertion isolates the *output* contract.
    Validating via :meth:`ChatResponse.model_validate` rather than spot-
    checking JSON keys means a future field rename in :class:`ChatResponse`
    fails this test instead of silently passing — pyright would catch the
    field rename in :func:`build_chat_agent` independently, but the route's
    wire contract belongs to the test layer.
    """
    client = app_with_overrides(TestModel())

    response = client.post("/chat", json={"message": "hello world"})

    assert response.status_code == 200, (
        f"expected 200 with TestModel override, got {response.status_code}: {response.text}"
    )
    parsed = ChatResponse.model_validate(response.json())
    assert isinstance(parsed.answer, str)
    assert isinstance(parsed.sources, list)


def test_chat_response_is_pure_chat_response_no_extra_fields(
    app_with_overrides: AppWithOverrides,
) -> None:
    """The wire body contains exactly ``answer`` and ``sources`` and nothing else.

    FastAPI's response_model coercion is the surface that enforces this:
    declaring ``response_model=ChatResponse`` on the route causes any extra
    keys returned by the agent to be stripped before serialisation. Asserting
    on the exact key set here pins that surface so a future refactor that
    drops ``response_model=`` (and therefore widens the contract to whatever
    the agent emits) fires this test.
    """
    client = app_with_overrides(TestModel())

    response = client.post("/chat", json={"message": "hello"})

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"answer", "sources"}, (
        f"expected exactly answer+sources keys (Req 3.2), got {sorted(body.keys())}"
    )
