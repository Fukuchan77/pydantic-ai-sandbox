# 011-eval-graders

> **Status: Draft**（改善提案 P4 の起票ドラフト。`specs/best-practices-review/improvement-plan.md` P4 が出典。
> `/sdd-init` での確定前に下記 Clarifications の未確定論点を解消する。）

outcome+behavior の評価グレーダ(Anthropic「Demystifying evals」)を `patterns/contracts` の
**単一ソース**として契約化し、evaluator-optimizer / deep-research / autonomous-agent の複数パターンで
共有する。ランタイムゲートと eval グレーダの定義ドリフトを 1 点で防ぐ。

## Project Description

evaluator-optimizer は Generator / Evaluator を物理分離し独立 judge を採用、hermetic テストも整備済みで、
公式の「self-eval バイアス回避」「独立 judge」に準拠する。一方、**outcome(最終成果)+ behavior(過程)の
両軸グレーダ定義**はパターン個別に散在し、横断的な単一ソースになっていない:

- evaluator-optimizer は `OptimizationResult` / `Iteration`(`verdict: pass|revise`)で
  ランタイムの収束ゲートを表現するが、これは「収束判定」であって多軸の **eval グレーダ**ではない。
- deep-research / autonomous-agent には outcome+behavior を多軸スコアで採点する共有契約が無い。

本 spec は outcome+behavior グレーダを契約(多軸スコアの `AuditReport` 相当)として `contracts/` に追加し、
3 パターンが同一契約を参照することで、ランタイムゲートと eval グレーダの単一ソース化を図る。

## Clarifications

### Session（要確定 — /sdd-init 前の未解決論点）

- **[要確定] グレーダ契約の所有 README**: 契約ドリフトテストは「1クラス = 1 README 所有」を強制する
  (`test_contract_drift.py` の `_README_PATHS` と `_OWNERS` 一意性)。共有グレーダは横断的なので、
  (a) 新規の横断 README(例 `patterns/EVAL-GRADERS.md` を `_README_PATHS` へ追加)を所有者にするか、
  (b) evaluator-optimizer README を所有者とし他パターンは参照に留めるか、を確定する。
- **[要確定] スコアスキーマ**: 多軸スコアの軸定義(例 outcome: correctness / completeness、
  behavior: tool-use discipline / guardrail-respect)と尺度(0–1 float か `Literal` 段階か)。
- **[要確定] judge の独立性表現**: グレーダ契約に judge メタ(独立 judge モデル ID / self-eval 禁止フラグ)を
  含めるか、契約は純データ(スコア + 根拠)に限定し独立性は実装規律に委ねるか。
- **[要確定] 既存 `OptimizationResult` との関係**: 収束ゲートとグレーダを別契約として併存させるか、
  グレーダを参照する形へ寄せるか(後方互換維持が前提)。

## Overview

outcome+behavior の多軸グレーダ契約(`GradeReport` 相当: 軸別スコア + 根拠 + 集約判定)を
`patterns/contracts` の単一実体として定義する。evaluator-optimizer はランタイム収束ゲートに加えて
この契約で最終成果を採点でき、deep-research は report の grounding/網羅を、autonomous-agent は
stop_reason / ガードレール遵守を、同一の軸スキーマで採点する。独立 judge による self-eval バイアス回避は
実装規律(物理分離・別モデル注入)として維持し、契約は採点結果のデータ形状を固定する。

## Scope

### In Scope

- outcome+behavior グレーダ契約(多軸スコア + 根拠 + 集約)を `patterns/contracts` へ追加し、README 正本 + 単一ドリフトテストへ登録。
- evaluator-optimizer / deep-research / autonomous-agent の **eval(テスト/グレーディング)**で同一契約を参照。
- 共有グレーダのオフライン hermetic グレーディング(決定論フェイク judge での採点形状検証)。
- 新規 spec(本書)に要件・ADR(所有 README / スコアスキーマ)・受け入れ条件を明文化。

### Out of Scope

- ランタイム本線ロジックの大規模リファクタ(各パターンの収束ゲートは現契約を維持)。
- ライブ LLM judge の runtime 実装(独立 judge は注入シーム/フェイクで検証)。
- 評価結果の永続化・ダッシュボード化。
- 6 パターン全部への横展開(本 spec は 3 パターンに限定)。

## Glossary

- **outcome グレーダ**: 最終成果物の品質軸を採点する(例 correctness / completeness)。
- **behavior グレーダ**: 過程・振る舞いの軸を採点する(例 tool-use discipline / guardrail 遵守)。
- **独立 judge**: 被評価系と物理分離した別モデル/別実装の採点者(self-eval バイアス回避)。
- **グレーダ契約**: 採点結果(軸別スコア + 根拠 + 集約判定)の型固定された単一ソース。

## Requirements（EARS）

### Requirement 1: 共有グレーダ契約
1.1 outcome+behavior の多軸スコアを表す単一契約(`GradeReport` 相当)を `patterns/contracts` に追加する。
1.2 契約は軸別スコア・各軸の根拠・集約判定を保持し、軸スキーマは Clarifications で確定したものに従う。
1.3 README 正本 = パッケージ実体の一致を `test_contract_drift.py` で検証する(所有 README は Clarifications で確定)。

### Requirement 2: 複数パターンからの参照
2.1 evaluator-optimizer / deep-research / autonomous-agent の eval が同一グレーダ契約を import して採点結果を構築する。
2.2 各パターンの既存ランタイム契約(`OptimizationResult` / `ResearchReport` / `AgentRunResult`)は後方互換を維持する。

### Requirement 3: 独立 judge と self-eval バイアス回避
3.1 採点は被評価系と分離した judge シーム(注入)で行い、self-eval を構造的に避ける。
3.2 judge はオフライン決定論フェイクで差し替え可能とし、hermetic に採点形状を検証する。

### Requirement 4: テスト
4.1 全グレーディング unit はネットワーク I/O ゼロ(決定論フェイク judge)。
4.2 共有グレーダ契約が 3 パターンの eval から参照されることを検証する。
4.3 契約ドリフトテストが緑であること(受け入れ条件)。

### Requirement 5: ドキュメント
5.1 グレーダ契約の所有 README に正本を置き、各パターン README の評価節へ参照を追記する。
5.2 `specs/best-practices-review/verification.md` の観点6(評価)へ単一ソース化を反映する(本 spec 完了時)。

## Non-Functional Requirements

- pyright strict / ruff strict / coverage ゲート維持。
- 依存ゼロ契約(`patterns_contracts` は pydantic のみ、外部ランタイム非依存)。
- 既存 6 パターン契約・ドリフトテストの後方互換を維持し、追加は単一ドリフトテストで担保。

## Out of Scope / Future Work

ランタイム本線の大規模リファクタ、ライブ judge runtime、評価結果の永続化、6 パターン全展開。

## Dependencies

`patterns-contracts`(パス依存、`pydantic>=2`)、evaluator-optimizer / deep-research / autonomous-agent の各 lane テスト基盤。

## References

- Anthropic, *Demystifying evals for AI agents*: https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- 既存: `patterns/contracts/`(evaluator_optimizer / deep_research / autonomous_agent)、`contracts/tests/unit/test_contract_drift.py`
- 出典: `specs/best-practices-review/improvement-plan.md` P4、`verification.md` 観点6
