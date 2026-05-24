"""V2 Beta API surface lock (Task 6.2 / Req 6.4).

Pins the four Pydantic AI V2 Beta surfaces enumerated in plan.md §2.5
and research.md R-1 against direct, full-path imports so that any
``2.0.0bN`` release that renames or removes one of them fires the test
at dependency-update time rather than at first-request time:

1. ``pydantic_ai.Agent`` constructor accepts ``model=...`` and
   ``output_type=...`` kwargs and returns an :class:`Agent` instance.
2. ``@agent.tool`` decorator registers a function as an agent tool that
   surfaces in :attr:`TestModel.last_model_request_parameters.function_tools`.
3. ``agent.override(model=...)`` returns a context manager that swaps
   the model for the duration of the ``with`` block.
4. ``result.output`` is the canonical accessor for the validated agent
   output (V1's ``result.data`` is intentionally unsupported — research.md
   R-1 records the migration).

These tests are deliberately decoupled from
``pydantic_ai_sandbox.agents.chat_agent`` so that an internal refactor
of the agent factory cannot mask an upstream V2 API regression.
"""

from __future__ import annotations

import pydantic_ai
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.test import TestModel

from pydantic_ai_sandbox.schemas.chat import ChatResponse


def test_agent_full_path_import_resolves_to_class() -> None:
    """``pydantic_ai.Agent`` is the documented top-level export.

    R-1 records the import path; if a future ``2.0.0bN`` moves the
    class behind a ``pydantic_ai.agents`` namespace this test catches
    it before any dependent code does.
    """
    assert pydantic_ai.Agent is Agent
    assert isinstance(Agent, type)


def test_agent_constructor_accepts_model_and_output_type_kwargs() -> None:
    """``Agent(model=..., output_type=...)`` constructs a typed agent.

    The kwargs are positional in the docs but spelled out by name here
    so a rename of either parameter (e.g. ``output_type`` → ``result_type``)
    fails this test rather than silently defaulting.
    """
    test_model = TestModel()
    agent = Agent[None, ChatResponse](
        model=test_model,
        output_type=ChatResponse,
        deps_type=type(None),
    )
    assert isinstance(agent, Agent)


def test_agent_tool_decorator_registers_the_decorated_function() -> None:
    """``@agent.tool`` attaches a tool that surfaces on the next run.

    ``TestModel.last_model_request_parameters.function_tools`` is the
    public hook the pydantic-ai docs use for this introspection
    (docs/toolsets.md). If the decorator stops mutating the agent or
    the introspection surface moves, this test fires.
    """
    test_model = TestModel()
    agent = Agent[None, ChatResponse](
        model=test_model,
        output_type=ChatResponse,
        deps_type=type(None),
    )

    # ``@agent.tool`` is a side-effecting decorator: it registers the
    # function on ``agent`` rather than producing a value the test reads
    # directly. Pyright's ``reportUnusedFunction`` cannot see through that
    # registration, so the suppression scope is local to this binding.
    @agent.tool
    def stub_tool(  # pyright: ignore[reportUnusedFunction]
        _ctx: RunContext[None], echo: str
    ) -> list[str]:
        """Tool body irrelevant — only registration is under test."""
        return [echo]

    agent.run_sync("trigger tool surfacing")

    params = test_model.last_model_request_parameters
    assert params is not None
    tool_names = [t.name for t in params.function_tools]
    assert "stub_tool" in tool_names


def test_agent_override_context_manager_swaps_model_for_block_only() -> None:
    """``agent.override(model=...)`` is a context manager that replaces
    the model for the duration of the ``with`` block and restores the
    original on exit. The test asserts both halves: the override is
    visible inside the block (the secondary model records the request),
    and the primary model is the one used after the block exits.
    """
    primary = TestModel()
    secondary = TestModel()
    agent = Agent[None, ChatResponse](
        model=primary,
        output_type=ChatResponse,
        deps_type=type(None),
    )

    with agent.override(model=secondary):
        agent.run_sync("inside override")

    assert secondary.last_model_request_parameters is not None, (
        "expected the secondary model to handle requests inside override block"
    )

    agent.run_sync("after override exit")

    # ``last_model_request_parameters`` updates on every request, so the
    # primary model should now have a recorded request as well.
    assert primary.last_model_request_parameters is not None, (
        "expected the primary model to handle requests after override block exits"
    )


def test_result_output_returns_validated_output_type_instance() -> None:
    """``result.output`` (not ``result.data``) is the V2 accessor (R-1)."""
    test_model = TestModel()
    agent = Agent[None, ChatResponse](
        model=test_model,
        output_type=ChatResponse,
        deps_type=type(None),
    )

    result = agent.run_sync("hello")

    # The accessor exists, returns a ChatResponse instance, and the
    # instance has the expected fields. ``hasattr`` would mask a None
    # attribute — using the access directly forces a real check.
    output = result.output
    assert isinstance(output, ChatResponse)
    assert isinstance(output.answer, str)
    assert isinstance(output.sources, list)
