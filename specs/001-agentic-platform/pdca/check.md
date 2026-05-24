# PDCA — Check Phase: 001-agentic-platform

- 生成日時: 2026-05-24
- 入力: `pdca/do.md` (1090 行 / 95 KB)、`spec.md`、`plan.md`、`tasks.md`、`spec.json`
- 評価対象: T1〜T12 全 12 タスク群 (約 32 サブタスク) のうち、実装着手済み = 全件、`tasks.md` チェックボックスは全て `[x]`。

> 本ドキュメントは事後生成。Plan/Do/Check の三点比較は do.md 内に逐次記録された期待値・実測値・差分を主たる証拠とする。

---

## 1. 期待値 vs 実測値 サマリ

| 観点 | Plan/Spec の期待値 | Do の実測値 | 判定 |
|---|---|---|---|
| **タスク完了率** | T1〜T12 全完了 | チェックボックス全 `[x]`、`/sdd-validate-impl` の指摘 3 件は Amendment で全件解消 | ✅ |
| **品質ゲート 4 種** (Req 7.1〜7.4) | ruff check / ruff format --check / pyright / pytest 全 PASS | `mise run check` 最終実行: lint PASS, format PASS (41 files), pyright **0 errors / 0 warnings / 0 info**, pytest **50 passed / 1 skipped (0.50s)**, 全体 2.67s | ✅ |
| **ハードコード Model ID 禁止** (Req 1.5) | ランタイム検査 + pre-commit pygrep の二重防御 | `tests/unit/test_no_hardcoded_model_ids.py` GREEN、`forbid-hardcoded-model-ids` フック PASS | ✅ |
| **ModelFactory 契約** (Req 2.x) | env 経由ディスパッチ / 4 プロバイダ / `_MVP_STUB_PROVIDERS` 未実装は `NotImplementedError` / I/O ゼロ | `factory.py` で実装、`httpx.{Client,AsyncClient}.send` パッチで I/O ゼロを確証 | ✅ |
| **FallbackModel** (Req 4.x) | `FALLBACK_ORDER` 解析 / 全 stub は fail-fast / 失敗で span 属性記録 | `_build_fallback` 実装、lifespan で eager dry-run、`gen_ai.operation.name == "invoke_agent"` で属性検証 | ✅ |
| **Logfire 計装** (Req 5.x) | trio (Pydantic AI / FastAPI / httpx) を fail-soft で計装 / 既定スクラブ + 追加パターン | `configure_observability` 実装、`bare except Exception` でフェイルソフト、`ScrubbingOptions(extra_patterns=["prompt","tool_input","tool_output"])` | ✅ |
| **/chat エンドポイント** (Req 3.x) | `ChatRequest` (min_length=1) → `Agent[None, ChatResponse].run` → 構造化 `ChatResponse` / 422 / 5xx | `api/routes/chat.py` 実装、TestModel オーバーライド + バリデーションエラー 4 ケース全 GREEN | ✅ |
| **/healthz** (Req 1.3) | `{"status":"ok","provider":...}` を 200 で返す | `api/routes/health.py` 実装、`LLM_PROVIDER` parametrize で 3 ケース GREEN | ✅ |
| **Ollama 実機 E2E** (Req 6.2) | `RUN_INTEGRATION_OLLAMA=1` ゲート / 実 daemon 利用 | `tests/integration/test_ollama_chat_e2e.py`、デフォルトレーンで skipped、手動実行で **1 passed in 18.93s** (granite4.1:8b 実機) | ✅ |
| **CI / セキュリティ** (Req 7〜9) | `ci.yml` / `security.yml` / `integration-ollama.yml` / `dependabot.yml` / `.gitleaks.toml` | 全 5 アーティファクト投入。paths-filter + actions/cache + concurrency + cron `:17`/`:37` 設定 | ✅ |
| **テスト数推移** | 単調増加 | 0 (T1) → 2 → 11 → 19 → 24 → 33 → 41 → 47 → 50 → 50 + 1skipped (T11) → 50 + 1skipped (T12) | ✅ |
| **TDD 規律** (Constitution I) | 全テストは Red → Green → Refactor の順序を踏む | do.md に各タスクの RED 観測ログあり (T2 では `_red_demo.py` の意図的ハードコード注入で失敗確認) | ✅ |
| **Constitution V** (品質ゲート不弱化) | `pyproject.toml` の lint/typecheck 設定を弱体化しない | `pyright` strict, ruff `S/C90/D/N/T20` を維持。`# noqa` 誤用 3 件は撤回し設定変更ではなくコード/コメントで対処 | ✅ |
| **カバレッジしきい値** (Req 7.7) | 当初は `fail_under = 0` (基準値)、Req 完了毎 +5pt | 現状 `fail_under = 0`、ratchet 未実施 | ⚠️ Act で扱う |

