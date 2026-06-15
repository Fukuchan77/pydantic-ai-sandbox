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

### P1 — per-PR を軽量・決定的に（Blocking）
- per-PR は `patterns-ci`（各レーンのオフライン）+ contracts + security を必須に維持。
- `patterns-integration-ollama` は per-PR トリガから外す（または non-blocking 表示に）。

### P2 — 実機統合を nightly マトリクスへ（Non-blocking on PR）
- 既存 `cron`（`47 4 * * 1`）を活用し、**1 レーン 1 ジョブの matrix** に分割。
  - 各ジョブに余裕ある `timeout-minutes`（例 60–90）と専用 Ollama daemon。
  - 並列実行で総 wall-clock を短縮、失敗レーンを局所化。
- llamaindex を matrix に復帰（`RUN_LLAMAINDEX_INTEGRATION=1`）。quarantine 解除はこの
  ジョブ分離が前提。

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

- [ ] per-PR は実機 LLM 非依存で 10 分以内に緑（決定的）。
- [ ] nightly でレーン別に実機統合が緑（llamaindex 含む 3 レーン）。
- [ ] collect 0 / 全 skip / import error が「成功」にならない（P3 ガードで赤）。
- [ ] `uv lock --check` が全レーンで緑、pre-release 混入なし。
- [ ] `mise` 取得起因の flaky 失敗が再発しない。

## Out of Scope / Open Questions

- フロントエンド（SSE EventSource クライアント）や WebSocket は対象外（各 spec の Out of Scope）。
- nightly のモデル選定（granite4.1:8b 継続か軽量化か）は容量計測後に決定。
- quarantine 解除のタイミング（P2 実装完了後）。

## Status

- 本計画は `/sdd`-style の入力ドキュメントであり、実装（ワークフロー再設計）は未着手。
- 現状の暫定措置は `retrospective.md` の Disposition を参照。
