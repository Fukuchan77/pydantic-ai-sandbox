"""Behavioral shape contract for the HITL models (Spec 012 Req 2.1, 2.2, 2.3).

Complements the AST/introspection parity in ``test_contract_drift.py`` by
exercising the three HITL contracts at runtime: that they re-export from the
package root (Req 2.1), expose exactly the fields declared in Req 2.2/2.3,
that ``ActionType`` is a closed vocabulary, and that ``amount_usd`` rejects
negative values. The approval-decision representation itself (pydantic-ai's
``ToolApproved``/``ToolDenied``) is deliberately out of scope -- this module
owns only the structured-output shape, not the resolution protocol.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from patterns_contracts import ActionType, ResolutionAction, SupportOutput


def test_hitl_models_reexport_from_package_root() -> None:
    # Req 2.1: consumers depend on the flat, submodule-agnostic import path.
    for model in (ResolutionAction, SupportOutput):
        assert issubclass(model, BaseModel)
    for name in ("ActionType", "ResolutionAction", "SupportOutput"):
        assert name in __import__("patterns_contracts").__all__


def test_resolution_action_field_set() -> None:
    # Req 2.2: ResolutionAction{action_type, target_id, amount_usd}.
    assert set(ResolutionAction.model_fields) == {"action_type", "target_id", "amount_usd"}


def test_support_output_field_set() -> None:
    # Req 2.3: SupportOutput{summary_of_issue, reasoning, requires_human_approval, action_plan}.
    assert set(SupportOutput.model_fields) == {
        "summary_of_issue",
        "reasoning",
        "requires_human_approval",
        "action_plan",
    }


@pytest.mark.parametrize("action_type", ["DISCOUNT", "UPGRADE", "ESCALATE"])
def test_action_type_accepts_closed_vocabulary(action_type: ActionType) -> None:
    action = ResolutionAction.model_validate(
        {"action_type": action_type, "target_id": "cust-1", "amount_usd": 10.0}
    )
    assert action.action_type == action_type


def test_action_type_rejects_value_outside_vocabulary() -> None:
    # Req 2.2: ActionType is a closed Literal vocabulary; "REFUND" is not a member.
    with pytest.raises(ValidationError):
        ResolutionAction.model_validate(
            {"action_type": "REFUND", "target_id": "cust-1", "amount_usd": 10.0}
        )


def test_resolution_action_rejects_negative_amount() -> None:
    # Req 2.2: amount_usd carries a ge=0 constraint.
    with pytest.raises(ValidationError):
        ResolutionAction.model_validate(
            {"action_type": "DISCOUNT", "target_id": "cust-1", "amount_usd": -1.0}
        )


def test_resolution_action_accepts_zero_amount() -> None:
    action = ResolutionAction.model_validate(
        {"action_type": "DISCOUNT", "target_id": "cust-1", "amount_usd": 0.0}
    )
    assert action.amount_usd == 0.0


def test_support_output_roundtrips_nested_action_plan() -> None:
    # Req 2.3: SupportOutput.action_plan is list[ResolutionAction]; a dict
    # payload coerces so it validates the same way a model's tool call would.
    output = SupportOutput.model_validate(
        {
            "summary_of_issue": "Customer disputes a duplicate charge.",
            "reasoning": "Charge matches a known billing-system duplicate bug.",
            "requires_human_approval": True,
            "action_plan": [
                {"action_type": "DISCOUNT", "target_id": "cust-1", "amount_usd": 25.0},
            ],
        }
    )
    assert len(output.action_plan) == 1
    assert isinstance(output.action_plan[0], ResolutionAction)
    assert output.action_plan[0].action_type == "DISCOUNT"


def test_support_output_requires_human_approval_must_be_bool() -> None:
    with pytest.raises(ValidationError):
        SupportOutput.model_validate(
            {
                "summary_of_issue": "x",
                "reasoning": "x",
                "requires_human_approval": "not-a-bool",
                "action_plan": [],
            }
        )


def test_support_output_missing_required_field_rejected() -> None:
    # Req 2.3: all four fields are mandatory -- action_plan has no default.
    with pytest.raises(ValidationError):
        SupportOutput.model_validate(
            {
                "summary_of_issue": "x",
                "reasoning": "x",
                "requires_human_approval": True,
            }
        )
