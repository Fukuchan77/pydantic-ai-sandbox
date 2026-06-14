"""Behavioral shape + discriminated-union contract for the SSE event models.

Spec 008-2c Req 2.1 / 2.4 / 8.3. Complements the AST/introspection parity in
``test_contract_drift.py`` (which locks the README normative block against the
package once the ``sse`` README is registered in Task 11) by exercising the five
event models and the ``SseEvent`` discriminated union at runtime: that they
re-export from the package root (Req 2.2), expose exactly the minimal fields
declared in the design (no raw-prompt / credential fields, Req 8.3), pin their
``type`` discriminator vocabulary (the SSE ``event:`` name is derived from it,
Req 2.3), and that a JSON payload round-trips through the discriminator to the
correct member (Req 2.1).
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from patterns_contracts import (
    CompletedEvent,
    ErrorEvent,
    SseEvent,
    StepStartedEvent,
    TokenEvent,
    ToolCalledEvent,
)

_ADAPTER: TypeAdapter[SseEvent] = TypeAdapter(SseEvent)

_EVENT_MODELS = (
    StepStartedEvent,
    ToolCalledEvent,
    TokenEvent,
    CompletedEvent,
    ErrorEvent,
)


def test_event_models_reexport_from_package_root() -> None:
    # Req 2.2: consumers depend on the flat, submodule-agnostic import path.
    import patterns_contracts

    for model in _EVENT_MODELS:
        assert issubclass(model, BaseModel)
    for name in (
        "StepStartedEvent",
        "ToolCalledEvent",
        "TokenEvent",
        "CompletedEvent",
        "ErrorEvent",
        "SseEvent",
    ):
        assert name in patterns_contracts.__all__


def test_each_event_field_set() -> None:
    # Req 2.1 / 8.3: minimal fields only -- no raw-prompt or credential field
    # exists on any event, so secrets cannot ride the `data:` line by accident.
    assert set(StepStartedEvent.model_fields) == {"type", "step"}
    assert set(ToolCalledEvent.model_fields) == {"type", "tool", "args_json"}
    assert set(TokenEvent.model_fields) == {"type", "text"}
    assert set(CompletedEvent.model_fields) == {"type", "output"}
    assert set(ErrorEvent.model_fields) == {"type", "message"}


def test_discriminator_tags_are_pinned() -> None:
    # Req 2.3: the SSE `event:` name is derived from this `type` discriminator,
    # so each tag is a fixed, defaulted Literal.
    assert StepStartedEvent(step="classify").type == "step_started"
    assert ToolCalledEvent(tool="search", args_json="{}").type == "tool_called"
    assert TokenEvent(text="Hel").type == "token"
    assert CompletedEvent(output="done").type == "completed"
    assert ErrorEvent(message="boom").type == "error"


def test_discriminated_union_routes_each_payload_to_its_member() -> None:
    # Req 2.1: a wire-shaped dict is dispatched by `type` to the right model.
    payloads: list[tuple[dict[str, str], type[BaseModel]]] = [
        ({"type": "step_started", "step": "classify"}, StepStartedEvent),
        ({"type": "tool_called", "tool": "search", "args_json": "{}"}, ToolCalledEvent),
        ({"type": "token", "text": "Hel"}, TokenEvent),
        ({"type": "completed", "output": "done"}, CompletedEvent),
        ({"type": "error", "message": "boom"}, ErrorEvent),
    ]
    for payload, expected in payloads:
        event = _ADAPTER.validate_python(payload)
        assert isinstance(event, expected)


def test_model_dump_json_roundtrips_through_union() -> None:
    # Req 2.1 / 4.2: model_dump_json() output re-validates to an equal instance
    # via the union -- the property the `data:` JSON serialization relies on.
    original = ToolCalledEvent(tool="search", args_json='{"q": "x"}')
    restored = _ADAPTER.validate_json(original.model_dump_json())
    assert isinstance(restored, ToolCalledEvent)
    assert restored == original


def test_unknown_discriminator_value_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python({"type": "nope", "text": "x"})


def test_missing_discriminator_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python({"step": "classify"})
