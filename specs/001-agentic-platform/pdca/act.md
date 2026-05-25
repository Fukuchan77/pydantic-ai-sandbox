# PDCA — Act Phase: 001-agentic-platform

- 生成日時: 2026-05-24
- 入力: `pdca/check.md` (本セッションで生成) / `pdca/do.md` / `spec.json` Amendment 台帳 / 直近の `mise run check` 結果
- 判定: **SUCCESS** — sandbox MVP スコープを完全達成。再利用可能な成功パターンを抽出し、再発リスクの高いミスを Mistake として明文化する。

---

## 1. Check 要約 (再掲・短縮)

| 区分 | 値 |
|---|---|
| タスク完了率 | T1〜T12 全完了 (`tasks.md` 全 `[x]`) |
| 品質ゲート | 4/4 全 PASS (`mise run check` 2.67s, pyright 0/0/0) |
| テスト | 50 passed + 1 skipped (unit) / 1 passed 18.93s (Ollama 実機) |
| Amendment | 3 件 (全件解消) |
| Constitution | I〜V 全準拠 |
| 重大逸脱 | T5.4 mixed-stub silent filter (再評価対象) |

総合判定: GREEN。本セッションでは "実装が動いた" 以上の **再利用知** に焦点を移す。

---

## 2. 成功パターン (Pattern 化対象)

### Pattern A. Env-driven `ModelFactory` × `_MVP_STUB_PROVIDERS` × `Literal` 三点固定

- **何が良かったか**: 「未実装プロバイダ」の集合がコード・型・テストの 3 箇所で一致。`Literal["ollama","watsonx","anthropic","bedrock","fallback"]` (config) ↔ `_MVP_STUB_PROVIDERS = frozenset({"watsonx","anthropic","bedrock"})` (factory) ↔ `test_factory_dispatch.py` パラメトリック (テスト) が "lockstep" している。新プロバイダ追加時の影響範囲が機械的にトレース可能。
- **副次効果**: lifespan の eager dry-run (T10) で all-stub 設定が即座に発火 (Req 4.5)、`/chat` 時刻まで遅延しない。
- **Pattern ファイル**: `.sdd/patterns/env-driven-modelfactory.md`

### Pattern B. `lru_cache(maxsize=1)` で `Depends(get_chat_agent)` × `agent.override` 互換

- **何が良かったか**: `get_chat_agent` をリクエスト毎に実行する素朴な factory にすると ContextVar override (Pydantic AI の `agent.override`) が伝播しない。`lru_cache(maxsize=1)` で同一インスタンスを Depends に流すことで `TestModel` 注入が成立。
- **再利用先**: 今後 `/vision/describe` 等を追加するときも同様パターン。
- **Pattern ファイル**: `.sdd/patterns/agent-lru-cache-override.md`

### Pattern C. 二層ハードコード防御 (lint + ランタイムスナップショット)

- **何が良かったか**: pre-commit pygrep `forbid-hardcoded-model-ids` (構文層) + `tests/unit/test_no_hardcoded_model_ids.py` (ランタイム層) が **同じ語彙集合** を共有。どちらかをすり抜けてももう片方が捕捉する。
- **将来化**: Bedrock の Cross-Region Inference Profile ID (`us.` / `eu.` / `jp.` / `global.`) も同じ語彙に追加するだけで防御が伸びる。
- **Pattern ファイル**: `.sdd/patterns/two-layer-id-guard.md` (本セッションでは Pattern A のみ別ファイルにし、B/C は次回 Reflect で詳細化)

### Pattern D. `with TestClient(app):` を選択する基準

- **基準**: lifespan を *発火させたい* ときだけ `with` 構文。発火させたくない単体テストは `TestClient(app)` (no-with)。FastAPI の lifespan は `with` 内でのみ実行されるという挙動を、構造的にテスト意図と結び付ける。
- **Pattern ファイル**: 共通カタログに後追いで追加 (Pattern A 以外は本セッション本数を絞る)

