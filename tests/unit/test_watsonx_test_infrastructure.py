"""Tests for the watsonx test infrastructure landed by Task 3.

Task 3 owns two shared test primitives consumed by the watsonx unit suite
(Tasks 7.1-7.8) and the fallback integration lane (Task 7.6):

* ``watsonx_settings_factory`` (``tests/conftest.py``, Task 3.1) — a builder
  that seats a complete, valid watsonx credential set (``LLM_PROVIDER=watsonx``
  + the four required ``WATSONX_*`` vars) and lets callers override individual
  keys (e.g. flip the transport, override a timeout, or express a credential as
  explicitly-absent by passing ``None``). It delegates to ``settings_factory``
  so the ambient-shell isolation contract (``_MANAGED_ENV_KEYS``) is inherited.
* ``watsonx_function_model_failing`` (``tests/support/model_fakes.py``,
  Task 3.2) — a ``FunctionModel`` double that raises
  :class:`pydantic_ai.exceptions.ModelAPIError` on every request, with a
  watsonx-flavoured ``model_name`` so it surfaces in the ``FallbackModel`` span
  chain. ``ModelAPIError`` is the *only* class ``FallbackModel`` recovers by
  default, so the double proves the failover path engages (Req 7.4).

These tests are the RED→GREEN evidence for Task 3 itself; the downstream
``test_watsonx_*`` files (Task 7) merely consume the primitives validated here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import FunctionModel

from tests.conftest import (
    WATSONX_TEST_APIKEY,
    WATSONX_TEST_MODEL_ID,
    WATSONX_TEST_PROJECT_ID,
    WATSONX_TEST_URL,
)
from tests.support.model_fakes import (
    function_model_returning_json,
    watsonx_function_model_failing,
)

if TYPE_CHECKING:
    from tests.conftest import WatsonxSettingsFactory


# --------------------------------------------------------------------------- #
# Task 3.1 — watsonx_settings_factory fixture                                  #
# --------------------------------------------------------------------------- #


def test_watsonx_settings_factory_builds_fully_credentialled_settings(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """Default invocation yields a watsonx-selected, fully-credentialled Settings.

    The four required credentials must be present and the API key recoverable,
    so downstream construction tests (Task 7.1) can build a ``WatsonxSDKModel``
    without re-seating env in every test.
    """
    settings = watsonx_settings_factory()

    assert settings.llm_provider == "watsonx"
    assert settings.watsonx_url == WATSONX_TEST_URL
    assert settings.watsonx_model_id == WATSONX_TEST_MODEL_ID
    assert settings.watsonx_project_id == WATSONX_TEST_PROJECT_ID
    assert settings.watsonx_apikey is not None
    assert settings.watsonx_apikey.get_secret_value() == WATSONX_TEST_APIKEY
    # Unset transport defaults to "sdk" (Req 2.2) — the factory leaves it unset.
    assert settings.watsonx_transport == "sdk"


def test_watsonx_settings_factory_applies_overrides(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """Caller overrides win over the seated defaults (transport + timeouts).

    Task 7.2 (litellm) and Task 7.3 (timeouts) rely on this knob to vary one
    field while keeping the rest of the credential set valid.
    """
    settings = watsonx_settings_factory(
        WATSONX_TRANSPORT="litellm",
        WATSONX_TIMEOUT_CONNECT="15",
        WATSONX_TIMEOUT_READ="200",
    )

    assert settings.watsonx_transport == "litellm"
    assert settings.watsonx_timeout_connect == 15
    assert settings.watsonx_timeout_read == 200
    # Overrides must not disturb the seated credentials.
    assert settings.watsonx_model_id == WATSONX_TEST_MODEL_ID


def test_watsonx_settings_factory_can_express_absent_credential(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """Passing ``None`` drops a credential, exercising the fail-fast gate.

    This is the path Task 7.8 uses to assert the boot-time ``ValueError`` —
    the factory must thread ``None`` through to ``settings_factory`` (which
    leaves the key unset) rather than coercing it to the default.
    """
    with pytest.raises(ValidationError) as exc_info:
        watsonx_settings_factory(WATSONX_PROJECT_ID=None)

    assert "WATSONX_PROJECT_ID" in str(exc_info.value)


# --------------------------------------------------------------------------- #
# Task 3.2 — watsonx_function_model_failing double                             #
# --------------------------------------------------------------------------- #


def test_watsonx_double_is_function_model_named_watsonx() -> None:
    """The double is a ``FunctionModel`` carrying a watsonx ``model_name``.

    The default ``model_name="watsonx"`` is what surfaces in the
    ``FallbackModel`` chain span ("fallback:...,watsonx") so Task 7.6 can
    assert watsonx participated in (and failed out of) the chain.
    """
    double = watsonx_function_model_failing()

    assert isinstance(double, FunctionModel)
    assert double.model_name == "watsonx"


def test_watsonx_double_raises_recoverable_model_api_error() -> None:
    """The double raises ``ModelAPIError`` and so triggers ``FallbackModel`` recovery.

    Placing the double as the first member with a healthy second member proves
    the raised error is in ``FallbackModel``'s default ``fallback_on`` tuple
    (``(ModelAPIError,)``) — i.e. watsonx failures fail *over* rather than
    *out* (Req 7.1/7.2/7.4). A raw exception would propagate and fail this test.
    """
    fallback = FallbackModel(
        watsonx_function_model_failing(message="watsonx is down"),
        function_model_returning_json({"reply": "second member answered"}),
    )
    agent = Agent(model=fallback)

    result = agent.run_sync("trigger failover")

    assert "second member answered" in result.output


def test_watsonx_double_message_and_name_are_customisable() -> None:
    """Both the error message and provider name are caller-tunable.

    Failover tests that distinguish multiple failing members (or assert on the
    surfaced message) need to vary these independently.
    """
    double = watsonx_function_model_failing(
        message="429 rate limited",
        model_name="watsonx-primary",
    )
    agent = Agent(model=double)

    try:
        agent.run_sync("anything")
    except ModelAPIError as err:
        assert "429 rate limited" in str(err)
    else:  # pragma: no cover - the double must always raise
        msg = "watsonx_function_model_failing did not raise ModelAPIError"
        raise AssertionError(msg)

    assert double.model_name == "watsonx-primary"
