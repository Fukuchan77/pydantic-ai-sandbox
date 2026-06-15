# CI Strategy Improvement Plan

`retrospective.md` の所見を受け、ゲート付き実機 LLM テストを含む CI を再設計するための
計画。目的は (a) per-PR シグナルを高速・決定的・信頼できるものにし、(b) 実機統合の
カバレッジを「空振り緑」なく維持し、(c) 容量・コストを予算内に収めること。

## Problem Statement

per-PR の単一ジョブで「3 レーン × 6 パターンの実機 8B 推論を逐次・45 分以内」は容量的に
破綻している（beeai だけで ~20 分）。実機 LLM テストは本質的に**非決定的・低速・環境依存**
であり、ブロッキングな per-PR ゲートに不向き。

## Principles

1. **Blocking ＝ 決定的なものだけ**: per-PR で必須にするのはオフライン（unit / contracts /
   hermetic / lint / pyright / coverage）。実機 LLM はブロッキングにしない。
2. **No false green**: skip 全件 / collect 0 / import error を「成功」と区別する。
3. **Isolation & parallelism**: 実機統合はレーン単位で分離し、失敗を局所化する。
4. **Reproducibility**: ツール・モデル・lock を固定し、flaky を構造的に排除する。

## Proposed Changes

### P1 — per-PR を軽量・決定的に（Blocking）✅ 実装済み（2026-06-15）
- per-PR は `patterns-ci`（各レーンのオフライン）+ contracts + security を必須に維持。
- `patterns-integration-ollama` から `pull_request:` トリガを削除（per-PR 非ブロッキング）。
  実機統合は PR のマージ判定に影響しない。

### P2 — 実機統合を nightly マトリクスへ（Non-blocking on PR）✅ 実装済み（2026-06-15）
- `cron` を nightly（`47 4 * * *`）に変更し、**1 レーン 1 ジョブの matrix** に分割
  （beeai / pydantic-ai / llamaindex / rag / sse の 5 レーン）。
  - 各ジョブに余裕ある `timeout-minutes`（60、llamaindex は 90）と専用 Ollama daemon。
  - `fail-fast: false` + レーン別 concurrency で失敗を局所化、並列で wall-clock 短縮。
  - 各レーンは `patterns:test:integration:<lane>` mise タスク経由で実行（gate は mise を通す）。
- llamaindex を matrix に復帰：専用タスクが `RUN_LLAMAINDEX_INTEGRATION=1` を opt-in。
  per-PR では quarantine のまま（二重ゲート）、nightly のみ実走。ジョブ分離が前提という
  quarantine 注記どおりの解除。

### P3 — 空振り検知（anti–false-green ガード）
- 統合スイートで「最低 collect 数」を検証（例: 期待 6 件 / レーン、0 件や全 skip を失敗扱い）。
- `--strict-markers` 採用、import error を成功にしない実行形態（lane ごとに独立 pytest）。

### P4 — lock 衛生
- CI に `uv lock --check`（全レーン）を追加し、pre-release 混入・lock ドリフトを検知。
- pre-release を既定で禁止（必要時のみ明示許可）。統合 extra を含めて lock を検証。

### P5 — 再現性・コスト
- `mise` バージョンと `jdx/mise-action` を pin（404 flaky の解消）。
- nightly の総時間圧縮: 軽量/量子化モデル、または `num_predict` をさらに抑制。
- 多層タイムアウト（Ollama request / litellm / Workflow / job）の値を 1 箇所で俯瞰できる
  ように定数化・ドキュメント化。

## Acceptance Criteria

- [x] per-PR は実機 LLM 非依存（`patterns-integration-ollama` の PR トリガ削除）— P1。
- [x] nightly でレーン別に実機統合（llamaindex 含む 5 レーンの matrix）— P2。
      ※ 各レーンの「緑」確認は最初の nightly／post-merge 実行で検証。
- [ ] collect 0 / 全 skip / import error が「成功」にならない（P3 ガードで赤）— 未着手。
- [ ] `uv lock --check` が全レーンで緑、pre-release 混入なし（P4）— 未着手。
- [ ] `mise` 取得起因の flaky 失敗が再発しない（P5）— 未着手。

## Out of Scope / Open Questions

- フロントエンド（SSE EventSource クライアント）や WebSocket は対象外（各 spec の Out of Scope）。
- nightly のモデル選定（granite4.1:8b 継続か軽量化か）は容量計測後に決定。
- quarantine 解除のタイミング（P2 実装完了後）。

## Status

- **P1 + P2 実装済み（2026-06-15）**: `patterns-integration-ollama.yml` を nightly per-lane
  matrix に再設計し per-PR トリガを削除。レーン別 mise タスクを `mise.toml` に追加。
- P3 / P4 / P5 は未着手（次イテレーション）。
- 暫定措置の経緯は `retrospective.md` の Disposition を参照。
