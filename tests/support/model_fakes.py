"""``FunctionModel`` fakes for fallback / failure injection (plan.md §2.10).

Two builders are exposed:

* :func:`function_model_raising` — wraps a ``FunctionModel`` whose body
  always raises a chosen exception. ``FallbackModel`` only treats
  ``ModelAPIError`` (and subclasses listed in ``fallback_on``) as
  recoverable, so callers steering failover should hand in
  ``ModelAPIError`` instances; arbitrary ``Exception`` subclasses
  propagate immediately and exercise the "non-recoverable" branch.
* :func:`function_model_returning_json` — wraps a ``FunctionModel`` whose
  body returns a single ``TextPart`` carrying the JSON encoding of the
  caller's payload. Used by T9.2 to feed the chat endpoint a structurally
  invalid output so the ``ChatResponse`` validator fires the 5xx path.

Both helpers accept an explicit ``model_name`` so the resulting
``FallbackModel`` chain renders human-readable provider identifiers in
its instrumentation span (``model_name="fallback:<a>,<b>"``); see
``tests/unit/test_fallback_failover.py``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models.function import AgentInfo

__all__ = [
    "function_model_raising",
    "function_model_returning_json",
    "watsonx_function_model_failing",
]


def function_model_raising(
    exc: Exception,
    *,
    model_name: str = "fake-raising",
) -> FunctionModel:
    """Build a ``FunctionModel`` whose ``function`` always raises ``exc``.

    Args:
        exc: Exception instance to raise on every request. Use
            ``pydantic_ai.exceptions.ModelAPIError`` (or a subclass) when
            the test wants ``FallbackModel`` to recover; any other type
            propagates without triggering the fallback chain because
            :class:`FallbackModel` defaults ``fallback_on`` to
            ``(ModelAPIError,)``.
        model_name: Identifier surfaced in instrumentation spans. The
            default keeps the name short and obviously fake to aid log
            reading; tests asserting on span text override it.

    Returns:
        A ``FunctionModel`` ready to plug into ``FallbackModel(...)`` or
        a direct ``Agent(model=...)`` construction.
    """

    def _explode(
        _messages: list[ModelMessage],
        _info: AgentInfo,
    ) -> ModelResponse:
        raise exc

    return FunctionModel(_explode, model_name=model_name)


def function_model_returning_json(
    payload: dict[str, Any],
    *,
    model_name: str = "fake-json",
) -> FunctionModel:
    """Build a ``FunctionModel`` that returns ``payload`` as a JSON ``TextPart``.

    The payload is serialised with the standard library so the test
    surface mirrors what a real provider would produce when asked for a
    free-form text response. Callers wanting structured tool-call output
    should construct a different fake; this helper is intentionally
    narrow.

    Args:
        payload: Dict serialised via :func:`json.dumps`. Pass an
            unexpected shape (e.g. ``{"unexpected": "shape"}``) to
            exercise the ``ChatResponse`` validation failure path
            (T9.2 / Req 3.4).
        model_name: Identifier surfaced in instrumentation spans.

    Returns:
        A ``FunctionModel`` ready to be passed to ``Agent(model=...)``
        or ``agent.override(model=...)``.
    """
    encoded = json.dumps(payload)

    def _respond(
        _messages: list[ModelMessage],
        _info: AgentInfo,
    ) -> ModelResponse:
        return ModelResponse(parts=[TextPart(encoded)])

    return FunctionModel(_respond, model_name=model_name)


def watsonx_function_model_failing(
    *,
    message: str = "simulated watsonx failure",
    model_name: str = "watsonx",
) -> FunctionModel:
    """Build a watsonx-flavoured ``FunctionModel`` that always raises ``ModelAPIError``.

    A thin specialisation of :func:`function_model_raising` for the watsonx
    failover lane (Task 3.2, consumed by Task 7.6). The double stands in for a
    failing ``WatsonxSDKModel`` *without* importing the SDK or touching the
    network: it raises :class:`pydantic_ai.exceptions.ModelAPIError`, which is
    the exact class ``FallbackModel`` recovers by default
    (``fallback_on=(ModelAPIError,)``). A real ``WatsonxSDKModel`` is required
    to wrap every SDK failure into ``ModelAPIError`` for this same reason
    (plan.md Entity 2); this fake encodes that contract on the test side so
    fallback tests stay hermetic.

    Args:
        message: Error text carried by the raised ``ModelAPIError`` — vary it
            to distinguish multiple failing members in one chain.
        model_name: Identifier surfaced in the ``FallbackModel`` chain span
            (``"fallback:...,watsonx"``); defaults to ``"watsonx"`` so failover
            tests can assert watsonx participated in (and failed out of) the
            chain.

    Returns:
        A ``FunctionModel`` ready to seat as a ``FallbackModel`` member or to
        drive a direct ``Agent(model=...)`` failure path.
    """
    return function_model_raising(
        ModelAPIError(model_name=model_name, message=message),
        model_name=model_name,
    )