### Pattern E. 1090 行の `pdca/do.md` を逐次蓄積する習慣

- **何が良かったか**: 各タスクで `Plan / Expected / Observed / Deviation` を書き続けたため、Reflect フェーズの subagent が 1 回のスイープで成功 / 失敗 / Pivot を網羅抽出できた。生成された Check ドキュメントの精度がここに依存。
- **教訓**: do.md を「Implementation log」ではなく「Reflect への入力 dataset」と再定義する。

---

## 3. Mistake / アンチパターン (再発防止対象)

### Mistake-1. `# noqa: <CODE>` を select 集合確認なしに書く (T3 / T4 / T5 で計 3 回)

- **何が起きたか**: `# noqa: ARG001`、`# noqa: ANN001`、`# noqa: BLE001` を書いたが、いずれも `pyproject.toml::[tool.ruff.lint].select` に当該ルールが入っていないため `RUF100 (Unused noqa)` が発火。
- **根本原因**: 「`# noqa` は ruff 全ルールに対して書ける」という一般知識を、`select` 集合という当プロジェクト固有の制約を確認せずに当てはめた。
- **影響**: 各回 1 回の RED → ノイズコミット 1 個分。設定弱体化リスクは Constitution V で抑止されたが、サイクル時間ロス。
- **再発防止**:
  1. `# noqa: <CODE>` を書く前に必ず `rg "<CODE>" pyproject.toml` で select 包含を確認。
  2. 含まれていない場合は noqa ではなくコード/コメントで対処 (T7 の bare except へ multi-line コメント貼付が好例)。
  3. checklist として Mistake ファイル化 (下記 §5)。

### Mistake-2. T7.2 の cross-task `_Depends:_` 8.2 を見落とす

- **何が起きたか**: T7 (Logfire) を着手したら T8.2 (`create_app()`) が必要だった。
- **根本原因**: `_Depends:_` 表記の視認性低 + 実装者がタスク順序を線形と誤認。
- **再発防止**:
  - `/sdd-impl` 着手前の prelude に `_Depends:_` 走査を組み込む (skill 改訂候補)。
  - `tasks.md` に依存グラフ DAG を併記する案 (将来の sdd-tasks 改善)。

### Mistake-3. Ollama の native API と OpenAI-compat API を取り違える (T11)

- **何が起きたか**: probe URL を `/api/version` で書いたが OpenAI-compat surface (`/v1/*`) には存在せず 404。
- **根本原因**: Ollama が **同一 daemon で 2 つの surface を提供** していることが運用知として未記録。
- **再発防止**:
  - 運用ノート (`.sdd/steering/` 化候補) に「Ollama 二系統 API」を記載。
  - probe URL は `/v1/models` (OpenAI-compat の正規ヘルスエンドポイント) を使う、を Pattern A に追記。

---

## 4. 学習を Rule に変換するマッピング

| 学び (Do/Check で観測) | 落とし所 (どこに記録するか) | 形式 |
|---|---|---|
| `# noqa` の select 確認 | `.sdd/mistakes/001-noqa-without-select-check-2026-05-24.md` | Mistake |
| Pyright strict + `_build_*` の `__all__` + 局所 ignore | Pattern A 文中に併記 | Pattern (副節) |
| `lru_cache(maxsize=1)` で Depends + override | `.sdd/patterns/agent-lru-cache-override.md` (将来) | Pattern |
| Ollama 二系統 API surface | `.sdd/steering/ollama-operations.md` (将来 Steering) | Steering |
| FallbackModel eager dry-run | Pattern A 中に併記 | Pattern (副節) |
| `with TestClient(app):` ↔ lifespan 発火 | テスト規約として `tests/conftest.py` docstring 内へ | Convention |
| `uv sync` は editable install しない | `mise run setup` への組込み | Tooling |
| カバレッジ ratchet 未起動 | 次回 `/sdd-tasks` で R-6 を Action 化 | Process |

