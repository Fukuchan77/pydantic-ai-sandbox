"""Tool-design demonstration tests (Anthropic "Writing tools for agents").

Exercise the namespaced ``directory_*`` demo tools fully offline: namespacing,
pagination (``limit`` / ``offset`` / ``next_offset``), filtering, truncation, the
``response_format`` knob, and noisy-input fallback to token-efficient defaults.
A final test drives the search tool through ``run_autonomous_agent`` to prove the
tools drop into the existing least-privilege ``allowed_tools`` seam.
"""

from __future__ import annotations

import json

from patterns_pydantic_ai.autonomous_agent import run_autonomous_agent
from patterns_pydantic_ai.tool_design import (
    DirectoryGetTool,
    DirectoryRecord,
    DirectorySearchTool,
    make_directory_tools,
)
from tests.support.model_fakes import FinalTurn, ToolTurn, turn_sequenced_model


def _records(count: int = 7) -> tuple[DirectoryRecord, ...]:
    return tuple(
        DirectoryRecord(
            identifier=f"u{index}",
            name=f"Person {index}",
            role="engineer" if index % 2 == 0 else "designer",
            notes=f"note for person {index}",
        )
        for index in range(count)
    )


def _approve_all(_tool: str, _args: str) -> bool:
    return True


def test_make_directory_tools_namespaces_under_a_shared_prefix() -> None:
    # Namespacing: related tools share the "directory_" prefix and the same corpus.
    search, get = make_directory_tools(_records())
    assert isinstance(search, DirectorySearchTool)
    assert isinstance(get, DirectoryGetTool)
    assert search.name == "directory_search"
    assert get.name == "directory_get"
    assert search.name.split("_")[0] == get.name.split("_")[0] == "directory"
    # Demo tools are read-only — never gated behind the approval hook.
    assert search.dangerous is False
    assert get.dangerous is False


def test_search_paginates_with_a_small_default_and_a_next_offset_cursor() -> None:
    # Token efficiency: with no limit the page is the small default (5), and the
    # next_offset cursor points past it so the agent can page forward.
    search, _ = make_directory_tools(_records(7))
    first = json.loads(search.run("{}"))
    assert first["total"] == 7
    assert first["returned"] == 5
    assert first["next_offset"] == 5
    assert len(first["items"]) == 5

    # The final page returns the remainder and a None cursor (end of results).
    last = json.loads(search.run(json.dumps({"offset": 5})))
    assert last["returned"] == 2
    assert last["next_offset"] is None


def test_search_filters_by_case_insensitive_query_substring() -> None:
    search, _ = make_directory_tools(_records(7))
    payload = json.loads(search.run(json.dumps({"query": "ENGINEER"})))
    # Even indices (0,2,4,6) are engineers -> 4 matches, case-insensitively.
    assert payload["total"] == 4
    assert payload["returned"] == 4
    assert payload["next_offset"] is None


def test_search_defaults_to_concise_and_honours_detailed_response_format() -> None:
    search, _ = make_directory_tools(_records(1))
    concise = json.loads(search.run(json.dumps({"limit": 1})))["items"][0]
    assert set(concise) == {"id", "name"}  # concise: only the essentials

    detailed = json.loads(search.run(json.dumps({"limit": 1, "response_format": "detailed"})))[
        "items"
    ][0]
    assert set(detailed) == {"id", "name", "role", "notes"}  # detailed: full metadata


def test_detailed_output_truncates_long_notes_with_a_marker() -> None:
    long_notes = "x" * 200
    search = DirectorySearchTool(
        records=(DirectoryRecord(identifier="u0", name="A", role="r", notes=long_notes),)
    )
    notes = json.loads(search.run(json.dumps({"response_format": "detailed"})))["items"][0]["notes"]
    assert notes.endswith("…")
    assert len(notes) == 81  # 80-char cap + 1-char truncation marker


def test_search_clamps_oversized_limit_to_the_hard_ceiling() -> None:
    # An oversized limit clamps to _MAX_LIMIT (25) so one call can't flood context.
    search, _ = make_directory_tools(_records(30))
    payload = json.loads(search.run(json.dumps({"limit": 100})))
    assert payload["returned"] == 25
    assert payload["next_offset"] == 25


def test_search_falls_back_to_defaults_for_invalid_pagination_params() -> None:
    search, _ = make_directory_tools(_records(7))
    # limit below 1, a negative offset, and a boolean limit all reset to defaults.
    assert json.loads(search.run(json.dumps({"limit": 0})))["returned"] == 5
    assert json.loads(search.run(json.dumps({"offset": -3})))["returned"] == 5
    assert json.loads(search.run(json.dumps({"limit": True})))["returned"] == 5
    # A non-int limit (string) is ignored rather than crashing the loop.
    assert json.loads(search.run(json.dumps({"limit": "lots"})))["returned"] == 5


def test_search_tolerates_missing_malformed_and_non_object_args() -> None:
    search, _ = make_directory_tools(_records(3))
    for args in ("", "   ", "{not json", "[1, 2, 3]"):
        payload = json.loads(search.run(args))
        assert payload["total"] == 3  # degrades to "return the default page of all"


def test_get_returns_one_record_at_the_requested_verbosity() -> None:
    _, get = make_directory_tools(_records(3))
    concise = json.loads(get.run(json.dumps({"id": "u1"})))
    assert concise == {"id": "u1", "name": "Person 1"}

    detailed = json.loads(get.run(json.dumps({"id": "u1", "response_format": "detailed"})))
    assert detailed["id"] == "u1"
    assert set(detailed) == {"id", "name", "role", "notes"}


def test_get_reports_not_found_for_an_unknown_id() -> None:
    _, get = make_directory_tools(_records(3))
    assert json.loads(get.run(json.dumps({"id": "missing"}))) == {
        "error": "not_found",
        "id": "missing",
    }


async def test_search_tool_plugs_into_the_autonomous_agent_loop() -> None:
    # Demonstration: the namespaced tool drops into run_autonomous_agent's
    # least-privilege allow-list and its JSON observation flows back as a step.
    search, _ = make_directory_tools(_records(7))
    model = turn_sequenced_model(
        [
            ToolTurn(tool="directory_search", args=json.dumps({"query": "designer"}), tokens=2),
            FinalTurn(text="found the designers", tokens=1),
        ]
    )

    result = await run_autonomous_agent(
        "find designers",
        model=model,
        max_iterations=5,
        allowed_tools=[search],
        approval_hook=_approve_all,
        budget=100,
    )

    assert result.stop_reason == "completed"
    assert result.final_output == "found the designers"
    assert len(result.steps) == 1
    assert result.steps[0].tool == "directory_search"
    observation = json.loads(result.steps[0].observation)
    assert observation["total"] == 3  # odd indices (1,3,5) are designers
