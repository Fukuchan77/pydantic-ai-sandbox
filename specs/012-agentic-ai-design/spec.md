# 012-agentic-ai-design

## Project Description

エージェント型AI 業務実装(HITL ハーネス / PydanticAI v2)を、レビュー
[specs/document-review/agentic-ai-design-v2-review.md](../document-review/agentic-ai-design-v2-review.md)
で確定した修正内容に基づいて仕様化する。

元設計ドキュメント「エージェント型AI 業務実装 設計ドキュメント — Python / PydanticAI v2」
(`specs/inputs/idea0.md` の後継にあたるアップロード資料)は、PydanticAI v2 公式の
Human-in-the-Loop(HITL)機構 — `ApprovalRequired` → `DeferredToolRequests` →
`ToolApproved`/`ToolDenied` による**停止・承認・再開**フロー — を核とするハーネス設計を示す。
レビューはこの設計を pydantic-ai-slim 2.3.0(lock 版)/ 2.9.0(最新)のソースと直接照合し、
HITL 機構・ハーネス設計の記述は**ほぼ正確**である一方、**そのままでは動かない誤り 4 件**と
セキュリティ節の欠落を指摘した。

本仕様の対象は、レビューで確定した「動く」設計を、本リポジトリの規約(pyright strict、
`pydantic-ai-slim[extras]`、モデル ID の env 経由ルーティング、TDD、カバレッジ ratchet)に
沿って実装可能な要件へ落とし込むことである。

### レビューが確定した修正(実装時の必須反映事項)

- **①** `Agent(instrument=True)` は v2 に存在しない(`TypeError`)。
  `logfire.instrument_pydantic_ai()` による計装に統一する。
- **②** `pytest-anyio` は実在しないプレースホルダ。本リポジトリ同様
  `pytest-asyncio`(`asyncio_mode = "auto"`)に揃える。
- **③** `FunctionModel` テスト例は `output_type=[SupportOutput, DeferredToolRequests]` と
  不整合(テキスト応答は出力リトライ枯渇で失敗)。最終応答を出力ツール呼び出し
  (`final_result`)にする。
- **④** Durable Execution の公式統合先は **Temporal / DBOS / Prefect** の 3 つ
  (Restate は Restate 側 SDK 提供)。
- 設計上の改善(A-3): `action_type` の `Literal` 化、再開後も
  `DeferredToolRequests` が返り得る点のガード、`UsageLimits` の run 間通算、
  `TestModel(call_tools=[...])` での対象絞り、`instructions` vs `system_prompt` の使い分け、
  疑似コード箇所の明示。
- セキュリティ(B): SSRF/XSS を踏まえた v1 併用時の下限 `>=1.99.0`、
  信頼できない `message_history`/URL 入力の扱い、`safe_download` 経路、依存監査 CI 常設。

## Clarifications

### Session 2026-07-11

- Q: 本 spec の成果物(deliverable)はどれか? → A: 新規 HITL リファレンス実装(レビュー確定版の停止・承認・再開ハーネスを、テスト付きの動くコードとして新規実装する)
- Q: HITL リファレンス実装の配置先は? → A: 新規 patterns レーン(patterns/ 配下の独立 uv プロジェクトとして。独自 lockfile/Python/ゲート、contracts パッケージ共有、patterns:* タスクファミリに準拠)
- Q: 実装フレームワークの範囲は? → A: pydantic-ai のみ(ApprovalRequired/DeferredToolRequests は pydantic_ai 固有機構のため、元設計 PydanticAI v2 に忠実に pydantic-ai ランドのみ)
- Q: 人間の承認(HITL)の経路は? → A: FastAPI 停止・再開エンドポイント(POST /run で停止=DeferredToolRequests を返す、POST /resume で承認結果を受けて再開。message_history/状態の永続化が必要)
- Q: Durable Execution とセキュリティ強化は今回のスコープに含めるか? → A: 両方とも今回はスコープ外(将来フェーズ)。MVP はインメモリ/プロセス内の状態ストアで /resume を実現し、Durable(Temporal/DBOS/Prefect)と SSRF/egress 強化は設計ノートとして記述のみ

## Scope

- In scope:
  - HITL 停止・承認・再開ハーネスの新規リファレンス実装(`ApprovalRequired` →
    `DeferredToolRequests` → `ToolApproved`/`ToolDenied` → 再開 → 構造化出力)
  - pydantic-ai 単独の新規 patterns レーン(独立 uv プロジェクト、Python 3.14、
    `pydantic-ai-slim[extras]`、contracts 共有、`patterns:*` ゲート準拠)
  - FastAPI `POST /run`(停止=`DeferredToolRequests`)/ `POST /resume`(承認結果で再開)
    エンドポイントと、インメモリ/プロセス内の状態(message_history)ストア
  - レビュー確定の必須修正 ①〜④ + 設計改善(A-3)の反映
    (①`instrument=True` 除去、②`pytest-asyncio`、③出力ツール応答、④Durable の正しい統合先、
    `Literal` 化、再開後 `DeferredToolRequests` ガード、`UsageLimits` 通算、
    `TestModel(call_tools=[...])`、`instructions` 使い分け)
  - `TestModel`/`FunctionModel` によるハーメティックなテスト、カバレッジ ratchet 遵守、
    live-model × fake-統合の integration レーン(`RUN_INTEGRATION_PATTERNS=1`)
