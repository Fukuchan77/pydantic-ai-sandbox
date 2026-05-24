"""Error-path tests for ``POST /chat`` (Task 9.2 / Req 3.4, 3.6).

Two classes of failure are pinned:

* **Request validation (422)** — bodies that fail the ``ChatRequest``
  Pydantic schema MUST be rejected by FastAPI's request validator with HTTP
  422 before the route handler runs (and therefore before any agent call).
  Two parametrised cases cover the spec text: an empty body and a body with
  the wrong type for ``message``.

* **Output validation (5xx)** — when the model returns a JSON shape that
  does not satisfy ``ChatResponse``, Pydantic AI raises
  :class:`UnexpectedModelBehavior` after exhausting its output-validation
  retries. The route delegates exception handling to FastAPI's default
  500-server-error path, so the client observes a 5xx status with no
  fragment of the upstream payload leaked into the response body.

The ``raise_server_exceptions=False`` flag on the ``app_with_overrides``
fixture's TestClient is what makes the 5xx path observable as a status code
rather than a re-raised exception in the test process — see the fixture
docstring for the lifecycle reasoning.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from pydantic_ai.models.test import TestModel

from tests.support.model_fakes import function_model_returning_json

if TYPE_CHECKING:
    from tests.conftest import AppWithOverrides


@pytest.mark.parametrize(
    ("payload", "case_id"),
    [
        pytest.param({}, "empty-body", id="empty-body"),
        pytest.param({"message": 123}, "wrong-type", id="wrong-type-int"),
        pytest.param({"message": ""}, "empty-string", id="empty-string"),
    ],
)
def test_chat_invalid_request_body_returns_422(
    app_with_overrides: AppWithOverrides,
    payload: dict[str, Any],
    case_id: str,
) -> None:
    """FastAPI request validation rejects invalid ``ChatRequest`` bodies (Req 3.6).

    All three cases exercise the same surface (FastAPI body validation against
    :class:`ChatRequest`) but cover three orthogonal failure modes: missing
    required field, wrong type for the field, and a value that violates the
    ``min_length=1`` constraint on ``message``. The ``case_id`` arg is a
    breadcrumb for failure messages — pytest's parametrise ``id`` would
    give the same context but only in collection output.
    """
    client = app_with_overrides(TestModel())

    response = client.post("/chat", json=payload)

    assert response.status_code == 422, (
        f"case={case_id}: expected 422 from FastAPI request validation, "
        f"got {response.status_code}: {response.text}"
    )


def test_chat_output_schema_violation_returns_5xx_without_partial_payload(
    app_with_overrides: AppWithOverrides,
) -> None:
    """A model returning the wrong JSON shape fires the 5xx path (Req 3.4).

    ``function_model_returning_json({"unexpected": "shape"})`` makes the model
    emit a TextPart whose JSON has none of :class:`ChatResponse`'s required
    fields. Pydantic AI tries to coerce the text into ``ChatResponse``, fails
    validation, exhausts the default retry budget, and raises
    :class:`UnexpectedModelBehavior`. The route does not catch the exception,
    so FastAPI's default 500 handler converts it to a generic Internal Server
    Error response.

    Two assertions encode "no partial data leaked" (Req 3.4):
    1. The status code is in the 5xx range.
    2. The response body does not contain the offending key
       (``"unexpected"``) that the model produced — proving the upstream
       payload did not flow through to the wire on a partial-success path.
    """
    bad_model = function_model_returning_json({"unexpected": "shape"})
    client = app_with_overrides(bad_model)

    response = client.post("/chat", json={"message": "trigger output failure"})

    assert 500 <= response.status_code < 600, (
        f"expected 5xx for output schema violation, got {response.status_code}: {response.text}"
    )
    assert "unexpected" not in response.text, (
        "Req 3.4: response body must not leak fragments of the model's "
        f"invalid payload, got: {response.text!r}"
    )
