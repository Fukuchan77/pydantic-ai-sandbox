"""Output-mode contract for ``build_chat_agent`` (Ollama JSON-schema fix).

The MVP integration lane (T11.1) discovered that ``granite4.1:8b`` —
the production Ollama model — fails the V2 default tool-mode structured
output recipe: it returns Markdown text that does not validate against
:class:`ChatResponse`. The fix is to switch to native JSON-schema mode
when the resolved provider supports it, which Ollama v0.5.0+ does via
``llama.cpp``'s grammar-constrained decoder.

Two assertions belong here, locked separately because they protect
different surfaces:

1. **Production path** — ``build_chat_agent()`` with no explicit ``model``
   arg routes through ``get_model()`` and (for an Ollama provider) gets
   an :class:`OllamaModel` whose profile says
   ``supports_json_schema_output: True``. The factory must wrap
   ``output_type`` in :class:`NativeOutput` so the OpenAI-compatible
   request body carries ``response_format={"type":"json_schema", ...}``.

2. **Explicit-injection path** — ``build_chat_agent(model=TestModel())``
   (and the same recipe with :class:`FunctionModel`) MUST keep the
   default tool-mode wiring. ``TestModel.profile`` reports
   ``supports_json_schema_output: False``; wrapping with
   :class:`NativeOutput` raises :class:`UserError` at run time. The
   network-free testing recipe (Req 10.2) depends on this branch
   keeping the plain :class:`ChatResponse` shape.

Together, these two tests pin the conditional that
``build_chat_agent`` must implement: "wrap in ``NativeOutput`` only when
the resolver picked the model itself and the profile says yes."
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pydantic_ai import NativeOutput
from pydantic_ai.models.test import TestModel

from pydantic_ai_sandbox.agents.chat_agent import build_chat_agent
from pydantic_ai_sandbox.config import get_settings
from pydantic_ai_sandbox.schemas.chat import ChatResponse

if TYPE_CHECKING:
    from tests.conftest import SettingsFactory


# Mirrors the values used elsewhere in the unit suite (test_factory_dispatch /
# test_factory_ollama_no_io). Stays outside FORBIDDEN_MODEL_ID_LITERALS so the
# hardcoded-model-ID guard (T2.1) keeps treating this module as clean.
DUMMY_OLLAMA_MODEL = "dummy-ollama-model"
DUMMY_OLLAMA_URL = "http://localhost:11434"


def test_build_chat_agent_production_path_uses_native_output(
    settings_factory: SettingsFactory,
) -> None:
    """``build_chat_agent()`` (no model arg) wraps output in NativeOutput.

    The production path resolves the model via ``get_model()``, which
    for ``LLM_PROVIDER=ollama`` returns an :class:`OllamaModel` whose
    profile reports ``supports_json_schema_output: True``. The factory
    is required to detect that capability and wrap ``output_type`` in
    :class:`NativeOutput`; without the wrap, V2 falls back to tool-mode
    structured output which ``granite4.1:8b`` fails to satisfy reliably.

    Asserting on ``agent.output_type`` (rather than poking the schema
    builder) keeps this test robust against future internal refactors:
    pydantic-ai's documented V2 surface exposes ``output_type`` as the
    serialised round-trip of whatever the constructor was passed, so
    the type the factory chose surfaces here verbatim.
    """
    settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
    )
    get_settings.cache_clear()

    try:
        agent = build_chat_agent()
    finally:
        get_settings.cache_clear()

    output_type = agent.output_type
    assert isinstance(output_type, NativeOutput), (
        f"production path must wrap output_type in NativeOutput so the V2 "
        f"OpenAI-compatible request carries response_format=json_schema; "
        f"got {output_type!r} instead. The integration lane (T11.1) "
        f"depends on this for the production Ollama model's "
        f"structured-output reliability."
    )
    # ``NativeOutput.outputs`` is annotated upstream as a generic
    # ``OutputTypeOrFunction[T] | Sequence[OutputTypeOrFunction[T]]`` whose
    # ``T`` parameter is unbound at our generic ``NativeOutput`` instance,
    # which pyright strict surfaces as ``reportUnknownMemberType``. The
    # ``is`` identity check below operates on any object regardless of
    # static type, so the suppression is scoped to this single read of the
    # attribute we deliberately introspect.
    outputs = cast(
        "object",
        output_type.outputs,  # pyright: ignore[reportUnknownMemberType]
    )
    assert outputs is ChatResponse, (
        f"NativeOutput.outputs must remain ChatResponse — the wire contract "
        f"is fixed by Req 3.2; got {outputs!r}"
    )


def test_build_chat_agent_test_model_path_uses_plain_chat_response(
    settings_factory: SettingsFactory,
) -> None:
    """Explicit ``model=TestModel()`` keeps plain ``ChatResponse`` output.

    ``TestModel.profile`` reports ``supports_json_schema_output: False``.
    Wrapping in :class:`NativeOutput` would raise :class:`UserError` at
    run time, breaking the network-free testing recipe Req 10.2 mandates
    and every test that relies on the ``app_with_overrides`` fixture.

    The factory therefore routes the explicit-injection path (caller
    passed ``model=...``) to the default tool-mode wiring. Asserting
    that ``agent.output_type is ChatResponse`` (identity, not just
    ``isinstance``) pins the exact symbol so a future refactor that
    silently re-wraps even on the explicit path would fire this test.
    """
    settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
    )
    get_settings.cache_clear()

    try:
        agent = build_chat_agent(model=TestModel())
    finally:
        get_settings.cache_clear()

    assert agent.output_type is ChatResponse, (
        f"explicit-model-injection path must keep the plain ChatResponse "
        f"output_type so TestModel/FunctionModel-based unit tests keep "
        f"running network-free; got {agent.output_type!r}"
    )
