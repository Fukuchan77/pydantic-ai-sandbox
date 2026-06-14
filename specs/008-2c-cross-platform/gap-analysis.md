# 008-2c-cross-platform — 実装ギャップ分析

> `/sdd-validate-gap` 出力。承認済み要件（spec.md, draft）と既存コードベースの
> ギャップを設計前に把握する。**決定ではなく情報と選択肢**を提示する。
> 言語: `ja`（spec.json）。

## 分析サマリ

- **マクロ構造のギャップはほぼゼロ**。本フィーチャは「`patterns/` 配下に
  新しい応用レイヤ独立レーンを 1 つ足す」ものであり、**Spec 007-2b の `patterns/rag/`
  がほぼそのままテンプレート**になる（depth 1 で `frameworks/` の兄弟、`contracts`
  へのパス依存、独自 `pyproject.toml`/`uv.lock`/`.python-version`、専用 mise 1 行追記、
  CI 専用ジョブ）。R1/R8/R9/R10/R11 は RAG レーンの型紙に沿った機械的拡張。
- **契約ドリフト検知は無改修で判別共用体に対応**。`test_contract_drift.py` の
  パーサは `Annotated[Union[...], Field(discriminator="type")]` 別名を
  `ApprovalHook` と同じく**自然にスキップ**し、各イベントモデルの
  `type: Literal[...]` 判別子は**インラインフィールド Literal として収集**する。
  必要なのは新モジュール `sse.py`・`__init__` 再エクスポート・README 正本ブロック・
  `_README_PATHS` への 1 エントリ登録のみ（R2）。
- **真に新規で最大の不確実性は「エージェント実行 → イベント列の導出」**（R3/R4）。
  既存 `run_routing` は最終値 `RoutedAnswer` を返すだけで、step/tool/token の
  逐次フックを持たない。`step_started → tool_called* → token* → completed` を
  どう生成するか（Pydantic AI V2 ストリーミング API か、台本フェイク駆動の自作
  ドライバか）が設計の中心論点。**`research.md` で一次情報検証必須**。
- **オフライン検証基盤は実証済み**。ルートアプリが `httpx.ASGITransport` +
  `TestClient` を多数のテストで既に使用（`tests/conftest.py` 他）。SSE レーンへの
  複製は確立パターン。ただし**切断・キャンセル経路の再現**（R6）と**決定論的
  トークンストリーミングのフェイク**（NFR-2）は新規で、いずれも research 対象。
- **推奨**: レーン追加というマクロ方針は RAG 先例で確定（Hybrid）。残る唯一の
  オープン軸である「イベント導出方式」を `research.md` で 3 案比較し、
  **フレームワーク非依存の `SseEvent` 契約 + 注入式イベントソース Protocol**
  （オフライン=台本ジェネレータ / 結合=Pydantic AI ストリーミングアダプタ）を
  軸に据える案を起点とする。

## 要件別ギャップ表

