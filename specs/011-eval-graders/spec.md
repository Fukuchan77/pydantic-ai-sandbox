# 011-eval-graders

> **Status: Draft（Clarifications 確定済）**。改善提案 P4 の起票ドラフト。
> 出典 `specs/best-practices-review/improvement-plan.md` P4。4 論点は IBM/Anthropic/Google/AWS の公式指針に
> 照らし CONFIRMED（→ ADR-1〜4）。`plan.md` / `tasks.md` / `spec.json` は未整備。

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

### Session 2026-06-24（公式指針に基づき CONFIRMED）

IBM / Anthropic / Google / AWS の公式技術情報に照らし、4 論点を確定（→ ADR-1〜4）。

- **グレーダ契約の所有 README → CONFIRMED**: **新規横断 README `patterns/EVAL-GRADERS.md`** を
  `test_contract_drift.py` の `_README_PATHS` へ追加し、共有グレーダ契約の所有者とする。**根拠**: P4 の
  目的が「outcome+behavior グレーダの単一ソース化・横展開」そのものであり、3 パターン共有の契約は真に
  横断的(P2 の `ResearchNote` が deep-research 固有なのと対照的)（ADR-1）。
- **スコアスキーマ → CONFIRMED**: **outcome 軸と behavior 軸を分離**して保持する。各軸は
  **離散 1–5 rating + 各段階の rubric 文言 + 証拠不足を表す `Unknown` + 根拠(rationale)必須**、
  最終集約は **partial credit を許す float**。例: outcome=`correctness`/`completeness`、
  behavior=`tool_use_discipline`/`guardrail_adherence`/`faithfulness`。**根拠**: Anthropic(transcript と
  outcome の分離 / 次元の分離 / Unknown / partial credit / reasoning を含める)、Google Vertex(criteria +
  5 点 rating_rubric)、AWS(correctness/completeness + Tool Selection Accuracy)、IBM(faithfulness +
  全判断の audit trail)（ADR-2）。
- **judge の独立性表現 → CONFIRMED**: 契約は **純データ(軸スコア + rationale + 集約)+ judge 出自の
  最小メタ(`judge_id` 等の任意フィールド)**に限定。`self_eval_forbidden` 等のフラグは契約に入れず、
  独立性は実装規律(別モデル注入・Generator/Evaluator 物理分離)で担保する。**根拠**: Anthropic は独立
  judge と人手キャリブレーションを運用規律として説き(型制約ではない)、IBM は誰が採点したかの監査証跡を
  重視。SSE レーンの「過剰な型制約で誤った安全感を与えない」方針と一貫（ADR-3）。
- **既存 `OptimizationResult` との関係 → CONFIRMED**: **併存(後方互換維持)**。`OptimizationResult`
  (`verdict: pass|revise`)はランタイム収束ゲート(in-the-loop)のまま、新グレーダ契約はオフライン/CI の
  多軸採点という別レイヤに置く。橋渡しは将来拡張。**根拠**: IBM は in-the-loop(実行中の判断点)と offline の
  2 モードを補完的と定義、Anthropic も収束判定と eval(CI 採点)を区別（ADR-4）。

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

### Requirement 1: 共有グレーダ契約（ADR-1, ADR-2）
1.1 outcome+behavior の多軸スコアを表す単一契約(`GradeReport` 相当)を `patterns/contracts` に追加する。
1.2 契約は **outcome 軸と behavior 軸を分離**して保持し、各軸は離散 1–5 rating + 証拠不足の `Unknown` + 根拠(rationale)必須、最終集約は partial credit を許す float とする。
1.3 各 rating 段階の意味は rubric 文言で定義する(Google Vertex の rating_rubric 方式)。
1.4 グレーダ契約の README 正本は **新規横断 README `patterns/EVAL-GRADERS.md`** を所有者とし、`_README_PATHS` へ登録のうえ 正本 = パッケージ実体の一致を `test_contract_drift.py` で検証する。

### Requirement 2: 複数パターンからの参照（ADR-4）
2.1 evaluator-optimizer / deep-research / autonomous-agent の eval が同一グレーダ契約を import して採点結果を構築する。
2.2 各パターンの既存ランタイム契約(`OptimizationResult` / `ResearchReport` / `AgentRunResult`)は後方互換を維持する。グレーダ契約はランタイム収束ゲートと**併存する別レイヤ**(オフライン/CI 採点)とし、既存契約を置換しない。
2.3 deep-research の採点対象には spec 010 で追加された `Finding.notes`(`ResearchNote` の distill 済みノート)を含める。IF `ResearchNote.key_point` が空または低信号(distill は空 `SearchResult.snippet` から空 key point を生成しうる)であるとき、THEN behavior/faithfulness 軸は silent にスコアせず `Unknown`(証拠不足、ADR-2)へマップする。

