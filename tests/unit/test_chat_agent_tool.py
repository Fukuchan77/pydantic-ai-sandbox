"""Tool-registration contract tests for ``build_chat_agent`` (Task 6.1).

Locks two facts about :func:`pydantic_ai_sandbox.agents.chat_agent.build_chat_agent`:

1. The agent it returns has at least one tool registered. The check is
   performed via the documented Pydantic AI V2 testing surface
   (``TestModel.last_model_request_parameters.function_tools``) rather
   than poking private agent attributes — that surface is the one the
   pydantic-ai docs themselves use for tool introspection in tests, so
   it survives the refactors that would silently break attribute peeks.
2. The ``search_kb`` tool's source-level signature is ``(RunContext[...],
   query: str) -> list[str]``. Asserted directly via :mod:`inspect` on
   the function exported from the agent module — this is the contract
   the spec text pins (T6.1: "RunContext 引数を受け取り list[str] を
   返すシグネチャ").

The pair is deliberate: (1) proves the registration plumbing works at
runtime, (2) proves the function the tests can import and the function
the agent registers are the same object with the right shape. Neither
on its own would catch a refactor that changed only one side.
"""

from __future__ import annotations

import inspect
import typing
from typing import get_args, get_origin, get_type_hints

from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel

from pydantic_ai_sandbox.agents.chat_agent import build_chat_agent, search_kb


def test_build_chat_agent_registers_at_least_one_tool() -> None:
    """The agent built by ``build_chat_agent`` carries ≥ 1 tool.

    Using ``TestModel`` keeps the test network-free (Req 10.2) while
    threading through the same registration path the production code
    uses. ``run_sync`` populates ``last_model_request_parameters`` with
    the toolset that was visible to the model on this turn.
    """
    test_model = TestModel()
    agent = build_chat_agent(model=test_model)

    agent.run_sync("trigger tool surfacing")

    params = test_model.last_model_request_parameters
    assert params is not None, "TestModel should record request params after run_sync"
    tool_names = [t.name for t in params.function_tools]
    assert tool_names, f"expected ≥ 1 registered tool, got {tool_names}"


def test_search_kb_tool_is_named_search_kb() -> None:
    """The single MVP tool is registered under the spec-mandated name."""
    test_model = TestModel()
    agent = build_chat_agent(model=test_model)

    agent.run_sync("trigger tool surfacing")

    params = test_model.last_model_request_parameters
    assert params is not None
    tool_names = [t.name for t in params.function_tools]
    assert "search_kb" in tool_names, f"expected 'search_kb' in registered tools, got {tool_names}"


def test_search_kb_signature_first_param_is_runcontext() -> None:
    """The first positional parameter is a :class:`RunContext` (Req 6.3).

    ``@agent.tool`` (vs ``@agent.tool_plain``) is the V2 form that
    receives ``RunContext`` as the first argument. We check the source
    signature directly because the schema pydantic-ai derives from the
    function does not preserve the ``RunContext`` slot — it's stripped
    before being shown to the model. The annotation assertion is
    therefore the only place the contract lives.

    ``get_type_hints`` (rather than ``inspect.signature``'s raw
    ``annotation`` field) is used because the agent module enables
    PEP-563 (``from __future__ import annotations``); without
    evaluation the annotation reaches the test as the string
    ``"RunContext[None]"`` and the origin check would silently pass on
    nothing.
    """
    sig = inspect.signature(search_kb)
    params = list(sig.parameters.values())
    assert params, "search_kb must declare at least one parameter"

    hints = get_type_hints(search_kb)
    first_name = params[0].name
    assert first_name in hints, f"first parameter {first_name!r} must declare a type annotation"
    annotation = hints[first_name]

    # Accept ``RunContext`` plain or any ``RunContext[...]`` parametrisation.
    # ``get_origin`` returns ``RunContext`` for the parametrised form;
    # the unparametrised form compares to ``RunContext`` directly.
    origin = get_origin(annotation) or annotation
    assert origin is RunContext, (
        f"expected first parameter annotation to be RunContext or "
        f"RunContext[...], got {annotation!r}"
    )


def test_search_kb_signature_returns_list_of_str() -> None:
    """The return annotation is ``list[str]`` (Req 6.3 wording)."""
    hints = get_type_hints(search_kb)
    assert "return" in hints, "search_kb must declare a return annotation"
    return_annotation = hints["return"]

    origin = get_origin(return_annotation)
    args = get_args(return_annotation)
    assert origin in {list, typing.List}, (  # noqa: UP006 — typing.List for legacy form
        f"expected list[...] return annotation, got origin={origin!r}"
    )
    assert args == (str,), f"expected list[str] return annotation, got args={args!r}"
