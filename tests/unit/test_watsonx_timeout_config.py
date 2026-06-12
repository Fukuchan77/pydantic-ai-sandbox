"""Timeout-configuration unit tests for the watsonx provider (Task 7.3 / Req 9.5).

Req 9.5 mandates a dedicated unit-test suite for watsonx *timeout configuration*
covering four cases: **default** values (30s connect / 120s read), **custom**
values (env overrides), **invalid** values (negative / zero / non-numeric), and a
**simulated-timeout** scenario. This file is that suite — the home the coverage
matrix maps Req 9.5 to.

Relationship to the sibling boundary files (no duplication of intent):

* The *transport-application* of timeouts — that the configured connect/read
  phases reach each transport's ``httpx`` client — is pinned per transport in
  ``test_watsonx_sdk_construction.py`` (``test_build_client_applies_default_timeouts``
  / ``..._overridden_timeouts``, via SDK-constructor spies) and
  ``test_watsonx_litellm_construction.py`` (``test_litellm_timeouts_wired_via_http_client``
  / ``..._honour_env_overrides``, via the built OpenAI client). Req 5.4 ("apply to
  both ``sdk`` and ``litellm``") is therefore already covered at the wiring grain.
* This file owns the **configuration source-of-truth** (the validated
  :class:`Settings` values both transports read) and the **simulated-timeout**
  behaviour, which no other file covers.

Covered requirements:

* **5.1** — default 30s connect / 120s read when the env vars are unset.
* **5.2 / 5.3** — ``WATSONX_TIMEOUT_CONNECT`` / ``WATSONX_TIMEOUT_READ`` override
  the defaults.
* **5.5** — a non-positive / non-numeric value fails fast at construction with a
  :class:`pydantic.ValidationError` naming the offending env var.
* **5.6 / SC-015** — when a timeout expires during a request, the timeout is
  surfaced **solely** through the (failover-recoverable) ``error.class`` channel:
  the underlying timeout exception is wrapped into
  :class:`pydantic_ai.exceptions.ModelAPIError`, its class name is carried for the
  span's ``error.class`` attribute, and **no** timeout-duration attribute is
  attached (the lean attribute cap of 8.3/8.4 wins; Logfire records wall-clock
  duration intrinsically).

All tests are hermetic: the configuration cases construct :class:`Settings` from
explicit env via the ``watsonx_settings_factory`` (no ambient leakage), and the
simulated-timeout case substitutes the lazy SDK client with a fake whose
``achat`` raises a genuine :class:`httpx.ReadTimeout` — zero network egress.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest
from pydantic import ValidationError
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters

from pydantic_ai_sandbox.llm.providers.watsonx import WatsonxSDKModel
from tests.conftest import WATSONX_TEST_MODEL_ID

if TYPE_CHECKING:
    from tests.conftest import WatsonxSettingsFactory


# --- 5.1: default timeouts -------------------------------------------------- #


def test_timeout_defaults_are_30s_connect_and_120s_read(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """Unset timeout env yields the 30s connect / 120s read defaults (Req 5.1, SC-014).

    The defaults are the single source of truth both transports read when no
    override is supplied; the construction tests prove those values reach each
    transport's ``httpx`` client.
    """
    settings = watsonx_settings_factory()

    assert settings.watsonx_timeout_connect == 30
    assert settings.watsonx_timeout_read == 120


# --- 5.2 / 5.3: custom (env-overridden) timeouts ---------------------------- #


def test_timeout_env_overrides_replace_the_defaults(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """``WATSONX_TIMEOUT_CONNECT`` / ``_READ`` override the defaults (Req 5.2/5.3).

    String env values (as the process actually supplies them) are parsed to the
    integer seconds the transports apply.
    """
    settings = watsonx_settings_factory(
        WATSONX_TIMEOUT_CONNECT="7",
        WATSONX_TIMEOUT_READ="300",
    )

    assert settings.watsonx_timeout_connect == 7
    assert settings.watsonx_timeout_read == 300


# --- 5.5: invalid timeouts fail fast at construction ------------------------ #


@pytest.mark.parametrize(
    ("env_var", "field_label"),
    [
        ("WATSONX_TIMEOUT_CONNECT", "connect"),
        ("WATSONX_TIMEOUT_READ", "read"),
    ],
)
@pytest.mark.parametrize(
    ("bad_value", "case"),
    [
        ("-1", "negative"),
        ("0", "zero"),
        ("abc", "non-numeric"),
        ("12.5", "non-integer-numeric"),
    ],
)
def test_timeout_rejects_invalid_value_at_construction(
    watsonx_settings_factory: WatsonxSettingsFactory,
    env_var: str,
    field_label: str,
    bad_value: str,
    case: str,
) -> None:
    """A non-positive / non-numeric timeout fails fast at construction (Req 5.5).

    Negative, zero, non-numeric and non-integer-numeric values are all rejected
    by the field validator. Because the failure happens during
    :class:`Settings` construction, an operator misconfiguration is caught at
    boot rather than deferred to the first request; the message names the
    offending env var so the fix is unambiguous. Pydantic wraps the validator's
    ``ValueError`` into :class:`pydantic.ValidationError` before it reaches the
    caller, so the test asserts on that.
    """
    with pytest.raises(ValidationError) as exc_info:
        watsonx_settings_factory(**{env_var: bad_value})

    assert env_var in str(exc_info.value), f"{field_label} / {case}"


# --- 5.6 / SC-015: simulated timeout → error.class only, no duration -------- #


class _TimingOutAchatClient:
    """Stand-in for ``ModelInference`` whose ``achat`` raises a timeout.

    Mirrors the real async coroutine's surface so the production ``request`` path
    runs unchanged, but the awaited ``achat`` raises the configured
    :class:`httpx.TimeoutException` — a genuine timeout exception — with no
    network egress.
    """

    def __init__(self, exc: httpx.TimeoutException) -> None:
        self._exc = exc

    async def achat(self, **_kwargs: Any) -> dict[str, Any]:
        raise self._exc


async def test_simulated_timeout_surfaces_via_error_class_without_duration(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """A request-time timeout surfaces solely via ``error.class`` (Req 5.6 / SC-015).

    Simulates a read timeout expiring during the ``achat`` call. The contract
    (clarified 2026-06-08, revising the original 5.6): the timeout is surfaced
    **only** through the ``error.class`` channel and **no** timeout-duration
    attribute is added, so spans stay within the lean cap of 8.3/8.4 (Logfire
    records wall-clock duration intrinsically). At the unit grain this means:

    1. the underlying :class:`httpx.ReadTimeout` is wrapped into the
       failover-recoverable :class:`pydantic_ai.exceptions.ModelAPIError`
       (``FallbackModel.fallback_on`` defaults to ``(ModelAPIError,)``), so the
       timeout triggers failover rather than escaping the chain;
    2. the timeout exception's class name is carried (in the message and via the
       chained ``__cause__``) — the information the span's ``error.class``
       attribute is derived from;
    3. the raised error exposes **no** duration / timeout-seconds attribute.
    """
    model = WatsonxSDKModel(watsonx_settings_factory())
    timeout_exc = httpx.ReadTimeout("read operation timed out")
    monkeypatch.setattr(model, "_build_client", lambda: _TimingOutAchatClient(timeout_exc))

    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hi")])]
    with pytest.raises(ModelAPIError) as exc_info:
        await model.request(messages, None, ModelRequestParameters())

    error = exc_info.value
    # (1) failover-recoverable wrapper, carrying the configured model identity.
    assert error.model_name == WATSONX_TEST_MODEL_ID
    # (2) the timeout exception class is the surfaced signal (error.class channel).
    assert error.__cause__ is timeout_exc
    assert "ReadTimeout" in str(error)
    # (3) no timeout-duration attribute is attached to the surfaced error.
    for forbidden in ("duration", "timeout", "timeout_duration", "elapsed", "seconds"):
        assert not hasattr(error, forbidden), forbidden
