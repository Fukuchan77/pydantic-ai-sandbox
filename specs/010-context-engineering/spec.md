# 010-context-engineering

> **Status: Draft（Clarifications 確定済）**。改善提案 P2 の起票ドラフト。
> 出典 `specs/best-practices-review/improvement-plan.md` P2。3 論点は IBM/Anthropic/Google/AWS の公式指針に
> 照らし CONFIRMED（→ ADR-1〜3）。`plan.md` / `tasks.md` / `spec.json` は未整備。

deep-research レーンに **compaction** と **structured note-taking**(Anthropic「Effective context
engineering for AI agents」)を実装し、sub-researcher → lead のハンドオフを「凝縮サマリ + ノート」に
限定して「最小の高信号トークン集合」を実現する。

## Project Description

deep-research(`patterns/deep-research/`)は既に sub-agent / context quarantine / 並列
researcher → 合成を実装済みで、Anthropic の multi-agent 技法・LangChain `open_deep_research` と
一致する。一方、公式 context engineering が重視する **compaction**(文脈上限近傍で要約し新コンテキストへ
再初期化)と **structured note-taking**(外部メモリ)は **runnable demo は存在するが本線へ未配線**:

- `patterns/deep-research/.../notes.py`(改善提案 P1/P2 の前段で追加済)が
  `distill_notes` / `render_notebook` / `compact_digest` / `ResearchNote` を提供し、
  `compact_digest` は `researcher._results_digest`(`Sequence[SearchResult] -> str`)の
  signature 互換ドロップインとして設計済み。解説は `docs/context-engineering.md`。
- ただし researcher の reflect ループは依然 `_results_digest` をハードコードで呼んでおり、
  compaction は DI シームとして差し替え可能になっていない。また sub-researcher → lead の
  ハンドオフ契約に外部メモリ(`notes`)フィールドが無く、findings は生のまま渡る。

本 spec は notes.py のデモを **本線の拡張シームへ昇格**させ、契約レベルで note-taking を固定する。

## Clarifications

### Session 2026-06-24（公式指針に基づき CONFIRMED）

IBM / Anthropic / Google / AWS の公式技術情報に照らし、3 論点を確定（→ ADR-1〜3）。

- **compaction シームの注入点 → CONFIRMED**: reflect ループの digest 生成を
  `digest_fn: Callable[[Sequence[SearchResult]], str]`（既定 `_results_digest`）として DI 化し、
  `compact_digest` を **opt-in** で注入する。既定（未注入）挙動は不変（後方互換）。Anthropic の
  「最も軽量・安全な compaction = tool result clearing」に倣い、生 result の畳み込みは軽量形から
  段階導入する（ADR-1）。
- **`notes` 契約の所有 README → CONFIRMED**: 新規 `ResearchNote` 契約を **deep-research README を
  所有者**として追加する（横断 README は新設しない）。`Citation` を RAG 契約に置く既存判断と同型。
  Anthropic「永続メモリは*将来の推論を制約し続ける情報のみ*」を受け、`key_point` に加え採用/棄却の
  判断を残せる拡張余地を持たせる（ADR-2）。
- **compaction の発火条件 → CONFIRMED**: v1 は **常時 digest 縮約**（note ベースの cap / dedup /
  truncate）に限定し、トークン上限トリガの文脈再初期化は **拡張点として文書化**（既存 token-budget
  seam へ接続）。決定論・byte 安定を維持（ADR-3）。

## Overview

researcher の reflect ループが毎ターン全 digest を再注入する代わりに、外部 notebook(distill した
高信号ノート)を保持する。各 `SearchResult` を 1 つの key point に縮約して `ResearchNote` として蓄積
(structured note-taking)、source anchor で重複排除し score 上位 `max_notes` に cap(compaction)。
sub-researcher は lead へ「凝縮サマリ + ノート」のみを渡し、生トランスクリプトは渡さない。全関数は
決定論・モデル非依存で、既存レーンと同じくオフライン hermetic テスト可能。

## Scope

### In Scope

- compaction 要約器を researcher reflect ループへ **DI シーム**として配線(既定は現挙動互換)。
- structured note-taking 外部メモリ契約(`notes` / `ResearchNote` 相当)を `patterns/contracts` へ追加し、
  sub-researcher → lead ハンドオフを「凝縮サマリ + ノート」に限定。README 正本 + 単一ドリフトテスト更新。
- notes.py(既存デモ)の本線昇格と `docs/context-engineering.md` の配線手順更新。
- 決定論フェイクによる hermetic unit(compaction の cap/dedup/truncation、ノート受け渡し)。
- 新規 spec(本書)に要件・ADR・受け入れ条件を明文化。

### Out of Scope

- トークン上限の実測トリガに基づく「文脈再初期化」フル実装(発火条件は拡張点として文書化、Clarifications 参照)。
- 永続化(notebook の checkpoint/resume)。
- 他レーン(rag / sse / autonomous-agent)への note-taking 横展開(将来イテレーション)。
- ライブ検索・LLM 実体(既存の DI seam / gated 結合に委譲)。

## Glossary

- **compaction**: 文脈を高信号サブセットへ縮約する操作(本線では dedup + score cap + truncation)。
- **structured note-taking**: 生トランスクリプトでなく distill した `ResearchNote` を外部メモリとして保持する技法。
- **notebook**: researcher が保持するノート集合の外部メモリ表現。
- **digest seam**: reflect プロンプトへ渡す results ブロック生成の差し替え点(`Sequence[SearchResult] -> str`)。

