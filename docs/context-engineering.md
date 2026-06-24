# Context Engineering — Anthropic「Effective context engineering」の適用

## 原則(公式が重視すること)

Anthropic の [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
は、コンテキスト汚染を抑える技法として次を挙げる。

1. **Compaction** — コンテキスト上限に近づいた会話を要約し、要約で新しいコンテキストを再初期化する。
   何を残し何を捨てるかの取捨選択が肝。
2. **Structured note-taking** — エージェントが外部「メモ帳」に要点・ToDo・方針を書き出し、必要時に
   引き戻す。直近コンテキストを汚さずに永続メモリを持つ。
3. **Sub-agents(multi-agent)** — 複雑タスクを専門 sub-agent に委譲し、各々が深掘りして**凝縮した
   サマリ**だけを親に返す。詳細な探索コンテキストは sub-agent 内に隔離される。

指針は **「desired outcome の確率を最大化する、最小の高信号トークン集合」** を見つけること。

## 現状ギャップ(なぜ改善するか)

Deep Research lane は **sub-agent / context quarantine / 並列 researcher → 合成**を既に実装済み
(`patterns/deep-research/`)。一方、sub-researcher の reflect ループは
[`researcher.py`](../patterns/deep-research/src/patterns_deep_research/researcher.py) の
`_results_digest(collected)` で**集めた全結果を毎ターン丸ごと**プロンプトへ再注入している。
検索のたびにプロンプトが肥大化し、モデルは低信号テキストを 1 トークンずつ読み直す ——
公式が戒める典型的なアンチパターン。

## 本リポジトリでの実演

実装: [`patterns/deep-research/src/patterns_deep_research/notes.py`](../patterns/deep-research/src/patterns_deep_research/notes.py)
テスト: `patterns/deep-research/tests/unit/test_notes.py`

外部の**ノートブック**を導入し、生の transcript ではなく**蒸留した高信号ノート**を保持する。

### Structured note-taking

各 `SearchResult` を 1 つの高信号な *key point*(先頭文を truncate)に縮約し、`ResearchNote`
(`source` / `locator` / `key_point` / `score`)として外部メモリに保持する。

### Compaction(最小の高信号トークン集合)

ノートは source アンカー(`source`/`locator`)で**重複排除**(最高スコア勝ち)し、スコア降順で
上位 `max_notes` 件に**圧縮**する。reflect ターンが実際に必要とする「最小の高信号トークン集合」に絞る。

```python
notes = distill_notes(results, max_notes=5)
# 1 アンカー 1 ノート、スコア降順、(source, locator) で決定的タイブレーク
render_notebook(notes)
# - [B#2] Beta point
# - [C#3] Gamma point
# - [A#1] Alpha is first
```

### シームへの接続(1 行差し替え)

`compact_digest` は `researcher._results_digest` と**同一シグネチャ**
(`Sequence[SearchResult] -> str`)。reflect ループの結果ブロック生成をそのまま置き換えられる。

```diff
# patterns/deep-research/src/patterns_deep_research/researcher.py
-from patterns_deep_research.compression import map_citations
+from patterns_deep_research.compression import map_citations
+from patterns_deep_research.notes import compact_digest

     action = (
         await action_agent.run(
             f"Subquestion: {subquestion.description}\n\n"
-            f"Results so far:\n{_results_digest(collected)}"
+            f"Results so far:\n{compact_digest(collected)}"
         )
     ).output
```

> 注: 本デモは凍結済みパイプラインの挙動・テストを乱さないため、`researcher.py` の配線自体は
> 変更していない(上記 diff は接続方法の提示)。`compact_digest` 単体が決定的に動作・テスト済み。

## 実行・テスト

Deep Research lane で:

```bash
cd patterns/deep-research
uv run pytest tests/unit/test_notes.py -q     # ノートブックのユニットテスト
uv run pytest tests/unit -q                   # lane 全体(カバレッジ 98% ゲート)
uv run ruff check . && uv run pyright          # lint + 型(strict)
```

`notes.py` は `dataclasses` / `typing` のみの純粋実装(モデル呼び出しなし)で、ネットワーク不要・
決定的。lane 全体のカバレッジは 100% を維持する。

## 適用範囲と非適用

- ✅ `_results_digest` と同一シグネチャの `compact_digest` を提供し、シーム接続を実演。
- ✅ structured note-taking + compaction を決定的・テスト付きで実装。
- ❌ 凍結済み `researcher.py` の配線・契約・ドリフト README は変更していない(Spec 009 維持)。
- 将来: reflect ループへの本配線、および compaction の要約器シーム化(`improvement-plan.md` P2)。