---

## 2. 重要な逸脱と是正ログ (Amendment 連動)

### 2.1 Amendment `2026-05-24T19:10:00Z` — bandit 非導入への一本化
- **検出**: 実装中に「ruff `S` (flake8-bandit 移植) で bandit のチェックは実質網羅される (S309/S322/S325/S320/S410 は Py2 / lxml 専用で Py3.14 strict には無関係)」と判明。
- **是正**: `spec.md` Q3 / Req 8.3 / Req 9.2、`plan.md` File Structure Plan、`research.md` security.yml、`tasks.md` T1.1 / T2.2 / T12.2、`pyproject.toml` dev デプから `bandit` を削除。spec.json に Amendment 追記。
- **判定**: Constitution V「症状ではなく原因に対処」に整合。

### 2.2 Amendment `2026-05-24T19:30:00Z` — 末端整合 (mise.toml / README.md)
- **検出**: `/sdd-validate-impl` Task 1 が MEDIUM 2 件 (両ファイルに bandit 表記残存) を検出。
- **是正**: 両ファイル該当行を `pytest / pip-audit; bandit ≡ ruff S` に書き換え。Amendment の `affected_artifacts` に両ファイルを追記。

### 2.3 Amendment `2026-05-24T20:15:00Z` — T10.2 boundary 整合
- **検出**: `/sdd-validate-impl` Task 10 が WARNING (boundary out-of-bounds) を検出。T10.2 実装で T9.3 の `tests/conftest.py::app_with_overrides` から `app.include_router(chat_router)` を撤去したが、T10.2 の `_Boundary:_` 宣言に `tests/conftest.py` が無かった。
- **是正**: `tasks.md` T10.2 `_Boundary:_` に `tests/conftest.py` を追加し、carry-over を 1 行で明文化。

### 2.4 タスク内逸脱 (正式 Amendment 化前提なし)

- **T5.4 mixed-stub silent filter**: `FALLBACK_ORDER=ollama,watsonx` のような混在設定で stub を黙って除外する仕様を採用。`tasks.md` の最小要件は all-stub の `RuntimeError` のみだが、stub の `NotImplementedError` を `/chat` 時刻に漏出させない / 運用者の相対順を尊重するという意図でこの最小逸脱を選択。do.md とインラインコメントに記録、Act フェーズで再評価対象に登録。
- **T7+T8 cross-task dependency**: T7.2 `_Depends:_ 8.2` を見落としやすい構造。AskUserQuestion で確認のうえ、両タスクを同一 `/sdd-impl` 起動内で連続実行して解消。
- **T11 probe URL bug**: Ollama の native (`/api/*`) と OpenAI-compat (`/v1/*`) 二系統 API を取り違え、最初の probe 実装が 404。`/v1/models` への切替と `.env.example` の正規 URL ピン留めで解消。

---

## 3. リソース消費・効率指標

| 指標 | 値 | コメント |
|---|---|---|
| `mise run check` 全体時間 | 2.67s | Pyright 含む 4 ゲートで 3 秒未満。CI 実行レイテンシ余裕あり。 |
| `pytest` 単独 | 0.50s (50 passed + 1 skipped) | 全テスト I/O ゼロ (Req 10.2)。 |
| Ollama E2E 実機 | 18.93s (1 passed) | granite4.1:8b 実機。`RUN_INTEGRATION_OLLAMA=1` ゲート。 |
| do.md 記録量 | 1090 行 / 95 KB | 各タスクで Plan/Expected/Observed/Deviation を逐次記録、Reflect 入力として十分。 |
| Amendment 件数 | 3 件 | いずれも `/sdd-validate-impl` 起源、設計文書側で `affected_artifacts` を追跡済み。 |
| Pivot / Rollback | 0 件 | スコープ・アーキテクチャ変更なし。 |

---

## 4. 品質メトリクス詳細