- Out of scope(将来フェーズ):
  - Durable Execution(Temporal / DBOS / Prefect)との公式統合(設計ノートとして記述のみ)
  - SSRF/egress 強化・`safe_download` 経路の実装(v1 併用時の下限 `>=1.99.0` 等は
    セキュリティノートとして記述のみ)
  - 永続 DB / 外部キューによる状態ストア(MVP はインメモリ)
  - beeai / llamaindex など他フレームワークでの HITL 実装

## Glossary

| Term | Definition |
|------|------------|
| HITL | Human-in-the-Loop。エージェント実行を承認必須ツールで停止し、人間の承認/拒否を受けて再開する制御パターン |
| HITL lane | 本 spec が新設する `patterns/hitl/` 独立 uv レーン |
| harness | run/resume を統括するオーケストレーション層(停止・承認・再開・予算通算・再 defer ガード) |
| HITL API | ハーネスを露出する FastAPI アプリ(`POST /run` / `POST /resume`) |
| the agent | pydantic-ai の `Agent`(承認必須ツール + 構造化出力型を持つ) |
| ApprovalRequired | 承認必須ツール未承認時に pydantic-ai が発する内部シグナル |
| DeferredToolRequests | 承認待ちツール呼び出し(`tool_name`/`args`/`tool_call_id`)を保持する遅延要求。停止時の run 戻り値 |
| DeferredToolResults | 再開時に承認結果(`approvals`)を渡す入力 |
| ToolApproved / ToolDenied | 個々のツール呼び出しの承認(`override_args` 可)/拒否(`message` 付き) |
| SupportOutput | ハーネスの最終構造化出力(`summary_of_issue`/`reasoning`/`requires_human_approval`/`action_plan`) |
| session | `/run` が発行し `/resume` が参照する、再開可能な実行の識別子(message_history + usage を紐付ける) |

## Requirements

### Requirement 1: 独立 patterns レーンとしての足場・ツール整合

新規 HITL 実装は既存応用レーン(rag/sse/deep-research)と対称な独立 uv レーンとして配置し、
ルートのゲート・依存解決・Python バージョンに巻き込まない。

**Acceptance Criteria**

1.1 THE HITL lane SHALL be an independent uv project rooted at `patterns/hitl/` with its own `pyproject.toml`, `uv.lock`, and `.python-version` pinned to Python `>=3.14`.
1.2 THE HITL lane SHALL depend on `pydantic-ai-slim` with explicit extras and SHALL NOT declare `beeai-framework` or `llamaindex` dependencies.
1.3 THE HITL lane SHALL import shared contract models from `patterns_contracts` via a `[tool.uv.sources]` path dependency and SHALL NOT re-declare those models inside the lane.
1.4 WHEN the `patterns:{setup,lint,format,typecheck,test,audit}` tasks run, THE mise task family SHALL execute `patterns/hitl` after the contracts→frameworks loop as an explicit single line, not via the `frameworks/*/` glob.
1.5 THE HITL lane SHALL enforce a test coverage floor of `fail_under = 98`.
1.6 WHEN the lane is added, THE repository CI SHALL enumerate it explicitly wherever lanes are listed by name: a dedicated lane job in `.github/workflows/patterns-ci.yml`, a row in the `security.yml` `patterns-pip-audit` matrix (so the daily CVE cron audits the lane's frozen lockfile — the gap the 2026-07 nltk incident exposed), and dependabot monitoring consistent with existing lanes.

### Requirement 2: HITL 契約の所有とドリフト検知

HITL の I/O モデルは既存の所有則(新レーンは自レーンの契約を `patterns_contracts` に所有させ、
README を正本とする)に従い、単一点でドリフト検知する。

**Acceptance Criteria**

2.1 THE HITL lane SHALL own its I/O contract (the structured support output, the action-item shape, and the closed `action_type` vocabulary) inside `patterns_contracts`, with the lane README ```python``` block as the canonical source.
2.2 THE `action_type` field SHALL be a closed `Literal["DISCOUNT", "UPGRADE", "ESCALATE"]`, not a free `str`.
2.3 THE `SupportOutput` contract SHALL require the fields `summary_of_issue`, `reasoning`, `requires_human_approval`, and `action_plan`.
2.4 THE contract drift test SHALL verify that the lane README canonical block equals the `patterns_contracts` implementation at a single point.

### Requirement 3: エージェント構築(レビュー修正 ① + A-3 の型安全/プロンプト方針)

**Acceptance Criteria**

3.1 THE agent SHALL be constructed with `output_type = [SupportOutput, DeferredToolRequests]`.
3.2 THE HITL lane SHALL NOT pass `instrument=True` to `Agent(...)` (unsupported in v2, raises `TypeError`); instrumentation SHALL be enabled solely through `logfire.instrument_pydantic_ai()`.
3.3 THE agent SHALL declare at least one tool with `requires_approval=True`.
3.4 THE agent SHALL express its guidance via `instructions` rather than `system_prompt`, so prompt text does not leak into carried-over `message_history` across resumes.
3.5 THE agent SHALL register an `@output_validator` that enforces the deterministic approval policy: IF any action in `action_plan` carries an amount exceeding the configured risk threshold while `requires_human_approval` is `False`, THEN the validator SHALL raise `ModelRetry` with corrective natural-language feedback so the model self-corrects within the run's retry budget (the original design's §6 "検証センサー").

