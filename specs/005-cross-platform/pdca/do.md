# 005-cross-platform — PDCA: Do（2026-06-12）

T1〜T9 を実装した。計画（plan.md）からの逸脱と実測知見のみ記す。

## 計画からの逸脱

1. **PydanticAI v2 の計装 API**: plan は `Agent(instrument=...)` を想定して
   いたが、v2.0.0b7 では kwarg が削除され
   `pydantic_ai.models.instrumented.instrument_model(model, settings)` に
   移行していた。パターンエントリポイントはモデルラップ方式に変更
   （ベータ API 変動リスク R-4 の実例）。
2. **beeai-framework のピン**: `==0.1.39`（実装時最新）。`_create` /
   `_create_structure` / `_create_stream` + `model_id` / `provider_id` の
   5点が抽象面。`provider_id` は `ProviderName` Literal 制約のため
   フェイクは "ollama" を借用（ネットワーク接続なし、コメントで明示）。
3. **語彙外経路の例外面（BeeAI）**: ValidationError は Workflow ランナーが
   `FrameworkError` にラップする（`__cause__` 保持）。テストは cause を
   検証する形にした。
4. **LlamaIndex 構造化出力のオフライン化**: 懸念どおり MockLLM は不適。
   `CustomLLM` 継承の ScriptedLLM（非 function-calling）で
   `astructured_predict` がテキスト補完プログラム + JSON パーサ経路に
   分岐することを実測確認 — フォールバック（R-2）は不要だった。
   フェイクと実機が同じ Pydantic 検証面に着地する。
5. **契約に `truncated: bool` を追加**: Req 3.2「切り捨ての判別可能性」を
   フィールドで満たす（README 正本に反映済み）。

## 実測値

- レーンゲート: 3レーンとも ruff / ruff format / pyright strict 0 error、
  pytest 12/12/11 passed、カバレッジ 97.8–98.0%（フロア 85）。
- ルートゲート無影響（Req 9.2）: 279 passed / カバレッジ 98.83%（フロア 98）、
  pre-commit 全フック Passed。契約同期テスト2本をルートに追加。
- pip-audit: 3レーンとも既知脆弱性の検出なし（ローカルパッケージの
  skip 表示のみ）。
