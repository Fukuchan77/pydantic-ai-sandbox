# Check Phase — 008-2c-cross-platform

PDCA Check: 実装結果（Do）を計画（Plan / spec）の期待値と突き合わせる。
`/sdd-reflect` が `pdca/do.md`・`plan.md`・`spec.md`・`tasks.md` から生成。

## Expectations vs. Results

| Expectation（plan / spec 由来） | Result（do.md 由来） | Status |
|-------------------------------|---------------------|--------|
| `patterns/sse/` を独立 uv レーン（Python 3.14・独自 lock）として新設（R1.1） | Task 0/1 で scaffold 完了、`uv sync --all-groups --locked` グリーン | ✅ |
| `patterns/contracts/` をパス依存 import、契約複製を持たない（R1.2） | `tool.uv.sources` 経由、契約は `patterns_contracts.sse` 単一実体 | ✅ |
| レーン src を framework-agnostic に保ち DI seam で配信対象注入（R1.3/NFR-3） | `EventSource` Protocol 注入、`app.py`/`events.py` は兄弟レーン非 import | ✅ |
| ルートワークフロー無変更（R1.4/11.2/10.3） | `mise run check` = 277 passed/4 skipped（Task 12/13 baseline と同値） | ✅ |
| 5 イベント + `SseEvent` 判別共用体を契約化・再エクスポート（R2.1/2.2） | `sse.py` 実装、`__all__` 追記、README 正本 + drift 登録（Task 11） | ✅ |
| `event:`=判別子 / `data:`=`model_dump_json()` 導出と逆写像（R2.3/4.2） | `to_sse` / `parse_sse_events`（`TypeAdapter`）実装、7 ケース green | ✅ |
| `POST /sse/runs` + `EventSourceResponse` 配信、順序保証・終端マーカー（R3/R4） | `create_app` DI seam 実装、順序・error 終端・終端マーカー検証 green | ✅ |
| ASGITransport でハッピーパスを net-zero 検証（R5.1/5.2） | `test_stream_order` + hermetic ガードで実ソケット非到達を立証 | ✅ |
| token を固定チャンクで決定論検証（R5.3/NFR-2） | `test_token_determinism` 3 ケース、byte 一致・query 非依存 | ✅ |
| 切断で生成器停止・リソース解放を net-zero 再現（R6） | `asgi_driver`（scope 直接駆動 + `http.disconnect` 注入）4 ケース green | ✅ |
| `configure_tracing` 適用 + span≥1（R7） | `observability.py` + `InMemorySpanExporter` 注入で span≥1 検証 | ✅ |
| SSE→OWASP マッピング・pre-commit 不変条件（R8） | `SECURITY-NOTES.md` 追加、gitleaks/model-id 全域被覆を実測確認 | ✅ |
| README 必須4セクション + 応用レイヤ索引（R9） | `patterns/sse/README.md` + `patterns/README.md` 索引追加 | ✅ |
| patterns 系 CI へ SSE レーン反映（R10/R11） | `patterns-ci.yml` 専用 `sse` ジョブ + paths、mise 7 タスク配線 | ✅ |
| カバレッジ `fail_under` を兄弟レーン parity へ ratchet（R5.4/NFR-4） | 85→**98**（実測 99.01%、1pt バッファ） | ✅ |

## Test & Quality Outcomes

- **テスト**: SSE レーン 36 passed / 1 skipped（結合は offline gate でスキップ）。
  contracts レーン 19 passed。ルート 277 passed / 4 skipped。
- **カバレッジ**: SSE レーン **99.01%**（`fail_under=98` 達成）。
  `observability.py`/`events.py`/`__init__.py` 100%、`app.py` 98%
  （唯一の未被覆 `app.py:113->exit` は R-4 rationale 付きで残置）。
- **Lint / format / type**: `ruff check` All passed / `ruff format --check` clean /
  `pyright`（strict, py314）0 errors。全 Wave で維持。
- **依存重量（Task 0 実測）**: runtime 閉包 11 pkg・ML wheel ゼロ、cold sync 0.79s /
  warm `--locked` 0.01–0.02s。CI 影響軽微。
- **パフォーマンス目標**: 数値目標は spec に非設定（応用レイヤデモ）。NFR-2 の決定論性
  （flakiness ゼロ）は固定チャンク台本で達成。

## Requirements Coverage

