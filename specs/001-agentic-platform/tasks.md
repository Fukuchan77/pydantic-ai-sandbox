# 001-agentic-platform 実装タスク (tasks.md)

> **対象**: `specs/001-agentic-platform/spec.md` Requirements 1–10 + NFR-1..7
> **設計**: `specs/001-agentic-platform/plan.md` §2 (Component Contracts) / §4 (File Structure Plan) / §6 (Traceability)
> **方針**: Test-First (Constitution Principle I) / Library-First / 環境変数中心主義
> **凡例**:
>
> - `(P)` = 同時並列実行可能 (依存解決後、ファイル境界が他の (P) と重ならないとき)
> - `_Boundary:_` = タスクが触れて良いファイルパスの集合 (plan.md §4 の File Structure Plan の項目のみを使用)
> - `_Depends:_` = 先行完了が必要なタスク ID。依存無しは `none`
> - `_Requirements:_` = カバーする spec.md 要件 ID (数値のみ、カンマ区切り)
> - 各メジャータスク末尾の `### Implementation Notes` は実装後に 1–3 行で学びを追記する欄 (生成時は空)

---

## Task 1. プロジェクト依存とタスクランナー整備

開発を開始する前に、依存とタスクランナーと開発者オンボーディング契約を最低限揃える。これは Constitution V (Quality Gates) と spec Req 7.5/8.5/NFR-2 の前提を成立させるためのブートストラップである。本タスクは `src/` 配下を一切触らないので Test-First 原則の対象外。

- [x] (P) **1.1** `pyproject.toml` に MVP 依存と coverage 設定を追加する
  - `pydantic-ai-slim[openai]` を runtime dep に追加 (Plan AD-6 / research.md R-1)。`pydantic-ai>=2.0.0b3,<3` は据え置き
  - dev/test extras に `pip-audit`, `pytest-cov` を追加 (bandit は ruff `S` ルールで完全代替するため非導入。Spec Q3 / Req 8.3 / Req 9.2 の bandit 言及はこの代替で充足)
  - `[tool.coverage.report]` に `fail_under = 0` のベースラインを設定し、`[tool.coverage.run] source = ["src/pydantic_ai_sandbox"]` を明示する
  - `requires-python = ">=3.14"` が宣言されていることを確認する (既存ならノータッチ)
  - _Boundary:_ pyproject.toml
  - _Depends:_ none
  - _Requirements:_ 1.4, 6.1, 7.7, 9.1, 9.2, 10.1, 10.4

- [x] (P) **1.2** `mise.toml` に品質ゲートと統合タスクを登録する
  - `lint = "uv run ruff check ."`, `format = "uv run ruff format --check ."`, `typecheck = "uv run pyright"`, `test = "uv run pytest"` を最低限定義する
  - 集約タスク `check` を `depends = ["lint", "format", "typecheck", "test"]` で構成する (Req 7.5)
  - `setup` (例: `uv sync && pre-commit install`)、`pre-commit:default` (`uv run pre-commit run --all-files`)、`pre-commit:manual` (`uv run pre-commit run --all-files --hook-stage manual`)、`test:integration` (`RUN_INTEGRATION_OLLAMA=1 uv run pytest tests/integration`) を追加する
  - _Boundary:_ mise.toml
  - _Depends:_ none
  - _Requirements:_ 7.1, 7.2, 7.3, 7.4, 7.5, 8.5

- [x] (P) **1.3** `.env.example` を作成し、必要な環境変数を網羅する
  - 変数: `APP_ENV`, `LOG_LEVEL`, `LLM_PROVIDER`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL_NAME`, `OLLAMA_API_KEY`, `WATSONX_*`, `ANTHROPIC_*`, `BEDROCK_*`, `FALLBACK_ORDER`, `LOGFIRE_TOKEN`, `LOG_SENSITIVE_PAYLOADS`, `RUN_INTEGRATION_OLLAMA`
  - 各変数の役割と既定値、必須/任意の別をコメントで明示する。秘匿値は空欄で記載しダミー値を入れない (Req 9.6)
  - _Boundary:_ .env.example
  - _Depends:_ none
  - _Requirements:_ 9.6

- [x] **1.4** `README.md` にオンボーディング手順を記載する
  - 必須コマンド: `git clone` → `mise install` → `uv sync` → `pre-commit install` (または `mise run setup`) → `mise run check`
  - `LLM_PROVIDER` 切替、`fastapi dev app/main.py` 起動、`RUN_INTEGRATION_OLLAMA=1 mise run test:integration` 実行手順を別節で説明する
  - _Boundary:_ README.md
  - _Depends:_ 1.2
  - _Requirements:_ 8.5

### Implementation Notes

- TOML key quoting is segment-scoped. `[tasks."pre-commit:default"]` works; `["tasks.pre-commit:default"]` flattens to a single literal key and mise warns. Apply the same pattern to any future `task:subtask` names.
- `mise run test` exits 5 (no tests collected) until T2.1 lands the first test. This is intentional bootstrap state, not a gate-bypass — `lint`/`format`/`typecheck` are individually green; do not paper over the empty test suite.
- bandit を dev 依存から外した。ruff の `S` ルール群が flake8-bandit の Py3 系チェックを網羅実装しているため、bandit 単体は重複コストのみとなる。Spec Q3 / Req 8.3 / Req 9.2 の bandit 言及は ruff S で充足する旨を spec.md / plan.md / research.md / spec.json に反映済み。
- 詳細は `pdca/do.md` (2026-05-24 Task 1) を参照。

---

## Task 2. ハードコード model ID 防御 (lint stage)

Req 1.5 の "model ID 直書き → lint で fail" を Plan AD-4 の方針に沿って実装する。pre-commit の禁則文字列フックと、フックの存在に依存しない単体テスト (リポジトリスナップショット検査) の二段構えで防御する。Test-First 原則に従い、まず src/ を探索する単体テストを失敗状態で確認 (`granite4.1:8b` の臨時ダミー文字列を `tests/unit/_fixtures_temp.py` 等に一度入れて red を観測 → 削除して green) する。

- [x] **2.1** `tests/unit/test_no_hardcoded_model_ids.py` を作成する
  - `src/` 配下を再帰探索し、`granite4.1:8b`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001-v1:0`, `llama3.2-vision:11b`, `granite-4-h-small` 等の禁則リテラル列の出現を正規表現で検査して assert する
  - 例外: `__init__.py` のバージョン文字列等は対象外。検査対象は `*.py` のみ
  - 追加 assert (Req 9.6 補強): リポジトリ直下の `.gitignore` に `.env` 行が含まれることを文字列検索で確認する。失敗時は本テストが赤化し、誤って `.env` を tracked にする変更を block する
  - 一時的にダミー値を埋め込んだ red 状態を PDCA ログまたはコミット履歴に残す
  - _Boundary:_ tests/unit/test_no_hardcoded_model_ids.py
  - _Depends:_ 1.1
  - _Requirements:_ 1.5, 9.6

