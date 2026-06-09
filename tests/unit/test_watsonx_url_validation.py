"""URL-format validation unit tests for the watsonx provider (Task 7.4 / Req 9.6).

Req 9.6 mandates a dedicated unit-test suite for ``WATSONX_URL`` *structural*
validation, covering three obligations: **valid** formats pass, **invalid**
formats fail fast with a detailed message, and **no network call** occurs during
validation (structure-only; reachability is deferred to runtime — Req 4.1/4.2/4.3).
This file is that suite — the authoritative home the coverage matrix maps Req 9.6
to.

Relationship to the sibling ``test_config.py`` block (no duplication of intent):

* ``test_config.py`` exercises the validator as one facet of the broader
  ``Settings`` env-var contract (Task 3.2), with a small smoke set of good/bad
  URLs alongside the credential gate and transport normalization.
* This file owns Req 9.6 end to end: it isolates the field validator from the
  credential gate (constructs with ``LLM_PROVIDER=ollama`` so an invalid
  ``WATSONX_URL`` can *only* surface from the URL validator, never the gate),
  asserts the *detailed* wording the operator sees, and proves the structural
  contract's edges — scheme case-folding, reachability-free acceptance of an
  unresolvable host, and the unset-is-skipped path.

The validator under test (``Settings._validate_watsonx_url``) accepts a value iff
:func:`urllib.parse.urlparse` yields an ``http``/``https`` scheme **and** a
non-empty ``netloc``; everything else is rejected. ``None`` (unset) is allowed —
the field is optional and the credential gate, not this validator, enforces
presence when watsonx is selected.

All tests are hermetic: ``settings_factory`` clears ``_MANAGED_ENV_KEYS`` before
building, so no ambient ``WATSONX_URL`` leaks in, and the no-network test detonates
``socket.socket`` to prove construction never opens a socket.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

if TYPE_CHECKING:
    from tests.conftest import SettingsFactory

# Ollama context that lets the URL validator run in isolation: a valid
# ollama selection satisfies the model-name gate and keeps the watsonx
# credential gate dormant, so an invalid WATSONX_URL surfaces from the
# field validator alone (its message is the only one under assertion).
_OLLAMA_BASE_URL = "http://localhost:11434"
_OLLAMA_MODEL = "dummy-ollama-model"


def _ollama_ctx(**overrides: str | None) -> dict[str, str | None]:
    """Return a minimal valid ollama env, with caller overrides layered on."""
    ctx: dict[str, str | None] = {
        "LLM_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": _OLLAMA_BASE_URL,
        "OLLAMA_MODEL_NAME": _OLLAMA_MODEL,
    }
    ctx.update(overrides)
    return ctx


# --- valid formats pass (round-trip unchanged) ------------------------------ #


@pytest.mark.parametrize(
    "good_url",
    [
        "https://us-south.ml.cloud.ibm.com",  # canonical IBM Cloud region host
        "http://localhost:8080",  # http scheme + explicit port
        "https://eu-de.ml.cloud.ibm.com/v1",  # path component retained
        "https://10.0.0.1:443",  # IP host + port
        "HTTPS://Example.com",  # scheme case-folded by urlparse → https
    ],
)
def test_valid_url_is_accepted_and_round_trips_unchanged(
    settings_factory: SettingsFactory,
    good_url: str,
) -> None:
    """A structurally-valid ``WATSONX_URL`` passes and is stored verbatim (Req 4.1).

    The validator returns the original string untouched (no normalization), so a
    host's original casing/path/port survive to the SDK/litellm call sites that
    consume it. ``HTTPS://Example.com`` is included deliberately: ``urlparse``
    lower-cases the *scheme* before the membership check, so an upper-cased
    scheme is accepted without the validator itself mutating the stored value.
    """
    settings = settings_factory(**_ollama_ctx(WATSONX_URL=good_url))

    assert settings.watsonx_url == good_url


def test_unset_url_is_allowed_and_skips_validation(
    settings_factory: SettingsFactory,
) -> None:
    """An absent ``WATSONX_URL`` is allowed — presence is the gate's job, not this one.

    ``watsonx_url`` is optional; the field validator short-circuits on ``None`` so
    an ollama-only (or any non-watsonx) deployment need not supply it. Requiring
    it when watsonx is actually selected is the credential gate's responsibility
    (Req 3.x), exercised in Task 7.8 — not this structural validator.
    """
    settings = settings_factory(**_ollama_ctx(WATSONX_URL=None))

    assert settings.watsonx_url is None


# --- invalid formats fail fast with a detailed message ---------------------- #


@pytest.mark.parametrize(
    ("bad_url", "reason"),
    [
        ("not-a-url", "no scheme, no host"),
        ("us-south.ml.cloud.ibm.com", "bare host parses as path, no scheme/netloc"),
        ("httpsexample.com", "missing :// separator"),
        ("ftp://example.com", "scheme outside {http, https}"),
        ("ws://example.com", "websocket scheme rejected"),
        ("file:///etc/passwd", "file scheme has no netloc and wrong scheme"),
        ("https://", "valid scheme but empty host"),
        ("http://", "valid scheme but empty host"),
        ("://nohost", "no scheme, no host"),
        ("", "empty string parses to empty scheme/netloc"),
    ],
)
def test_invalid_url_fails_fast_with_detailed_message(
    settings_factory: SettingsFactory,
    bad_url: str,
    reason: str,
) -> None:
    """An ill-formed ``WATSONX_URL`` is rejected at construction (Req 4.2).

    Either a non-``http(s)`` scheme *or* a missing host trips the validator. The
    failure happens during :class:`Settings` construction — fail-fast, before any
    request — and the surfaced message is *detailed*: it names the offending env
    var, states the required ``http(s)://`` shape, and offers a concrete example.
    Asserting on that distinctive wording also proves it is the *format* validator
    that fired, not the watsonx credential gate (which shares the ``WATSONX_URL``
    token but is kept dormant here via ``LLM_PROVIDER=ollama``).

    Pydantic wraps the validator's ``ValueError`` into
    :class:`pydantic.ValidationError` before it reaches the caller, so the test
    asserts on that surfaced class.
    """
    with pytest.raises(ValidationError) as exc_info:
        settings_factory(**_ollama_ctx(WATSONX_URL=bad_url))

    message = str(exc_info.value)
    assert "WATSONX_URL" in message, reason
    # Detailed-message contract: required shape + concrete example, not a bare
    # "invalid value". This wording is unique to the format validator, so its
    # presence distinguishes the format failure from the credential gate's.
    assert "must be a valid URL" in message, reason
    assert "http(s)://" in message, reason
    assert "us-south.ml.cloud.ibm.com" in message, reason
    # The offending value is echoed back so the operator sees exactly what was set.
    assert repr(bad_url) in message, reason


# --- no network / reachability call occurs during validation ---------------- #


def test_validation_opens_no_network_socket(
    settings_factory: SettingsFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """URL validation is purely structural — it never opens a socket (Req 4.1/4.3).

    Detonate the stdlib ``socket.socket`` constructor, then build a
    fully-credentialled watsonx :class:`Settings`. Construction — including URL
    validation *and* the credential gate — must complete without touching the
    network; a DNS lookup or connection attempt would trip the booby-trapped
    constructor and fail the test.
    """
    import socket

    def _boom(*_args: object, **_kwargs: object) -> None:
        msg = "URL validation must not open a network socket"
        raise AssertionError(msg)

    monkeypatch.setattr(socket, "socket", _boom)

    settings = settings_factory(
        LLM_PROVIDER="watsonx",
        WATSONX_APIKEY="k-watsonx-test-secret",
        WATSONX_PROJECT_ID="proj-0000",
        WATSONX_URL="https://us-south.ml.cloud.ibm.com",
        WATSONX_MODEL_ID="dummy-watsonx-model",
    )

    assert settings.watsonx_url == "https://us-south.ml.cloud.ibm.com"


def test_unresolvable_host_passes_validation_proving_no_reachability_check(
    settings_factory: SettingsFactory,
) -> None:
    """A well-formed but unreachable host is accepted — reachability is deferred (Req 4.3).

    A ``.invalid`` TLD (RFC 6761: guaranteed never to resolve) is structurally a
    valid ``https://host`` URL. That it passes validation is positive proof the
    validator checks *shape only* and performs no DNS resolution or connection —
    reachability surfaces at request time, not construction time.
    """
    settings = settings_factory(
        **_ollama_ctx(WATSONX_URL="https://watsonx-does-not-exist-zzz.invalid"),
    )

    assert settings.watsonx_url == "https://watsonx-does-not-exist-zzz.invalid"
