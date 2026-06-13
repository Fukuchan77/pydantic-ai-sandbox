# 006-2a-cross-platform — PDCA: Do（2026-06-13）

実装の進捗・計画からの逸脱・実測知見を記す。

## Task 1.1 — 契約パッケージの骨組み

### 実施

- `patterns/contracts/` を新設し境界4ファイルを作成:
  `pyproject.toml`（pydantic のみ runtime 依存 / `requires-python >=3.13` /
  hatchling / レーン同型の ruff・pyright ミラー / first-party
  `patterns_contracts`）、`.python-version`=3.13、`README.md`（パッケージ概要・
  import 面・正本との関係）、空再エクスポート `src/patterns_contracts/__init__.py`
  （docstring + `__all__: list[str] = []`）。

### TDD（RED→GREEN）

- Task 1.1 の境界に test ファイルは含まれない（drift test は Task 2.3 所有）ため、
  実行可能ゲートとして `import patterns_contracts` の RED→GREEN を採用。
  - RED: skeleton 作成前 `uv run python -c "import patterns_contracts"`
    → `ModuleNotFoundError: No module named 'patterns_contracts'`。
  - GREEN: `uv sync --all-groups` 後に同コマンドが `import ok; __all__ = []`。

### 検証ゲート（実測）

- `uv run ruff check .` → All checks passed
- `uv run ruff format --check .` → 1 file already formatted
- `uv run pyright`（strict / 3.13）→ 0 errors, 0 warnings, 0 informations
- `uv build` → wheel + sdist 生成成功（packaging 構成の妥当性確認）

### 計画からの逸脱・知見

- なし（plan.md File Structure Plan どおり）。
- `uv sync` の副産物として `patterns/contracts/uv.lock` が生成済み
  （Task 1.5 の正式成果物。1.5 は未チェックのまま据え置き、到達時に再現性検証で確定）。
- `uv build` の `dist/` は root `.gitignore` の `dist/` 規則で無視されるため無害。

## Task 1.2 — routing / orchestrator-workers 契約のサブモジュール移行

### 実施

- 3レーンの既存 `contracts.py` を diff し、モデル定義は完全一致・差分は
  docstring/コメント文言のみと確認（beeai==llamaindex は完全一致、pydantic-ai は
  docstring 微差のみ）。
- 7モデルをパターン別2サブモジュールへ**フィールド無変更**で移植:
  - `routing.py`: `Route`(Literal billing/technical/general) / `RouteDecision` /
    `RoutedAnswer`
  - `orchestrator_workers.py`: `SubTask` / `TaskPlan` / `WorkerResult` /
    `OrchestratedResult`
- module docstring のみ新文脈へ更新（「単一実体 + README 正本 + drift test(2.3)」）。
  各サブモジュールに自前 `__all__` を付与（フラット再エクスポートは Task 1.4 が所有）。

### TDD（RED→GREEN）

- 境界（routing.py / orchestrator_workers.py）に test ファイルは含まれない
  （drift test は Task 2.3 所有）ため、Task 1.1 同様 `import` を実行可能ゲートに採用。
  - RED: 作成前 `from patterns_contracts.routing import ...` /
    `from patterns_contracts.orchestrator_workers import ...`
    → `ModuleNotFoundError: No module named 'patterns_contracts.routing'`（両方）。
  - GREEN: 作成後、7シンボルを import し**全モデルを instantiate**
    （`OrchestratedResult.truncated` 既定 `False` を assert）→ 成功。

### 検証ゲート（実測）

- import GREEN → `GREEN ok: 7 symbols imported + instantiated; truncated default = False`
- `uv run ruff check .` → All checks passed!
- `uv run ruff format --check .` → 3 files already formatted
- `uv run pyright`（strict / 3.13）→ 0 errors, 0 warnings, 0 informations

### 計画からの逸脱・知見

- なし（plan.md File Structure Plan の routing.py / orchestrator_workers.py どおり）。
- `__init__.py` のフラット再エクスポート（1.4）・`uv.lock` 再生成（1.5）は境界外の
  ため未着手で据え置き。現時点で `from patterns_contracts import RouteDecision` は
  未解決（想定どおり。1.4 で解消）。
- `VIRTUAL_ENV` 警告はルート .venv とパッケージ .venv の不一致由来で無害
  （uv はパッケージローカル `.venv` を正しく使用）。

