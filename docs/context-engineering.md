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

## 解決したギャップ(Spec 010 で本線昇格)

Deep Research lane は **sub-agent / context quarantine / 並列 researcher → 合成**を既に実装済み
(`patterns/deep-research/`)。残るギャップは、sub-researcher の reflect ループが
[`researcher.py`](../patterns/deep-research/src/patterns_deep_research/researcher.py) の
`_results_digest(collected)` で**集めた全結果を毎ターン丸ごと**プロンプトへ再注入していた点だった ——
検索のたびにプロンプトが肥大化し、モデルは低信号テキストを 1 トークンずつ読み直す、公式が戒める
典型的アンチパターン。加えて sub-researcher → lead のハンドオフ契約に外部メモリ(`notes`)が無く、
findings は生のまま渡っていた。

Spec 010 はこのデモを **本線の拡張シームへ昇格**させた。reflect ループの digest 生成を `digest_fn`
DI シーム化(既定は現挙動と byte 互換、`compact_digest` を **opt-in** で注入)し、`ResearchNote` を
`patterns_contracts` の単一契約へ昇格して `Finding.notes` に載せ、ハンドオフを「凝縮サマリ + ノート」へ
固定した(生トランスクリプト非伝播)。

## 本リポジトリでの実装

実装: [`patterns/deep-research/src/patterns_deep_research/notes.py`](../patterns/deep-research/src/patterns_deep_research/notes.py)
契約: [`patterns/contracts/src/patterns_contracts/deep_research.py`](../patterns/contracts/src/patterns_contracts/deep_research.py)(`ResearchNote` / `Finding.notes`)
テスト: `patterns/deep-research/tests/unit/test_notes.py`、`test_researcher.py`、`test_research.py`

外部の**ノートブック**を導入し、生の transcript ではなく**蒸留した高信号ノート**を保持する。

### Structured note-taking

各 `SearchResult` を 1 つの高信号な *key point*(先頭文を truncate)に縮約し、`ResearchNote`
(`source` / `locator` / `key_point` / `score`)として外部メモリに保持する。`ResearchNote` は
`patterns_contracts` の単一実体(`frozen=True` の Pydantic `BaseModel`)で、正本は deep-research README が
所有し `test_contract_drift.py` が package との一致を機械検証する。

### Compaction(最小の高信号トークン集合)

ノートは source アンカー(`source`/`locator`)で**重複排除**(最高スコア勝ち)し、スコア降順 +
`(source, locator)` タイブレークで上位 `max_notes` 件に**圧縮**、key point を `key_point_chars` で
可視マーカー付きに truncate する。reflect ターンが実際に必要とする「最小の高信号トークン集合」に絞る。
`max_notes` / `key_point_chars` が非正なら `ValueError` で loud-fail する。

```python
notes = distill_notes(results, max_notes=5)
# 1 アンカー 1 ノート、スコア降順、(source, locator) で決定的タイブレーク
render_notebook(notes)
# - [B#2] Beta point
# - [C#3] Gamma point
# - [A#1] Alpha is first
```

### 本線配線(reflect digest の DI シーム)

`compact_digest` は `researcher._results_digest` と**同一シグネチャ**
(`Sequence[SearchResult] -> str`)で、reflect ループの結果ブロック生成を差し替える `digest_fn`
シームへドロップインする。`run_subquestion` / `run_deep_research` の双方が `digest_fn` を公開し、
**注入時のみ**ノートベース縮約へ切り替わる。既定(未注入)は `_results_digest` のまま現挙動と byte 一致
(後方互換)で、`test_researcher.py` が捕捉した reflect プロンプト文字列の完全一致でこの不変を固定する。

```python
from patterns_deep_research.notes import compact_digest
from patterns_deep_research.research import run_deep_research

# opt-in: compact_digest を注入すると全 sub-researcher の reflect digest が
# ノートベース縮約になる(未注入なら現挙動と byte 互換)。
report = await run_deep_research(
    query,
    model=model,
    search=search,
    digest_fn=compact_digest,
)
```

`max_notes` などの調整は `functools.partial` で seam シグネチャを保ったまま注入できる。