- **Pyright (strict, Py3.14)**: 0 errors / 0 warnings / 0 information。Pyright が `_build_*` クロスモジュール参照を `reportPrivateUsage` で警告した局所で `__all__` + 共有理由コメント付き `# pyright: ignore[reportPrivateUsage]` で対処。Constitution V 維持。
- **Ruff lint**: `S` (security), `C90` (≤10 complexity), `N` (naming), `D` (Google docstrings), `TCH` (type-only imports), `T20` (no-print) を含む全選択ルール PASS。
- **Ruff format**: 41 ファイル既整形。
- **pre-commit (default stage)**: 全フック PASS (ruff lint / ruff format --check / pyright / forbid-hardcoded-model-ids / detect-secrets)。
- **pre-commit (manual stage)**: pytest / pip-audit / gitleaks (CI が `--hook-stage manual` で実行)。
- **カバレッジ**: `[tool.coverage.report] fail_under = 0` 暫定基線。`ci.yml` で `--cov-report=xml` を生成し PR で diff coverage コメント (`py-cov-action/python-coverage-comment-action@v3`)。実数値は do.md には記録されていない。

---

## 5. Constitution 5 原則の達成度

| 原則 | 期待 | 実測 | 判定 |
|---|---|---|---|
| I. Test-First (NON-NEGOTIABLE) | RED → GREEN → REFACTOR を全タスクで遵守 | do.md に各タスクの RED 確認ログあり (T2 では意図的ハードコード注入で失敗確認、T7.4 のみ contract-probe につき初回 GREEN を許容理由付きで記録) | ✅ |
| II. Strict Type Safety | Pyright strict / `Any` は I/O 境界限定 | strict 維持 / `Any` 漏出なし / 型のみ import は `TYPE_CHECKING` ガード遵守 | ✅ |
| III. Library-First | Pydantic AI / FastAPI / Logfire の公式 API のみ使用 | 該当。`OpenAIChatModel + OllamaProvider`, `FallbackModel`, `logfire.instrument_*` で踏破 | ✅ |
| IV. SDD Pipeline | spec → plan → tasks → impl → validate → reflect | 全フェーズ通過、Amendment は `spec.json.amendments` で台帳化 | ✅ |
| V. Quality Gates | 4 ゲート全 PASS / 設定弱体化禁止 | 達成。Pyright `_build_*` 警告も設定変更ではなく `__all__` + 局所無視で対処 | ✅ |

---

## 6. ふりかえりに送る課題 (Act への入力)

1. **`# noqa: <CODE>` を `pyproject.toml::[tool.ruff.lint].select` 確認なしに書く** という同一ミスが T3/T4/T5 で 3 回発生。原因: 一般的な `# noqa` 知識を select 集合の存在を認識せずに転用。`RUF100` で都度補正できているがチェックリスト化したい。→ Act の Pattern 化候補。
2. **Pyright strict + アンダースコア命名** の摩擦 (T4/T5/T10): `__all__` 宣言 + 局所 `# pyright: ignore[reportPrivateUsage]` + 共有理由コメントの 3 点セットが定型化した。→ Act で Pattern 化。
3. **`uv sync` は editable install を行わない** (T3): 一度だけ `uv pip install -e .` 必要。→ `mise run setup` への組込み候補。
4. **Ollama 二系統 API の混同** (T11): native (`/api/*`) vs OpenAI-compat (`/v1/*`)。→ 運用ノートとして Steering 書き出し候補。
5. **T5.4 mixed-stub silent filter の正式判断** (Req 2.4 / Req 4.5 と境界): 現状は最小逸脱解釈。→ 次の `/sdd-validate-impl` で明示判定もしくはテスト硬化対象。
6. **カバレッジ ratchet 未実施**: `fail_under = 0` のまま。Plan R-6 が定めた +5pt step を起動するか、CI artifact 上の数値を取得して 1 段階目を確定させたい。
7. **CI integration-ollama レーンの初回実機検証**: 投入済みだが `paths-filter` トリガが do.md ログ範囲では未発火。最初の `src/pydantic_ai_sandbox/{llm,agents,schemas}/**` 触れる PR で観測予定。

---

## 7. 結論

- **総合判定**: **GREEN — production-ready for sandbox MVP scope**.
- 全 12 タスク群完了 / 全 4 品質ゲート PASS / 50 unit + 1 integration test / Constitution 5 原則準拠 / 3 Amendment は全件解消。
- `/sdd-reflect` で形式知化すべき Pattern (成功) と Mistake (再発リスク) が複数浮上。次フェーズ (Act) でそれらを `.sdd/patterns/` および Serena memory に書き出す。
