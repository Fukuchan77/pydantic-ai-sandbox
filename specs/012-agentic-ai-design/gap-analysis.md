# 実装ギャップ分析 — 012-agentic-ai-design (HITL ハーネス / PydanticAI v2)

> 承認済み要件 (spec.md、13 要件) を既存コードベースと照合し、設計/計画フェーズに渡す
> 情報と選択肢を提示する。**決定ではなく材料**を出すのが本ドキュメントの目的。
>
> 注: 本 feature は既に `plan.md` / `research.md` / `tasks.md` を持ち phase = `tasks-generated`。
> 本ギャップ分析は事後的に足場適合性を裏取りし、計画の前提が既存パターンと矛盾しないかを
> 検証する位置づけ。矛盾があれば `## 深掘りが必要な論点` に明示する。

## 分析サマリ

- **新規性は低い。足場はほぼ既製**。`patterns/hitl/` は存在しないが、`patterns/sse/`
  (Python 3.14 + FastAPI app-factory + `patterns_contracts` パス依存 + 98 カバレッジ) が
  ほぼそのまま流用できるテンプレートで、Req 1/2/9/11/12 は既存レーンの**対称配線の複製**で満たせる。
- **HITL 機構は 100% ライブラリ実装済み**。`ApprovalRequired` / `DeferredToolRequests` /
  `DeferredToolResults` / `ToolApproved` / `ToolDenied` / `ApprovalRequiredToolset` は
  導入済み pydantic-ai (`patterns/sse/.venv` = v2.3.0 系) の `__init__.py` から全て公開済み。
  `requires_approval` は `tools.py:453/480`、`ctx.tool_call_approved` は `_run_context.py:79`
  に実在 (Req 5.4 の権威)。レビュー確定修正 ①〜④ は「誤りを避ける」ネガティブ制約で、実装難度に寄与しない。
- **真に新規なのは 2 点のみ**: (a) 停止/承認/再開を統括する**ハーネス層**
  (Req 4〜7: 再 defer ガード + `UsageLimits` 通算) と、(b) **FastAPI ステートフル
  セッションストア** (Req 8)。後者はルートアプリの「単一ターン・状態レス」規約に前例が無く、
  本 spec で最も設計判断を要する。
- **統合上の主要課題は state store の設計**。in-memory / プロセス内で `message_history` +
  `usage` を `session` キーで保持する必要があり、ルート app のステートレス Agent とは異質。
  二重 resume・並行アクセス・ライフタイムのセマンティクスは 013 へ委譲済みだが、**ストアの
  責務分割 (harness と別モジュール)** は本 spec の設計事項。
- **要注意の不整合が 1 件**: dependabot は frameworks 3 レーンのみ `directories` 列挙し、
  応用兄弟レーン (rag/sse/deep-research) を**監視していない**。Req 1.6 の
  「dependabot monitoring consistent with existing lanes」は解釈が割れる (下記 G-1)。

## 要件別ギャップ表

