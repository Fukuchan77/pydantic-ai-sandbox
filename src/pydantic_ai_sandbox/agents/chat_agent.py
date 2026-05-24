"""``ChatAgent`` factory and ``search_kb`` tool stub (plan.md §2.5).

Builds the Pydantic AI V2 :class:`Agent` that backs the ``/chat``
endpoint. Two concrete decisions live here:

1. ``search_kb`` is defined at module level (not as a closure inside
   :func:`build_chat_agent`) and registered via the ``tools=[...]``
   constructor kwarg. Module-level definition gives the unit test
   (``tests/unit/test_chat_agent_tool.py``) a stable import target for
   :func:`inspect.signature` checks; constructor-time registration
   keeps the production path identical to the testing path so the same
   agent shape is exercised in both.

2. The factory accepts an optional ``model`` parameter so callers (and
   tests) can inject a substitute without going through
   :func:`agent.override`. ``override`` remains the right tool for
   ``with``-block-scoped swaps inside an existing agent; ``model=...``
   on the factory is the DI seam for "build a fresh agent with this
   model from the start", which is what the FastAPI ``Depends`` path
   needs once T9.3 wires the route.

Boundary rules from plan.md §2.5:

* The agent produces structured ``ChatResponse`` output only — that
  matches Req 3.2's "at least one structured field" requirement and
  drives the V2 ``output_type`` coercion path Req 6.2 wants exercised.
* No HTTP routing or Logfire span emission lives here. ``instrument_
  pydantic_ai`` (T7.3) handles span emission automatically; the route
  layer (T9.3) handles request shaping.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import Agent, RunContext

from pydantic_ai_sandbox.llm import get_model
from pydantic_ai_sandbox.schemas.chat import ChatResponse

if TYPE_CHECKING:
    from pydantic_ai.models import Model

__all__ = ["build_chat_agent", "search_kb"]


_INSTRUCTIONS = (
    "あなたはユーザーの質問に答える日本語アシスタントです。"
    "回答は必ず ChatResponse スキーマに従い、"
    "`answer` フィールドに自然言語の回答を、"
    "`sources` フィールドに参照した知識ベース項目の識別子リストを記載してください。"
    "知識ベース検索が必要な場合は `search_kb` ツールを呼び出してから回答してください。"
    "スキーマから外れたフィールドを生成してはいけません。"
)
"""Agent system prompt.

Encoded in Japanese to match the project language (CLAUDE.md / spec.json
``language: ja``). The literal pinning of ``ChatResponse`` field names
inside the prompt is intentional — it gives the model a concrete schema
to mirror, reducing the rate at which it generates unexpected keys that
would trip the Req 3.4 5xx path.
"""


def search_kb(_ctx: RunContext[None], query: str) -> list[str]:
    """Stub knowledge-base lookup returning a deterministic placeholder.

    The MVP does not ship a real retrieval backend (out of scope per
    spec.md "Out of Scope"). Returning a single-element list with the
    query echoed back keeps the contract fixed for the integration test
    (T11.1) which asserts ``sources`` is non-empty when the agent
    invokes the tool, while making it obvious in logs that the
    response is synthetic.

    Args:
        _ctx: Pydantic AI run context. Unused in the stub but required
            so the V2 ``@agent.tool`` registration path (which detects
            ``RunContext`` as the first parameter) routes correctly —
            the alternative ``@agent.tool_plain`` form would skip the
            ``RunContext`` parameter and would cost us the future seam
            for threading deps through.
        query: Search string the model produced for retrieval. Echoed
            into the placeholder result for log readability.

    Returns:
        A list with a single placeholder identifier. Real retrieval
        lands in a follow-up spec; the shape of the return type is
        load-bearing because ``test_chat_agent_tool.py`` asserts
        ``list[str]`` directly via :mod:`inspect`.
    """
    return [f"kb-stub:{query}"]


def build_chat_agent(model: Model | None = None) -> Agent[None, ChatResponse]:
    """Construct the chat agent backing ``POST /chat``.

    Args:
        model: Optional model override. When ``None`` (the production
            path) the model is resolved via
            :func:`pydantic_ai_sandbox.llm.get_model`, which reads
            ``Settings.llm_provider``. Tests pass ``TestModel()`` /
            ``FunctionModel(...)`` directly to keep the run network-free
            (Req 10.2).

    Returns:
        A fully-configured :class:`Agent` whose ``output_type`` is
        :class:`ChatResponse`, with :func:`search_kb` registered as the
        single MVP tool. The generic parameters spell the dependency
        and output types so pyright strict catches output-type drift at
        the call site rather than at first ``run_sync``.
    """
    resolved = model if model is not None else get_model()
    # ``deps_type=type(None)`` is load-bearing for pyright strict: the
    # ``Agent.__init__`` default is ``object``, which does not satisfy
    # the ``Agent[None, ...]`` type-arg annotation we declare in the
    # return type. Passing ``type(None)`` realigns the runtime ``deps_type``
    # field with the static ``AgentDepsT`` parameter so the overload
    # resolver picks the ``deps_type=None`` flavour.
    return Agent[None, ChatResponse](
        model=resolved,
        output_type=ChatResponse,
        instructions=_INSTRUCTIONS,
        deps_type=type(None),
        tools=[search_kb],
    )