```python
from functools import partial

digest_fn = partial(compact_digest, max_notes=3, key_point_chars=80)
report = await run_deep_research(query, model=model, search=search, digest_fn=digest_fn)
```

### compression ターンは full digest を維持

reflect ループだけが `digest_fn` を経由する。**compression ターン**(finding サマリ生成 + 引用源選択)は
注入有無に関わらず `_results_digest(collected)` の **full 出力**を使い続ける。引用は researcher が実際に
取得した `SearchResult` に対応必須で、縮約で source を落とすと `EmptyCitationError` /
`DanglingCitationError` を誘発しかねないため、citation grounding を保全する設計(ADR-A)。

### Finding.notes ハンドオフ

reflect ループ終了後、`Finding.notes = distill_notes(collected)` を充填する。sub-researcher → lead の
ハンドオフは「凝縮サマリ + ノート」のみで、生トランスクリプト全文は渡さない(Anthropic の sub-agent
凝縮サマリ原則)。`distill_notes([])` は `[]` を返すため、空 gather でも `Finding.notes=[]` の安全既定に
なる(後方互換)。

## 拡張点(v1 非対象 + token-budget seam)

ADR-3 に従い、v1 は **常時 digest 縮約**(note ベースの cap / dedup / truncate)に限定する。次は
v1 では提供せず、拡張点として明記する。

- **トークン上限トリガの文脈再初期化** — 公式 compaction の核(上限近傍で会話を要約し新コンテキストへ
  再初期化)は v1 非対象。生 result の畳み込み(Anthropic「tool result clearing」相当)も含めない。
  Anthropic も「最も軽量・安全な compaction」からの段階導入を推奨しており、本レーンは決定論・byte 安定を
  保ちやすい常時縮約から入る。
- **既存 token-budget seam への接続** — 上限トリガ実装の自然な接続点は、deep-research が既に拡張点として
  文書化している **token-budget seam**(autonomous-agent の `_budget_spent` ≒ `ModelResponse.usage`
  合算)。ファンアウトに被せた予算ガードが上限近傍を検知したら、`digest_fn` を経由する縮約から
  文脈再初期化へエスカレートする、という段階化が描ける。詳細は
  [SECURITY-NOTES.md](../patterns/SECURITY-NOTES.md) と
  [deep-research COMPARISON.md](../patterns/deep-research/COMPARISON.md) を参照。

## 実行・テスト

Deep Research lane で:

```bash
cd patterns/deep-research
uv run pytest tests/unit/test_notes.py -q       # ノートブックのユニットテスト
uv run pytest tests/unit/test_researcher.py -q  # digest_fn シーム + Finding.notes 充填
uv run pytest tests/unit/test_research.py -q     # end-to-end opt-in(digest_fn 透過)
uv run pytest tests/unit -q                      # lane 全体(カバレッジ 98% ゲート)
uv run ruff check . && uv run pyright            # lint + 型(strict)
```

`notes.py` は `patterns_contracts` の `ResearchNote` を import する純粋実装(モデル呼び出しなし)で、
ネットワーク不要・決定的。全 unit は autouse `block_network` + 決定論フェイクでネットワーク I/O ゼロ、
lane 全体のカバレッジは 100% を維持する。

## 適用範囲と非適用

- ✅ reflect ループへ `digest_fn` DI シームを本線配線(既定は `_results_digest` と byte 互換、
  `compact_digest` を opt-in 注入)。`run_subquestion` / `run_deep_research` の双方が公開。
- ✅ `ResearchNote` を `patterns_contracts` の単一契約へ昇格し `Finding.notes` に固定。ハンドオフを
  「凝縮サマリ + ノート」へ限定(生トランスクリプト非伝播)。
- ✅ structured note-taking + compaction を決定的・テスト付きで実装(cap / dedup / truncation / 順序)。
- ✅ compression ターンは full `_results_digest` を維持し citation grounding を保全(ADR-A)。
- ❌ トークン上限トリガの文脈再初期化・生 result の畳み込みは v1 非対象(上記「拡張点」)。
- ❌ notebook の永続化(checkpoint/resume)、他レーン(rag / sse)への note-taking 横展開は将来イテレーション。
