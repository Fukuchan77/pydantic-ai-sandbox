# レビュー: エージェント型AI 業務実装 設計ドキュメント(Python / PydanticAI v2)

対象: アップロード資料「エージェント型AI 業務実装 設計ドキュメント — Python / PydanticAI v2」
(`specs/inputs/idea0.md` の後継にあたる設計資料)

- **検証日**: 2026-07-11
- **検証方法**: pydantic-ai-slim **2.3.0**(本リポジトリの lock 版)と **2.9.0**(PyPI 最新)の
  ホイールを取得しソースコードと直接照合。pydantic-evals は 2.9.0。要修正箇所は
  pydantic-ai-slim 2.9.0 の venv 上で**実行して再現・修正確認済み**(付録の検証ログ参照)。
  脆弱性は PyPI Advisory DB(JSON API)と GitHub Advisory を照会。
- **結論**: 資料の核心である HITL 公式機構・ハーネス設計の記述は**ほぼ正確**。ただし
  **そのままでは動かない誤りが 4 件**(うち 1 件は `TypeError`、1 件はテスト例の破綻)ある。
  セキュリティ節の追加と、検証基準バージョンの明記を推奨。

---

## A. API 検証結果(v2.3.0 / v2.9.0 で確認、結論は同一)

### A-1. 正確だった記述

| 資料の記述 | 確認箇所(2.9.0) |
|---|---|
| `ApprovalRequired` / `DeferredToolRequests` / `DeferredToolResults` / `ToolApproved` / `ToolDenied` を `pydantic_ai` ルートから import | `pydantic_ai/__init__.py` の `__all__` |
| `ctx.tool_call_approved` で承認済み判定(§3.3 条件付き承認) | `_run_context.py:92` |
| `@tool_plain(requires_approval=True)` / `@tool(retries=2)` | `agent/__init__.py:2058` ほか |
| `run(message_history=..., deferred_tool_results=DeferredToolResults(approvals=...))` で再開、`user_prompt` 省略可 | `agent/abstract.py` |
| `DeferredToolRequests.approvals`(`ToolCallPart` のリスト、`tool_name`/`args`/`tool_call_id`) | `tools.py` |
| §3.2 `pydantic_ai.capabilities.HandleDeferredToolCalls` — ハンドラは `(RunContext, DeferredToolRequests) -> DeferredToolResults \| None` | `capabilities/deferred_tool_handler.py:15` |
| `UsageLimits(request_limit, tool_calls_limit, total_tokens_limit)` | `usage.py:268-276` |
| `Agent(retries=2)` は int で tools / output 両予算を設定(資料コメント通り) | `agent/abstract.py`(`AgentRetries`) |
| `output_type=[SupportOutput, DeferredToolRequests]` / `@output_validator` + `ModelRetry` | docstring・実装で確認 |
| `Agent.override(model=..., deps=...)` / `models.ALLOW_MODEL_REQUESTS` / `TestModel` / `FunctionModel` / `AgentInfo` の import パス | `models/test.py`, `models/function.py` |
| pydantic-evals: `Dataset(name=, cases=, evaluators=)`, `IsInstance(type_name=)`, `MaxDuration(seconds=)`, `LLMJudge(rubric, include_input, model)`, `evaluate_sync`, `report.print()` | pydantic-evals 2.9.0 `dataset.py`, `evaluators/common.py` |
| `anthropic:claude-sonnet-4-6` は既知モデル名 | `models/_known_model_names.py`(2.9.0 には `claude-sonnet-5` / `claude-opus-4-8` も追加済み) |
| `ToolApproved(override_args={...})` / `ToolDenied(message)` の意味論(§3.1 表) | `tools.py` |

補足: §3.2 のインライン解決には `requests.build_results(approve_all=True)` という
ヘルパー(`tools.py:272`)もあり、全承認の定型を短く書ける。

### A-2. 誤り(要修正、重要度順)

#### ①【動かない】`Agent(instrument=True)` は v2 に存在しない(§2 L98・§4 表)

