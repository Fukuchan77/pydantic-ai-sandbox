# Retrospective — Cross-Platform Patterns (005–008) & Gated Live CI

実装イテレーション 005〜008（クロスプラットフォーム・パターン／RAG／SSE）と、その
ゲート付き実機 Ollama 統合 CI を対象とした振り返り。`patterns-integration-ollama`
ジョブが繰り返し失敗・最終的にジョブ予算超過で cancel された事象を起点に、原因を層
ごとに整理し、CI 戦略見直し（→ `improvement-plan.md`）の入力とする。

## Scope

- 対象: `patterns/frameworks/{pydantic-ai,llamaindex,beeai}`, `patterns/{contracts,rag,sse}`
- 対象 CI: `.github/workflows/patterns-integration-ollama.yml`（single job / 3 lanes 逐次 /
  `granite4.1:8b` on `ubuntu-latest` / `timeout-minutes: 45`）
- 期間: 2026-06-14 の PR #5 / #6 / #7（マージ済）および PR #8（修正中）

## What Went Well

- **オフライン層が一貫して堅牢**: unit / contracts / hermetic / lint / pyright / カバレッジ
  ゲート（`fail_under=98`）は全コミットで安定通過。コード本体の設計（決定的処理、loud-fail、
  DI シーム、判別共用体、observability）に品質上の指摘なし。
- **層別の原因切り分けが機能**: 失敗のたびにログから単一根本原因へ到達できた
  （mise 404 → litellm timeout → anyio → httpx → OOM → workflow timeout → job 予算）。
- **修正の局所性**: beeai はテストヘルパーのみ、llamaindex は dep 宣言とテスト設定のみで
  本番ソースを変えずに対処できた（`timeout` 等の knob が既に公開されていた）。

## What Went Wrong — Root Causes

| # | 事象 | 真因 | 種別 |
|---|------|------|------|
| 1 | `mise` 取得 404 で複数ジョブ失敗 | `jdx/mise-action` の配布アセット一時 404（バージョン非固定） | インフラ/flaky |
| 2 | beeai parallelization が 600s timeout | CPU で 8B を並行 2 本 → litellm 既定 600s 超過 | 容量 |
| 3 | llamaindex 実機が import で即死 | lock に `anyio` 欠落・`httpx 1.0.dev3`（開発版 pre-release）混入 | lock 不整合（既存） |
| 4 | llamaindex OOM（20GB KV cache） | `context_window=-1`（モデル最大コンテキスト要求） | 設定 |
| 5 | llamaindex Workflow 120s timeout | LlamaIndex Workflows 既定タイムアウト（request_timeout とは別層） | 容量 |
| 6 | ジョブが ~45 分で cancel | 3 レーン逐次 × 8B/CPU が `timeout-minutes:45` 超過 | CI 設計 |

## Key Finding — “Hidden Never-Green”

**llamaindex の実機統合レーンは、これまで一度も end-to-end で成功したことがなかった。**
`anyio` 欠落による import 失敗（と OOM）で常に前段で停止しており、その失敗は統合ジョブ
末尾ログ（最後のレーン）に隠れていたため、005/006/007 のマージ時に見落とされた。

- 影響: 「ゲート付き統合テストが緑」という表示が、**実際には一度も実走していない状態**を
  覆い隠していた。
- 教訓: skip/collect-0/import-error を「緑」と区別できない CI は、カバレッジの錯覚を生む。
  → 改善計画の「空振り検知（anti–false-green）」へ反映。

## Secondary Findings

- **lock 衛生**: llamaindex の `uv.lock` に開発版 `httpx 1.0.dev3` が固定され、`anyio` が
  欠落していた。統合 extra を含むパスで lock が検証されていなかった証左。
- **容量設計の前提崩れ**: 「6×3=18 ライブ生成を 45 分で逐次」は、全レーンが実走する前提で
  成り立っていなかった。実走可能になった瞬間に予算を超過した（#6）。
- **多層タイムアウト**: Ollama `request_timeout`、litellm `timeout`、LlamaIndex Workflow
  timeout、ジョブ `timeout-minutes` が独立に存在し、最内層だけ直しても次の層で落ちた。

## Disposition（現時点の措置）

- beeai タイムアウト修正（`timeout=1200s` + `max_tokens=512`）— 恒久採用。
- llamaindex 依存修復（`anyio` 追加 / `httpx>=0.27,<1` → 0.28.1 再 lock）— 恒久採用。
- llamaindex `context_window=8192` / `num_predict=512` / Workflow `timeout` — 恒久採用
  （レーンを実走可能にする修正）。
- llamaindex 実機レーンは `RUN_LLAMAINDEX_INTEGRATION=1` で **quarantine**（コードは維持、
  per-PR CI からは除外）— 暫定。恒久方針は `improvement-plan.md` で決定する。

### 追記（2026-06-15）— 恒久対応を実装

per-PR で quarantine 後も、beeai + pydantic-ai の 2 レーンだけで遅いランナーでは
`timeout-minutes:45` に到達した（実測）。これは事象 #6（CI 設計）が単発でなく構造的で
あることの裏付けであり、`improvement-plan.md` の **P1 + P2 を実装**した：

- **P1**: `patterns-integration-ollama.yml` から `pull_request:` トリガを削除。per-PR の
  ブロッキング・シグナルは `patterns-ci.yml`（オフライン）のみに限定。
- **P2**: 実機統合を **1 レーン 1 ジョブの nightly マトリクス**へ再設計（専用 daemon /
  レーン別 `timeout-minutes` / `fail-fast:false` / レーン別 concurrency）。llamaindex は
  専用 mise タスク（`patterns:test:integration:llamaindex`）で `RUN_LLAMAINDEX_INTEGRATION=1`
  を opt-in し、マトリクスへ復帰（quarantine はジョブ分離が前提という注記どおり）。

P3（空振り検知）/ P4（lock 衛生）/ P5（再現性）は本 PR の範囲外。次イテレーションで対応。
