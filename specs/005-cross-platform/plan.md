# 005-cross-platform — Implementation Plan

要件は spec.md、検証根拠は research.md を参照。本書は設計判断（AD）と
ファイル配置・CI 設計を定める。

## §1 アーキテクチャ決定

- **AD-1: 独立 uv プロジェクト（uv workspace 不採用）**。
  requires-python の交差が空集合（research.md R-3）。各レーンが独自
  pyproject.toml / uv.lock / .python-version を持ち、mise タスクと CI
  マトリクスで束ねる。pip-audit がロックファイル毎に帰属する副次効果あり。
- **AD-2: パッケージはフレームワーク単位、ドキュメントはパターン単位**。
  uv プロジェクトは3つ。パターン契約の正本と必須4セクションは
  `patterns/<pattern>/README.md`。将来6パターンに拡張しても
  プロジェクト数が増えない。
- **AD-3: 共有契約コードは第1イテレーションでは複製**（各レーン約25行）。
  独立プロジェクト間のパス依存を避ける。第2イテレーションで
  `tool.uv.sources` パス依存の shared-contracts へ昇格可能。
- **AD-4: SDD はスリム実施**。research.md は検証済み調査ドキュメントを
  転載・要約し再調査しない。pdca/ は実行時に記録。
- **AD-5: Python はレーン毎**。pydantic-ai=3.14（ルートと同一イディオム）、
  beeai=3.13（上限 `<3.14`）、llamaindex=3.13（3.14 wheel ギャップ回避）。
  mise グローバルは 3.14 のまま、各レーンの `.python-version` から uv が
  3.13 を解決する。

## §2 ディレクトリ構成

```
patterns/
├── README.md                      # 二軸タクソノミー + FW 比較表 + 索引（Req 1.4）
├── SECURITY-NOTES.md              # CVE 根拠・フロア・OWASP マッピング（Req 7.1）
├── routing/README.md              # 契約正本 + 必須4セクション（Req 1.3, 2.1）
├── orchestrator-workers/README.md # 同上（Req 1.3, 3.1）
└── frameworks/
    ├── pydantic-ai/               # py3.14, pydantic-ai-slim[openai]>=2.0.0b6
    │   ├── pyproject.toml / uv.lock / .python-version / README.md
    │   ├── src/patterns_pydantic_ai/{__init__,contracts,observability,
    │   │                             routing,orchestrator_workers}.py
    │   └── tests/{unit/*, integration/test_ollama_e2e.py}
    ├── beeai/                     # py3.13, beeai-framework（厳密ピン）
    │   └── src/patterns_beeai/... + tests/support/fake_chat_model.py
    └── llamaindex/                # py3.13, llama-index-core ほか
        └── src/patterns_llamaindex/... + tests/support/fake_llm.py
```

## §3 パターン実装方針

- **routing**（Req 2）: 分類は各フレームワークの構造化出力プリミティブ
  （PydanticAI=`output_type=RouteDecision`、LlamaIndex=Workflow step 内
  structured 出力、BeeAI=ChatModel 構造化出力）。経路別回答は
  経路→instructions のマッピングで実装し、フレームワーク間で意味的に同型に保つ。
- **orchestrator-workers**（Req 3）: プラン生成（構造化出力）→
  `max_workers` で切り捨て → 並列ワーカー → 統合。LlamaIndex は
  `ctx.send_event` fan-out / `ctx.collect_events`、他は `asyncio.gather`。
- 経路語彙・フィールド名はレーン間で完全一致（NFR-3 の契約テストが
  フィールド名集合をアサート）。

## §4 テスト設計

- ユニット: research.md R-4 のフェイク戦略。スモーク（Req 4.2）→
  正常系・違反系（Req 4.3）。カバレッジ fail_under=85（NFR-4）。
- 結合: `RUN_INTEGRATION_PATTERNS=1` ゲート（Req 5）。アサーションは
  契約レベルのみ。
- 計装テスト: `InMemorySpanExporter` 注入でスパン >=1（Req 6.2）。

## §5 mise タスク（Req 9.1）

`patterns:setup|lint|format|typecheck|test|audit|check|test:integration` —
実装は `for d in patterns/frameworks/*/; do (cd "$d" && uv run ...); done`
の `set -e` ループ。`patterns:check` は lint/format/typecheck/test を集約。

## §6 CI（Req 8）

- **patterns-ci.yml**: paths=`patterns/**`, `mise.toml`, ワークフロー自身。
  `fail-fast: false` のマトリクス（lane × dir）。uv コマンド直接実行
  （ループ式 mise タスクだと1レーンの失敗が他レーンを隠すため — この
  乖離はワークフローヘッダに明記）。
- **patterns-integration-ollama.yml**: integration-ollama.yml の
  デーモン構築・キャッシュ戦略を踏襲（restore-keys プレフィクス
  `ollama-model-` で既存モデルブロブを共有）。単一ジョブで
  `mise run patterns:test:integration` を逐次実行（モデル pull 1回）。

## §7 ルート設定への変更（最小・アプリ挙動不変）

- ルート pyproject.toml: ruff `extend-exclude = ["patterns"]`、
  pyright `exclude = ["patterns", ...defaults]`（適用済み）。
- .pre-commit-config.yaml: ruff/pyright 3フックに `exclude: ^patterns/`
  （適用済み）。gitleaks / model-ID ガードは patterns/ もカバー継続（Req 7.4）。
- dependabot.yml: pip エコシステムに patterns 3 ディレクトリを追加。
- トレードオフ: レーンの lint/型ゲートはコミット時でなく mise/CI 時で担保
  （spec Clarifications 参照）。

## §8 リスク

| # | リスク | 緩和策 |
|---|---|---|
| R-1 | BeeAI フェイクが内部 `_create` シグネチャに依存 | beeai-framework を `==` ピン、スモークテストでドリフト検知 |
| R-2 | LlamaIndex 構造化出力のオフライン化が MockLLM で不成立 | スクリプト化フェイク or prompt+JSON パースへフォールバック（README 型安全セクションに記録） |
| R-3 | BeeAI の OTel 統合 API が不明確 | 手動スパンフォールバック。テストは「スパン存在」のみ |
| R-4 | pydantic-ai v2 ベータの API 変動 | ルートと同一フロア（>=2.0.0b6）、ルート更新に追従（NFR-2） |
| R-5 | レーン間契約ドリフト | フィールド名集合の契約テスト + README 正本 |