## Task 1.3 — 新4パターンの契約モデルとツール抽象

### 実施

- 4サブモジュールを作成し計11シンボルを定義（フィールドは spec.md Data Model に
  忠実）:
  - `prompt_chaining.py`: `ChainStep{name,output}` / `GateOutcome{passed,detail}` /
    `ChainResult{steps, gate, final_output: str|None=None}`
  - `parallelization.py`: `Branch{index,output}` /
    `ParallelResult{variant: Literal["sectioning","voting"], branches, aggregate}`
  - `evaluator_optimizer.py`: `Iteration{index,candidate,
    verdict: Literal["pass","revise"], feedback}` /
    `OptimizationResult{iterations, final_output,
    stop_reason: Literal["passed","max_iterations"]}`
  - `autonomous_agent.py`: `AgentStep{index,tool,observation,budget_spent: int(ge=0)}` /
    `AgentRunResult{steps, final_output: str|None=None,
    stop_reason: Literal["completed","max_iterations","budget_exceeded","denied"],
    total_budget_spent: int(ge=0)}` + `Tool` Protocol（`name`/`dangerous`/`run`）+
    `ApprovalHook = Callable[[str,str],bool]`。

### 設計判断

- **Literal の配置**: `variant`/`verdict`/`stop_reason` は各々単一モデルでのみ使用
  されるため、named alias 化せずフィールド annotation に inline 配置。共有される
  `Route` のみ named alias とした 1.2 の方針、および README import 面・plan の
  再エクスポート一覧（named export 無し）と整合。ドリフト parser は inline Literal も
  抽出可能（Task 2.3 が所有）。
- **早期終了の判別性を契約で保証**: `ChainResult.final_output` / `AgentRunResult.
  final_output` を既定 `None` とし、ゲート不合格・ガードレール発火時に silent 継続
  できない契約面を確立（R3.3 / R6.2）。
- **予算の非負制約**: `budget_spent` / `total_budget_spent` に `ge=0` を付与
  （トークン数は非負、R6.1）。
- **Tool/ApprovalHook はドリフト対象外**: Protocol は `model_fields` を持たず、
  Callable エイリアスも同様。正本一致は pyright strict が担保（plan「型システムの
  責務」）。module docstring に parser スキップを明記。

### TDD（RED→GREEN）

- 境界に test ファイル無し（drift test は Task 2.3 所有）のため 1.1/1.2 同様
  `import` を実行可能ゲートに採用。
  - RED: 作成前 `from patterns_contracts.prompt_chaining import ...`（4サブモジュール）
    → `ModuleNotFoundError: No module named 'patterns_contracts.prompt_chaining'`。
  - GREEN: 11シンボル import + 全モデル instantiate + 契約面アサート
    （`final_output` 既定 `None` × 2、`ge=0` 違反 / 各 Literal 語彙外を `ValidationError`
    で棄却、`Tool` 構造的適合 + `ApprovalHook` 呼出）→ 成功。

### 検証ゲート（実測）

- GREEN → `GREEN ok: 11 symbols imported + instantiated; Literals + ge=0 + None defaults enforced`
- `uv run ruff check .` → All checks passed!
- `uv run ruff format --check .` → 7 files already formatted
- `uv run pyright`（strict / 3.13）→ 0 errors, 0 warnings, 0 informations

### 計画からの逸脱・知見

- なし（plan.md Data Model / File Structure Plan どおり）。
- フラット再エクスポート（1.4）・uv.lock 再生成（1.5）は境界外のため据え置き。
  現時点で `from patterns_contracts import ChainResult` は未解決（想定どおり、1.4 で解消）。

## Task 1.4 — フラット再エクスポート面の確立

### 実施

- `src/patterns_contracts/__init__.py` を skeleton（`__all__ = []`）から、6サブモジュール
  の全18シンボルをフラット再エクスポートする実体へ更新。import 群は6サブモジュール
  からの from-import、`__all__` は18エントリ。これにより
  `from patterns_contracts import ...` の安定 import 面が README import 面と一致。
- module docstring 末尾段落を「1.4 で populate / 現時点は何も export しない」から
  「1.4 で確立済み / submodule-agnostic な安定 import パス」へ更新。

### TDD（RED→GREEN）

