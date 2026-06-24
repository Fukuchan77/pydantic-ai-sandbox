# Tool Design — Anthropic「Writing tools for agents」の適用

## 原則(公式が重視すること)

Anthropic の [Writing effective tools for AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents)
は、エージェント用ツールの設計で次を重視する。

1. **Namespacing** — 関連ツールを共通プレフィックスでグルーピングし(サービス別 `asana_search` /
   リソース別 `asana_projects_search`)、ツール境界をモデルが識別しやすくする。
2. **Token efficiency** — コンテキストを浪費しうるツール応答には **pagination / range選択 /
   filtering / truncation** を、**妥当な既定値つきで**実装する。全件を返してモデルに 1 件ずつ
   読ませるのは限られたコンテキストの浪費。
3. **`response_format`** — `concise`(要点のみ)/ `detailed`(全メタデータ)を切り替える
   パラメータを用意し、エージェントが必要な分だけトークンを払えるようにする。
4. **厳格なデータモデル** — 期待する入出力を明示し、曖昧さを型で排除する。

## 本リポジトリでの実演

実装: [`patterns/frameworks/pydantic-ai/src/patterns_pydantic_ai/tool_design.py`](../patterns/frameworks/pydantic-ai/src/patterns_pydantic_ai/tool_design.py)
テスト: `patterns/frameworks/pydantic-ai/tests/unit/test_tool_design.py`

既存の autonomous-agent ループ(`run_autonomous_agent`)は、ツールを
`allowed_tools: Sequence[Tool]`(最小権限の allow-list = 注入シーム)として受け取る。デモはこの
シームに差し込める `patterns_contracts.Tool` Protocol 準拠ツール(`name` / `dangerous` /
`run(args) -> str`)として実装した。

### Namespacing

`make_directory_tools()` は共通プレフィックス `directory_` を持つツール対を返す。

```python
search, get = make_directory_tools(records)
assert search.name == "directory_search"
assert get.name == "directory_get"
```

### Token efficiency(pagination / filter / truncation)

`directory_search` の `run` は JSON 引数(`query` / `limit` / `offset` / `response_format`)を受け、
**フィルタ済み・ページング済み・truncate 済み**の結果と、次ページ用の `next_offset` カーソルを返す。
`limit` 省略時は小さい既定値(`_DEFAULT_LIMIT=5`)、上限は `_MAX_LIMIT=25` にクランプ。これにより
1 回の呼び出しがコンテキストを溢れさせない。

```python
import json
# 既定の小さなページ + 次ページカーソル
page = json.loads(search.run("{}"))
# {"total": 7, "returned": 5, "next_offset": 5, "items": [...]}

# 大きすぎる limit はハード上限 25 にクランプ
json.loads(search.run(json.dumps({"limit": 100})))["returned"]  # -> 25
```

詳細出力の自由記述(`notes`)は `_DETAIL_NOTE_CHARS=80` で truncate し、末尾に `…` を付けて
切り詰めを可視化する。

### `response_format`(concise / detailed)

既定はトークン効率の良い `concise`(`id` + `name` のみ)。`detailed` を指定したときだけ
全メタデータを返す。

```python
json.loads(search.run(json.dumps({"limit": 1})))["items"][0].keys()
# -> {"id", "name"}                     (concise: 要点のみ)
json.loads(search.run(json.dumps({"limit": 1, "response_format": "detailed"})))["items"][0].keys()
# -> {"id", "name", "role", "notes"}    (detailed: 全メタデータ)
```

`directory_get` は ID で 1 件だけを返す「狙い撃ち」ツール。リスト全走査の代わりに該当エントリへ
直接ジャンプでき、`response_format` も尊重する。未ヒット時は小さな `{"error": "not_found"}` を返す。

### 堅牢性(noisy 入力の劣化)

引数が欠落・不正 JSON・非オブジェクトのときは例外を投げず、トークン効率の良い既定へフォールバック
する。ノイズの多いツール呼び出しでもループを壊さず、小さく安全な結果に劣化する。

### autonomous-agent ループへの接続

凍結済みの core には手を入れず、注入シーム経由でそのまま動く。

```python
search, _ = make_directory_tools(records)
result = await run_autonomous_agent(
    "find designers",
    model=model,
    max_iterations=5,
    allowed_tools=[search],      # 最小権限 allow-list = ツール設計シーム
    approval_hook=approve,
    budget=100,
)
```

## 実行・テスト

PydanticAI lane で:

```bash
cd patterns/frameworks/pydantic-ai
uv run pytest tests/unit/test_tool_design.py -q     # ユニット + ループ統合
uv run ruff check . && uv run pyright                # lint + 型(strict)
```

`tool_design.py` は `json` / `dataclasses` / `typing` のみに依存する純粋実装(pydantic 非依存)で、
ネットワーク不要・決定的。lane 全体のカバレッジゲート(`fail_under=98`)を維持する。

## 適用範囲と非適用

- ✅ 既存 `Tool` Protocol / `allowed_tools` シームに接続する実行可能デモとして追加。
- ❌ 凍結済みの 6 パターン契約・他 lane・ドリフト README は変更していない(Spec 006-2a 維持)。
- 将来: 同原則を BeeAI / LlamaIndex lane のツールにも横展開可能(`improvement-plan.md` P1)。