- **現状**: 実装コードの `Agent(..., instrument=True, ...)` と §4 表の
  「`logfire.instrument_pydantic_ai()` または `instrument=True`」。
- **根拠**: 2.3.0 / 2.9.0 とも `Agent.__init__` に `instrument` パラメータは無い。実行すると
  `TypeError: Agent.__init__() got an unexpected keyword argument 'instrument'`(検証ログ [1])。
  v1 → v2 の非互換変更。
- **具体策**: `instrument=True,` の行を削除。資料冒頭の `logfire.instrument_pydantic_ai()` が
  全 Agent を計装するのでそれで十分。個別制御が必要なら v2 では
  `Agent.instrument_all()` / `agent.instrument` プロパティ /
  `capabilities=[Instrumentation(...)]`(2.9.0)を使う。§4 表も修正。

#### ②【存在しないパッケージ】`pytest-anyio`(§5.4)

- **現状**: `uv add --dev pytest pytest-anyio ruff pyright pydantic-evals`。
- **根拠**: PyPI の `pytest-anyio` は 0.0.0 のプレースホルダのみ。anyio の pytest プラグインは
  `anyio` 本体に同梱される。また §5.2 のテストコードには async テストを動かすための
  マーカー/モード設定が無い(このままでは収集されず素通りする)。
- **具体策**: `pytest-anyio` → `anyio`(テストに `@pytest.mark.anyio` +
  `anyio_backend` fixture)か、本リポジトリと同じ `pytest-asyncio`
  (`asyncio_mode = "auto"` を pyproject に設定)へ変更。

#### ③【動かない】§5.2 の FunctionModel テスト例

- **現状**: `call_model` が最終応答として `ModelResponse(parts=[TextPart("調査が完了しました")])`
  を返す。
- **根拠**: この Agent の `output_type` は `[SupportOutput, DeferredToolRequests]` で
  テキスト出力を許容しない。テキストのみの応答は「`Please call a tool.`」のリトライになり
  (`_agent_graph.py` の出力リトライ経路)、`call_model` は常に TextPart を返すため
  retries を使い切って `UnexpectedModelBehavior: Exceeded maximum output retries (2)`
  で落ちる(検証ログ [2] で再現)。
- **具体策**: 最終応答を出力ツール呼び出しにする(検証ログ [3] で成功確認):

```python
GOOD_OUTPUT = {
    "summary_of_issue": "double charge",
    "reasoning": "verified logs",
    "requires_human_approval": False,
    "action_plan": [{"action_type": "DISCOUNT", "target_id": "acme-co", "amount_usd": 10.0}],
}

def call_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    if len(messages) == 1:
        return ModelResponse(parts=[ToolCallPart("search_customer_context", {"query": "請求"})])
    return ModelResponse(parts=[ToolCallPart("final_result", GOOD_OUTPUT)])
```

#### ④【事実誤認】Durable Execution の公式統合先(§4 表・§6 フェーズ4)

- **現状**: 「Durable Execution(Temporal / Restate 等との公式統合)」。
- **根拠**: 2.9.0 の `pydantic_ai/durable_exec/` に存在する統合は
  **temporal / dbos / prefect** の 3 つ。Restate の統合は Restate 側 SDK が提供するもので
  pydantic-ai の公式統合ではない。
- **具体策**: 「Temporal / DBOS / Prefect との公式統合(Restate は Restate 側 SDK の統合)」に修正。

### A-3. 設計上の指摘(動くが改善推奨)

1. **`run_support` は再開後も `DeferredToolRequests` が返り得る**(承認済みツール実行後に
   モデルが別の承認必須ツールを呼ぶケース)。戻り値型 `SupportOutput` と不整合。
   2 回目の `run` を while ループにするか、`isinstance` ガードで明示的に失敗させる。
2. **`action_type: str` は `Literal["DISCOUNT", "UPGRADE", "ESCALATE"]` にする**。
   description 頼みは「出力スキーマを型レベルで強制」という資料自身の設計思想と矛盾する。
