# 010-context-engineering

> **Status: Draft**（改善提案 P2 の起票ドラフト。`specs/best-practices-review/improvement-plan.md` P2 が出典。
> `/sdd-init` での確定前に下記 Clarifications の未確定論点を解消する。）

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

### Session（要確定 — /sdd-init 前の未解決論点）

- **[要確定] compaction シームの注入点**: reflect ループの digest 生成を
  `digest_fn: Callable[[Sequence[SearchResult]], str]`(既定 `_results_digest`)として DI 化し、
  `compact_digest` を差し替え可能にするか。既定挙動を変えずシームのみ追加する想定で良いか。
- **[要確定] `notes` 契約の所有 README**: 契約ドリフトテストは「1クラス = 1 README 所有」を強制する
  (`test_contract_drift.py` の `_README_PATHS`)。`notes` フィールド/ノート型を `Finding` に内包するか、
  新規 `ResearchNote` 契約として deep-research README を所有者に追加するか。
- **[要確定] compaction の発火条件**: トークン上限近傍での要約再初期化を v1 で実装するか、
  v1 は note ベースの digest 縮約(常時 compaction)に留め、上限トリガは拡張点として文書化するか。

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

### Requirement 1: compaction DI シーム
1.1 researcher reflect ループは digest 生成を注入可能なシーム(`digest_fn`、既定 `_results_digest`)として公開する。
1.2 `compact_digest` をそのシームへ注入でき、注入時はノートベースの縮約 digest を reflect プロンプトへ供給する。
1.3 既定(未注入)では現行挙動を変えない(後方互換)。

### Requirement 2: structured note-taking 契約
2.1 distill したノート型(`ResearchNote` 相当: `source` / `locator` / `key_point` / `score`)を `patterns/contracts` の単一実体として追加する。
2.2 sub-researcher → lead のハンドオフは「凝縮サマリ + ノート」に限定し、生トランスクリプト全文を渡さない。
2.3 ノート契約の README 正本 = パッケージ実体の一致を `test_contract_drift.py` で検証する(所有 README は Clarifications で確定)。

### Requirement 3: compaction の決定性と上限
3.1 ノートは source anchor で重複排除(最高 score 優先)し、score 降順 + `(source, locator)` タイブレークで決定論順序とする。
3.2 retained ノートは `max_notes` で cap、key point は文字数上限で可視マーカー付き truncate する。
3.3 非正の `max_notes` / `key_point_chars` は `ValueError` で loud-fail する。

### Requirement 4: テスト
4.1 全 unit はネットワーク I/O ゼロ(既存 autouse `block_network` + 決定論フェイク)。
4.2 compaction(cap / dedup / truncation / 順序)とノート受け渡し(凝縮サマリ + ノートのみ)を契約レベルで検証する。
4.3 レーンのカバレッジゲート(`fail_under`)を維持する(現状 100%)。

### Requirement 5: ドキュメント
5.1 `docs/context-engineering.md` を本線配線手順へ更新し、deep-research README の該当節へ準拠状況を追記する。
5.2 `specs/best-practices-review/verification.md` の観点5(context engineering)を実装済へ反映する(本 spec 完了時)。

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
- Anthropic, *How we built our multi-agent research system*
- LangChain, *open_deep_research*
- 既存: `patterns/deep-research/`(researcher / notes.py)、`docs/context-engineering.md`、`specs/009-deep-research/spec.md`
- 出典: `specs/best-practices-review/improvement-plan.md` P2、`verification.md` 観点5