- Covered: **37/37（100%）** — R1〜R11 の全 numeric 受入基準にタスク割当・実装・検証あり
  （tasks.md Coverage Matrix と一致）。
- NFR-1〜6 も対応 numeric ID 経由で被覆（NFR-1=uv.lock コミット、NFR-2=台本フェイク、
  NFR-3=DI seam、NFR-4=ratchet、NFR-5=drift テスト、NFR-6=切断時解放検証）。
- Gaps: なし。

## Deviations from Design

1. **prerelease alpha 封じ込め（Task 0→1 申し送り）**: pydantic-ai V2 beta 解決に必須な
   `[tool.uv] prerelease = "allow"` が無制約だと runtime の pydantic を `2.14.0a1`(alpha) に
   巻き込む。plan には未記載の制約で、runtime dep へ `pydantic>=2,<2.14` の stable 上限ピンを
   追加し lock 上で `pydantic==2.13.4`(stable) に確定（症状ではなく原因を解消）。
2. **`is_disconnected` poll の位置づけ再確認**: plan は「`is_disconnected` ポーリング +
   `except CancelledError`」の併用を指示。実装ソース一次確認（starlette 1.3.1
   `requests.py:328`）で poll は事前キャンセル済み `CancelScope` 内の非ブロッキング peek =
   実質ノーオペと判明。load-bearing な停止経路は **CancelledError 一本**、poll は協調的二次
   手段として設計どおり残置（research.md I-3 に整合、spec R6.2 文面も調整済み）。
3. **カバレッジ着地 = 98（100 ではない）**: `app.py:113->exit`（`aclose is None` アーム）は
   注入される `EventSource` が全て async generator のため実務到達不能。R-4 に従い brittle な
   100 ratchet を避け、rationale 明記の上で残置。
4. **結合テストの load-bearing 検証手段**: 実 Ollama はサンドボックス不可のため、アダプタの
   正当性を同一パイプライン × `FunctionModel`（net-zero）の throwaway ハーネスで RED→GREEN
   実証（証跡は do.md に保全、ハーネス非コミット）。

いずれも spec の WHAT を変えず、HOW の精緻化（plan の前提を実測で補正）に留まる。

## Issues Encountered

| Issue | Root cause | Resolution |
|-------|-----------|------------|
| 初回 `uv sync` が pydantic-graph pre-release で解決不能（Task 0） | uv は既定で pre-release を採らない | pydantic-ai レーン前例の `prerelease = "allow"` を踏襲 |
| runtime pydantic が alpha に解決（Task 1） | 無制約 prerelease が共有 pydantic を巻き込む | `pydantic>=2,<2.14` stable 上限ピンで封じ込め |
| `__all__` 追記で drift テスト 4 件 RED（Task 2） | SSE README 正本未作成（= Task 11、Task 4 依存で着手不可） | Task 境界を厳守し中間 RED として保全、Task 11 で構造的解消（R2.4） |
| ruff D301（docstring 内 `\n`）/ I001（import 順）（Task 3） | `r"""` 無し docstring に `\`、path-dep を third-party 誤配置 | 散文へ言い換え + isort 規約どおり並べ替え |
| pyright `reportUnusedFunction`（nested route, Task 4） | app-factory の closure で `@app.post` が入れ子 | リポジトリ既存 idiom `# pyright: ignore[...]` で抑止 |

全て blind retry を禁じて根本原因を特定・解消。silent な糊塗（README スタブ・分岐 neuter の
放置）は行わず、中間状態は根本原因 + 解消タスクを明示記録。

## Assessment

実装は計画を**完全充足**した。13 タスク（Spike 含む）が全て RED→GREEN→Refactor を経て
green、37/37 要件被覆、カバレッジ 99.01%（gate 98）、ルートワークフロー無変更を実測で確認。
TDD 規律（憲法 I）は全タスクで load-bearing な RED を証跡化し、純テスト/ドキュメント/設定
タスクでも throwaway ハーネスや分岐 neuter で teeth を立証した。Plan からの逸脱は全て
「実測による前提補正」であり spec の WHAT を損なわない。

**プロダクション準備度**: 応用レイヤデモとして十分に堅牢。ただし spec の Out of Scope どおり
フロントエンド・WebSocket・本格認証/レート制限は未実装で、本番公開には認証・接続上限の
実体化が前提（SECURITY-NOTES に明記済み）。次工程は `/sdd-validate-impl` による独立検証。
