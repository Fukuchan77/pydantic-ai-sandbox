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

### P3 — 空振り検知（anti–false-green ガード）✅ 実装済み（2026-06-15）
- 共有 pytest プラグイン `patterns_contracts.pytest_live_guard` を追加。各レーンは
  `tests/integration/conftest.py` の 1 行 re-export で配線（ロジックは 1 箇所）。
- 各レーン mise タスクが `EXPECT_LIVE_TESTS=<n>`（6/6/6/1/1）を宣言。実行テスト数が
  これ未満（collect 0 / 全 skip / 想定外 skip）なら、pytest が緑でもセッションを赤にする。
- import/collection error は元々 pytest が exit 2 で赤 → ガードは「全 skip / collect 0」の
  穴を塞ぐ。`EXPECT_LIVE_TESTS` 未設定時（オフライン/集約/quarantine）は不活性で誤発火しない。
- 検証: all-skip+EXPECT → 赤、no-EXPECT → 緑、実行あり+EXPECT → 緑 を実機相当で確認。

### P4 — lock 衛生 ✅ 実装済み（2026-06-15・beta 採用を前提に再設計）

**前提（重要）**: 一部レーンは pre-release を**意図的に**採用している。一律禁止は不可。
- `pydantic-ai`: `pydantic-ai-slim[openai]>=2.0.0b6`（v2 beta）→ `[tool.uv] prerelease = "allow"`。
- `sse`: dev closure が `pydantic-graph` の pre-release に依存 → 同じく `prerelease = "allow"`。
- `beeai`: `beeai-framework==0.1.39`（0.1.81 等の 0.x も同様）は **PEP440 上は通常リリース** → 対象外。

**実装**:
- 全 4 ジョブ（lane matrix / contracts / rag / sse）に `uv lock --check` を追加（fast-fail の
  ドリフトゲート）。既存の `uv sync --all-groups --locked` は install 時のバックストップ。
  これが root cause #3（pyproject 制約外の dep が lock に入る＝`httpx 1.0.dev3`）の再発を阻止する
  実効的な仕組み。全 6 lock で `uv lock --check` 緑を確認。
- 「許可／不許可」は**レーン単位の `[tool.uv] prerelease`** を単一の宣言的真実源とする。

**pre-release allowlist ガードは見送り（重要な実測）**:
- 実装前に全 lock を走査したところ、**6/6 のロックに正当・稼働中の pre-release が広範に存在**：
  `pydantic==2.14.0a1`（全レーン）、`opentelemetry-*==0.63b1`、`litellm==1.89.0rc2`、
  `numpy==2.5.0rc1`、`sqlalchemy==2.1.0b2` など。これらは現状 green（sync/test/pip-audit 通過）。
- よって「pre-release を allowlist で制限」は**この技術スタックでは非現実的**（正当な pre-release で
  CI が赤になり、bump のたびに allowlist 保守が必要）。content ベースの ban/allowlist は採用しない。
- root cause #3 への防御は **pyproject 制約 + `uv lock --check`（lock が制約を満たすことを保証）**
  と **P3 ガード（import error/never-green を赤に）** の組み合わせで担保する。

### P5 — 再現性・コスト（実機ノブの定数集約を実装済み 2026-06-15 / 残りは未着手）
- ✅ 多層の実機ノブ（Ollama `context_window`/`num_ctx`・generation cap・request timeout・
  LlamaIndex Workflow timeout）を `patterns_contracts.live_ollama` に**単一の定数群**として集約し、
  各レーンが import して使用。OOM の原因（`context_window` 未指定で num_ctx=モデル最大）を
  docstring に明記し、OpenAI 互換経路（pydantic-ai/sse）が context 上限を要しない理由も併記。
  → rag が llamaindex と同型 OOM を踏み直した再発を構造的に防止。
- ✅ Ollama モデルキャッシュを**レーン別 save キー**（`...-${{ matrix.lane }}`）＋共有
  `restore-keys: ollama-model-` に変更。同一キーへの同時保存レース（cache post-step が落ち、
  テスト緑のジョブを赤にする flake）を排除。共有 prefix で復元は引き続き全レーン共有。
- ⬜ `mise` / `jdx/mise-action` の pin（404 flaky 解消）。
- ⬜ nightly の総時間圧縮: 軽量/量子化モデル、または `num_predict` のさらなる抑制。

## Acceptance Criteria

- [x] per-PR は実機 LLM 非依存（`patterns-integration-ollama` の PR トリガ削除）— P1。
- [x] nightly でレーン別に実機統合（llamaindex 含む 5 レーンの matrix）— P2。
      ※ 各レーンの「緑」確認は最初の nightly／post-merge 実行で検証。
- [x] collect 0 / 全 skip / import error が「成功」にならない（P3 ガードで赤）。
- [x] 実機ノブ（context_window/num_predict/timeout）を 1 箇所に定数集約（P5 一部）。
- [x] `uv lock --check` を全レーン CI に追加（lock ドリフト検知）— P4。
      ※ pre-release の content ban/allowlist は意図的に不採用（正当な pre-release が広範に存在）。
- [ ] `mise` 取得起因の flaky 失敗が再発しない（P5 残）— 未着手。

## Out of Scope / Open Questions

- フロントエンド（SSE EventSource クライアント）や WebSocket は対象外（各 spec の Out of Scope）。
- nightly のモデル選定（granite4.1:8b 継続か軽量化か）は容量計測後に決定。
- quarantine 解除のタイミング（P2 実装完了後）。

## Status

- **P1 + P2 実装済み（2026-06-15）**: `patterns-integration-ollama.yml` を nightly per-lane
  matrix に再設計し per-PR トリガを削除。レーン別 mise タスクを `mise.toml` に追加。
  post-merge マトリクスで 5/5 レーン green を確認（rag OOM 修正含む）。
- **P3 実装済み（2026-06-15）**: anti-false-green ガード（`patterns_contracts.pytest_live_guard`
  + 各レーン conftest + `EXPECT_LIVE_TESTS`）。
- **P4 実装済み（2026-06-15）**: `patterns-ci.yml` の全 4 ジョブに `uv lock --check`（ドリフト
  ゲート）を追加。pre-release allowlist は実測（6/6 lock に正当な pre-release）を踏まえ不採用。
- **P5 一部実装済み（2026-06-15）**: 実機ノブを `patterns_contracts.live_ollama` に定数集約。
  残（mise pin / nightly 時間圧縮）は次イテレーション。
- 暫定措置の経緯は `retrospective.md` の Disposition を参照。