3. **`UsageLimits` は run ごとにリセットされる**。停止・再開フローで予算を通算したい場合は
   再開 run に `usage=result.usage` を渡す(`run()` は `usage` パラメータを受ける)。
   「コスト暴走のシャットアウト」を意図するなら明記すべき。
4. **`TestModel` はデフォルトで全ツールを呼ぶ**ため、`requires_approval=True` の
   `escalate_to_legal` により §5.2 の `result.output` は `DeferredToolRequests` になり得る
   (`is not None` は通るが、`SupportOutput` を期待するアサートは壊れる)。
   `TestModel(call_tools=[...])` で対象を絞るなどの注意書きを推奨。
5. **v2 は `instructions` が推奨**。`system_prompt` は message_history に残留する挙動差があり、
   複数 Agent 間で履歴を持ち回す設計では意図しないプロンプト混入の原因になる。
   資料は `system_prompt` で統一されているため、使い分けの注記を追加すると良い。
6. **`pydantic-ai` フルパッケージより `pydantic-ai-slim[必要な extras]` を推奨**(§5.4)。
   フル版は全プロバイダの依存を引き込む。本リポジトリも
   `pydantic-ai-slim[logfire,openai]` を採用(root `pyproject.toml` 参照)。
   pydantic-evals は独立配布(現行 2.9.0)。
7. `search_customer_context` の `-> dict` は pyright strict 前提なら `dict[str, Any]` 明示か
   TypedDict / BaseModel に。`DatabaseConn` / `ask_human` / `fake_deps` は未定義のため
   「疑似コード」であることを明記する。
8. §3.3 末尾の注記「遅延ツール結果は…モデルが発行した順序で並ぶ」は 2.9.0 ソースから
   裏取りできなかった。削除するか出典を付ける。
9. 資料に**検証基準バージョン**(例: pydantic-ai-slim 2.9.0、2026-07 時点)を明記する。
   §6 の「モデル ID は随時置換」と同じ運用が API シグネチャにも必要(本レビューの
   ①④はまさにバージョン差で生じる類の誤り)。

---

## B. セキュリティ検証結果

### B-1. pydantic-ai 本体の既知脆弱性(GitHub Advisory / PyPI Advisory DB、2026-07-11 時点)

| Advisory | CVE | 内容 | 影響範囲 | 修正版 |
|---|---|---|---|---|
| GHSA-2jrp-274c-jhv3 | CVE-2026-25580 | URL ダウンロード処理の SSRF(内部ネットワーク・クラウドメタデータへ到達)。信頼できない `message_history` を受ける構成(`Agent.to_web` / VercelAIAdapter / AGUIAdapter)が影響 | >=0.0.26 <1.56.0 | 1.56.0 |
| GHSA-cqp8-fcvh-x7r3 | CVE-2026-46678 | 上記の不完全修正: `force_download='allow-local'` 時に IPv6 遷移形式(IPv4-mapped / 6to4 / NAT64)でメタデータ IP ブロックリストをバイパス(CVSS 6.8) | >=1.56.0 <1.99.0 | 1.99.0 |
| GHSA-wjp5-868j-wqv7 | CVE-2026-61437 | Web UI の CDN URL パストラバーサル → Stored XSS | >=1.34.0 <1.51.0 | 1.51.0 |

- **v2 系(2.3.0 / 2.9.0)には既知脆弱性なし**(PyPI Advisory DB 照会で確認)。
  2.9.0 は SSRF 対策モジュール `_ssrf.py`(`safe_download`: プライベート IP・クラウド
  メタデータ帯域の遮断、IPv6 遷移形式の埋め込み IPv4 デコード検査)を同梱しており、
  上記アドバイザリの教訓が実装に反映されている。
- 資料推奨スタックの現行版(pydantic 2.13 / logfire 4.37 / fastapi 0.136.1)も既知脆弱性なし。

### B-2. 資料への反映提案(§5 に「セキュリティ」節を追加)

