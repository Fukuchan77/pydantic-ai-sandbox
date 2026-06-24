"""Tool-design demonstration for the autonomous-agent loop (Anthropic "Writing tools for agents").

A *runnable demonstration* — deliberately outside the frozen six-pattern
contracts — of the tool-design best practices from Anthropic's "Writing effective
tools for AI agents":

* **Namespacing** — related tools share a ``<resource>_<verb>`` prefix
  (``directory_search`` / ``directory_get``) so the model can tell their
  boundaries apart at a glance.
* **Token efficiency** — search **paginates** (``limit`` / ``offset`` with a small
  default and a hard ``_MAX_LIMIT`` ceiling), **filters** (case-insensitive
  ``query`` substring), and **truncates** long free-text, so one call can never
  flood the context window with low-signal tokens.
* **``response_format``** — a ``concise`` (id + name only) vs ``detailed`` (full
  record) knob, defaulting to ``concise`` so the agent pays for extra detail only
  when it asks for it.

Both tools satisfy the shared ``patterns_contracts.Tool`` Protocol
(``name`` / ``dangerous`` / ``run(args) -> str``), so they drop straight into
``run_autonomous_agent(..., allowed_tools=make_directory_tools(records))`` through
the existing least-privilege allow-list seam. ``run`` accepts a JSON ``args``
string (the shape a model emits as ``ToolCallPart.args``) and returns a compact
JSON string; missing or malformed parameters fall back to the token-efficient
defaults rather than raising, so a noisy tool call degrades to a small, safe
result instead of breaking the loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

    from patterns_contracts import Tool

__all__ = [
    "DirectoryGetTool",
    "DirectoryRecord",
    "DirectorySearchTool",
    "ResponseFormat",
    "make_directory_tools",
]

ResponseFormat = Literal["concise", "detailed"]
"""Output verbosity knob: ``concise`` (id + name) or ``detailed`` (full record)."""

_DEFAULT_LIMIT: Final = 5
"""Page size when the caller omits ``limit`` — small by default (token efficiency)."""
_MAX_LIMIT: Final = 25
"""Hard ceiling on page size so a single call can never flood the context window."""
_DETAIL_NOTE_CHARS: Final = 80
"""Truncation cap applied to a record's free-text notes in ``detailed`` output."""
_TRUNCATION_MARKER: Final = "…"
"""Suffix appended to a value that was shortened, so truncation stays visible."""


@dataclass(frozen=True, slots=True)
class DirectoryRecord:
    """One directory entry the demo tools page, filter, and render over."""

    identifier: str
    name: str
    role: str
    notes: str


def _parse_args(args: str) -> dict[str, object]:
    """Parse a tool-call ``args`` JSON string into a dict, tolerating noise.

    A missing, non-JSON, or non-object ``args`` yields an empty dict so callers
    fall back to defaults instead of raising mid-loop.
    """
    if not args.strip():
        return {}
    try:
        parsed: object = json.loads(args)
    except json.JSONDecodeError:
        return {}
    return cast("dict[str, object]", parsed) if isinstance(parsed, dict) else {}


def _clamp_int(raw: object, *, default: int, minimum: int, maximum: int | None = None) -> int:
    """Coerce ``raw`` to a bounded int, falling back to ``default`` when invalid.

    Booleans are rejected (``isinstance(True, int)`` is True) so a stray ``true``
    never reads as ``1``. Values below ``minimum`` reset to ``default``; values
    above ``maximum`` (when given) clamp down to it.
    """
    if not isinstance(raw, int) or isinstance(raw, bool):
        return default
    if raw < minimum:
        return default
    return min(raw, maximum) if maximum is not None else raw


def _coerce_format(raw: object) -> ResponseFormat:
    """Read the ``response_format`` knob, defaulting to the token-efficient ``concise``."""
    return "detailed" if raw == "detailed" else "concise"


def _truncate(text: str, limit: int) -> str:
    """Truncate ``text`` to ``limit`` chars, appending a marker when shortened."""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + _TRUNCATION_MARKER


