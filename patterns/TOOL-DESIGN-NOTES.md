# TOOL-DESIGN-NOTES — patterns/ レーンのツール設計規約（改善提案 P1）

Anthropic「[Writing effective tools for AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents)」
の原則を本リポジトリのツール設計規約として明文化し、各原則の**準拠状況**（実装シーム /
実演 / 受容した非適用）を一点に集約する。[SECURITY-NOTES.md](SECURITY-NOTES.md) と同じ位置づけの
正本ドキュメントで、ツールを追加・変更する際はここを起点に準拠を確認する。

実演（runnable demo）の正本は
[`patterns/frameworks/pydantic-ai/.../tool_design.py`](frameworks/pydantic-ai/src/patterns_pydantic_ai/tool_design.py)、
解説は [`docs/tool-design.md`](../docs/tool-design.md)。デモは凍結済みの6パターン契約・他 lane・
ドリフト README を変更せず、既存の `Tool` Protocol / `allowed_tools` シームに差し込む（Spec 006-2a 維持）。

## 規約と準拠状況

| 公式原則 | 本リポジトリの規約 | 準拠状況 | 根拠 |
|---|---|---|---|
| **Namespacing**（関連ツールを共通プレフィックスでグルーピングし境界を識別しやすくする） | ツール名は `<resource>_<verb>` 規約（例 `directory_search` / `directory_get`）。同一リソース群は共通プレフィックスを共有する | ✅ 実演 | `make_directory_tools()` が `directory_` 接頭辞のツール対を返す（`tool_design.py`） |
| **Token 効率**（pagination / range 選択 / filtering / truncation を妥当な既定値つきで） | コンテキストを溢れさせうる応答は **pagination（`limit`/`offset`、小さな既定 + ハード上限）**・**filter（`query`）**・**truncation（長い自由記述を可視マーカー付きで切詰め）** を実装する。全件返却は禁止 | ✅ 実演 | `directory_search`: 既定 `_DEFAULT_LIMIT=5` / 上限 `_MAX_LIMIT=25` クランプ / `next_offset` カーソル / `query` 部分一致 / `_DETAIL_NOTE_CHARS=80` truncate（末尾 `…`） |
| **`response_format`**（`concise` / `detailed` の切替で必要分だけトークンを払う） | 既定は token 効率の良い `concise`（最小フィールド）。`detailed` 指定時のみ全メタデータを返す | ✅ 実演 | `_coerce_format()` が既定 `concise`（`id`+`name`）、`detailed` で全フィールド（`tool_design.py`） |
| **厳格なデータモデル**（期待入出力を型で明示し曖昧さを排除） | 構造化出力は `output_type` + 依存ゼロの [`patterns_contracts`](contracts/) 契約で型強制し、契約ドリフトテストで一貫性を担保 | ✅ 既存実装 | `patterns/contracts/`, `contracts/tests/unit/test_contract_drift.py`（全 lane 一致を1点検証） |
| **実行前入力検証**（信頼できない引数を実行前に拒否） | パストラバーサル等は実行前に拒否。デモツールは欠落・不正 JSON・非オブジェクト引数を**例外送出せず token 効率の良い既定へ劣化**させ、noisy なツール呼出でループを壊さない | ✅ 既存実装 + 実演 | autonomous-agent の入力検証 / `_parse_args()`・`_clamp_int()`（bool 拒否含む）の防御的フォールバック |
| **最小権限のツール公開**（エージェントが触れるツールを許可制にする） | ツールは `allowed_tools: Sequence[Tool]`（最小権限 allow-list = 注入シーム）として渡す。許可外は実行せずハード停止（`stop_reason="disallowed_tool"`） | ✅ 既存実装 | `run_autonomous_agent(..., allowed_tools=...)`、[SECURITY-NOTES.md](SECURITY-NOTES.md) OWASP マッピング |

## パターン別の適用範囲

| パターン | ツール面 | 準拠状況 |
|---|---|---|
| **autonomous-agent** | 唯一のツールループ型。`Tool` Protocol（`name`/`dangerous`/`run(args)->str`）+ `allowed_tools` シーム。`directory_*` デモが namespacing / token 効率 / `response_format` を実演 | ✅ 規約準拠・実演あり |
| routing / orchestrator-workers / parallelization / prompt-chaining / evaluator-optimizer | ワークフロー型でツールループを持たない。構造化出力の型強制（`output_type` + 契約）が該当 | ✅ 厳格データモデルのみ該当 |
| rag / sse / deep-research（応用層） | researcher の外部 I/O は注入された `SearchProvider` **のみ**（最小権限）。検索は `top_k`、ファンアウトは cap で token 上限化 | ✅ 最小権限・上限設計で準拠 |

## 受容した非適用（Accepted Scope）

| 項目 | 状態 | 根拠 / 見直し条件 |
|---|---|---|
| token 効率 / `response_format` 実演は PydanticAI lane のみ | 1 lane で実演 | 受け入れ条件「デモツール1件以上」を満たす。BeeAI / LlamaIndex lane への横展開は将来イテレーション（改善提案 P1 注記） |
| デモは pydantic 非依存の純 stdlib | 意図的 | ネットワーク不要・決定的。lane のカバレッジゲートを維持しつつ凍結契約を触らない |