### Requirement 4: 承認必須ツールでの停止

**Acceptance Criteria**

4.1 WHEN the model calls a `requires_approval` tool that has not been approved, THE harness SHALL return a `DeferredToolRequests` result instead of executing the tool.
4.2 WHEN the harness returns `DeferredToolRequests`, THE result SHALL expose each pending tool call with its `tool_name`, `args`, and `tool_call_id`.

### Requirement 5: 承認・拒否による再開

**Acceptance Criteria**

5.1 WHEN a resume supplies approvals as `DeferredToolResults(approvals=...)`, THE harness SHALL resume the run by passing `message_history` and `deferred_tool_results` and SHALL NOT require a new `user_prompt`.
5.2 WHEN a pending tool call is approved with `ToolApproved`, THE harness SHALL execute that tool; WHEN approved with `ToolApproved(override_args=...)`, THE harness SHALL execute it with the overridden arguments.
5.3 WHEN a pending tool call is denied with `ToolDenied(message=...)`, THE harness SHALL NOT execute the tool and SHALL surface the denial message to the model.
5.4 WHERE a tool applies conditional approval, THE agent SHALL treat `ctx.tool_call_approved` as the authority that gates the approved-only behavior.

### Requirement 6: 再開後の再 defer ガード(A-3.1)

**Acceptance Criteria**

6.1 IF a resumed run again returns `DeferredToolRequests` (the model calls another approval-required tool after resume), THEN THE harness SHALL either continue the approve→resume loop until a terminal `SupportOutput` is produced, or fail loudly via an explicit `isinstance` guard, and SHALL NOT mis-type the deferred result as `SupportOutput`.

### Requirement 7: 予算(UsageLimits)の停止・再開通算(A-3.3)

**Acceptance Criteria**

7.1 THE harness SHALL apply `UsageLimits(request_limit, tool_calls_limit, total_tokens_limit)` to each run.
7.2 WHEN a run is resumed, THE harness SHALL pass the prior run's `usage` into the resume run so the budget accumulates across the stop/resume boundary.
7.3 IF a usage limit is exceeded, THEN THE harness SHALL terminate the run with a usage-limit error instead of continuing.

### Requirement 8: FastAPI 停止・再開エンドポイントと状態ストア

注: `/resume` の消費セマンティクス(同一 session の二重 resume、usage-limit 超過時の
HTTP マッピング)とセッション識別子の衛生・監査証跡は
[specs/013-agentic-ai-security](../013-agentic-ai-security/spec.md) が要件化する。

**Acceptance Criteria**

8.1 WHEN a client `POST`s to `/run` with a prompt, THE HITL API SHALL execute the agent and, if a `requires_approval` tool is pending, respond with the pending approval requests and a resumable `session` identifier.
8.2 WHEN the agent completes without any pending approval, THE HITL API SHALL respond with the structured `SupportOutput`.
8.3 WHEN a client `POST`s to `/resume` with a `session` identifier and approval decisions, THE HITL API SHALL resume the stored run and respond with either the `SupportOutput` or a further set of pending approvals.
8.4 THE state store SHALL persist each session's `message_history` and accumulated `usage` in-memory, keyed by the `session` identifier, for the lifetime of the process.
8.5 IF `/resume` is called with an unknown `session` identifier, THEN THE HITL API SHALL respond with a `404` status.
8.6 THE HITL API SHALL be assembled by an app-factory and, in tests, be exercised with `with TestClient(app):` so the lifespan runs.

### Requirement 9: 可観測性

**Acceptance Criteria**

9.1 WHEN the HITL API starts, THE HITL lane SHALL enable `logfire.instrument_pydantic_ai()` (plus FastAPI/httpx instrumentation) fail-soft, so an unconfigured or failing exporter does not block startup.

