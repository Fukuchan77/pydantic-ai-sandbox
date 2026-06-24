# Docs — Implementation Best-Practice Guides

公式(IBM / Anthropic / Google)の AI Agent / Agentic AI 定義・ベストプラクティスに対する本
リポジトリの**検証**は `specs/best-practices-review/` にある。本 `docs/` は、その検証で挙がった
**実装ベストプラクティスの改善提案を実際のコードへ適用した結果**を、原則・実装・テストの形で
まとめたガイド集。

各ガイドは「公式が何を推奨するか」→「本リポジトリのどのコードがどう実演するか(ファイルパス + 抜粋)」
→「どうテスト/実行するか」の順で読める。

## ガイド一覧

| ガイド | 適用した原則 | 公式ソース | 実演コード |
|--------|------------|-----------|-----------|
| [tool-design.md](./tool-design.md) | ツール設計: namespacing / トークン効率(pagination・filter・truncation)/ `response_format`(concise・detailed) | Anthropic "Writing tools for agents" | `patterns/frameworks/pydantic-ai/src/patterns_pydantic_ai/tool_design.py` |
| [context-engineering.md](./context-engineering.md) | コンテキスト工学: structured note-taking / compaction /「最小の高信号トークン集合」 | Anthropic "Effective context engineering" | `patterns/deep-research/src/patterns_deep_research/notes.py` |

## 設計方針(なぜデモとして追加したか)

本リポジトリの 6 パターン契約は Spec 006-2a に対して**凍結**され、3 フレームワーク lane 間の
ドリフトテスト・カバレッジゲート(`fail_under=98`)・pyright strict で守られている。改善提案を
凍結済みの契約へ直接ねじ込むのではなく、既存の**拡張シーム**に接続する形で「実行可能・テスト付き」
のデモとして追加した:

- ツール設計デモは、autonomous-agent ループの `allowed_tools: Sequence[Tool]`(最小権限の注入シーム)
  に差し込める `Tool` Protocol 準拠ツールとして実装。
- コンテキスト工学デモは、sub-researcher の reflect ループが使う `_results_digest` と
  **同一シグネチャ**の `compact_digest` を提供し、1 行差し替えで接続できる。

凍結済み契約・他 lane・ドリフト README には手を入れていない。

## 関連

- 検証レポート: [`../specs/best-practices-review/verification.md`](../specs/best-practices-review/verification.md)
- 改善提案(優先度付き): [`../specs/best-practices-review/improvement-plan.md`](../specs/best-practices-review/improvement-plan.md)