- 境界（`__init__.py` 単独）に test ファイル無し（drift test は Task 2.3 所有）のため
  1.1〜1.3 と同様 `import` を実行可能ゲートに採用。
  - RED: 更新前 `from patterns_contracts import RouteDecision, ChainResult,
    AgentRunResult, Tool, ApprovalHook`
    → `ImportError: cannot import name 'RouteDecision' from 'patterns_contracts'`。
  - GREEN: 18シンボルを flat import + `set(pc.__all__)==expected`（18件）+
    全 `__all__` 要素が attribute として present を assert → 成功。

### 検証ゲート（実測）

- `uv run ruff check .` → All checks passed!
- `uv run ruff format --check .` → 7 files already formatted
- `uv run pyright`（strict / 3.13）→ 0 errors, 0 warnings, 0 informations
- `uv run pytest --no-cov` → No files found in testpaths（テスト不在、想定どおり）

### 計画からの逸脱・知見

- **RUF022 はコメント区切りセクションを尊重しない**: 当初 README import 面に倣い
  パターン別グループ化コメント付き `__all__` を書いたが、RUF022 は `__all__` 全体を
  isort 順（case-insensitive）に整列し、コメントが意味的に誤った位置へ散らばった
  （例: `ParallelResult` が `# orchestrator-workers` 直下）。誤誘導コメントは無コメント
  より悪いと判断し、グループ化コメントを廃してフラットソート1本へ統一。論理
  グルーピングの説明責務は README import 面が担う。
- I001（import ブロック整列）も発生したが `--fix` で解消（safe fix）。RUF022 のみ
  unsafe fix だったため `--unsafe-fixes` で整列後、散乱コメントを手動除去。
- `uv.lock` 再生成（1.5）は境界外のため据え置き。

## Task 1.5 — 契約パッケージ uv.lock の正式生成と再現性担保

### 実施

- 1.1 の `uv sync` 副産物として既に存在していた `patterns/contracts/uv.lock` を
  Task 1.5 の正式成果物へ昇格。`uv lock` で明示再生成し、現行 `pyproject.toml`
  （runtime: `pydantic>=2` のみ / dev group: pip-audit, pyright, pytest,
  pytest-asyncio, pytest-cov, ruff）から 44 packages を `requires-python >=3.13`
  の floor で解決。lock 内容は無変更（git `A` のまま）。

### TDD（RED→GREEN）

- 境界（`uv.lock` 単独）に test ファイル無しのため、1.1〜1.4 と同様に実行可能
  ゲート（=再現性検証コマンド）を RED→GREEN に採用。
  - RED: `mv uv.lock uv.lock.bak && uv lock --check`
    → `error: Unable to find lockfile at 'uv.lock', but '--check' was provided` /
    exit 2。ゲートが正規 lock の欠如を確実に検知する（teeth がある）ことを確認。
  - GREEN: `uv lock` で再生成 → 退避版と sha256 が**バイト一致**
    （`9c4eb4ff…f0e5`）。決定論的再生成＝再現可能であることを実証。退避版は削除。

### 検証ゲート（実測）

- `uv lock --check`（lock ↔ pyproject 整合）→ `Resolved 44 packages`, exit 0
- `uv sync --all-groups --locked`（lock から厳密インストール、改変なし）
  → `Resolved 44 packages` / `Checked 43 packages`, exit 0
- 再生成前後 sha256 一致: `9c4eb4ffbcc38100497097b054e3f9112357c94a2fb07c5ee021a8cfc123f0e5`
- `git status --short patterns/contracts/uv.lock` → `A`（内容無変更のまま staged）

### 計画からの逸脱・知見

- 逸脱なし（plan.md「lane contract wiring」§ Owns: lockfile 再生成、NFR-1 どおり）。
- 知見: lock は 1.1 時点で既に canonical（再生成で diff ゼロ）だったため、1.5 は
  「新規生成」ではなく「再現性の形式的証明 + 正式成果物化」が実体。`--locked` は
  root `.venv` に対する `VIRTUAL_ENV` 不一致 warning を出すが、contracts 配下の
  `.venv` を対象に解決・検証は正常完了（exit 0）— 無害。
- これで Major Task 1（shared-contracts パッケージ新設）の全サブタスク（1.1〜1.5）完了。