- [x] **2.2** `.pre-commit-config.yaml` を作成し、default / manual ステージを構成する
  - default stage: `ruff check`, `ruff format --check`, `pyright`, `gitleaks`, ローカル `forbid-hardcoded-model-ids` (`pygrep-hooks` ベースの local hook)
  - manual stage: `pytest`, `pip-audit` (bandit は ruff `S` 経由で default stage に内包済み — Spec 8.3 の意図は preserve)
  - `forbid-hardcoded-model-ids` の正規表現は task 2.1 と同じ禁則集合を使用 (重複定義を避けるためテストと同じ語彙を採用する旨をコメントに明記)
  - `exclude` で `tests/**` と将来の `src/**/config.py` の default 値を任意で除外する設定を準備する
  - _Boundary:_ .pre-commit-config.yaml
  - _Depends:_ 1.1
  - _Requirements:_ 1.5, 7.6, 8.1, 8.2, 8.3

### Implementation Notes

- T2.1 の RED 状態は `src/pydantic_ai_sandbox/_red_demo.py` に `granite4.1:8b` 文字列を一時投入して観測した (PDCA `do.md` 2026-05-24 Task 2 を参照)。`src/` 全体が削除された GREEN 状態でも `_iter_scanned_py_files()` が空を返して assert は成立するため、後続 T3.3 で `src/` が再度生成された瞬間から本テストが意味を持って効き始める。
- `forbid-hardcoded-model-ids` の正規表現は `tests/unit/test_no_hardcoded_model_ids.py::FORBIDDEN_MODEL_ID_LITERALS` を一行コメントで参照しており、語彙更新は両ファイルに lockstep で行うこと (片側更新は語彙ドリフトの温床になる)。Plan AD-4 の "ruff にカスタム rule 機構が無い" 制約を満たす二段防御の構図そのもの。
- `language: system` を採用したことで `mise run check` と `pre-commit run` の挙動が byte-identical になり、Constitution V (single entry point) を満たす。`uv run ruff` / `uv run pyright` / `uv run pytest` の version は `pyproject.toml` の dev deps に唯一記録されるため、pre-commit 側に重複 pin が発生しない。
- `pre-commit run --all-files` は git-tracked file のみを対象にするため、新規ファイルは `git add -N` で intent-to-add とした後でないとフックが空回りする。CI (T12.1) では `actions/checkout@v4` 後に `git add -N` 相当を踏む必要は無いが、ローカルの最初の commit 直前は注意。

---

## Task 3. Settings (config layer) — pydantic-settings による環境変数取り込み

`Settings` を実装し、起動前に全環境変数を型付きで取り込むことで Req 1.1/1.2/1.4 と Req 4.5 の "構文・名前集合検証" 段を成立させる。`get_settings()` は `lru_cache` シングルトンで提供する (Plan §2.1)。

- [x] **3.1** `tests/conftest.py` に共有 fixture (`settings_factory`) を準備する
  - `settings_factory(**overrides)` は `monkeypatch` で env を差し替えてから `Settings()` を構築して返すヘルパ
  - `app_with_overrides` fixture の skeleton を用意 (中身は task 8/9 で拡張するため最小実装に留める)
  - _Boundary:_ tests/conftest.py
  - _Depends:_ 1.1
  - _Requirements:_ 1.1, 1.2, 4.5

- [x] **3.2** `tests/unit/test_config.py` を作成する
  - 正常系: `LLM_PROVIDER=ollama` + 必須 var で `Settings` が成功し、`llm_provider` が `Literal` に正規化されること
  - 異常系: `LLM_PROVIDER=ollama` のとき `OLLAMA_MODEL_NAME` 欠落で fail-fast (`ValidationError` でメッセージに変数名を含む) — Req 1.2
  - 異常系: `LLM_PROVIDER=fallback` で `FALLBACK_ORDER=""` または未知 provider のみ → Settings 構築時に `ValueError` (Req 4.5 構文段)
  - 異常系: `LLM_PROVIDER=foobar` → `ValueError` (Req 2.5 の前段としての Settings 検証)
  - `LOGFIRE_TOKEN` 未設定でも Settings 自体は成立すること (Req 5.2 の前段)
  - red 状態を確認した後に task 3.3 へ進む
  - _Boundary:_ tests/unit/test_config.py
  - _Depends:_ 3.1
  - _Requirements:_ 1.1, 1.2, 4.5