def _haystack(record: DirectoryRecord) -> str:
    """Build the lowercase searchable blob a ``query`` substring is matched against."""
    return f"{record.name} {record.role} {record.notes}".lower()


def _render(record: DirectoryRecord, response_format: ResponseFormat) -> dict[str, str]:
    """Render a record at the requested verbosity (the token-efficiency knob)."""
    if response_format == "concise":
        return {"id": record.identifier, "name": record.name}
    return {
        "id": record.identifier,
        "name": record.name,
        "role": record.role,
        "notes": _truncate(record.notes, _DETAIL_NOTE_CHARS),
    }


@dataclass(slots=True)
class DirectorySearchTool:
    """Namespaced, paginating, filtering, truncating search tool (``directory_search``).

    ``run`` accepts a JSON object with optional ``query`` (case-insensitive
    substring filter), ``limit`` / ``offset`` (pagination, small default, clamped
    to ``_MAX_LIMIT``), and ``response_format``. It returns a JSON object carrying
    the matched ``total``, the ``returned`` count, a ``next_offset`` cursor
    (``None`` at the end), and the page ``items`` — so the agent can page forward
    without ever pulling the whole corpus into context.
    """

    records: tuple[DirectoryRecord, ...]
    name: str = "directory_search"
    dangerous: bool = False

    def run(self, args: str) -> str:
        """Return a paged, filtered, truncated JSON view of the directory."""
        params = _parse_args(args)
        query = str(params.get("query", "")).strip().lower()
        limit = _clamp_int(
            params.get("limit"), default=_DEFAULT_LIMIT, minimum=1, maximum=_MAX_LIMIT
        )
        offset = _clamp_int(params.get("offset"), default=0, minimum=0)
        response_format = _coerce_format(params.get("response_format"))

        matched = [record for record in self.records if query in _haystack(record)]
        page = matched[offset : offset + limit]
        end = offset + len(page)
        next_offset = end if end < len(matched) else None
        return json.dumps(
            {
                "total": len(matched),
                "returned": len(page),
                "next_offset": next_offset,
                "items": [_render(record, response_format) for record in page],
            },
            sort_keys=True,
        )


@dataclass(slots=True)
class DirectoryGetTool:
    """Namespaced single-record lookup honouring ``response_format`` (``directory_get``).

    ``run`` accepts a JSON object with ``id`` and optional ``response_format`` and
    returns the one matching record (or a small ``{"error": "not_found"}`` object)
    — the targeted alternative to scanning a list, so the agent skips straight to
    the relevant entry instead of reading the whole directory token by token.
    """

    records: tuple[DirectoryRecord, ...]
    name: str = "directory_get"
    dangerous: bool = False

    def run(self, args: str) -> str:
        """Return one record (or a not-found marker) as JSON."""
        params = _parse_args(args)
        record_id = str(params.get("id", "")).strip()
        response_format = _coerce_format(params.get("response_format"))
        match = next((record for record in self.records if record.identifier == record_id), None)
        if match is None:
            return json.dumps({"error": "not_found", "id": record_id}, sort_keys=True)
        return json.dumps(_render(match, response_format), sort_keys=True)


def make_directory_tools(
    records: Sequence[DirectoryRecord],
) -> tuple[DirectorySearchTool, DirectoryGetTool]:
    """Build the namespaced ``directory_*`` toolset for the autonomous-agent loop.

    Args:
        records: The directory corpus the tools page, filter, and render over.

    Returns:
        The search and get tools sharing the ``directory_`` prefix (namespacing),
        ready to pass as ``allowed_tools`` to ``run_autonomous_agent``.
    """
    frozen = tuple(records)
    return DirectorySearchTool(records=frozen), DirectoryGetTool(records=frozen)


if TYPE_CHECKING:
    # Static guard: both demo tools structurally satisfy the contracts ``Tool``
    # Protocol (mirrors the StubTool guard in tests/support). pyright fails here if
    # a field or the run signature ever drifts out of the Protocol's shape.
    _search_is_tool: type[Tool] = DirectorySearchTool
    _get_is_tool: type[Tool] = DirectoryGetTool