本セッションでは **Pattern A** と **Mistake-1** を実ファイル化し、残りは index に列挙して次回 Reflect の宿題に送る。

---

## 5. プロセス改善提案

### 5.1 `/sdd-impl` skill の prelude に依存走査を追加
- 着手タスクの `_Depends:_` 走査と未完了依存の警告を Red ステップ前にエコーする。Mistake-2 の再発を構造的に抑止。

### 5.2 `mise run setup` の追加
- 内容案:
  ```toml
  [tasks.setup]
  run = ["uv sync", "uv pip install -e .", "uv run pre-commit install"]
  description = "First-time bootstrap (editable install + git hooks)"
  ```
- これで Mistake-2 の同類 (環境セットアップ knowledge の暗黙化) を緩和。

### 5.3 PDCA テンプレートの整備
- 現状 `~/.sdd/settings/templates/pdca/{check,act}-template.md` が未配置。本セッションの check.md / act.md を雛型として `~/.sdd/settings/templates/pdca/` に逆輸入する候補。

### 5.4 カバレッジ ratchet の起動
- 次の `/sdd-tasks` イテレーションで Plan R-6 (`fail_under` を Req 完了毎に +5pt) を実 Action 化する。CI artifact から実数値を 1 度取得し、最初の閾値を確定させる。

### 5.5 T5.4 mixed-stub silent filter の正式判断
- 次回 `/sdd-validate-impl` で「黙って drop」/ 「明示 ValueError」/ 「警告ログのみ」の 3 案で判定確定。Req 2.4 と Req 4.5 の境界条件として明文化。

---

## 6. 生成アーティファクト

本 Reflect セッションで生成・更新するファイル:

| パス | 状態 |
|---|---|
| `specs/001-agentic-platform/pdca/check.md` | 新規生成 |
| `specs/001-agentic-platform/pdca/act.md` | 本ファイル (新規生成) |
| `.sdd/patterns/env-driven-modelfactory.md` | 新規生成 (Pattern A) |
| `.sdd/mistakes/001-noqa-without-select-check-2026-05-24.md` | 新規生成 (Mistake-1) |
| Serena memory `001-agentic-platform/pdca-act` | 新規 (本セッション学習サマリ) |

---

## 7. Next Actions

優先度順 (✅ = 同 Reflect セッション内で実施済み、Amendment 2026-05-24T22:30:00Z 参照):

1. ✅ **(High)** カバレッジ ratchet 起動 — 実測 98% に対し `fail_under = 93` (実測−5pt) を `pyproject.toml::[tool.coverage.report]` に設定。CI workflows/ci.yml が既に `pytest --cov` を実行する構成のため、PR 段階で閾値割れが検出される。
2. ✅ **(High)** `mise run setup` 改善 — `uv sync && uv pip install -e . && uv run pre-commit install` に拡張、editable install を初回 bootstrap で seat。
3. ✅ **(Med)** T5.4 mixed-stub silent-drop の正式仕様化 — ユーザ承認のもと「最小逸脱解釈」から「正式仕様」へ格上げ。tasks.md T5.4 Implementation Notes と spec.json amendments に明記。`test_build_fallback_skips_stub_members_when_real_members_remain` が契約として既存。
4. ✅ **(Low)** 残 Pattern (B/C/D) の `.sdd/patterns/` 化 — 同 Reflect セッションで `agent-lru-cache-override.md` / `two-layer-id-guard.md` / `with-testclient-lifespan.md` を生成。
5. ✅ **(Low)** PDCA テンプレートを `~/.sdd/settings/templates/pdca/` に逆輸入 — `check-template.md` / `act-template.md` を本セッションのフォーマットから抽出して配置。
6. **(Med)** CI integration-ollama レーンの初回実機検証 — 投入済み workflow のトリガを観測する作業。本リポジトリの最初の `src/pydantic_ai_sandbox/{llm,agents,schemas}/**` 触れる PR で paths-filter 発火を観測。検証手順は [`specs/001-agentic-platform/pdca/integration-ollama-verification.md`](integration-ollama-verification.md) に記載。
7. **(Med)** Spec `002-multi-provider` の起票準備 — watsonx (`LiteLLMProvider`)、Anthropic (`AnthropicModel`)、Bedrock (Cross-Region Inference Profile) を実装に昇格。`/sdd-init` 用入力ドラフトを [`specs/inputs/idea1-002-multi-provider.md`](../../inputs/idea1-002-multi-provider.md) に作成済み。`unit/test_factory_dispatch.py` の "NotImplementedError 期待" を成功 assert に反転させる流れを Plan に明示する想定。
8. **(Low)** Pydantic AI V2 GA リリース監視 — Req 6.5 によりバンプ PR が `unit/test_chat_agent_v2_surface.py` の失敗で自動的に migration トリガとなる設計が既に成立、追加対応不要。

