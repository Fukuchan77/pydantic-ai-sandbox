"""Smoke test for the HITL lane scaffold (Spec 012-agentic-ai-design Req 10.1, X-2).

Three concerns live here:

* the lane package ``patterns_hitl`` imports cleanly, and the shared HITL
  contract (``patterns_contracts.hitl``) is reachable through the lane's
  path dependency (Req 1.3 / NFR-3 — the lane never redeclares it);
* the lane's hermetic guard (``tests/unit/conftest.py``) actually disables
  real model requests by default, so no unit test in this lane can reach a
  live provider (Req 10.1 / NFR "Performance / hermeticity");
* the same conftest's autouse ``block_network`` socket guard actually fires
  on a real internet connect attempt, not only on the pydantic-ai model path.
"""

from __future__ import annotations

import socket

import pytest
from patterns_contracts import ActionType, ResolutionAction, SupportOutput
from pydantic_ai import models

from tests.support.hermetic import NetworkReachError


def test_patterns_hitl_imports() -> None:
    import patterns_hitl

    assert patterns_hitl.__name__ == "patterns_hitl"


def test_hitl_contract_importable_via_path_dependency() -> None:
    action: ActionType = "DISCOUNT"
    output = SupportOutput(
        summary_of_issue="customer disputes a duplicate charge",
        reasoning="the ledger shows the same charge posted twice",
        requires_human_approval=True,
        action_plan=[ResolutionAction(action_type=action, target_id="cust-1", amount_usd=25.0)],
    )
    assert output.action_plan[0].action_type == "DISCOUNT"


def test_hermetic_guard_blocks_real_model_requests_by_default() -> None:
    assert models.ALLOW_MODEL_REQUESTS is False


def test_block_network_guard_loud_fails_on_internet_connect() -> None:
    # Load-bearing proof the autouse socket guard is not vacuous: a real AF_INET connect
    # must be intercepted before any I/O (a loopback closed port would otherwise raise
    # ConnectionRefusedError).
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
        pytest.raises(NetworkReachError),
    ):
        sock.connect(("127.0.0.1", 9))
