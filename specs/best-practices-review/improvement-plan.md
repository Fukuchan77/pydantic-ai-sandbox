# Improvement Plan — AI Agents / Agentic AI 実装ベストプラクティス

`verification.md` の検証結果を入力に、本リポジトリ(`pydantic-ai-sandbox`)を公式実装
ベストプラクティス(主に Anthropic の各ガイダンス)へさらに寄せるための改善提案。
優先度は **実装ベストプラクティス** 観点で付与。各提案は現状・根拠・具体策・受け入れ条件をセットで記す。

## 優先度一覧

| ID | 提案 | 観点 | 優先度 | 規模 |
|----|------|------|--------|------|
| P1 | ツール設計を Anthropic「Writing tools for agents」原則へ準拠・明示 | ツール設計 | 高 | 中 |
| P2 | context engineering(compaction / structured note-taking)の実装化 | コンテキスト | 中 | 大 |
| P3 | 公式参照に AWS(Bedrock Agents / Well-Architected for GenAI)を追記 | 定義・参照 | 低 | 小 |
| P4 | 評価(evals)の outcome+behavior グレーダを契約化して横展開 | 評価 | 中 | 中 |

---

## P1 — ツール設計を「Writing tools for agents」原則へ準拠・明示【高】

**現状**: autonomous-agent のデモツール(`patterns/.../tools` 相当)は副作用フリーの canned 文字列を返す。
型強制(`output_type` + `contracts/`)と実行前入力検証(パストラバーサル拒否)は実装済みだが、
公式が重視する **token 効率 / namespacing / `response_format`** の実演とドキュメント明示がない。

**公式根拠**: Anthropic「Writing tools for agents」
— pagination/filter/truncation による token 効率、サービス/リソース別 namespacing
(例 `notes_search` / `records_delete`)、`response_format`(`concise` / `detailed`)。

**具体策**:
1. デモツールを namespacing 規約(`<resource>_<verb>`)へ統一し、`patterns/SECURITY-NOTES.md` 同様に
   ツール設計規約ドキュメントを追加(`patterns/TOOL-DESIGN-NOTES.md` 等)。
2. 少なくとも 1 つのデモツールに token 効率の最小実装(`limit` / `offset` / 既定 truncation)と
   `response_format`(`concise` / `detailed`)を実装し、契約モデルへ反映。
3. 各パターン README の「ツール設計」節に公式原則への準拠状況を追記。

**受け入れ条件**: ツール設計規約ドキュメントが存在し、デモツール 1 件以上で
pagination/truncation と `response_format` が動作。契約ドリフトテストが緑。

---

## P2 — context engineering(compaction / note-taking)の実装化【中】

**現状**: deep-research は sub-agent / context quarantine / 並列 researcher→合成を実装済み
(Anthropic の multi-agent 技法・LangChain open_deep_research と一致)。一方、**compaction** と
**structured note-taking** は未実装。

**公式根拠**: Anthropic「Effective context engineering」
— compaction(文脈上限近傍で要約し新コンテキストへ再初期化)、structured note-taking(外部メモリ)、
「最小の高信号トークン集合」。

**具体策**:
1. deep-research の researcher ループに compaction フック(要約器)を DI シームとして追加し、
   既存の決定的フェイクで hermetic テスト可能にする。
2. structured note-taking 用の外部メモリ契約(`notes` フィールド)を `contracts/` に追加し、
   sub-researcher → lead のハンドオフを「凝縮サマリ + ノート」に限定。
3. 新規 spec(`specs/0NN-context-engineering/`)として要件・ADR・受け入れ条件を明文化。

**受け入れ条件**: compaction とノート受け渡しがネットワークフリーテストで検証され、
カバレッジゲート(`fail_under`)を維持。

---

## P3 — 公式参照に AWS を追記【低】

**現状**: 公式参照は IBM / Anthropic / Google が中心で AWS が欠落。

**具体策**: `verification.md` および関連 README の References に
AWS Bedrock Agents / AWS Well-Architected for Generative AI を追記し、
本リポジトリのガードレール/プロバイダ非依存設計との対応関係を 1 段落で補足。
(URL は依頼時に未提供のため、公式ドキュメント確定後に追記する。)

**受け入れ条件**: References に AWS 公式 2 件が追加され、対応関係の記述がある。

---

## P4 — 評価グレーダの契約化と横展開【中】

**現状**: evaluator-optimizer は Generator/Evaluator を分離し独立 judge を採用。hermetic テストも整備済み。
一方、outcome+behavior の **グレーダ定義** はパターン個別で、横断的な単一ソースになっていない。

**公式根拠**: Anthropic「Demystifying evals」— outcome(最終成果)+ behavior(過程)の両軸スコア、
独立 judge による self-eval バイアス回避。

**具体策**:
1. outcome+behavior グレーダ契約を `contracts/` に追加(`AuditReport` 相当の多軸スコア)。
2. evaluator-optimizer / deep-research / autonomous-agent で同一グレーダ契約を共有し、
   ランタイムゲートと eval グレーダの単一ソース化を図る。

**受け入れ条件**: 共有グレーダ契約が複数パターンから参照され、契約ドリフトテストが緑。

---

## 進め方の推奨

1. **P1 を先行**(高優先・中規模、ツール設計はリファレンス教材としての価値が最も高い)。
2. P3 は P1 と同 PR で軽微に対応可能。
3. P2 / P4 は spec 起票 → 実装の順で、既存の hermetic テスト方針とカバレッジゲートを維持して進める。
