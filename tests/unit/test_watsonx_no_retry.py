"""No-retry contract tests for the watsonx SDK transport (Task 7.5 / Req 9.7).

Req 9.7 (FR-051) — "unit tests confirming no retry attempts occur for any error
type" — maps **solely** to this file in the coverage matrix, so it is the
authoritative home for the watsonx provider's no-retry contract. That contract
is the Ollama-consistent decision (Req 6.1/6.3/6.4): the provider implements
*no* retry loop and delegates all resilience to the fallback chain. It has two
complementary facets, one per construction phase:

* **Construction pin (the source of no-retry).** ``ModelInference`` is built
  with ``max_retries=0``, disabling the SDK's own retry loop at its origin
  (Req 6.1 / ADR-2). Asserted hermetically via a recording spy — the SDK's
  ``APIClient`` authenticates over the network at construction, so every SDK /
  httpx constructor is substituted and no egress occurs.
* **Behavioural pin (no retry on any failure).** For *every* error type
  ``request`` can encounter — the SDK base ``WMLClientError`` and its
  subclasses, the underlying httpx transport errors, *and* an unexpected
  non-API error that propagates unwrapped — the failing call is made **exactly
  once**: the first failure surfaces immediately with no second attempt. This is
  the literal "for any error type" half of Req 9.7. The lazy first-call client
  build (Req 4.4) is pinned too, since a network failure there must also get no
  retry.

These are characterization tests: the source already exists (``max_retries=0``
wiring at Task 5.2; the retry-free ``request`` body at Task 5.4), so they pin
and guard the contract rather than drive new code — the same posture as Tasks
7.1/7.3/7.4. The RED was the absent file (a collection error). The
single-error-type no-retry probe in ``test_watsonx_sdk_construction.py``
(``test_request_does_not_retry_on_failure``) is Task 5.4's incidental coverage;
this file generalises it to *every* error type and is Req 9.7's self-contained
home.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

# Imported at module scope (not used by name) so the SDK's ``httpx_wrapper``
# builds its ``class HTTPXAsyncClient(httpx.AsyncClient)`` subclass against the
# *real* ``httpx.AsyncClient`` before the construction test substitutes it with
# a spy — a function-typed spy installed first would make that subclass
# statement raise ``TypeError`` at import time (see test_watsonx_sdk_construction).
import ibm_watsonx_ai.foundation_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
import pytest
from ibm_watsonx_ai.wml_client_error import WMLClientError
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters

from pydantic_ai_sandbox.llm.providers.watsonx import WatsonxSDKModel

if TYPE_CHECKING:
    from tests.conftest import WatsonxSettingsFactory


# ---------------------------------------------------------------------------
# Construction pin — ``ModelInference(max_retries=0)`` (Req 6.1 / ADR-2)
# ---------------------------------------------------------------------------


class _ConstructorSpy:
    """Records the keyword arguments a substituted constructor was called with."""

    def __init__(self, _instances: list[_ConstructorSpy], **kwargs: Any) -> None:
        self.kwargs = kwargs
        _instances.append(self)


def _spy_factory() -> tuple[Any, list[_ConstructorSpy]]:
    """Return a ``(spy_class, instances)`` pair for one substituted constructor.

    The returned callable swallows arbitrary keyword arguments (matching the
    real SDK constructors' keyword-only surfaces) and appends each instance to
    ``instances`` so the test can read back the recorded call.
    """
    instances: list[_ConstructorSpy] = []

    def _make(**kwargs: Any) -> _ConstructorSpy:
        return _ConstructorSpy(instances, **kwargs)

    return _make, instances


def test_model_inference_built_with_max_retries_zero(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """``_build_client`` constructs ``ModelInference`` with ``max_retries=0`` (Req 6.1).

    This is the *source* of the no-retry contract: passing ``max_retries=0``
    disables the ``ibm-watsonx-ai`` SDK's own internal retry loop, so a failing
    inference raises on the first attempt rather than being retried inside the
    SDK. Every SDK / httpx constructor is substituted with a recording spy so
    the wiring is asserted with zero network egress (the real ``APIClient``
    authenticates at construction).
    """
    cred_spy, _ = _spy_factory()
    api_spy, _ = _spy_factory()
    mi_spy, model_inferences = _spy_factory()
    http_spy, _ = _spy_factory()

    # SDK symbols first (their modules are already imported at module scope),
    # then httpx last so no SDK import observes a function-typed AsyncClient.
    monkeypatch.setattr("ibm_watsonx_ai.Credentials", cred_spy)
    monkeypatch.setattr("ibm_watsonx_ai.APIClient", api_spy)
    monkeypatch.setattr("ibm_watsonx_ai.foundation_models.ModelInference", mi_spy)
    monkeypatch.setattr(httpx, "AsyncClient", http_spy)

    model = WatsonxSDKModel(watsonx_settings_factory())
    model._build_client()  # pyright: ignore[reportPrivateUsage]

    assert model_inferences[0].kwargs["max_retries"] == 0


# ---------------------------------------------------------------------------
# Behavioural pin — the failing call is made exactly once for any error type
# ---------------------------------------------------------------------------


class _FakeSDKSubError(WMLClientError):
    """A stand-in ``WMLClientError`` subclass with the plain base constructor.

    The real SDK subclasses (``ApiRequestFailure`` / ``AuthenticationError``)
    require a ``response`` argument that is awkward to fabricate hermetically;
    this local subclass inherits ``WMLClientError``'s constructor unchanged so
    it proves the no-retry guarantee holds for *every* SDK error subclass, not
    just the base.
    """


class _CountingFailingClient:
    """Stand-in for ``ModelInference`` whose ``achat`` always raises, counting calls.

    The ``calls`` counter is the load-bearing assertion: the no-retry contract
    (Req 6.1/6.3/6.4) requires the failing call be made exactly once — there is
    no provider-level retry loop, so the first failure propagates immediately.
    """

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.calls = 0

    async def achat(self, **_kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        raise self._exc


def _stub_failing_achat(
    monkeypatch: pytest.MonkeyPatch,
    model: WatsonxSDKModel,
    exc: BaseException,
) -> _CountingFailingClient:
    """Replace ``model._build_client`` with a client whose ``achat`` raises ``exc``."""
    client = _CountingFailingClient(exc)
    monkeypatch.setattr(model, "_build_client", lambda: client)
    return client


@pytest.mark.parametrize(
    ("exc", "label"),
    [
        (WMLClientError("watsonx api request failed"), "WMLClientError base"),
        (_FakeSDKSubError("auth rejected"), "WMLClientError subclass"),
        (httpx.ReadTimeout("read timed out"), "httpx timeout"),
        (httpx.ConnectError("connection refused"), "httpx connect error"),
        (httpx.HTTPError("generic transport error"), "httpx.HTTPError base"),
    ],
)
async def test_request_does_not_retry_recoverable_error(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
    exc: Exception,
    label: str,
) -> None:
    """Every failover-recoverable error type fails on the first ``achat`` call.

    For the full set of errors ``request`` wraps into ``ModelAPIError`` — the
    SDK base ``WMLClientError`` and any subclass, plus the httpx transport
    errors (timeout / connect / the ``HTTPError`` base) — the failing call is
    invoked exactly once. No retry loop sits between the failure and the wrapper
    ("any error type", Req 9.7); resilience is the fallback chain's job alone.
    """
    model = WatsonxSDKModel(watsonx_settings_factory())
    client = _stub_failing_achat(monkeypatch, model, exc)

    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hi")])]
    with pytest.raises(ModelAPIError):
        await model.request(messages, None, ModelRequestParameters())

    assert client.calls == 1, label


async def test_request_does_not_retry_unwrapped_error(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """An unexpected (unwrapped) error is also made exactly once — no retry.

    The no-retry contract spans *every* error type, not only the
    failover-recoverable ones. A non-SDK / non-httpx error (here a
    programming-bug ``RuntimeError``) propagates unwrapped (it must fail loud
    rather than masquerade as a recoverable ``ModelAPIError``), and it too is
    raised on the first attempt — the absence of a retry loop is unconditional.
    """
    model = WatsonxSDKModel(watsonx_settings_factory())
    client = _stub_failing_achat(monkeypatch, model, RuntimeError("unexpected"))

    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hi")])]
    with pytest.raises(RuntimeError, match="unexpected"):
        await model.request(messages, None, ModelRequestParameters())

    assert client.calls == 1


async def test_first_call_client_build_failure_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """A failure building the SDK client on the first call gets no retry (Req 4.4).

    The SDK client is built lazily on the first request and its ``APIClient``
    authenticates over the network, so an unreachable endpoint surfaces from
    ``_build_client`` rather than ``achat``. That first-call build is attempted
    exactly once — the no-retry contract covers the build path as well as the
    inference call — and the failure still surfaces as ``ModelAPIError`` so the
    fallback chain can recover it.
    """
    model = WatsonxSDKModel(watsonx_settings_factory())
    calls = {"n": 0}
    boom = httpx.ConnectError("name resolution failed")

    def _raise() -> Any:
        calls["n"] += 1
        raise boom

    monkeypatch.setattr(model, "_build_client", _raise)

    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("hi")])]
    with pytest.raises(ModelAPIError):
        await model.request(messages, None, ModelRequestParameters())

    assert calls["n"] == 1