1. **バージョン下限**: v1 系を併用する場合は **>=1.99.0** を必須とする(SSRF 2 件 + XSS の修正済み下限)。
2. **SSRF 注意**: 信頼できない `message_history` や URL 入力(マルチモーダル)を扱う構成では
   `force_download='allow-local'` を使わない。エージェントに URL 取得能力を持たせる場合は
   v2 の `safe_download` 経路(または同等の egress 制御)を通す。
3. **依存監査の CI 常設**: pip-audit(依存 CVE)+ gitleaks(秘密検知)+ supply-chain watch
   (litellm 2026-03 yank 事案は idea0.md §14 参照)。本リポジトリの
   `.github/workflows/security.yml` が実装例(毎日 cron で凍結 lockfile も再監査する構成)。

---

## C. CI の pip-audit 失敗 — 原因と修正(本ブランチで対応済み)

### C-1. 現状(2026-07-11 時点)

- security ワークフローの **daily cron が 2026-07-03 以降ほぼ連続で failure**
  (直近 run 29139787855)。失敗ジョブは `pip-audit patterns (rag)` と
  `pip-audit patterns (llamaindex)` の 2 つのみ。root + 他 5 レーンは green。

### C-2. 原因

- 両レーンの lockfile が固定する **nltk 3.9.4** に
  **PYSEC-2026-597 / CVE-2026-12243** が 2026-07 初頭に登録された。
  内容: `nltk/data.py` の `_UNSAFE_NO_PROTOCOL_RE` が `../` のみ検査し
  `..%2f` 等の**パーセントエンコードされたトラバーサルを検査しない**
  (GitHub Issue #3504 修正の不完全対応)。
- advisory の `fixed_in` が空のため、pip-audit は「修正版なしの検出」として exit 1。
  nltk は llama-index 系の**推移的依存**(両レーンとも直接依存ではない)。
- 全 7 レーンの lockfile をローカルで pip-audit にかけ、CI と同一の結果
  (rag / llamaindex のみ nltk 3.9.4 で fail)を再現済み。

### C-3. 修正(本ブランチのコミットに含む)

- `patterns/rag` と `patterns/frameworks/llamaindex` で
  `uv lock --upgrade-package nltk` を実行し **nltk 3.9.4 → 3.10.0** に更新。
  3.10.0 には脆弱性登録がなく、更新後の lockfile が **pip-audit をパスすることを確認済み**。
- 更新後の両レーンで `uv sync --all-groups --locked` + `pytest` を実行し、
  **rag: 58 passed, 1 skipped / llamaindex: 41 passed, 6 skipped** で回帰なしを確認。
- 運用メモ: 「fix 未提供の advisory で daily cron が赤くなる」ケースは今後も起き得る。
  その時点で上流に修正が無い場合は、pip-audit の `--ignore-vuln <ID>`(期限コメント付き)で
  一時抑止し、issue 化して追跡するのが定石。今回は上流修正(3.10.0)が既にあるため不要。

---

## 付録: 検証ログ(pydantic-ai-slim 2.9.0 / Python 3.11 venv)

検証スクリプトは資料 §2 相当の Agent(フェイク DB・`Literal` 化した `action_type`)を構築し、
以下を確認した:

```text
[1] Agent(instrument=True) -> TypeError: Agent.__init__() got an unexpected keyword argument 'instrument'
[2] ドキュメント原文の例 -> UnexpectedModelBehavior: Exceeded maximum output retries (2)
[3] 修正版 -> SupportOutput OK: double charge
[4a] 停止 -> DeferredToolRequests: tool=apply_discount args={'amount_usd': 100.0, 'reason': 'comp'}
[4b] 再開 -> SupportOutput OK (requires_human_approval=True)
ALL CHECKS PASSED
```

- [1] = A-2①(`instrument` kwarg は TypeError)
- [2] = A-2③(資料原文の FunctionModel 例は破綻)
- [3] = A-2③ の修正版が動作
- [4a][4b] = 資料 §2/§8 の HITL 停止・再開フロー自体は**設計通り動作する**
  (`ApprovalRequired` → `DeferredToolRequests` → `ToolApproved` で再開 → 構造化出力)
