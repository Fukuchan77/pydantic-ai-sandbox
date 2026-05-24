"""Per-provider Model builders (plan.md §2.3 / §2.4).

Each module in this package owns the construction recipe for one LLM
backend and nothing else. The factory in :mod:`pydantic_ai_sandbox.llm.factory`
is the only legitimate consumer; this namespace stays import-free at
package level so a missing optional dependency in one provider stub
does not poison the others.
"""