---

## 8. 結論

`001-agentic-platform` は **MVP スコープを構成的に完了** した。"動く" を超えて "再利用できる" 段階に到達している。本 Reflect で形式知化した Pattern A と Mistake-1 を起点に、次イテレーション (`002-multi-provider` 想定) で実 LLM プロバイダを順次追加していく際の地ならしは整った。

---

## 9. Amendment 2026-05-24T(post-Reflect): adversarial-review HIGH+MEDIUM 全消化

`/code-reviewing` → `/adversarial-review` の二段レビューで抽出された HIGH 1 件 + MEDIUM 3 件を、ブランチ `fix/log-sensitive-payloads-scrubbing` 上に 2 コミットで完全消化した。LOW 5 件は spec `002-multi-provider` で構造が動く箇所と隣接するため意図的に未着手 (本 Amendment §9.4 参照)。

### 9.1 消化したファインディング

| Sev | 件名 | 出典 | コミット | 検出経路 |
|-----|------|------|---------|---------|
| HIGH | `LOG_SENSITIVE_PAYLOADS` が dead field — Req 5.4 SHALL 違反 | adversarial pass 1 | `bdeea39` | `grep` で field 参照箇所が config.py / .env.example / conftest 以外に無いことを確認 |
| MEDIUM | シークレット env を `str` で保持 — `repr(settings)` / `exc_info=True` で leak | adversarial pass 1 | `f5d3466` | `__repr__` semantics 解析 + stdlib logger が Logfire scrubbing に通らない経路の特定 |
| MEDIUM | `ChatRequest.message` 上限なし — body amplification | adversarial pass 1 | `f5d3466` | Starlette body-size cap が未配線である事実の確認 |
| MEDIUM | `assert members` が `python -O` で strip される | adversarial pass 2 | `f5d3466` | `pyproject.toml::ignore` に `S101` が居る事実 + `-O` semantics の組み合わせ |

### 9.2 適用した修正と TDD 観測

**`bdeea39` (HIGH)**:
- `logging_setup.py` に `settings.log_sensitive_payloads` 分岐を追加。default-deny は従来通り、opt-in は `scrubbing=False` (Logfire 公式 sentinel) + 第二の WARNING で audit-trail を残す
- 新規テスト `test_configure_disables_scrubbing_when_log_sensitive_payloads_true` を RED 観測してから着地
- 50 → 51 passed

**`f5d3466` (MEDIUM ×3)**:
- `config.py`: 4 シークレットフィールド (`ollama_api_key` / `watsonx_apikey` / `anthropic_api_key` / `logfire_token`) を `SecretStr | None` 化
- `logging_setup.py` / `llm/providers/ollama.py`: SDK 境界でのみ `.get_secret_value()` 展開
- `schemas/chat.py`: `_MESSAGE_MAX_LENGTH = 8192` 定数 + `Field(max_length=...)`
- `llm/fallback.py`: `assert members, ...` → `if not members: raise RuntimeError(...)`
- 新規テスト 4 件 (`test_build_fallback_raises_runtime_error_on_empty_members_post_validator_drift`, `exceeds-max-length` parametrise case, `test_secret_fields_redact_in_repr`, `test_secret_field_value_is_recoverable_via_get_secret_value`) を RED 観測してから着地
- 51 → 55 passed