## Requirements（EARS）

### Requirement 1: compaction DI シーム（ADR-1）
1.1 researcher reflect ループは digest 生成を注入可能なシーム(`digest_fn: Callable[[Sequence[SearchResult]], str]`、既定 `_results_digest`)として公開する。
1.2 `compact_digest` をそのシームへ **opt-in** で注入でき、注入時はノートベースの縮約 digest を reflect プロンプトへ供給する。
1.3 既定(未注入)では現行挙動を変えない(後方互換)。
1.4 生 result の畳み込み(Anthropic「tool result clearing」相当)は最も軽量な compaction 形として段階導入し、v1 は digest 縮約に限定する(上限トリガは ADR-3 の拡張点)。

### Requirement 2: structured note-taking 契約（ADR-2）
2.1 distill したノート型 `ResearchNote`(`source` / `locator` / `key_point` / `score`、将来 `decision` 系を拡張可能)を `patterns/contracts` の単一実体として追加する。
2.2 sub-researcher → lead のハンドオフは「凝縮サマリ + ノート」に限定し、生トランスクリプト全文を渡さない。
2.3 `ResearchNote` の README 正本は **deep-research README を所有者**とし、正本 = パッケージ実体の一致を `test_contract_drift.py` で検証する(横断 README は新設しない)。

### Requirement 3: compaction の決定性と上限（ADR-3）
3.1 ノートは source anchor で重複排除(最高 score 優先)し、score 降順 + `(source, locator)` タイブレークで決定論順序とする。
3.2 retained ノートは `max_notes` で cap、key point は文字数上限で可視マーカー付き truncate する(常時 digest 縮約)。
3.3 非正の `max_notes` / `key_point_chars` は `ValueError` で loud-fail する。
3.4 トークン上限近傍での文脈再初期化は v1 非対象とし、既存 token-budget seam へ接続する拡張点として文書化する。

### Requirement 4: テスト
4.1 全 unit はネットワーク I/O ゼロ(既存 autouse `block_network` + 決定論フェイク)。
4.2 compaction(cap / dedup / truncation / 順序)とノート受け渡し(凝縮サマリ + ノートのみ)を契約レベルで検証する。
4.3 レーンのカバレッジゲート(`fail_under`)を維持する(現状 100%)。

### Requirement 5: ドキュメント
5.1 `docs/context-engineering.md` を本線配線手順へ更新し、deep-research README の該当節へ準拠状況を追記する。
5.2 `specs/best-practices-review/verification.md` の観点5(context engineering)を実装済へ反映する(本 spec 完了時)。

## ADR（確定事項）

### ADR-1: compaction は DI シーム + opt-in、軽量形から段階導入
reflect ループの digest 生成を `digest_fn`(既定 `_results_digest`)として DI 化し、`compact_digest` を
opt-in で注入する。既定挙動は不変。**根拠**: Anthropic は「最も軽量・安全な compaction は tool result
clearing」とし、全文脈の再初期化より軽量形からの導入を推奨。DI 化は既存 `SearchProvider`/`model`/`on_event`
と同じ seam 規律に揃い、決定論フェイクで hermetic テスト可能。後方互換も満たす。

### ADR-2: `ResearchNote` は deep-research README が所有（横断 README を作らない）
note-taking は researcher 固有のメモリであり横断概念ではないため、`Citation` を RAG 契約に置く既存判断と
同型に deep-research README を所有者とする。**根拠**: ドリフトテストの「1クラス = 1 README 所有」を自然に
満たす。Anthropic「永続メモリは*将来の推論を制約し続ける情報のみ*(選好・決定・失敗した手法)」を受け、
`key_point` に加え採用/棄却の判断を残せる拡張余地(`decision` 系)を spec に明記する。

### ADR-3: v1 は常時 digest 縮約、上限トリガは拡張点
v1 は note ベースの常時縮約(cap/dedup/truncate)に限定し、トークン上限近傍の文脈再初期化は
SECURITY-NOTES.md 記載の token-budget seam へ接続する拡張点として文書化する。**根拠**: Anthropic も
軽量形からの導入を推奨。常時縮約は byte 安定・決定論を保ちやすく、本レーンの hermetic 方針と整合。

## Non-Functional Requirements

- pyright strict / ruff strict / coverage `fail_under` 維持。
- import 時 I/O ゼロ・決定論(byte 安定)。
- 凍結済み 6 パターン契約・他レーン・ドリフト README の不要変更を避ける(必要な契約追加は単一ドリフトテストで担保)。

## Out of Scope / Future Work

トークン上限トリガの文脈再初期化、notebook 永続化、他レーンへの note-taking 横展開。

## Dependencies

`patterns-contracts`(パス依存)、deep-research レーン既存ランタイム、既存 `notes.py` デモ・`docs/context-engineering.md`。

## References

- Anthropic, *Effective context engineering for AI agents*: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic Cookbook, *Context engineering: memory, compaction, and tool clearing*: https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools
- Anthropic, *How we built our multi-agent research system*
- LangChain, *open_deep_research*
- 既存: `patterns/deep-research/`(researcher / notes.py)、`docs/context-engineering.md`、`specs/009-deep-research/spec.md`
- 出典: `specs/best-practices-review/improvement-plan.md` P2、`verification.md` 観点5
