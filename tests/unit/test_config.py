"""Unit tests for ``pydantic_ai_sandbox.config.Settings`` (Task 3.2).

Locks the env-var contract from plan.md §2.1:

* normal path — LLM_PROVIDER=ollama + required vars → constructs cleanly.
* fail-fast — missing OLLAMA_MODEL_NAME under provider=ollama surfaces a
  ValidationError naming the offending env var (Req 1.2).
* fail-fast — provider=fallback with empty / all-unknown FALLBACK_ORDER is
  rejected at Settings construction (Req 4.5 構文段).
* fail-fast — unknown LLM_PROVIDER value is rejected (Req 2.5 前段).
* LOGFIRE_TOKEN absence does not block startup (Req 5.2 前段).

Note on exception class: tasks.md T3.2 mentions "ValueError" for
fallback / unknown-provider cases. In Pydantic v2 a validator raising
``ValueError`` is wrapped into :class:`pydantic.ValidationError` before
reaching the caller, and ``ValidationError`` is *not* a subclass of
``ValueError``. The tests therefore assert on ``ValidationError`` (the
class actually surfaced) and inspect the error chain / message for the
expected wording.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, get_args, get_type_hints

import pytest
from pydantic import ValidationError

from pydantic_ai_sandbox.config import Settings, get_settings

if TYPE_CHECKING:
    from tests.conftest import SettingsFactory, WatsonxSettingsFactory


# A placeholder model name that is intentionally outside
# FORBIDDEN_MODEL_ID_LITERALS so these tests cannot inadvertently regress
# the hardcoded-model-ID guard (T2.1) when scanned.
DUMMY_OLLAMA_MODEL = "dummy-ollama-model"
DUMMY_OLLAMA_URL = "http://localhost:11434"


def test_ollama_happy_path_returns_frozen_literal_provider(
    settings_factory: SettingsFactory,
) -> None:
    settings = settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
    )

    # llm_provider must be normalised to the Literal alphabet; equality
    # check is enough — the type system guarantees the rest at static time.
    assert settings.llm_provider == "ollama"
    assert settings.ollama_model_name == DUMMY_OLLAMA_MODEL

    # frozen=True (plan §2.1): mutation must be blocked.
    with pytest.raises(ValidationError):
        settings.llm_provider = "anthropic"  # pyright: ignore[reportAttributeAccessIssue]


def test_llm_provider_literal_alphabet_is_authoritative() -> None:
    """Lock the Literal alphabet so silent additions can't slip through.

    plan.md §2.1 specifies five providers; tasks downstream (T4.x, T5.x)
    branch on this exact set. If anyone adds or renames a provider the
    Literal hint is the one place that must change in lockstep with the
    factory dispatch table — this test surfaces the drift.
    """
    hints = get_type_hints(Settings)
    literal_args = set(get_args(hints["llm_provider"]))
    assert literal_args == {"ollama", "watsonx", "anthropic", "bedrock", "fallback"}


def test_ollama_provider_requires_model_name(
    settings_factory: SettingsFactory,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        settings_factory(
            LLM_PROVIDER="ollama",
            OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
            OLLAMA_MODEL_NAME=None,
        )

    # The validator MUST name the offending variable so operators can fix
    # the deployment from the error alone (Req 1.2).
    assert "OLLAMA_MODEL_NAME" in str(exc_info.value)


def test_unknown_llm_provider_is_rejected(
    settings_factory: SettingsFactory,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        settings_factory(LLM_PROVIDER="foobar")

    # Pydantic's Literal-mismatch error mentions the offending value;
    # we assert that hint to guard against accidental ``str`` widening.
    assert "foobar" in str(exc_info.value)


def test_fallback_provider_rejects_empty_order(
    settings_factory: SettingsFactory,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        settings_factory(
            LLM_PROVIDER="fallback",
            FALLBACK_ORDER="",
        )

    assert "FALLBACK_ORDER" in str(exc_info.value)


def test_fallback_provider_rejects_only_unknown_members(
    settings_factory: SettingsFactory,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        settings_factory(
            LLM_PROVIDER="fallback",
            FALLBACK_ORDER="not-a-provider,also-bogus",
        )

    msg = str(exc_info.value)
    assert "FALLBACK_ORDER" in msg
    assert "not-a-provider" in msg or "also-bogus" in msg


def test_fallback_provider_accepts_known_member(
    settings_factory: SettingsFactory,
) -> None:
    """``FALLBACK_ORDER=ollama`` must parse — the unknown-only check is
    not a blanket ban on single-member lists."""
    settings = settings_factory(
        LLM_PROVIDER="fallback",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
        FALLBACK_ORDER="ollama",
    )
    assert settings.fallback_order == "ollama"


def test_logfire_token_optional(settings_factory: SettingsFactory) -> None:
    settings = settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
        LOGFIRE_TOKEN=None,
    )

    assert settings.logfire_token is None
    # Explicitly check the field surfaces — Req 5.2 前段 ("Settings 自体は成立")
    # depends on this attribute existing and being None when the env var
    # is unset.
    assert hasattr(settings, "logfire_token")


def test_secret_fields_redact_in_repr(
    settings_factory: SettingsFactory,
) -> None:
    """Secret fields render as redacted in ``repr(settings)`` and ``str(...)``.

    Adversarial review (MEDIUM) flagged that plain ``str | None`` typing
    leaks tokens whenever a Settings instance is interpolated into a log
    line or unhandled-traceback frame — the stdlib ``logger.warning(...,
    exc_info=True)`` path in :mod:`logging_setup` is *not* Logfire-scrubbed
    at the formatter layer, so a leaked token propagates to whatever log
    aggregator is configured. ``pydantic.SecretStr`` overrides
    ``__repr__`` / ``__str__`` to return ``"**********"`` regardless of
    payload, eliminating the leak surface end-to-end.

    This test pins the four secret-bearing fields. Adding a new credential
    field that bypasses ``SecretStr`` will fail this assertion immediately,
    keeping the leak guard in lockstep with the schema.
    """
    leak_canary = "k-mvp-credential-DO-NOT-LOG"
    settings = settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
        OLLAMA_API_KEY=leak_canary,
        WATSONX_APIKEY=leak_canary,
        ANTHROPIC_API_KEY=leak_canary,
        LOGFIRE_TOKEN=leak_canary,
    )

    rendered = repr(settings) + "|" + str(settings)
    assert leak_canary not in rendered, (
        f"secret token leaked into repr/str output of Settings; "
        f"all four secret fields MUST be SecretStr-typed. "
        f"Rendered={rendered!r}"
    )


def test_secret_field_value_is_recoverable_via_get_secret_value(
    settings_factory: SettingsFactory,
) -> None:
    """``SecretStr.get_secret_value()`` returns the raw token at SDK call sites.

    The SecretStr wrapper hides values at repr time but MUST surface them
    on demand for SDK construction (e.g., ``OllamaProvider(api_key=...)``,
    ``logfire.configure(token=...)``). Asserting via
    :meth:`SecretStr.get_secret_value` rather than ``str(settings.field)``
    is the documented Pydantic v2 contract; relying on ``str(...)`` would
    only return the redacted form.
    """
    raw = "k-recovered-secret"
    settings = settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
        LOGFIRE_TOKEN=raw,
    )

    assert settings.logfire_token is not None
    assert settings.logfire_token.get_secret_value() == raw


# --------------------------------------------------------------------------- #
# Task 2 — watsonx configuration & fail-fast validation (Req 2.2/2.4/2.5,      #
# 3.1/3.2/3.3, 4.1/4.2/4.3, 5.1/5.2/5.3/5.5).                                   #
#                                                                              #
# These lock the config-layer contract for the watsonx provider: timeout       #
# fields + validators, transport normalization/default, URL-format validation, #
# and the credential gate. Per Pydantic v2 a validator-raised ``ValueError`` is #
# surfaced to the caller as :class:`pydantic.ValidationError`, so the tests     #
# assert on that class and inspect the message for the required wording.        #
# --------------------------------------------------------------------------- #

# Placeholder credentials kept outside FORBIDDEN_MODEL_ID_LITERALS so this file
# never regresses the hardcoded-model-ID guard.
DUMMY_WATSONX_URL = "https://us-south.ml.cloud.ibm.com"
DUMMY_WATSONX_MODEL = "dummy-watsonx-model"
DUMMY_WATSONX_SECRET = "k-watsonx-test-secret"
DUMMY_WATSONX_PROJECT = "proj-0000"


def _watsonx_creds() -> dict[str, str]:
    """Return a complete, valid watsonx credential override set."""
    return {
        "WATSONX_APIKEY": DUMMY_WATSONX_SECRET,
        "WATSONX_PROJECT_ID": DUMMY_WATSONX_PROJECT,
        "WATSONX_URL": DUMMY_WATSONX_URL,
        "WATSONX_MODEL_ID": DUMMY_WATSONX_MODEL,
    }


# --- 2.1 / 5.1-5.3: timeout fields + defaults + env overrides --------------- #


def test_watsonx_timeout_defaults_are_30_and_120(
    settings_factory: SettingsFactory,
) -> None:
    """Unset timeout env → 30s connect / 120s read (Req 5.1, SC-014)."""
    settings = settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
    )
    assert settings.watsonx_timeout_connect == 30
    assert settings.watsonx_timeout_read == 120


def test_watsonx_timeout_env_overrides(
    settings_factory: SettingsFactory,
) -> None:
    """`WATSONX_TIMEOUT_CONNECT` / `_READ` override the defaults (Req 5.2/5.3)."""
    settings = settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
        WATSONX_TIMEOUT_CONNECT="10",
        WATSONX_TIMEOUT_READ="240",
    )
    assert settings.watsonx_timeout_connect == 10
    assert settings.watsonx_timeout_read == 240


# --- 2.5: timeout validators reject non-positive / non-numeric -------------- #


@pytest.mark.parametrize("bad_value", ["0", "-5", "abc", "3.5"])
def test_watsonx_timeout_connect_rejects_invalid(
    settings_factory: SettingsFactory,
    bad_value: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        settings_factory(
            LLM_PROVIDER="ollama",
            OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
            OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
            WATSONX_TIMEOUT_CONNECT=bad_value,
        )
    assert "WATSONX_TIMEOUT_CONNECT" in str(exc_info.value)


@pytest.mark.parametrize("bad_value", ["0", "-1", "not-a-number"])
def test_watsonx_timeout_read_rejects_invalid(
    settings_factory: SettingsFactory,
    bad_value: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        settings_factory(
            LLM_PROVIDER="ollama",
            OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
            OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
            WATSONX_TIMEOUT_READ=bad_value,
        )
    assert "WATSONX_TIMEOUT_READ" in str(exc_info.value)


# --- 2.3: transport normalization, default, and valid-value error ----------- #


def test_watsonx_transport_defaults_to_sdk(
    settings_factory: SettingsFactory,
) -> None:
    """Unset `WATSONX_TRANSPORT` → `"sdk"` (Req 2.2)."""
    settings = settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
    )
    assert settings.watsonx_transport == "sdk"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("SDK", "sdk"), ("sdk", "sdk"), ("LiteLLM", "litellm"), ("LITELLM", "litellm")],
)
def test_watsonx_transport_is_case_insensitive(
    settings_factory: SettingsFactory,
    raw: str,
    expected: str,
) -> None:
    """`WATSONX_TRANSPORT` is matched case-insensitively (Req 2.4)."""
    settings = settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
        WATSONX_TRANSPORT=raw,
    )
    assert settings.watsonx_transport == expected


def test_watsonx_transport_rejects_unknown_value(
    settings_factory: SettingsFactory,
) -> None:
    """Out-of-set transport fails fast and lists the valid values (Req 2.5)."""
    with pytest.raises(ValidationError) as exc_info:
        settings_factory(
            LLM_PROVIDER="ollama",
            OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
            OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
            WATSONX_TRANSPORT="grpc",
        )
    msg = str(exc_info.value)
    assert "sdk" in msg
    assert "litellm" in msg


def test_watsonx_transport_blank_value_defaults_to_sdk(
    settings_factory: SettingsFactory,
) -> None:
    """An empty `WATSONX_TRANSPORT` (`""`) normalises to `"sdk"` (Req 2.2).

    A blank string is a real env-channel value (`WATSONX_TRANSPORT=` in a
    `.env`), distinct from an unset var: the `mode="before"` validator strips and
    lower-cases it to `""`, then falls back to the `"sdk"` default rather than
    failing the `Literal` check.
    """
    settings = settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
        WATSONX_TRANSPORT="",
    )
    assert settings.watsonx_transport == "sdk"


def test_watsonx_transport_none_value_defaults_to_sdk(
    settings_factory: SettingsFactory,
) -> None:
    """An explicit `None` for `watsonx_transport` normalises to `"sdk"` (Req 2.2).

    The env channel can only carry strings, so the validator's `value is None`
    branch is reachable only via a direct init kwarg. Seat valid ollama env via
    the factory's side effects (it clears `_MANAGED_ENV_KEYS` and sets the ollama
    vars), then pass `watsonx_transport=None` directly: the `mode="before"`
    validator must run (returning `"sdk"`) — were it skipped, `None` would fail
    the non-optional `Literal["sdk", "litellm"]` check instead.
    """
    settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
    )
    settings = Settings(watsonx_transport=None)  # pyright: ignore[reportArgumentType]
    assert settings.watsonx_transport == "sdk"


def test_watsonx_transport_non_string_value_is_rejected(
    settings_factory: SettingsFactory,
) -> None:
    """A non-string `watsonx_transport` fails fast listing the valid values (Req 2.5).

    Like the `None` branch, a non-string value cannot arrive via the env channel;
    a direct init kwarg (`123`) drives the validator's `not isinstance(value, str)`
    guard, which raises the same valid-values `ValueError` as an out-of-set string
    (wrapped by Pydantic into `ValidationError`).
    """
    settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
    )
    with pytest.raises(ValidationError) as exc_info:
        Settings(watsonx_transport=123)  # pyright: ignore[reportArgumentType]
    msg = str(exc_info.value)
    assert "sdk" in msg
    assert "litellm" in msg


# --- 2.4: URL format validation (I/O-free) ---------------------------------- #


@pytest.mark.parametrize(
    "good_url",
    [
        "https://us-south.ml.cloud.ibm.com",
        "http://localhost:8080",
        "https://eu-de.ml.cloud.ibm.com/v1",
    ],
)
def test_watsonx_url_accepts_valid_format(
    settings_factory: SettingsFactory,
    good_url: str,
) -> None:
    settings = settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
        WATSONX_URL=good_url,
    )
    assert settings.watsonx_url == good_url


@pytest.mark.parametrize(
    "bad_url",
    ["not-a-url", "ftp://example.com", "https://", "://nohost", "us-south.ml.cloud.ibm.com"],
)
def test_watsonx_url_rejects_invalid_format(
    settings_factory: SettingsFactory,
    bad_url: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        settings_factory(
            LLM_PROVIDER="ollama",
            OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
            OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
            WATSONX_URL=bad_url,
        )
    assert "WATSONX_URL" in str(exc_info.value)


def test_watsonx_url_validation_makes_no_network_call(
    settings_factory: SettingsFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """URL validation is structural only — never opens a socket (Req 4.1/4.3).

    Patches the stdlib socket constructor to explode on use, then constructs a
    fully-credentialled watsonx Settings. Construction (incl. URL validation
    and the credential gate) must complete without touching the network.
    """
    import socket

    def _boom(*_args: object, **_kwargs: object) -> None:
        msg = "construction must not open a network socket"
        raise AssertionError(msg)

    monkeypatch.setattr(socket, "socket", _boom)

    settings = settings_factory(
        LLM_PROVIDER="watsonx",
        **_watsonx_creds(),
    )
    assert settings.watsonx_url == DUMMY_WATSONX_URL


# --- 2.2 / 3.1-3.3: credential gate (direct + fallback selection) ----------- #


@pytest.mark.parametrize(
    "missing_key",
    ["WATSONX_APIKEY", "WATSONX_PROJECT_ID", "WATSONX_URL", "WATSONX_MODEL_ID"],
)
def test_watsonx_direct_selection_requires_each_credential(
    settings_factory: SettingsFactory,
    missing_key: str,
) -> None:
    """LLM_PROVIDER=watsonx + one missing cred → ValueError naming it (Req 3.2)."""
    creds = _watsonx_creds()
    creds[missing_key] = None  # type: ignore[assignment]  # express "explicitly absent"
    with pytest.raises(ValidationError) as exc_info:
        settings_factory(LLM_PROVIDER="watsonx", **creds)
    assert missing_key in str(exc_info.value)


@pytest.mark.parametrize(
    "missing_key",
    ["WATSONX_APIKEY", "WATSONX_PROJECT_ID", "WATSONX_URL", "WATSONX_MODEL_ID"],
)
def test_watsonx_fallback_membership_requires_each_credential(
    settings_factory: SettingsFactory,
    missing_key: str,
) -> None:
    """watsonx in FALLBACK_ORDER + missing cred → boot-time ValueError (Req 3.3).

    The gate is intentionally stricter than the Ollama gate: a
    ``FALLBACK_ORDER=ollama,watsonx`` deployment with partial watsonx creds
    fails fast at boot rather than at the first failover (plan.md Entity 1).
    """
    creds = _watsonx_creds()
    creds[missing_key] = None  # type: ignore[assignment]
    with pytest.raises(ValidationError) as exc_info:
        settings_factory(
            LLM_PROVIDER="fallback",
            FALLBACK_ORDER="ollama,watsonx",
            OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
            OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
            **creds,
        )
    assert missing_key in str(exc_info.value)


def test_watsonx_direct_selection_with_full_creds_constructs(
    settings_factory: SettingsFactory,
) -> None:
    settings = settings_factory(LLM_PROVIDER="watsonx", **_watsonx_creds())
    assert settings.llm_provider == "watsonx"
    assert settings.watsonx_project_id == DUMMY_WATSONX_PROJECT
    assert settings.watsonx_apikey is not None
    assert settings.watsonx_apikey.get_secret_value() == DUMMY_WATSONX_SECRET


def test_watsonx_gate_dormant_when_not_selected(
    settings_factory: SettingsFactory,
) -> None:
    """An ollama deployment with no watsonx creds must still construct.

    The watsonx gate must NOT fire when watsonx is neither the direct provider
    nor a member of an active fallback chain — otherwise a plain Ollama
    deployment would be forced to supply watsonx credentials it never uses.
    """
    settings = settings_factory(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
    )
    assert settings.watsonx_apikey is None


def test_get_settings_is_cached(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory: SettingsFactory,  # used for env-clearing side-effect; clear cache below.
) -> None:
    """``get_settings`` returns a process-wide singleton (lru_cache).

    The factory fixture clears the env first; then we configure a happy
    path manually and assert two calls return the *same* object.
    """
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", DUMMY_OLLAMA_URL)
    monkeypatch.setenv("OLLAMA_MODEL_NAME", DUMMY_OLLAMA_MODEL)

    get_settings.cache_clear()
    first = get_settings()
    second = get_settings()
    try:
        assert first is second
    finally:
        get_settings.cache_clear()


# --------------------------------------------------------------------------- #
# Task 7.8 — credential-gate exhaustive edges (Req 3.2, 3.3 / SC-004).         #
#                                                                              #
# Task 2 landed the gate itself and its one-cred-missing naming tests above    #
# (Req 3.2 — "names the specific variable"). Per the coverage matrix Req       #
# 3.2/3.3 map to *both* 2.2 and 7.8; this section is 7.8's authoritative home  #
# for the slices Task 2 left uncovered:                                        #
#                                                                              #
#   * Req 3.3 / SC-004 — the boot-time *2-second* fail-fast ceiling. This is   #
#     the only genuinely net-new contract: Task 2 asserted *which* variable    #
#     is named, never the *timing* of the failure.                             #
#   * the all-credentials-missing message shape (the one-at-a-time tests       #
#     always leave three creds present, so the gate's ``missing:`` list only   #
#     ever holds a single entry there).                                        #
#   * gate membership robustness — ``FALLBACK_ORDER`` case/whitespace — and    #
#     the dormant-under-fallback-without-watsonx False branch.                 #
#   * the fallback full-creds positive (symmetric to the direct happy path).   #
#                                                                              #
# These exercise the *existing* Task 2.2 gate (characterization tests written  #
# after the source landed), not new source — same posture as Tasks 7.1/7.3-7.5.#
# --------------------------------------------------------------------------- #


# Generous ceiling for SC-004's "fail within 2 seconds". The gate is pure
# Python with no I/O (the socket-boom test above proves construction opens no
# socket), so real elapsed is sub-millisecond; 2.0s is the literal spec ceiling,
# not a perf benchmark, so this asserts the contract without flaking on a loaded
# CI runner.
_FAIL_FAST_CEILING_SECONDS = 2.0


@pytest.mark.parametrize("selection", ["direct", "fallback"])
def test_watsonx_missing_credential_fails_within_two_seconds(
    settings_factory: SettingsFactory,
    watsonx_settings_factory: WatsonxSettingsFactory,
    selection: str,
) -> None:
    """Missing watsonx cred → boot-time ValueError within 2s (Req 3.3 / SC-004).

    Task 2's tests pin *which* variable is named (Req 3.2); this pins the
    *timing* half — SC-004's 2-second startup-failure ceiling — on both the
    direct (``LLM_PROVIDER=watsonx``) and fallback-membership selection paths.
    """
    start = time.perf_counter()
    with pytest.raises(ValidationError) as exc_info:
        if selection == "direct":
            watsonx_settings_factory(WATSONX_APIKEY=None)
        else:
            settings_factory(
                LLM_PROVIDER="fallback",
                FALLBACK_ORDER="ollama,watsonx",
                OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
                OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
                WATSONX_PROJECT_ID=DUMMY_WATSONX_PROJECT,
                WATSONX_URL=DUMMY_WATSONX_URL,
                WATSONX_MODEL_ID=DUMMY_WATSONX_MODEL,
                # WATSONX_APIKEY intentionally omitted → gate must fire.
            )
    elapsed = time.perf_counter() - start
    assert "WATSONX_APIKEY" in str(exc_info.value)
    assert elapsed < _FAIL_FAST_CEILING_SECONDS


def test_watsonx_direct_all_credentials_missing_names_var_and_lists_all(
    watsonx_settings_factory: WatsonxSettingsFactory,
) -> None:
    """All four creds absent → ValueError names a variable AND lists every one.

    Task 2's one-at-a-time tests always leave three creds present, so the gate's
    ``missing:`` list only ever holds a single entry there. This pins the
    multi-missing message shape: the leading clause names a concrete
    ``WATSONX_*`` variable (Req 3.2) and *every* absent variable appears in the
    enumerated list, so an operator missing all four sees the full set.
    """
    with pytest.raises(ValidationError) as exc_info:
        watsonx_settings_factory(
            WATSONX_APIKEY=None,
            WATSONX_PROJECT_ID=None,
            WATSONX_URL=None,
            WATSONX_MODEL_ID=None,
        )
    msg = str(exc_info.value)
    for name in (
        "WATSONX_APIKEY",
        "WATSONX_PROJECT_ID",
        "WATSONX_URL",
        "WATSONX_MODEL_ID",
    ):
        assert name in msg


def test_watsonx_fallback_all_credentials_missing_fails_fast(
    settings_factory: SettingsFactory,
) -> None:
    """watsonx in FALLBACK_ORDER with no watsonx creds → boot-time ValueError."""
    with pytest.raises(ValidationError) as exc_info:
        settings_factory(
            LLM_PROVIDER="fallback",
            FALLBACK_ORDER="ollama,watsonx",
            OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
            OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
        )
    assert "WATSONX_APIKEY" in str(exc_info.value)


def test_watsonx_fallback_membership_is_case_and_whitespace_insensitive(
    settings_factory: SettingsFactory,
) -> None:
    """The gate detects watsonx membership after strip()/lower() (Req 3.3).

    The gate lower-cases and strips each ``FALLBACK_ORDER`` entry before the
    membership test. Were it to compare raw tokens, a deployer writing
    ``FALLBACK_ORDER=ollama, WatsonX`` would slip partial creds past the gate
    and defer the failure to the first failover — defeating fail-fast. This
    pins that a spaced, mixed-case ``watsonx`` entry still arms the gate.
    """
    with pytest.raises(ValidationError) as exc_info:
        settings_factory(
            LLM_PROVIDER="fallback",
            FALLBACK_ORDER="ollama, WatsonX",
            OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
            OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
            # watsonx creds intentionally absent → gate must fire.
        )
    assert "WATSONX_APIKEY" in str(exc_info.value)


def test_watsonx_gate_dormant_under_fallback_without_watsonx(
    settings_factory: SettingsFactory,
) -> None:
    """A fallback chain that excludes watsonx needs no watsonx creds.

    Complements ``test_watsonx_gate_dormant_when_not_selected`` (direct ollama)
    by pinning the gate's False branch under ``LLM_PROVIDER=fallback``: with
    ``FALLBACK_ORDER=ollama,anthropic`` and no watsonx creds, construction must
    succeed — otherwise a watsonx-free fallback deployment would be forced to
    supply credentials it never uses.
    """
    settings = settings_factory(
        LLM_PROVIDER="fallback",
        FALLBACK_ORDER="ollama,anthropic",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
    )
    assert settings.llm_provider == "fallback"
    assert settings.watsonx_apikey is None


def test_watsonx_fallback_membership_with_full_creds_constructs(
    settings_factory: SettingsFactory,
) -> None:
    """watsonx in FALLBACK_ORDER + full creds → constructs (positive symmetric).

    The direct-selection happy path is pinned above
    (``test_watsonx_direct_selection_with_full_creds_constructs``); this is its
    fallback-membership twin, proving the gate *passes* — not merely stays
    dormant — when watsonx participates in the chain with complete creds.
    """
    settings = settings_factory(
        LLM_PROVIDER="fallback",
        FALLBACK_ORDER="ollama,watsonx",
        OLLAMA_BASE_URL=DUMMY_OLLAMA_URL,
        OLLAMA_MODEL_NAME=DUMMY_OLLAMA_MODEL,
        **_watsonx_creds(),
    )
    assert settings.llm_provider == "fallback"
    assert settings.watsonx_apikey is not None
    assert settings.watsonx_apikey.get_secret_value() == DUMMY_WATSONX_SECRET