### 9.3 副次的に観測された Pattern / Mistake

- **Pattern (再確認)**: T2.1 の hardcoded-model-ID guard は今回 schemas/chat.py の docstring 中の `granite4.1:8b` リテラルを実際に検出して fail させた。「Pattern: two-layer ID guard」が想定どおり機能している実観測。新 Pattern として記述する必要なし。
- **Mistake 候補**: `_INSTRUCTIONS` 系のドキュメンテーション中で本番モデル ID を例示文字列として書く誘惑がある。schemas/chat.py の `_MESSAGE_MAX_LENGTH` docstring を当初 `Matches granite4.1:8b's...` で書いて T2.1 が即座に止めた。`.sdd/mistakes/` への昇格は不要 (既存 mistake-1 と同系統で、防御層は機能している)。docstring 規約として「本番モデル ID リテラルは env 変数名経由で参照する」を **本 Amendment 内に明文化** することで足りる。

### 9.4 未消化 LOW (`002-multi-provider` 同時処理推奨)

| Sev | 件名 | 推奨タイミング |
|-----|------|---------------|
| LOW | factory dispatch の stub 各 branch を `return _build_<stub>()` 形式に統一 | 002 で stub 撤去と同時 (差分が同所に集約) |
| LOW | `FALLBACK_ORDER` parser 重複 (config.py / fallback.py) | 002 の Settings 拡張時に `Settings.fallback_members` cached property に集約 |
| LOW | `_INSTRUCTIONS` ↔ `ChatResponse` lockstep test | 002 の Vision/Tool 拡張で prompt 構造が動くタイミング |
| LOW | `_MANAGED_ENV_KEYS` を `Settings.model_fields` から派生 | 002 の env 拡張時に同時更新 |
| LOW | `_build_fallback` import 非対称 (eager / lazy) | 002 で `pydantic_ai_sandbox.llm` の re-export 整備時 |

判断根拠: いずれも 002 で隣接ファイルが動くため独立対応すると同一行近傍を二度触ることになる。MVP の `git blame` 解読性も損なわれる。

### 9.5 品質ゲート (本 Amendment 完了時点)

```
ruff check        ✅
ruff format       ✅
pyright (strict)  ✅ 0 errors
pytest            ✅ 55 passed / 1 skipped (integration lane gated)
```

50 → 55 (+5 件、内訳: HIGH 1 / MEDIUM 4)。カバレッジ ratchet (`fail_under = 93`) は未到達リスクなし — 新規 src 行は約 30 行、対応テストが直接 cover している。

### 9.6 次フェーズへの引き継ぎ

- ブランチ `fix/log-sensitive-payloads-scrubbing` を `main` にマージしてから `002-multi-provider` を起票する。マージ前提が崩れると LOW 5 件のうち `_MANAGED_ENV_KEYS` 派生化が `SecretStr` 移行の影響範囲と再衝突する。
- `002-multi-provider` の `/sdd-init` 入力ドラフト ([specs/inputs/idea1-002-multi-provider.md](../../inputs/idea1-002-multi-provider.md)) に **本 §9.4 の LOW 5 件を Cleanup タスクとして組み込む** ことを `/sdd-tasks` 段階で明文化すること。これを忘れると再び adversarial pass で同じ LOW が浮上する。
- `Mistake` 候補としての「docstring 内本番モデル ID リテラル禁止」を `.sdd/mistakes/` に昇格させるかは、002 の最初の `/code-reviewing` で同じ guard が再発火したら判断する。一度きりの観測で昇格させると mistake DB が低 S/N 化する。
