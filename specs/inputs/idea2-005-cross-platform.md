# Idea: Spec 005 — Cross-Platform Agent Pattern Collection

- 起票日: 2026-06-12
- 前提: `001-agentic-platform`〜`003-litellm-integration` 完了（main マージ済み、277 unit GREEN、coverage 98%）
- ねらい: PydanticAI・BeeAI Framework・LlamaIndex Workflows を横断した
  **エージェント実装ベストプラクティス・パターン集** を `patterns/` 配下に構築する。
  PydanticAI v2 / LlamaIndex 系はベータ版だが検証目的で意図的に採用する。

---

## 1. 入力ドキュメントと検証結果

ユーザー提供の調査ドキュメント2本を起点とする:

1. **AI Agent / Agentic AI 開発フレームワーク ベストプラクティス調査レポート**
   — 3フレームワーク役割分担（PydanticAI=型安全/テスト/可観測性の参照基準、
   LlamaIndex=RAG/ドキュメント処理、BeeAI=マルチエージェント協調/A2A・ACP）、
   Anthropic「Building Effective Agents」5ワークフロー+autonomous agent ×
   IBM「AI Agent vs Agentic AI」粒度の二軸タクソノミー、モノレポ構成案。
2. **Production Architectures for Agentic AI**
   — Harness/Code Mode/Monty、BeeAI RequirementAgent 宣言的制約、
   LlamaIndex Workflows イベント駆動、Docling HybridChunker、
   FastAPI EventSourceResponse、CVE 群と OWASP Agentic AI Top 10。

両ドキュメントの主要主張は 2026-06-11 に Web 検証済み（詳細は
`specs/005-cross-platform/research.md`）。CVE 情報・フレームワーク機能の主張は
ほぼすべて一次情報で裏付けられた。未検証は LlamaAgents 公式 docs（403）と
細部 API のみで、実装時に実測確認する。

## 2. ユーザー決定事項（確定）

1. **構成 = 漸進追加**: 既存 `src/` アプリ・CI は無変更。`patterns/` を新設。
2. **Python = パッケージ毎分離**: 各フレームワークレーンは独立 uv プロジェクト
   （独自 pyproject.toml / uv.lock / .python-version）。
   beeai-framework は `<3.14` 上限のため uv workspace は構造的に不可能。
3. **第1イテレーション = 基盤 + 代表2パターン**:
   routing と orchestrator-workers を 3 フレームワークで実装比較。
   各パターン README に「型安全 / テスト / 可観測性 / セキュリティ」必須4セクション。

## 3. スコープ外（将来イテレーション）

- 残り4パターン（prompt-chaining / parallelization / evaluator-optimizer /
  autonomous-agent）
- Docling + LlamaIndex RAG レーン（HybridChunker、引用付き回答）
- FastAPI EventSourceResponse SSE デモアプリ
- BeeAI A2A/ACP 相互運用サーバ
- Pydantic Evals の CI 組込（SpanTree スパンベース評価）
- shared-contracts 共有パッケージ化

## 4. /sdd 起動時の解決済み論点

- uv workspace か独立プロジェクトか → **独立プロジェクト**（requires-python 交差が空）
- パターン単位かフレームワーク単位のパッケージか → **フレームワーク単位3つ**
  （パターン比較ドキュメントは `patterns/<pattern>/README.md` に集約）
- 共有契約コードの置き場 → 第1イテレーションは**各レーンに複製**
  （正本はパターン README、将来 `tool.uv.sources` パス依存で昇格）

## 5. 参考

- `specs/005-cross-platform/research.md` — 検証結果全文・CVE 表
- `specs/inputs/idea0.md` / `idea1-002-multi-provider.md` — 既存基盤の設計系譜
- Anthropic "Building Effective Agents" (2024-12-19)
- OWASP Agentic AI Top 10 (2025-12) / OWASP LLM Top 10 2025