### Requirement 10: ハーメティックなテスト(レビュー修正 ②③ + A-3.4)

**Acceptance Criteria**

10.1 THE HITL lane SHALL configure `pytest-asyncio` with `asyncio_mode = "auto"` and SHALL NOT depend on the non-existent `pytest-anyio` package.
10.2 WHEN a `FunctionModel` test drives the agent to a terminal answer, THE final `ModelResponse` SHALL be an output tool call (e.g. `final_result`) rather than a bare `TextPart`, so the `[SupportOutput, DeferredToolRequests]` output type accepts it.
10.3 WHERE a `TestModel` is used to drive the approval flow, THE test SHALL constrain the called tools via `TestModel(call_tools=[...])` so a `requires_approval` tool does not silently turn every result into `DeferredToolRequests`.
10.4 THE unit tests SHALL cover the full stop→approve→resume→structured-output path and the deny path with zero real provider I/O.

### Requirement 11: 統合レーン(空振り緑の禁止)

**Acceptance Criteria**

11.1 THE HITL integration tests SHALL be gated by `RUN_INTEGRATION_PATTERNS=1` and excluded from the default hermetic test run.
11.2 THE HITL integration task SHALL declare `EXPECT_LIVE_TESTS=<n>` so a collected-zero or all-skipped run fails red.
11.3 WHERE a live-model integration lane is wired into CI, THE lane SHALL be isolated into the dispatch-only (or scheduled) live-integration workflows — consistent with the current policy that both Ollama live-integration workflows are `workflow_dispatch`-only — and SHALL NOT carry a `pull_request:` trigger.

### Requirement 12: モデル ID の衛生(レビュー修正 ④ 周辺 + 二層ガード)

**Acceptance Criteria**

12.1 THE HITL lane SHALL route the live model id through an environment variable and SHALL NOT hardcode a model string (e.g. `anthropic:claude-sonnet-4-6`) in source.
12.2 THE HITL lane SHALL pass the repository-wide `forbid-hardcoded-model-ids` pre-commit hook and its backing test.

### Requirement 13: Durable / セキュリティの設計ノート(記述のみ)

将来フェーズの統合・強化はスコープ外だが、レビュー B 節・修正 ④ の知見を README に残す。

**Acceptance Criteria**

13.1 THE HITL lane README SHALL document Durable Execution's official pydantic-ai integrations as Temporal / DBOS / Prefect (Restate being provided by Restate's own SDK), as future work, without implementing them.
13.2 THE HITL lane README SHALL document the security guidance — a `>=1.99.0` floor when interoperating with pydantic-ai v1 (SSRF/XSS advisories), the SSRF risk of untrusted `message_history` / URL inputs, and the `safe_download` egress path — without implementing egress hardening.
13.3 THE HITL lane README SHALL record the verification baseline version (pydantic-ai-slim version + date) against which the API usage was confirmed.

## Non-Functional Requirements

- **Performance / hermeticity**: The default `mise run patterns:test` path for the HITL lane SHALL perform zero external network, process, or filesystem I/O; all agent behavior is driven by `TestModel` / `FunctionModel`.
- **Type safety**: pyright **strict** against Python 3.14. `Any` is permitted only at I/O boundaries and SHALL be narrowed via Pydantic models before flowing inward.
- **Lint policy**: The lane SHALL satisfy the same ruff rule set enforced repo-wide (`S`, `C90 ≤ 10`, `D` Google docstrings, `N`, `T20` no-`print`, `TCH`, `BLE`) without local weakening.
- **Coverage**: `fail_under = 98` for the lane; the added `patterns_contracts` shapes remain covered by the contracts package gate.
- **Security floor (documented)**: When pydantic-ai v1 is used alongside, the required floor is `>=1.99.0`; the HITL lane itself builds on a v2 line with no known advisories.

## Out of Scope / Future Work

- Durable Execution integration (Temporal / DBOS / Prefect) — documented as future work only.
- SSRF/egress hardening and the `safe_download` code path — documented as a security note only.
- Persistent state storage (external DB / queue) — the MVP state store is in-memory only.
- HITL implementations in other frameworks (beeai / llamaindex) — pydantic-ai only, since `ApprovalRequired` / `DeferredToolRequests` are pydantic-ai-specific mechanisms.
- `/resume` consumption semantics, session-identifier hygiene, approval audit trail — owned by [specs/013-agentic-ai-security](../013-agentic-ai-security/spec.md).

---

_Initialized: 2026-07-11T22:37:41+0900_
_Requirements generated: 2026-07-11_
_Requirements updated: 2026-07-12(レビュー指摘 4 点適用: AC 1.6 / 3.5 追加、11.3 文言修正、消費セマンティクスの 013 委譲を明記)_