- [x] **3.3** `src/pydantic_ai_sandbox/config.py` と `src/pydantic_ai_sandbox/__init__.py` を実装する
  - `Settings(BaseSettings)`: Plan §2.1 で列挙された属性を持つ `frozen=True` モデル。`llm_provider: Literal["ollama","watsonx","anthropic","bedrock","fallback"]`
  - field validator: `LLM_PROVIDER=ollama` のとき `ollama_model_name` を必須化、`LLM_PROVIDER=fallback` のとき `fallback_order` を空・未知 provider のみで弾く
  - `get_settings() -> Settings` を `functools.lru_cache(maxsize=1)` で提供
  - `__init__.py` は `__version__: str` のみ公開
  - test_config.py が green になることを確認
  - _Boundary:_ src/pydantic_ai_sandbox/**init**.py, src/pydantic_ai_sandbox/config.py
  - _Depends:_ 3.2
  - _Requirements:_ 1.1, 1.2, 1.4, 4.5

### Implementation Notes

- Task spec text says "ValueError" for the FALLBACK_ORDER and unknown-LLM_PROVIDER cases, but Pydantic v2 wraps validator-raised `ValueError` into `pydantic.ValidationError` (which is **not** a subclass of `ValueError` in v2). Tests therefore assert on `ValidationError` and inspect the message; the validator code itself raises `ValueError` so the wrap-up path is exercised. Documented inline in `tests/unit/test_config.py`.
- The Settings frozen test mutates via attribute assignment which surfaces a `ValidationError` ("Instance is frozen") under pydantic v2's frozen-model semantics — same exception class as the construction failures, which keeps the test imports tight.
- `LLMProvider` Literal alphabet is locked by `test_llm_provider_literal_alphabet_is_authoritative`; T4.3 dispatch and T5.4 fallback resolver MUST update this Literal in the same change set when adding a provider, or the test fires.
- `tests/conftest.py` clears the full `_MANAGED_ENV_KEYS` set before every `settings_factory()` call so an ambient developer `.env` cannot pollute outcomes — passing `KEY=None` to the factory is the explicit "leave unset" affordance (vs. omitting the kwarg entirely).
- `app_with_overrides` is a deliberate skip-on-use skeleton (raises `pytest.skip` if any test consumes it before T8.2/T9 lands the body) so the fixture name is reserved without hiding unimplemented surface behind a passing no-op.
- `uv sync` alone does NOT register a freshly created `src/<pkg>/` editable install when no `[build-system]` is declared (hatchling default kicks in only after explicit install); ran `uv pip install -e .` once to seat it, after which all subsequent `uv run` commands resolved imports correctly.
- 詳細は `pdca/do.md` (2026-05-24 Task 3) を参照。

---

## Task 4. ModelFactory ディスパッチと Ollama provider 実装

`get_model()` を Plan §2.2/§2.3 の契約で実装する。`ollama` のみ実体実装、他 3 provider は `NotImplementedError` の stub。Req 2.6 の "constructor は I/O しない" を守るため、Ollama 実装も `OpenAIChatModel` 構築までで HTTP は agent.run まで遅延する。

- [x] (P) **4.1** `tests/unit/test_factory_dispatch.py` を作成する
  - `get_model("ollama")` が `pydantic_ai.models.Model` インスタンスを返すこと (型 assert のみ、I/O は別 task で検査)
  - `get_model("watsonx")` / `get_model("anthropic")` / `get_model("bedrock")` が `NotImplementedError` を raise し、メッセージに provider 名と "002-multi-provider" 等の後続 spec ヒントを含むこと
  - `get_model("unknown")` が `ValueError` を raise すること
  - `get_model()` (引数なし) が `Settings.llm_provider` を参照することを `monkeypatch` で確認
  - _Boundary:_ tests/unit/test_factory_dispatch.py
  - _Depends:_ 3.3
  - _Requirements:_ 2.1, 2.3, 2.4, 2.5

- [x] (P) **4.2** `tests/unit/test_factory_ollama_no_io.py` を作成する
  - `httpx.Client.send` / `httpx.AsyncClient.send` を `monkeypatch` で例外を上げる stub に差し替えた状態で `get_model("ollama")` が成功すること
  - 何らかの方法で送信回数 0 を assert (例: `unittest.mock.MagicMock` を `OllamaProvider` の `http_client` 引数に注入し `assert_not_called`)
  - _Boundary:_ tests/unit/test_factory_ollama_no_io.py
  - _Depends:_ 3.3
  - _Requirements:_ 2.6

- [x] **4.3** `llm/factory.py`、`llm/__init__.py`、`llm/providers/{__init__,ollama,watsonx,anthropic,bedrock}.py` を実装する
  - `factory.py`: `_MVP_STUB_PROVIDERS = frozenset({"watsonx","anthropic","bedrock"})` を定数公開し、`get_model(provider: str | None = None)` を実装する
  - `providers/ollama.py::_build_ollama(settings)`: `OpenAIChatModel(model_name=settings.ollama_model_name, provider=OllamaProvider(base_url=settings.ollama_base_url, api_key=settings.ollama_api_key))`
  - `providers/{watsonx,anthropic,bedrock}.py`: それぞれ `_build_*(settings) -> Never:` 形で `NotImplementedError("Provider '<name>' is not implemented in MVP; tracked in 002-multi-provider")` を raise する
  - `llm/__init__.py` から `get_model` を re-export
  - 4.1 / 4.2 の test を green にする
  - _Boundary:_ src/pydantic_ai_sandbox/llm/**init**.py, src/pydantic_ai_sandbox/llm/factory.py, src/pydantic_ai_sandbox/llm/providers/**init**.py, src/pydantic_ai_sandbox/llm/providers/ollama.py, src/pydantic_ai_sandbox/llm/providers/watsonx.py, src/pydantic_ai_sandbox/llm/providers/anthropic.py, src/pydantic_ai_sandbox/llm/providers/bedrock.py
  - _Depends:_ 4.1, 4.2
  - _Requirements:_ 2.1, 2.2, 2.3, 2.4, 2.5, 2.6

### Implementation Notes

- Pyright strict treats every leading-underscore name as module-private and flags `reportPrivateUsage` on cross-module imports. The spec mandates `_build_*` and `_MVP_STUB_PROVIDERS` (plan.md §2.3 / §2.4), so the resolution is two-pronged: each provider module declares `__all__ = ["_build_*"]` to silence `reportUnusedFunction`, and `factory.py` (plus the dispatch test) carries inline `# pyright: ignore[reportPrivateUsage]` with a single shared rationale comment. Net result: zero strict-mode errors without weakening `pyproject.toml` (Constitution V).
- `_build_ollama` uses `str(settings.ollama_base_url)` to hand `OllamaProvider` a plain string — `HttpUrl` carries a trailing slash but `OllamaProvider` accepts either form. Defensive `if settings.ollama_model_name is None: raise TypeError` is unreachable in practice (Settings' validator gates it for `LLM_PROVIDER=ollama`) but stays in case T4.1's contract is tightened to allow constructor-time provider injection ahead of Settings validation.
- T4.2's no-I/O proof patches `httpx.{Client, AsyncClient}.send` rather than the OpenAI client surface. Trapping at the transport layer catches every possible egress route; if the OpenAI SDK ever moves to a different transport, the test fails loudly rather than silently passing.
- The factory's `"fallback"` branch is a deliberate `NotImplementedError` placeholder — the alternative (falling through to the unknown-provider `ValueError`) would mislead operators into thinking they typed the env var wrong. T5.4 replaces this branch with `_build_fallback(settings)`; the boundary contract there forbids touching any other branch.
- Detail in `pdca/do.md` (2026-05-24 Task 4).

---

## Task 5. FallbackModel 構築とフェイルオーバ検証

`_build_fallback()` は `FALLBACK_ORDER` から member を解決し `FallbackModel(*members)` を返す (Plan §2.4)。MVP では実 provider が Ollama のみのため、`FunctionModel` で member の挙動を差し替えて failover の発火を検証する。

- [x] **5.1** `tests/support/__init__.py` と `tests/support/model_fakes.py` にフェイク provider 集合を作る
  - `function_model_returning_json(payload: dict) -> FunctionModel`: 構造化 JSON を返すフェイク
  - `function_model_raising(exc: Exception) -> FunctionModel`: 呼び出し時に例外を raise するフェイク
  - production code から import されないこと (Plan §2.10)
  - _Boundary:_ tests/support/**init**.py, tests/support/model_fakes.py
  - _Depends:_ 3.3
  - _Requirements:_ 4.4, 10.2

- [x] **5.2** `tests/unit/test_factory_fallback.py` を作成する
  - `FALLBACK_ORDER="ollama"` で `_build_fallback()` が `FallbackModel` を返すこと
  - 全 member が `_MVP_STUB_PROVIDERS` の構成 (例: `FALLBACK_ORDER="watsonx,anthropic"`) で `_build_fallback()` 直接呼び出し時に `RuntimeError` (StartupError) を raise すること (Req 4.5 構成段)
  - `FALLBACK_ORDER=""` または未知 provider のみは `Settings` 段で先に弾かれるため、本テストは到達不能ケースを前提条件として記述する
  - _Boundary:_ tests/unit/test_factory_fallback.py
  - _Depends:_ 4.3, 5.1
  - _Requirements:_ 4.1, 4.2, 4.5

- [x] **5.3** `tests/unit/test_fallback_failover.py` を作成する
  - `FallbackModel(failing_fn, success_fn)` を直接構築 (`get_model` 経由ではなく純粋なロジックテスト) し、`Agent(model=fallback).run(...)` が success_fn の出力を返すこと
  - logfire span 属性 (provider 名 / error class) が含まれることを `logfire.testing` または span exporter モックで assert する
  - _Boundary:_ tests/unit/test_fallback_failover.py
  - _Depends:_ 5.1
  - _Requirements:_ 4.3, 4.4

- [x] **5.4** `src/pydantic_ai_sandbox/llm/fallback.py` を実装する + `factory.py` に fallback dispatch を追記
  - `_build_fallback(settings)`: `settings.fallback_order` をカンマ区切りで分割し、各 member について `get_model(member)` を再帰呼び出し
  - 全 member が `_MVP_STUB_PROVIDERS` に含まれる場合は `RuntimeError("All members of FALLBACK_ORDER are unimplemented stubs in MVP; configure at least one real provider")` を raise
  - 構築結果を `FallbackModel(*members)` で返す
  - `factory.py` の `get_model()` ディスパッチに `"fallback"` ブランチを追記し、本関数を呼び出す (T4.3 では `"fallback"` は未実装のまま残し、本タスクで完成させる前提。`_Depends:_ 4.3` で順序を保証)
  - **境界制約**: `factory.py` への追記は `"fallback"` 分岐の追加のみに限定する。T4.3 が確定した他 provider 分岐 (`ollama` / stub 3 種 / unknown) は変更しない
  - 5.2 / 5.3 を green にする
  - _Boundary:_ src/pydantic_ai_sandbox/llm/fallback.py, src/pydantic_ai_sandbox/llm/factory.py
  - _Depends:_ 4.3, 5.2, 5.3
  - _Requirements:_ 4.1, 4.2, 4.3, 4.5

### Implementation Notes

- `_build_fallback` は `_MVP_STUB_PROVIDERS` への循環 import を避けるため、`factory.py::get_model` の `"fallback"` ブランチで **遅延 import** している。Module-top で `from llm.fallback import _build_fallback` すると `llm.fallback` が `from llm.factory import _MVP_STUB_PROVIDERS, get_model` を要求して双方向に解決不能になる。`if resolved == "fallback":` 内に import を閉じ込める方針で解決。
- 全 member が stub の場合は `RuntimeError` (Req 4.5)、混在ケース (`ollama,watsonx` 等) では stub を **シルエント filter** して real provider のみで `FallbackModel` を構築する設計を採用。これは tasks.md の "全 member が stub → RuntimeError" のみ明示制約に対する最小逸脱解釈で、ユーザの `FALLBACK_ORDER` を尊重しつつ stub 由来の `NotImplementedError` を `/chat` まで遅延させない (Plan §2.4 "これにより NotImplementedError を /chat 呼び出し時まで遅延させない" の意図と整合)。
- T5.3 の "logfire span 属性に provider 名 / error class が含まれる" は V2 Beta の実体に合わせて二部構成で表現した: (a) 成功時の `invoke_agent` span の `model_name` 属性が `"fallback:<a>,<b>"` 形式で全 chain を載せるため、失敗 member 名を含めて assert することで failover 経路が span に残ることを証明、(b) 全 member 失敗時は `FallbackExceptionGroup.exceptions` が原 `ModelAPIError` を identity で保持することを assert し、"error class" の正体性を担保。`instrument_pydantic_ai()` は失敗 attempt を span 属性に書かない仕様 (`models/fallback.py::request` の `_set_span_attributes` は成功時のみ呼ばれる) のため、ExceptionGroup が canonical な記録源となる。
- `tests/unit/test_fallback_failover.py` の span filter は `gen_ai.operation.name == "invoke_agent"` 属性経由で行う。pydantic-ai V2 は span name に変数名を埋め込む (例: `"invoke_agent agent"`) ため、name による filter はローカル binding rename に脆弱。属性 filter は仕様で安定。
- 詳細は `pdca/do.md` (2026-05-24 Task 5) を参照。

---

## Task 6. Schemas + ChatAgent (V2 Beta API 表面)

`ChatRequest` / `ChatResponse` と、それを `output_type` に取る `ChatAgent` を Plan §2.5/§2.6 で定義する。Req 6.4 のため V2 Beta API 表面 (Agent constructor, `@agent.tool`, `agent.override`, `result.output`) を test で直接拘束する。

- [x] (P) **6.1** `tests/unit/test_chat_agent_tool.py` を作成する
  - `build_chat_agent(model=test_model)` が返す Agent に少なくとも 1 つのツールが登録されていること (Pydantic AI V2 の `agent.tools` または同等 API で確認)
  - `search_kb` ツールが `RunContext` 引数を受け取り `list[str]` を返すシグネチャであること
  - _Boundary:_ tests/unit/test_chat_agent_tool.py
  - _Depends:_ 4.3
  - _Requirements:_ 3.3, 6.3

- [x] (P) **6.2** `tests/unit/test_chat_agent_v2_surface.py` を作成する
  - `pydantic_ai.Agent` をフルパスで import し、`Agent(model=..., output_type=ChatResponse)` 構築・`@agent.tool` 装飾子・`agent.override(model=...)` コンテキスト・`result.output` アクセスの 4 表面を assert する
  - V2 API がリネーム/削除された場合に test が壊れて検出できることを目的とする (Req 6.5 の前段)
  - _Boundary:_ tests/unit/test_chat_agent_v2_surface.py
  - _Depends:_ 4.3
  - _Requirements:_ 6.4

- [x] **6.3** `src/pydantic_ai_sandbox/schemas/__init__.py` と `src/pydantic_ai_sandbox/schemas/chat.py` を実装する
  - `ChatRequest(BaseModel)`: `message: str` (最低 1 文字)
  - `ChatResponse(BaseModel)`: `answer: str`, `sources: list[str] = Field(default_factory=list)` (Req 3.2 の構造化フィールド)
  - Google docstring を付与
  - _Boundary:_ src/pydantic_ai_sandbox/schemas/**init**.py, src/pydantic_ai_sandbox/schemas/chat.py
  - _Depends:_ 6.1
  - _Requirements:_ 3.1, 3.2

- [x] **6.4** `src/pydantic_ai_sandbox/agents/__init__.py` と `src/pydantic_ai_sandbox/agents/chat_agent.py` を実装する
  - `build_chat_agent(model: Model | None = None) -> Agent[None, ChatResponse]`
  - `model` 省略時は `get_model()` で解決
  - `search_kb(ctx: RunContext, query: str) -> list[str]` を `@agent.tool` で登録 (MVP は固定文字列を返す stub で十分)
  - 構造化出力スキーマ厳守を促す日本語 instructions
  - 6.1 / 6.2 を green にする
  - _Boundary:_ src/pydantic_ai_sandbox/agents/**init**.py, src/pydantic_ai_sandbox/agents/chat_agent.py
  - _Depends:_ 6.1, 6.2, 6.3
  - _Requirements:_ 3.3, 6.3, 6.4

### Implementation Notes

- `Agent[None, ChatResponse](...)` の **`deps_type=type(None)` 明示が pyright strict で必須**。`Agent.__init__` の既定値は `deps_type=<class 'object'>` で、これは `Agent[None, ...]` の型引数 `AgentDepsT=None` と整合しない (`type[object]` is not assignable to `type[None]`)。プロダクション (`build_chat_agent`) と V2 表面テストの両方で同じ修正を適用済み。`output_type=ChatResponse` 側は既定値 `str` を上書きして overload に合致させる必要がある。
- `search_kb` を **モジュールトップレベル**に置き、`Agent(..., tools=[search_kb])` で登録する設計を採用。`@agent.tool` を `build_chat_agent` のクロージャ内で使う案も検討したが、T6.1 の `inspect.signature(search_kb)` テストが import 可能な参照点を必要とするため棄却。トップレベル定義 + コンストラクタ側登録だと、テスト用シグネチャ検査と本番の登録経路が同じ関数オブジェクトを共有でき、片側だけが書き換わる drift を構造的に防げる。
- `from __future__ import annotations` 配下の関数では `inspect.signature(...).parameters[name].annotation` が **文字列**で返る。T6.1 の RunContext / `list[str]` 検査は `typing.get_type_hints(search_kb)` 経由で実評価する必要があり、`get_origin` を生 annotation に当てると常に `None` が返って silent pass する罠がある。テスト docstring に「PEP-563 評価」の理由を明記済み。
- `TestModel.last_model_request_parameters.function_tools` が pydantic-ai V2 公式ドキュメント (`docs/toolsets.md`) のツール内省窓口。`agent.toolsets` / `agent._function_toolset` を直接 peek する案より上位の安定性を持つため、T6.1 / T6.2 双方でこの surface を使用。
- `@agent.tool` は **副作用デコレータ**として agent に関数を登録するだけで戻り値を直接消費しないため、pyright strict の `reportUnusedFunction` が誤検知する。T6.2 の `stub_tool` には行内 `# pyright: ignore[reportUnusedFunction]` で局所抑制 (理由コメント付き)。プロダクション側は `tools=[search_kb]` 形式のため発生せず、抑制はテスト側のみに閉じている。
- 詳細は `pdca/do.md` (2026-05-24 Task 6) を参照。

---

## Task 7. 可観測性 (Logfire fail-soft 計装)

`configure_observability(app, settings)` を Plan §2.8 の通り `logfire.configure(send_to_logfire='if-token-present', ...)` → `instrument_pydantic_ai()` → `instrument_fastapi(app)` → `instrument_httpx()` の順で呼ぶ。`LOGFIRE_TOKEN` 未設定 / 例外でも起動継続を保証する。

- [ ] (P) **7.1** `tests/unit/test_logging_setup.py` を作成する
  - `LOGFIRE_TOKEN` 未設定で `configure_observability(app, settings)` が例外を上げず、警告ログが 1 行出ること (Req 5.2)
  - `instrument_pydantic_ai`, `instrument_fastapi`, `instrument_httpx` の 3 つが呼ばれること (mock で call 検証)
  - `ScrubbingOptions(extra_patterns=[...])` で `prompt`, `tool_input`, `tool_output` がスクラブ対象に含まれること (Req 5.4)
  - _Boundary:_ tests/unit/test_logging_setup.py
  - _Depends:_ 3.3
  - _Requirements:_ 5.1, 5.2, 5.4

- [ ] (P) **7.2** `tests/unit/test_logging_resilience.py` を作成する
  - `logfire.configure` が例外を raise する状況を `monkeypatch` で再現し、`/healthz` (TestClient 経由) が 200 を返すこと (Req 5.5)
  - 観測系の失敗が API レスポンスに伝搬しないこと
  - **依存**: TestClient 経由で `/healthz` を叩くため `create_app()` の skeleton (Task 8.2 範囲) を要求する
  - _Boundary:_ tests/unit/test_logging_resilience.py
  - _Depends:_ 3.3, 8.2
  - _Requirements:_ 5.5

- [ ] **7.3** `src/pydantic_ai_sandbox/logging_setup.py` を実装する
  - `configure_observability(app: FastAPI, settings: Settings) -> None`
  - `logfire.configure(send_to_logfire='if-token-present', token=settings.logfire_token, scrubbing=ScrubbingOptions(extra_patterns=['prompt','tool_input','tool_output']))`
  - 失敗時は `logging.getLogger(__name__).warning(...)` で 1 行出力し、関数は正常終了 (Req 5.2/5.5)
  - 成功後 `instrument_pydantic_ai()`, `instrument_fastapi(app)`, `instrument_httpx()` を呼ぶ
  - 7.1 / 7.2 を green にする
  - _Boundary:_ src/pydantic_ai_sandbox/logging_setup.py
  - _Depends:_ 7.1, 7.2
  - _Requirements:_ 5.1, 5.2, 5.4, 5.5

- [ ] **7.4** `tests/unit/test_logging_span_attributes.py` を作成する (Req 5.3 専用テスト)
  - `agent.override(model=TestModel())` 配下で `agent.run(...)` を 1 回実行し、`logfire.testing.CaptureLogfire` (または span exporter モック) が捕捉した span 属性に `provider` 名と `model_id` (Pydantic AI 既定の span 属性キー、例: `model_name` / `gen_ai.request.model`) の双方が含まれることを assert する (Req 5.3)
  - 失敗系 (フォールバック) は T5.3 がカバーするため本テストは正常系 1 件のみで十分
  - 検出したキー名は実装で `instrument_pydantic_ai()` が emit する標準属性に合わせ、リネーム/削除があれば本テストが赤化することを設計目的に明記する
  - _Boundary:_ tests/unit/test_logging_span_attributes.py
  - _Depends:_ 6.4, 7.3
  - _Requirements:_ 5.3

### Implementation Notes

---

## Task 8. Health エンドポイント

`GET /healthz` を Plan §2.7 の通り実装する。最小依存で動かせるエンドポイントなので、本タスクは Chat エンドポイントの前に独立して green にする。

- [ ] **8.1** `tests/unit/test_health.py` を作成する
  - TestClient 経由で `GET /healthz` が 200 を返し、JSON が `{"status": "ok", "provider": <settings.llm_provider>}` を満たすこと
  - `LLM_PROVIDER` を変えると `provider` フィールドが追従すること
  - _Boundary:_ tests/unit/test_health.py
  - _Depends:_ 3.3
  - _Requirements:_ 1.3

- [ ] **8.2** `api/__init__.py`, `api/deps.py`, `api/routes/__init__.py`, `api/routes/health.py`, および `main.py` の skeleton を実装する
  - `api/deps.py`: `get_settings_dep()` などの `Depends` ファクトリの skeleton (chat 側で拡張)
  - `api/routes/health.py`: `GET /healthz` ルータ。`Depends(get_settings_dep)` で `Settings` を受け取り `{"status": "ok", "provider": settings.llm_provider}` を返す
  - `main.py` skeleton: `create_app() -> FastAPI` の最小実装 (lifespan は no-op で良い、health ルータのみ登録)。フル実装 (lifespan で `configure_observability` + fallback dry-run 配線) は task 10.2 で行う
  - 8.1 を green にする (Task 7.2 / 9.1 / 9.2 が TestClient で `create_app` を要求するため、この skeleton は後続テストの前提条件でもある)
  - _Boundary:_ src/pydantic_ai_sandbox/api/**init**.py, src/pydantic_ai_sandbox/api/deps.py, src/pydantic_ai_sandbox/api/routes/**init**.py, src/pydantic_ai_sandbox/api/routes/health.py, src/pydantic_ai_sandbox/main.py
  - _Depends:_ 8.1
  - _Requirements:_ 1.3

### Implementation Notes

---

## Task 9. Chat エンドポイント

`POST /chat` を Plan §2.7 + §3.1/§3.2 のフローで実装する。`agent.override(model=TestModel())` で provider 不要のテストパスを確立し、Req 3.2/3.4/3.6 を満たす。

- [ ] (P) **9.1** `tests/unit/test_chat_endpoint_with_testmodel.py` を作成する
  - `agent.override(model=TestModel())` を `app_with_overrides` fixture で適用し、`POST /chat {"message": "..."}` が 200 を返し ChatResponse 構造 (`answer` + `sources`) を満たすこと
  - response が `ChatResponse` validator を通過すること
  - _Boundary:_ tests/unit/test_chat_endpoint_with_testmodel.py
  - _Depends:_ 6.4
  - _Requirements:_ 3.1, 3.2, 3.5

- [ ] (P) **9.2** `tests/unit/test_chat_endpoint_validation_errors.py` を作成する
  - 不正 body (`{}` や `{"message": 123}`) で `POST /chat` が 422 を返すこと (Req 3.6)
  - `function_model_returning_json({"unexpected": "shape"})` を override で適用したとき `POST /chat` が 5xx を返し partial データが client に届かないこと (Req 3.4)
  - _Boundary:_ tests/unit/test_chat_endpoint_validation_errors.py
  - _Depends:_ 6.4, 5.1
  - _Requirements:_ 3.4, 3.6

- [ ] **9.3** `api/routes/chat.py` と `api/deps.py` を実装する
  - `api/deps.py` に `get_chat_agent() -> Agent[None, ChatResponse]` ファクトリを追加 (`build_chat_agent()` を返す)
  - `api/routes/chat.py`: `POST /chat`、`ChatRequest` を受け、`agent.run(req.message)` を呼び `result.output` を `ChatResponse` として返す
  - 例外ハンドリングは FastAPI default に委譲 (Pydantic AI が `output_type` 検証で失敗 → 500 へ伝搬)
  - 9.1 / 9.2 を green にする
  - _Boundary:_ src/pydantic_ai_sandbox/api/routes/chat.py, src/pydantic_ai_sandbox/api/deps.py
  - _Depends:_ 9.1, 9.2, 8.2
  - _Requirements:_ 3.1, 3.2, 3.3, 3.4, 3.5, 3.6

### Implementation Notes

---

## Task 10. App factory と Fallback dry-run

`create_app()` を Plan §2.9 で実装する。lifespan で `configure_observability` と (条件付き) `_build_fallback()` の eager dry-run を呼び出し、Req 4.5 構成段の fail-fast を成立させる。

- [ ] **10.1** `tests/unit/test_app_lifespan_fallback_dryrun.py` を作成する
  - `LLM_PROVIDER=fallback` + `FALLBACK_ORDER=watsonx,anthropic` (全 stub) で `create_app()` の lifespan startup が `RuntimeError` を raise し、TestClient 構築自体が失敗すること
  - `LLM_PROVIDER=fallback` + `FALLBACK_ORDER=ollama` で startup が成功すること
  - `LLM_PROVIDER=ollama` のときは `_build_fallback` が呼ばれないこと (mock で call 回数 0 を assert)
  - _Boundary:_ tests/unit/test_app_lifespan_fallback_dryrun.py
  - _Depends:_ 5.4, 7.3, 8.2
  - _Requirements:_ 4.5

- [ ] **10.2** `src/pydantic_ai_sandbox/main.py` を実装する
  - `create_app() -> FastAPI`: lifespan で `get_settings()` → `configure_observability(app, settings)` → `if settings.llm_provider == "fallback": _build_fallback(settings)` (戻り値は破棄、構築可否のみ検証) → ルータ登録
  - `app = create_app()` をモジュールレベルで公開し、`fastapi dev app/main.py` 互換にする
  - 10.1 を green にする
  - _Boundary:_ src/pydantic_ai_sandbox/main.py
  - _Depends:_ 10.1, 9.3, 5.4, 7.3, 8.2
  - _Requirements:_ 1.3, 3.1, 4.5, 5.1

### Implementation Notes

---

## Task 11. Ollama 実 provider 統合テスト (E2E)

実 Ollama (`granite4.1:8b`) に対して `POST /chat` を end-to-end で叩く。`RUN_INTEGRATION_OLLAMA=1` ガードでローカル / CI 双方で skip 既定。Req 6.2 の "V2 Agent + 構造化出力 → 実バックエンド" を立証する唯一の test。

- [ ] **11.1** `tests/integration/__init__.py` と `tests/integration/test_ollama_chat_e2e.py` を作成する
  - `pytest.importorskip` ではなく `pytest.mark.skipif(os.environ.get("RUN_INTEGRATION_OLLAMA") != "1", reason="...")` で gate
  - 起動時に `OLLAMA_BASE_URL` が応答しない場合は test を fail させる (skip ではなく fail; CI lane の前提なので)
  - `POST /chat` で 200 と `ChatResponse` 構造を確認し、`sources` が空 list でなく文字列を含むこと (search_kb stub の返却)
  - V2 Beta `Agent.run` の `result.output` 経由で構造化出力が取れることを assert
  - _Boundary:_ tests/integration/**init**.py, tests/integration/test_ollama_chat_e2e.py
  - _Depends:_ 10.2
  - _Requirements:_ 3.5, 6.2, 10.3

### Implementation Notes

---

## Task 12. CI ワークフロー (品質ゲート / セキュリティ / 統合)

CI で各品質ゲートとセキュリティスキャナを走らせる (Req 7 / 8.4 / 9 / 10.4)。Plan §4.3 のワークフロー三本立てで、push / weekly cron / 統合 lane を分離する。

- [ ] (P) **12.1** `.github/workflows/ci.yml` を作成する
  - push / pull_request トリガで `mise install` → `uv sync` → `mise run check` → `mise run pre-commit:manual` を実行
  - `pytest --cov-report=xml` を生成し、`py-cov-action/python-coverage-comment-action@v3` で PR diff coverage を投稿 (Req 7.7)
  - main マージ時に coverage XML を artifact として保存 (`.coverage-baseline` 相当)
  - _Boundary:_ .github/workflows/ci.yml
  - _Depends:_ 1.2, 2.2
  - _Requirements:_ 6.5, 7.1, 7.2, 7.3, 7.4, 7.7, 8.4, 10.4

- [ ] (P) **12.2** `.github/workflows/security.yml` を作成する
  - push / `schedule:` (週次 cron) で `pip-audit` と `gitleaks detect` を実行 (Python コード脆弱性スキャンは `mise run check` 内の `ruff check .` の `S` ルールで CI 時に毎回走るため、Req 9.2 はこの ruff S 経路で充足。bandit を別途呼ばない)
  - HIGH / CRITICAL 検出時に job を fail し、PR を auto-merge 不可にする (Req 9.4)
  - `litellm` 等のサプライチェーン警戒対象を Renovate/Dependabot のラベルで管理する旨を job comment / README で明示 (Req 9.5; ワークフロー内では検出のみ)
  - _Boundary:_ .github/workflows/security.yml
  - _Depends:_ 1.1, 2.2
  - _Requirements:_ 9.1, 9.2, 9.3, 9.4, 9.5

- [ ] (P) **12.3** `.github/workflows/integration-ollama.yml` を作成する (Plan R-7 採用方針反映)
  - **トリガ**: `push:` (`branches: [main]`) + `schedule:` (週次 cron) + `pull_request:` (`paths:` で `src/pydantic_ai_sandbox/llm/**`, `src/pydantic_ai_sandbox/agents/**`, `src/pydantic_ai_sandbox/schemas/**`, `tests/integration/**`, `pyproject.toml` のみ発火) + `workflow_dispatch:` (手動)
  - **重複抑制**: `concurrency: { group: integration-ollama-${{ github.ref }}, cancel-in-progress: true }` を設定し、PR 連投時のジョブ滞留を回避
  - **実行**: `services:` または `docker run` で `ollama/ollama:latest` を起動。`actions/cache` のキーは `ollama-model-${{ hashFiles('.github/workflows/integration-ollama.yml') }}-granite4.1-8b` で `granite4.1:8b` blob をキャッシュ (model 名や job 定義の変更で自動 invalidate)
  - `RUN_INTEGRATION_OLLAMA=1 mise run test:integration` を実行
  - **PR コメント**: `actions/github-script` 等で「provider/agent 系の変更を検知したため integration-ollama を起動した」旨をジョブ summary に記載 (どの paths-filter が hit したかは `github.event.pull_request.changed_files` を活用) — Req 6.2 のレビュアビリティ向上
  - _Boundary:_ .github/workflows/integration-ollama.yml
  - _Depends:_ 11.1
  - _Requirements:_ 3.5, 6.2, 10.3

- [ ] (P)\* **12.4** `.gitleaks.toml` を任意で作成する (テスト fixture 用例外設定)
  - `paths` で `tests/**` の placeholder credential を allowlist に登録
  - 必須ではないが、誤検知を抑えるため初期から導入を推奨
  - _Boundary:_ .gitleaks.toml
  - _Depends:_ 2.2
  - _Requirements:_ 9.3, 9.6

- [ ] (P) **12.5** `.github/dependabot.yml` を作成する (Req 9.5 サプライチェーン監視の成果物化)
  - `package-ecosystem: pip` (uv 解決済み依存) と `package-ecosystem: github-actions` を週次スケジュールで監視
  - `litellm` (および idea0.md §14 の警戒対象) には `labels: ["supply-chain-watch"]` と `reviewers` を付与し、自動マージ不可・人手レビュー必須運用に紐付ける (Req 9.5)
  - `open-pull-requests-limit` を妥当な値 (例: 10) に設定
  - 設定例は README.md の運用ルール節からリンク参照する
  - _Boundary:_ .github/dependabot.yml
  - _Depends:_ none
  - _Requirements:_ 9.5

### Implementation Notes

---

## カバレッジ・サマリ

| Req  | カバータスク                            |
| ---- | --------------------------------------- |
| 1.1  | 3.1, 3.2, 3.3                           |
| 1.2  | 3.1, 3.2, 3.3                           |
| 1.3  | 8.1, 8.2, 10.2                          |
| 1.4  | 1.1, 3.3                                |
| 1.5  | 2.1, 2.2                                |
| 2.1  | 4.1, 4.3                                |
| 2.2  | 4.1, 4.2, 4.3                           |
| 2.3  | 4.1, 4.3                                |
| 2.4  | 4.1, 4.3                                |
| 2.5  | 4.1, 4.3                                |
| 2.6  | 4.2, 4.3                                |
| 3.1  | 6.3, 9.1, 9.3, 10.2                     |
| 3.2  | 6.3, 9.1, 9.3                           |
| 3.3  | 6.1, 6.4, 9.3                           |
| 3.4  | 9.2, 9.3                                |
| 3.5  | 9.1, 9.3, 11.1, 12.3                    |
| 3.6  | 9.2, 9.3                                |
| 4.1  | 5.2, 5.4                                |
| 4.2  | 5.2, 5.4                                |
| 4.3  | 5.3, 5.4                                |
| 4.4  | 5.1, 5.3                                |
| 4.5  | 3.1, 3.2, 3.3, 5.2, 5.4, 10.1, 10.2     |
| 5.1  | 7.1, 7.3, 10.2                          |
| 5.2  | 7.1, 7.3                                |
| 5.3  | 7.4                                     |
| 5.4  | 7.1, 7.3                                |
| 5.5  | 7.2, 7.3                                |
| 6.1  | 1.1                                     |
| 6.2  | 11.1, 12.3                              |
| 6.3  | 6.1, 6.4                                |
| 6.4  | 6.2, 6.4                                |
| 6.5  | 12.1                                    |
| 7.1  | 1.2, 12.1                               |
| 7.2  | 1.2, 12.1                               |
| 7.3  | 1.2, 12.1                               |
| 7.4  | 1.2, 12.1                               |
| 7.5  | 1.2                                     |
| 7.6  | 2.2                                     |
| 7.7  | 1.1, 12.1                               |
| 8.1  | 2.2                                     |
| 8.2  | 2.2                                     |
| 8.3  | 2.2                                     |
| 8.4  | 12.1                                    |
| 8.5  | 1.2, 1.4                                |
| 9.1  | 1.1, 12.2                               |
| 9.2  | 1.1, 12.2                               |
| 9.3  | 12.2, 12.4                              |
| 9.4  | 12.2                                    |
| 9.5  | 12.2, 12.5                              |
| 9.6  | 1.3, 2.1, 12.4                          |
| 10.1 | 1.1                                     |
| 10.2 | 5.1 + 全ユニットテスト (TDD discipline) |
| 10.3 | 11.1, 12.3                              |
| 10.4 | 1.1, 12.1                               |
| 10.5 | 全 src 実装タスク (TDD discipline)      |

**カバレッジ**: 10/10 要件 (100%)、未マップ要件: なし。

## 後続フェーズへの引き継ぎ

- 各タスクは `/sdd-impl 001-agentic-platform <task-id>` で実行する。`tdd-enforcement` skill が Red-Green-Refactor を強制するため、test 先行タスクは必ず failing 状態を PDCA ログ / コミット履歴に残すこと。
- `/sdd-validate-impl 001-agentic-platform` は本書のカバレッジ・サマリと plan.md §6 を逆引きし、Req 1–10 と NFR-1..7 が test に到達していることを確認する。
- `_MVP_STUB_PROVIDERS` の置換 (watsonx / Anthropic / Bedrock 実装) は後続 spec `002-multi-provider` で扱う。