| Req | 必要ケイパビリティ | 分類 | 根拠・既存資産 |
|---|---|---|---|
| **R1** SSE 独立レーン新設 + 契約配線 | depth 1 兄弟レーン、`contracts` パス依存、レーン間 import 禁止、DI seam | 🔧 拡張 | `patterns/rag/pyproject.toml`（`[tool.uv.sources] patterns-contracts = { path = "../contracts" }`）がほぼそのまま流用可。docling 依存を fastapi/sse-starlette/httpx へ差替えるだけ |
| **R2** 型付きイベント判別共用体 + 契約 | 5 イベントモデル + `SseEvent` 判別共用体、`patterns_contracts` 再エクスポート、README 正本、ドリフト検知 | 🔧 拡張 | `contracts/src/patterns_contracts/{rag,routing}.py` が型紙。**ドリフトテスト無改修**（後述「設計インサイト」）。`__init__.py` の flat 再エクスポートに追記、`_README_PATHS` に `"sse"` 登録 |
| **R3** FastAPI エンドポイント + SSE 配信 | `EventSourceResponse`、エージェント駆動、モデル DI seam | 🆕 新規（一部既存） | `patterns/` に FastAPI/sse-starlette は**未導入**（ルートには有るが R1.4/R10.3 で改変禁止）。DI seam の発想は `run_routing(model=...)`・ルート `build_chat_agent` に前例 |
| **R4** イベント列の順序と意味 | `step_started→tool_called*→token*→completed`、各 `data` の `model_validate`、エラー終端 | 🆕 新規 | **最大ギャップ**: `run_routing` は最終 `RoutedAnswer` のみ返し逐次イベントを持たない。導出方式は未確立（research 必須） |
| **R5** オフライン検証（ASGITransport） | `httpx.ASGITransport` インプロセス、順序/型検証、決定論トークン | 🔧 拡張 | ルート `tests/conftest.py`・`test_chat_endpoint_*` で ASGITransport/TestClient 実証済。決定論トークンフェイクは新規（既存レーンフェイクはツールループ台本でトークン増分は未対応） |
| **R6** 切断・キャンセル経路 | 早期切断でジェネレータ停止 + リソース解放、例外を握り潰さない | 🆕 新規 | リポジトリに切断再現テストの前例なし。`request.is_disconnected()` + `CancelledError`/`GeneratorExit`（Clarifications 採択）。ASGITransport 上での切断再現方法は research 対象 |
| **R7** 可観測性 | `configure_tracing()` 適用、span≥1、末端 span 確認 | ✅ 充足（複製） | 各レーンの `observability.py`（`InMemorySpanExporter` 注入、`SimpleSpanProcessor`）がほぼ同一。routing 配信なら pydantic-ai 流の `gen_ai.*` ネイティブ（`InstrumentationSettings`） |
| **R8** セキュリティ | SSE リスク→OWASP マッピング、`pip-audit`、機微情報非掲載、フック非除外 | 🔧 拡張 | `SECURITY-NOTES.md:53` の「RAG→OWASP LLM」節が型紙（SSE 節を追加）。`pip-audit` は全レーン dev 依存 + CI 既設。gitleaks/forbid-hardcoded-model-ids は既にリポジトリ全域（R8.4 は不変条件の確認のみ） |
| **R9** ドキュメント・タクソノミー | README 必須4セクション + 正本、`patterns/README.md` 応用レイヤ索引 | 🔧 拡張 | `patterns/rag/README.md`（タイトル→契約正本 fenced→パイプライン→必須4セクション→ライブラリ）が完全な型紙。`patterns/README.md:29` の「応用レイヤー（RAG）」節に SSE 行/別セクションを追加 |
| **R10** CI | `patterns-ci.yml` 反映、Ollama 結合は integration、ルート無変更 | 🔧 拡張 | SSE は兄弟レーン＝**専用ジョブ**（contracts/rag と同型、matrix エントリにはしない）。`patterns/sse/**` paths トリガ追加。結合は `patterns-integration-ollama.yml` に `patterns/sse/**` 追記 |
| **R11** 開発体験 | 全 `patterns:*` task が SSE を含む、ルート `check` 無変更 | 🔧 拡張 | 各 task に `(cd patterns/sse && …)` を**レーンループの後に 1 行追記**（RAG と同手順）。ルート `check` は patterns/ 除外済で R11.2 は構造的に成立 |

凡例: ✅ 既存で充足 / 🔧 部分的（拡張要） / 🆕 新規構築。

## 設計インサイト: 契約ドリフトテストは無改修で判別共用体に対応

`patterns/contracts/tests/unit/test_contract_drift.py` の挙動を精査した結果、
**判別共用体パターンは既存パーサで完全にサポートされる**:

- `SseEvent = Annotated[Union[...], Field(discriminator="type")]` は Pydantic
  モデルクラスでも `Literal` でもないため、`_package_shape()` の分岐で
  `isinstance(member, type)` False → `_value_literal()` None となり、
  **`ApprovalHook`（Callable 別名）と同じく設計上スキップ**される。README 側でも
  `_collect_named_literals` の `_annotation_literal` が `Annotated` head を
  `Literal` と認識せず None を返すため、別名は両側で対称にスキップされる。
- 各イベントモデルの `type: Literal["step_started"]` 等の判別子は、
  `_collect_model` がインライン `AnnAssign` の Literal として収集し、
  `field_literals` で README==パッケージの語彙一致を検証する。これは判別子の
  値ドリフト（`event:` 名の正本）を自動的にロックする利点。

➡ **必要作業は加法のみ**: `sse.py` 追加 / `__init__.py` 再エクスポート追記 /
README 正本ブロック作成 / `_README_PATHS` に `"sse"` 行追加。R2.4（既存契約・
ドリフトテストを破壊しない）は構造的に満たされる。

## 統合上の課題（research / plan で解く論点）

1. **【最重要】イベント列の導出方式**（R3/R4 ⇄ NFR-2）。`run_routing` は最終値のみ。
   Pydantic AI V2 のストリーミング/イベント API（`agent.run_stream` / `agent.iter`
   グラフノード、`FunctionModel` のストリーム対応可否）を一次情報で確認し、
   `step_started/tool_called/token/completed` への写像可能性と決定論性を検証する。
2. **二層 DI seam とレーン非結合**（R1.3 ⇄ R3.3 ⇄ NFR-3）。
   モデル seam（フェイク/Ollama）に加え、**配信対象ランナー seam**が必要。
   R1.3 は SSE レーン src からの `patterns_pydantic_ai` import を禁ずるため、
   SSE レーンは「イベントを yield するランナー」の Protocol を定義し**注入で受ける**。
   routing 実体の結線は結合テスト境界に限定する（src は非依存）。seam の正確な
   契約形状は論点 1 の結論に依存。