| Req | 必要ケイパビリティ | 分類 | 証拠 / 既存パターン |
|-----|------------------|------|-------------------|
| **1.1–1.4** レーン足場 (3.14 / extras / contracts パス依存 / mise 明示 1 行) | 🔧 拡張 | [patterns/sse/pyproject.toml](../../patterns/sse/pyproject.toml) が完全テンプレ (3.14, `[tool.uv.sources]`, ruff/pyright strict)。[mise.toml](../../mise.toml#L97-L151) は各 task で contracts→frameworks ループ後に `(cd patterns/{rag,sse,deep-research} && …)` を 1 行追記する規約 — hitl 行を追加するのみ |
| **1.5** カバレッジ 98 | ✅ 既存 | sse `fail_under = 98` ([pyproject.toml](../../patterns/sse/pyproject.toml#L131))。同値を宣言 |
| **1.6** CI 明示列挙 (patterns-ci 専用ジョブ / security matrix / dependabot) | 🔧 拡張 + ⚠ | patterns-ci.yml は rag/sse/deep-research の専用ジョブ + paths-ignore 除外の前例あり ([.github/workflows/patterns-ci.yml](../../.github/workflows/patterns-ci.yml#L28-L60))。security.yml `patterns-pip-audit` matrix は 7 レーン列挙済み (L155-161)、hitl 行追加で対称。**dependabot は G-1 の判断待ち** |
| **2.1–2.4** 契約所有 + ドリフト検知 | 🔧 拡張 | ドリフト機構は単一点で確立 ([test_contract_drift.py](../../patterns/contracts/tests/unit/test_contract_drift.py))。`patterns_contracts/hitl.py` 追加 + README `## パターン契約` ブロックが正本。**app レーン README を parser が拾うかは G-2 で要確認** |
| **2.2** `action_type` を閉じた `Literal` | ✅ 既存 | 閉じた `Literal` 語彙は既存契約 (`stop_reason`/`Route`/`verdict`) と同型。drift test が Literal 集合を検証 |
| **3.1–3.4** Agent 構築 (`output_type=[SupportOutput, DeferredToolRequests]`, `instrument=True` 除去, `requires_approval` ツール, `instructions`) | 🆕 新規 | 新規コードだが全て library-native。`instrument=True` を渡さないのはネガティブ制約 (Req 3.2)。計装は `logfire.instrument_pydantic_ai()` に一元化 ([logging_setup.py](../../src/pydantic_ai_sandbox/logging_setup.py) が前例) |
| **3.5** `@output_validator` + `ModelRetry` の検証センサー | 🔧 拡張 | `ModelRetry` による自己修正は RAG レーンの引用接地検証で確立済みパターン ([patterns/rag/](../../patterns/rag/) citation loud-fail)。閾値超過×未承認で `ModelRetry` を送出 |
| **4.1–4.2** 承認必須ツールで停止 | 🆕 新規 | library-native。`requires_approval=True` 未承認時に pydantic-ai が `DeferredToolRequests` を返す ([tools.py:453/480/649](../../patterns/sse/.venv/lib/python3.14/site-packages/pydantic_ai/tools.py)) |
| **5.1–5.4** 承認/拒否で再開 | 🆕 新規 | `DeferredToolResults(approvals=...)` / `ToolApproved(override_args=)` / `ToolDenied(message=)` / `ctx.tool_call_approved` すべて実在 ([_run_context.py:79](../../patterns/sse/.venv/lib/python3.14/site-packages/pydantic_ai/_run_context.py)) |
| **6.1** 再開後の再 defer ガード | 🆕 新規 | ハーネス側の `isinstance` 分岐ロジック。前例なし (本 spec 固有の制御) |
| **7.1–7.3** `UsageLimits` 停止/再開通算 | 🆕 新規 | library-native。resume 時に前 run の `usage` を渡して予算を通算。ハーネスが保持 |
| **8.1–8.6** FastAPI `/run` `/resume` + in-memory state store | 🆕 新規 (**最重要**) | app-factory + `with TestClient(app):` は sse/ルートで確立 ([app.py](../../patterns/sse/src/patterns_sse/app.py))。だが **session キーの `message_history`+`usage` 永続化はルートの「状態レス単一ターン」規約に前例なし** (product.md §4)。最大の設計判断点 |
| **9.1** 可観測性 fail-soft | ✅ 既存 | sse `observability.py` / ルート `logging_setup.py` が `instrument_pydantic_ai` + fastapi/httpx を fail-soft 起動する規範を提供 |
| **10.1–10.4** ハーメティックテスト (`pytest-asyncio` auto, 出力ツール応答, `TestModel(call_tools=[...])`, 停止→承認→再開/deny 全経路) | 🔧 拡張 | `TestModel`/`FunctionModel` は repo 全域で一級。autonomous-agent レーンの**ターン列フェイク**が「ツール呼出→FB→最終回答」台本化の前例 (`.sdd/patterns/deterministic-tool-loop-budget-seam.md`)。`pytest-anyio` を使わない (②) はネガティブ制約 |
| **11.1–11.3** 統合レーン (空振り緑禁止) | 🔧 拡張 | `patterns_contracts.pytest_live_guard` + `EXPECT_LIVE_TESTS=<n>` 機構が確立 ([pytest_live_guard.py](../../patterns/contracts/src/patterns_contracts/pytest_live_guard.py))。live 統合は `patterns-integration-ollama.yml` (dispatch-only) に隔離、`pull_request:` トリガ無し |
| **12.1–12.2** モデル ID 衛生 | ✅ 既存 | 二層ガード (pre-commit pygrep + `tests/unit/test_no_hardcoded_model_ids.py`) は `patterns/` を含むリポジトリ全域に自動適用。env 経由 (`ANTHROPIC_MODEL` 等) で通す |
| **13.1–13.3** Durable/セキュリティ設計ノート | 🆕 新規 (doc-only) | README 記述のみ。Durable 統合先 = Temporal/DBOS/Prefect (④)、v1 併用時 `>=1.99.0` フロア、検証ベースライン version+date。実装なし |

**集計**: ✅ 満たす 4 / 🔧 拡張 (既存パターン複製) 6 / 🆕 新規 8 (うち doc-only 1)。
新規 8 のうち Req 4/5/7 は library-native の薄いラッパ、実質的な新規設計は **Req 6 (再 defer ガード) と
Req 8 (state store) と Req 3 (Agent 組立)** に集中する。

## 統合上の課題

1. **ステートフル化 (Req 8) がリポジトリ規約と異質**。ルート app と全応用レーンは
   「Agent は状態を持たない・単一ターン」を前提 (product.md §4)。session キーで
   `message_history`+`usage` をプロセス内保持するのは初。→ **ストアを harness とは別モジュール**
   (`store.py` 等) に切り出し、responsibility=file の §2 原則を維持するのが自然。
   in-memory dict の並行アクセス (uvicorn worker) は MVP スコープ外だが、モジュール境界だけは今決める。
2. **契約ドリフト parser の app レーン対応 (Req 2.4)**。drift test の docstring は
   「各 `patterns/<pattern>/README.md`」と記述。rag/deep-research も契約を所有するため
   app レーン README は既に拾われているはずだが、hitl README が確実に glob 対象かを
   実装前に確認 (G-2)。
3. **dependabot の非対称 (Req 1.6)**。応用兄弟レーンは現状 dependabot 未監視 (G-1)。
   「consistent with existing lanes」の解釈で配線先が変わる。
4. **カバレッジ 98 × 分岐の多いハーネス**。resume / deny / 再 defer / usage-limit 超過の
   各分岐を `TestModel(call_tools=[...])` と `FunctionModel` の台本で網羅する必要。
   sse レーンが 1 分岐を「到達不能 glue」として文書化しつつ 98 を守った前例あり
   ([pyproject.toml コメント](../../patterns/sse/pyproject.toml#L121-L131))。
5. **Python 3.14 strict**。pyright 3.14 strict / ruff `target-version = "py314"`。
   `Any` は I/O 境界のみで Pydantic narrowing。FastAPI ハンドラの `@app.post` は
   pyright が貫通できないため sse 同様 `# pyright: ignore[reportUnusedFunction]` が要る。

## アプローチ選択肢

配置 (新規 patterns 応用兄弟レーン・pydantic-ai 単独) は clarifications で確定済みのため、
選択肢はレーン**内部構成**と **state store 設計**に絞る。

### レーン内部のモジュール分割

| 案 | 内容 | コスト | リスク | 適合 |
|----|------|--------|--------|------|
| **A (推奨)** sse 対称の責務分割 | `agent.py` (Agent 組立 + output_validator) / `harness.py` (run/resume + 予算通算 + 再 defer ガード) / `store.py` (in-memory session store) / `app.py` (create_app, DI seam で agent/store 注入) / `observability.py` | 中 | 低 (既存 §2/§8 原則に完全整合) | ◎ |
| **B** ハーネス集約 | harness + store + app を 1〜2 ファイルに凝集 | 低 | 中 (responsibility=file 違反、C90≤10 に触れやすい、差分レビュー困難) | △ |
| **C** frameworks/pydantic-ai へ co-locate | 既存レーンに hitl モジュール追加 | 低 | 高 (clarifications 違反 = 新レーン指定。frameworks は 6 パターン横断比較の場で応用層ではない) | ✕ 却下 |

→ **案 A を推奨**。sse レーンの `create_app(*, event_source, tracer_provider)` DI seam を
`create_app(*, agent, store, tracer_provider)` に写像すれば、テストは fake agent (`TestModel`
override) と in-memory store を注入して完全 hermetic に停止/再開/deny を駆動できる。

### state store の抽象度 (Req 8.4)

| 案 | 内容 | コスト | リスク |
|----|------|--------|--------|
| **A (推奨)** 素の in-memory 具象 + 細い Protocol seam | `dict[session, SessionState]` を薄い `SessionStore` Protocol 背後に置き、将来 Durable/永続 DB を差し替え点として文書化 | 中 | 低 (013/将来フェーズへの拡張点を今の DI seam 規律で確保) |
| **B** 具象 dict のみ | Protocol 無しで dict 直持ち | 低 | 中 (013 のセキュリティ要件・将来永続化で再設計) |

→ **案 A を推奨**。`SearchProvider`/`digest_fn` と同型の DI seam 規律 (structure.md §8-8) に
そろえ、013 (二重 resume・監査証跡) と将来 Durable 統合の差し替え点を今のうちに Protocol で残す。
ただし MVP 実体は in-memory 具象 1 つのみ (over-engineering を避ける)。

## 深掘りが必要な論点 (計画フェーズへ)

- **G-1 (要判断)**: dependabot の配線先。現状 `directories` は frameworks 3 レーンのみで、
  応用兄弟レーン (rag/sse/deep-research) は**未監視**。Req 1.6 の「consistent with existing lanes」は
  (a) 応用レーンの現状 = 未監視に倣う / (b) frameworks 式 `directories` に hitl を足す、の 2 解釈。
  security.yml の daily pip-audit が全レーン CVE を拾う (2026-07 nltk の教訓) ので機能的空白は
  埋まるが、**dependabot の追従自動化は別問題**。計画で方針を明記すべき。
- **G-2 (要確認)**: contracts ドリフト test が `patterns/hitl/README.md` を確実に glob するか
  (rag/deep-research の app レーン README が既に拾われている前提を実測で裏取り)。拾わないなら
  parser の README 探索リストへ hitl を明示追加するタスクが要る。
- **G-3 (設計確認)**: `SupportOutput` を出力ツール (`final_result`) として返す FunctionModel 台本
  (Req 10.2) と、`TestModel(call_tools=[...])` で `requires_approval` ツールのみ呼ばせて
  `DeferredToolRequests` を確実に誘発する台本 (Req 10.3) の具体形。autonomous-agent の
  ターン列フェイクを写経できるか、HITL 固有の停止/再開 2 フェーズを台本化する新手が要るか。
- **G-4 (検証ベースライン)**: Req 13.3 の「pydantic-ai-slim version + date」。導入済み venv は
  v2.3.0 系 (sse `.venv`)。hitl レーンが実際に解決する version を lockfile 確定後に README へ記録。

## Next Steps

1. 本ギャップ分析を踏まえ、既存 `plan.md` / `tasks.md` の前提と G-1〜G-4 の整合を確認する
   (phase は既に `tasks-generated`)。齟齬があれば計画側を改訂。
2. 未着手なら `/sdd-plan 012-agentic-ai-design` で技術計画を確定 (案 A ×案 A を土台に)。
3. G-1 (dependabot 方針) は実装前に確定させ、Req 1.6 の受入基準を一意化する。

---

## 解決記録(実測と design 反映、2026-07-12)

上記 G-1〜G-4 / 統合課題を実測で裏取りし、`plan.md` / `research.md` / `tasks.md` へ反映済み。

| ID | 事実確認(実測) | 解決(反映先) |
|---|---|---|
| G-1 | `dependabot.yml` pip `directories` = frameworks 3 レーンのみ(確認済み) | **方針固定(research AD-9)**: dependabot は pydantic-ai 依存レーンを個別監視(frameworks 3 + hitl を `directories` へ追加)。応用兄弟レーン未監視は本 spec スコープ外の既知ギャップ(daily security cron が補完)。R1.6 の合否 = `directories` に `/patterns/hitl` が存在すること(deterministic)。plan LaneScaffold / tasks T7.2 に明記 |
| G-2 | **glob ではなく明示登録**: `_README_PATHS` dict への 1 行追加(`test_contract_drift.py:49`)。パーサは `## パターン契約` 直後の最初の python fence を ast で個別パース。**実測**: 計画中の正本ブロック(`ActionType` col-0 エイリアス + `ResolutionAction` + `SupportOutput`)をパーサ関数の verbatim 転写に通し、パッケージ側 introspection(実 pydantic モデル)と classes / fields / named_literals / field_literals の 4 面で**完全一致**(research I-7)。alias 参照(`action_type: ActionType`)も対称一致 | 計画変更なし。登録タスクは既存 T2.2(明示 1 行追加)で正しい |
| G-3 | 停止/再開 2 フェーズ台本は**新手が必要だが実行確認済み**: レビュー付録の検証スクリプトで `len(messages)==1` → 承認必須ツール呼び出し、以降 → `ToolCallPart("final_result", ...)` の単一関数台本が pydantic-ai-slim 2.9.0 で動作済み(停止 run と再開 run を messages 長で判別) | research I-1 に台本の具体形を明記。T5.1 が `tests/support/function_model_scripts.py` へ転用。`TestModel(call_tools=[...])` 側は T4.1 |
| G-4 | 検証ベースライン = **pydantic-ai-slim 2.9.0(2026-07-11 実行検証)**。レーンのフロアを `>=2.9.0` にすれば lockfile 解決版 ≥ 検証版が保証される | README(R13.3、T2.1)+ pyproject フロア(T3.1)の両方に固定。lockfile 確定後の実解決版を README へ追記 |
| HIGH(DI シーム) | sse は `create_app(*, event_source, tracer_provider=None)`(確認済み) | **案 A 採用**: `create_app(*, agent, store=None, instrument=True)`(plan HitlApp / research AD-8 / T6.2)。tracer_provider ではなく `instrument: bool` なのは、本レーンの計装が OTel provider 注入ではなく logfire ブートストラップ(R9.1)のため — fail-soft な `enable_observability()` を lifespan で呼ぶか否かのフラグが等価の注入点。013 は同シームへ `audit_emitter=` を追加 |
| state store 案 A(Protocol seam) | — | 採用: `SessionStore` は細い Protocol + in-memory 具象 1 つ(over-engineering 回避)。013 の状態機械拡張・将来 Durable の差し替え点として plan SessionStore に明記 |
| H-1(第2層未走査) | `test_no_hardcoded_model_ids.py:18` は `SRC_DIR = REPO_ROOT / "src"` のみ rglob — patterns/ 未走査を確認。第1層 pre-commit は patterns を走査する(確認済み) | **T7.3 新設**(R12.2、plan ModelIdGuardSecondLayer / research AD-10): 走査対象へ `patterns/*/src` を追加。TDD は植え込みリテラルで赤確認。**事前 grep 実施済み(2026-07-12)**: 全レーン src で禁止リテラル 5 種の出現 0 件 — 拡張は既存レーンを赤化しない |
| M-1(R12.2 未マップ) | tasks の `_Requirements:_` に 12.2 不在を確認 | T7.3 が 12.2 を保持。完了ゲートも「二層とも通過」へ更新 |
| M-2(3.14 赤証跡) | コンテナは uv の 3.14 取得が proxy 403(実測、research I-5) | T3.2 に証跡手順を明文化: CI(patterns-ci hitl ジョブ)で赤→緑を確認し run URL をコミット/PDCA 記録へ残す(既存 3.14 レーンと同運用) |