### Requirement 3: 独立 judge と self-eval バイアス回避（ADR-3）
3.1 採点は被評価系と分離した judge シーム(注入)で行い、self-eval を構造的に避ける。
3.2 judge はオフライン決定論フェイクで差し替え可能とし、hermetic に採点形状を検証する。
3.3 契約は純データ(軸スコア + rationale + 集約)+ judge 出自の最小メタ(`judge_id` 等の任意フィールド)に限定し、self-eval 禁止フラグ等の規律は型制約にしない(実装規律で担保)。

### Requirement 4: テスト
4.1 全グレーディング unit はネットワーク I/O ゼロ(決定論フェイク judge)。
4.2 共有グレーダ契約が 3 パターンの eval から参照されることを検証する。
4.3 契約ドリフトテストが緑であること(受け入れ条件)。

### Requirement 5: ドキュメント
5.1 グレーダ契約の所有 README に正本を置き、各パターン README の評価節へ参照を追記する。
5.2 `specs/best-practices-review/verification.md` の観点6(評価)へ単一ソース化を反映する(本 spec 完了時)。

## ADR（確定事項）

### ADR-1: 共有グレーダは新規横断 README `patterns/EVAL-GRADERS.md` が所有
3 パターン共有の契約は真に横断的なので、横断 README を単一ソースの所在とし `_README_PATHS` へ登録する。
**根拠**: P4 の目的が「単一ソース化・横展開」そのもの。P2 の `ResearchNote`(deep-research 固有)とは
対照的で、評価グレーダは複数パターンに跨る。ドリフトテストの「1クラス = 1 README 所有」も満たす。

### ADR-2: スコアは outcome/behavior 分離 × 1–5 rating + Unknown + rationale、集約は float
outcome 軸と behavior 軸を分離し、各軸は離散 1–5 rating(各段階 rubric 定義)+ 証拠不足 `Unknown` +
rationale 必須、最終集約は partial credit を許す float。**根拠**: Anthropic(transcript と outcome の分離 /
次元の分離 / Unknown / partial credit / reasoning を含める)、Google Vertex(criteria + 5 点
rating_rubric)、AWS(correctness/completeness + Tool Selection Accuracy)、IBM(faithfulness + audit
trail)の合流点。rationale 必須は本リポジトリの「silent empty 禁止」規律と一致。

### ADR-3: 独立性は実装規律、契約は純データ + judge 最小メタ
契約は軸スコア + rationale + 集約 + `judge_id` 等の最小メタに限定し、self-eval 禁止フラグは型に入れない。
独立性は別モデル注入・Generator/Evaluator 物理分離で担保。**根拠**: Anthropic は独立 judge と人手
キャリブレーションを運用規律として説き、IBM は採点者の監査証跡を重視。SSE レーンの「過剰な型制約で誤った
安全感を与えない」方針と一貫。

### ADR-4: 既存収束ゲートと併存（置換しない）
`OptimizationResult`(`verdict: pass|revise`)はランタイム収束ゲート(in-the-loop)のまま、グレーダ契約は
オフライン/CI の多軸採点という別レイヤに置く。**根拠**: IBM は in-the-loop(実行中の判断点)と offline の
2 モードを補完的と定義、Anthropic も収束判定と eval(CI 採点)を区別。後方互換を壊さず単一ソース化を達成。

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
- Google Cloud, *Details for managed rubric-based metrics (Vertex AI Gen AI evaluation)*: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/rubric-metric-details
- AWS, *Evaluate Amazon Bedrock Agents with Ragas and LLM-as-a-judge*: https://aws.amazon.com/blogs/machine-learning/evaluate-amazon-bedrock-agents-with-ragas-and-llm-as-a-judge/
- AWS, *Build reliable AI agents with Amazon Bedrock AgentCore Evaluations*: https://aws.amazon.com/blogs/machine-learning/build-reliable-ai-agents-with-amazon-bedrock-agentcore-evaluations/
- IBM, *Agentic AI evaluation (watsonx documentation)*: https://www.ibm.com/docs/en/watsonx/saas?topic=sdk-agentic-ai-evaluation
- 既存: `patterns/contracts/`(evaluator_optimizer / deep_research / autonomous_agent)、`contracts/tests/unit/test_contract_drift.py`
- 関連 spec: `specs/010-context-engineering/spec.md`(deep-research に `Finding.notes` / `ResearchNote` を追加。Req 2.3 のとおり本 spec の deep-research グレーダは distill 済みノートも採点対象に含む)
- 出典: `specs/best-practices-review/improvement-plan.md` P4、`verification.md` 観点6