3. **切断再現 over ASGITransport**（R6）。`httpx` クライアント側で
   ストリームコンテキストを早期 close した際に、サーバ側 `is_disconnected()` /
   `CancelledError` / `GeneratorExit` がどう発火しクリーンアップを保証できるかを
   一次情報で確認（sse-starlette の切断ハンドリング現行 API も含む）。
4. **決定論的トークンストリーミングのフェイク**（NFR-2 / R5.3）。既存レーンフェイク
   （`turn_sequenced_model` 等）はツールループ/投票の台本化でありトークン増分の
   台本供給は未対応。固定チャンク列でトークンを供給する新フェイクの形状を定義。
5. **Python バージョン選択**（3.13 vs 3.14）。RAG/llamaindex の 3.13 ピンは
   docling/llamaindex の 3.14 wheel ギャップ回避が理由で、**SSE 依存
   （fastapi/sse-starlette/httpx）には該当しない**。結合配信対象の routing は
   pydantic-ai レーン（3.14）に在る。3.14 採用が自然だが plan で明示確定する。

## アプローチ選択肢

### マクロ方針（レーン追加）— RAG 先例で実質確定

レーン粒度では「拡張 vs 新規」の対立はない。Spec 007-2b が
「共有契約を再利用しつつ新しい兄弟レーンを足す Hybrid」を確立済みで、本フィーチャは
その型紙を踏襲する（mise 1 行追記・CI 専用ジョブ・SECURITY-NOTES/README 索引追記）。

### イベント導出方式 — 唯一のオープン軸（research で比較）

| 案 | 適合条件 | コスト | リスク |
|---|---|---|---|
| **A: Pydantic AI ネイティブストリーミング** — `run_stream`/`iter` のイベントを `SseEvent` に写像 | 真のトークンデルタ・`tool_called` を idiomatic に得たい | 中（API 調査要） | フレームワーク固有イベントモデルへの結合。`FunctionModel` のストリーム決定論が要検証。NFR-3（src 非結合）と緊張 |
| **B: 自作イベント発火ドライバ** — 注入ランナーを呼び台本フェイクからイベント合成 | 完全決定論・最小の切断制御を最優先 | 低 | token が合成的（フェイクが増分を台本供給しない限り「実物」でない）。「routing 実行の実体感」が薄い |
| **C: Hybrid（推奨起点）** — fw 非依存 `SseEvent` 契約 + 注入式イベントソース Protocol。オフライン=台本ジェネレータ（決定論）/ 結合=Pydantic AI ストリーミングアダプタ（routing） | NFR-3（src 非結合）と NFR-2（決定論）を両立しつつ実経路を結合レーンで実証 | 中 | 二実装の保守。Protocol 形状が論点 1 の結論に依存 |

> C は R1.3（レーンソース非依存）/ NFR-3 / NFR-2 / R6（切断制御の容易さ）を同時に
> 満たしやすく、結合レーンで「実モデル × 実ストリーミング」を別途実証できる。
> 最終決定は `research.md` の Pydantic AI V2 ストリーミング API 検証結果に委ねる。

## research.md で一次情報検証すべき項目

- sse-starlette の現行 `EventSourceResponse` API と切断ハンドリング（Clarifications で明記）。
- FastAPI `request.is_disconnected()` の挙動 + 非同期ジェネレータの
  `CancelledError`/`GeneratorExit` クリーンアップ保証。
- Pydantic AI V2 のストリーミング/イベント API（`run_stream` / `agent.iter`）と
  `FunctionModel` のストリーム決定論（NFR-2 を満たせるか）。
- `httpx.ASGITransport` 上でのクライアント早期切断の再現手法（R6.2）。
- fastapi / sse-starlette / httpx のバージョン・ベータ注意事項（R9.3）。

## 既存資産の参照ポイント（plan の起点）

- レーン型紙: `patterns/rag/`（`pyproject.toml` / `README.md` / `tests/{unit,integration,support}/`）
- 契約 + ドリフト: `patterns/contracts/src/patterns_contracts/{__init__,rag,routing}.py` /
  `patterns/contracts/tests/unit/test_contract_drift.py`
- DI seam 前例: `patterns/frameworks/pydantic-ai/src/patterns_pydantic_ai/routing.py`（`run_routing(*, model)`）
- 可観測性型紙: `patterns/frameworks/pydantic-ai/src/patterns_pydantic_ai/observability.py`
- ASGITransport 前例: ルート `tests/conftest.py` / `tests/unit/test_chat_endpoint_with_testmodel.py`
- 配線型紙: `mise.toml`（`patterns:*` の `(cd patterns/rag && …)` 追記）/
  `.github/workflows/patterns-ci.yml`（`rag:` 専用ジョブ）/
  `.github/workflows/patterns-integration-ollama.yml`（`patterns/rag/**` paths）
- セキュリティ/索引型紙: `patterns/SECURITY-NOTES.md:53`（RAG→OWASP 節）/
  `patterns/README.md:29`（応用レイヤー索引）

---

_Gap analysis generated (/sdd-validate-gap): 2026-06-14_
