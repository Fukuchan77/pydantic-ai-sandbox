"""Report synthesis + progress-event tests for the Deep Research lane (Spec 009 Req 6, 10).

The report writer merges findings into report text and assembles the deduplicated
citation union. The optional ``on_event`` seam emits the ``ProgressEvent`` union in
order (brief → plan → researcher_started* → finding_ready* → report_ready) so a
consumer can stream progress without importing the lane internals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from patterns_deep_research import run_deep_research
from tests.support.fake_search import FakeSearchProvider
from tests.support.model_fakes import plan_payload, scripted_model

if TYPE_CHECKING:
    from patterns_contracts import ProgressEvent


async def test_report_text_and_citation_union() -> None:
    # Two researchers both cite the same default source -> the report dedupes it.
    model = scripted_model(
        plan=plan_payload(["q1", "q2"]),
        text="The synthesised report body.",
    )
    report = await run_deep_research(
        "q", model=model, search=FakeSearchProvider(), max_researchers=2
    )
    assert report.report == "The synthesised report body."
    assert len(report.findings) == 2
    # Both findings cite "anthropic-multi-agent" (the scripted default) -> deduped to 1.
    assert len(report.citations) == 1
    assert report.citations[0].source == "anthropic-multi-agent"


async def test_progress_events_emitted_in_order() -> None:
    seen: list[ProgressEvent] = []

    async def _collect(event: ProgressEvent) -> None:
        seen.append(event)

    model = scripted_model(plan=plan_payload(["q1", "q2"]))
    await run_deep_research(
        "q",
        model=model,
        search=FakeSearchProvider(),
        max_researchers=2,
        on_event=_collect,
    )

    types = [event.type for event in seen]
    assert types[0] == "brief_ready"
    assert types[1] == "plan_ready"
    assert types[-1] == "report_ready"
    # One started + one finding per researcher (order within the parallel pair is
    # not pinned, but the counts and the terminal marker are).
    assert types.count("researcher_started") == 2
    assert types.count("finding_ready") == 2
