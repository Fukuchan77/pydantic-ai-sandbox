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

---

## Task 2.1 — 新4パターン README 正本 fenced block 新設

### 実施内容

- `patterns/prompt-chaining/`・`parallelization/`・`evaluator-optimizer/`・
  `autonomous-agent/` の4ディレクトリと各 `README.md` を新設。各 README に
  `## パターン契約（正本）` を置き、`patterns_contracts` の実体と一致する正本
  ```python fenced block を記載（routing/orchestrator-workers の既存スタイル踏襲:
  bare annotation + JP インラインコメント、`Literal` はフィールド annotation 内
  インライン）。必須4セクション本文・3実装表は Task 11 が所有のため未記載。
- 正本ブロック内容（パッケージと完全一致）:
  - prompt-chaining: `ChainStep{name,output}` / `GateOutcome{passed,detail}` /
    `ChainResult{steps,gate,final_output=None}`（Literal なし）
  - parallelization: `Branch{index,output}` /
    `ParallelResult{variant:Literal["sectioning","voting"],branches,aggregate}`
  - evaluator-optimizer: `Iteration{index,candidate,verdict:Literal["pass","revise"],feedback}` /
    `OptimizationResult{iterations,final_output,stop_reason:Literal["passed","max_iterations"]}`
  - autonomous-agent: `AgentStep{index,tool,observation,budget_spent}` /
    `AgentRunResult{steps,final_output=None,stop_reason:Literal["completed","max_iterations","budget_exceeded","denied"],total_budget_spent}`
    + `Tool` Protocol / `ApprovalHook` 併記（parser スキップを本文明示）

### RED→GREEN（憲法 I）

境界の正規 drift test は Task 2.3 所有で未存在。その parser 挙動を先取り再現する
アドホック検証（`/tmp/verify_drift_2_1.py`）を RED→GREEN ゲートに採用 — README の
fenced block を `ast` でクラス単位抽出（不正 signature `model/llm`・`Tool` Protocol・
`ApprovalHook` をスキップ）し、`patterns_contracts` の `model_fields` / `Literal`
語彙と照合。

- RED: README 4件不在 → `MISSING README ×4`, exit 1（パッケージ import は成功 =
  ゲートに teeth がある）。
- GREEN: 4 README とも class/field/Literal 完全一致 → `ALL MATCH`, exit 0。
- ドリフト検知力の実証: parallelization で `aggregate→aggregated` 改名 + `voting`
  語彙除去を一時注入 → `DRIFT in parallelization`（field set / Literal 両方の差分を
  検出, exit 1）→ 復元で `ALL MATCH`（exit 0）。

### 検証ゲート（実測）

- 境界は README.md（markdown）のみ。プロジェクトに markdown linter（markdownlint/
  mdformat）・該当 test/build コマンドは未設定（正規 drift test は Task 2.3 が新設）。
  → 本タスクの意味ある検証は上記 drift-mirror ゲート（`ALL MATCH`, exit 0）。
- `patterns/contracts/` は無改変（`git status --short patterns/contracts/` 空）。
- root `mise run check` は patterns/ 除外により本変更の影響を受けない（NFR-3 / R13.2）。

### 計画からの逸脱・知見

- 逸脱なし（plan.md「docs / security / taxonomy」§ Owns: 正本 fenced block）。
- 知見: 正本ブロック抽出の曖昧性回避として所在説明の散文に literal な ```python を
  置かない（「下記の Python コードブロック」表記）。Task 2.3 parser の
  `index("```python")` 誤マッチ防止の前提を README 側で先に確立。
- 知見: drift parser は `model/llm` 等の不正 signature を含むため**全ブロック
  `ast.parse` 不可** → クラス単位の textual 抽出が必須。この設計制約を 2.1 の
  検証ハーネスで実証済み（Task 2.3 実装の前提として有効）。

## Task 2.2 — routing / orchestrator-workers README 契約所在記述の更新

### 実施内容

- `patterns/routing/README.md`・`patterns/orchestrator-workers/README.md` の
  `## パターン契約（正本）` 直下の所在記述を、新4パターン（Task 2.1）と同一の
  散文テンプレへ統一: 「契約の実体は依存ゼロの `patterns_contracts` パッケージ /
  下記 Python コードブロックが正本 / `test_contract_drift.py` が両者一致を1点検証
  （Req 2.1–2.3 / NFR-5）/ エントリ signature は parser スキップ」。
- routing は旧記述（「各レーンの `contracts.py` はこの定義の複製。ドリフトは
  ルートの `tests/unit/test_patterns_contract_sync.py` が検知」）を置換 — 旧 root
  クロス複製テストへの参照を除去（Req 1.5、その実体は Task 2.4 で削除）。
- orchestrator-workers は元々所在記述が無く、heading 直後に同テンプレを新規挿入。
- 既存正本 ```python fenced block（routing 3シンボル / orchestrator-workers 4
  シンボル + 不変条件）は**無改変**。所在記述に literal な ```python を置かない
  Task 2.1 の前提も維持。

### RED→GREEN（憲法 I）

境界の正規 drift test は Task 2.3 所有で未存在のため、その parser 挙動を先取り
再現する drift-mirror に Task 2.2 固有の prose-location アサーションを足した
アドホック検証（`/tmp/verify_drift_2_2.py`）を RED→GREEN ゲートに採用。両 README
正本ブロックを `ast`/textual でクラス単位抽出（`model/llm` 不正 signature を
スキップ）し `patterns_contracts.model_fields` / `Literal` 語彙と照合 + 所在記述の
文言を検査。

- RED: 編集前 → drift 部は ALL MATCH（正本無改変なので当然）だが prose 部が 6 件
  失敗（routing: 旧 sync-test 参照残存 / 旧「複製」記述残存 / `patterns_contracts`
  参照欠如 / `test_contract_drift.py` 参照欠如、orchestrator-workers: 新2参照欠如）、
  exit 1。ゲートに teeth がある（所在記述の差分を検知する）ことを確認。
- GREEN: 編集後 → `ALL MATCH (drift mirror) + prose location updated`, exit 0。

### 検証ゲート（実測）

- 境界は README.md（markdown）2件のみ。markdown linter / 該当 test/build は
  プロジェクト未設定（正規 drift test は Task 2.3 が新設）→ 意味ある検証は上記
  drift-mirror + prose ゲート（exit 0）。
- 正本ブロック無改変の機械確認: `git diff` 上 class/field/`async def` 行の増減は
  ゼロ（変更は所在記述の散文行のみ。routing -2/+9、orchestrator-workers +8）。
- `patterns/contracts/` は無改変（`git status --short patterns/contracts/` 空）。
- root `mise run check` は patterns/ 除外により本変更の影響を受けない（NFR-3 / R13.2）。

### 計画からの逸脱・知見

- 逸脱なし（plan.md「docs / security / taxonomy」§ Owns: 所在記述更新）。
- 知見: orchestrator-workers は旧 README に所在記述自体が無かった（routing のみ旧
  root テスト参照を持っていた）。タスク文言「契約所在記述を…へ更新」を、欠落側は
  新規挿入で充足する解釈を採り、2レーンで所在記述テンプレを対称化。
- 知見: drift-mirror 部は正本ブロック無改変ゆえ RED 時点で既に MATCH。Task 2.2 の
  実質的な RED→GREEN は prose-location アサーションが担う（ドキュメント更新タスク
  でも実行可能ゲートに teeth を持たせるための構成）。

## Task 2.3 — 単一点ドリフトテストの作成

### 実施内容

- `patterns/contracts/tests/unit/test_contract_drift.py` を新設（境界どおり1ファイル）。
  Task 2.1/2.2 で先取り実証した drift-mirror parser を正規テストへ昇格し、旧 root
  クロス複製テスト（`tests/unit/test_patterns_contract_sync.py`、削除は Task 2.4）の
  検知力を単一点へ縮約。
- **README 側パース**: 6 README（routing/orchestrator-workers/新4）の `## パターン契約`
  見出し直下 ```python fence を heading anchor で抽出（Task 11 が追加する4セクションの
  python ブロック混入に頑健）。fence 全体は entry signature の `*, model/llm` が非合法
  Python のため `ast.parse` 不可 → col-0 を境に top-level 構文へ分割し**構文単位**で
  パース。クラス（Pydantic モデル）の field 名 + inline `Literal` 語彙、module-level
  Literal alias（`Route`）を抽出。`Route` のような named alias は2パス（先に alias 収集
  → 次に `route: Route` の bare Name を解決）でパッケージ側 field-level Literal と対称化。
- **パッケージ側 introspect**: `patterns_contracts.__all__` を走査し、`BaseModel`
  サブクラスは `model_fields` + 各 field annotation の `get_origin is Literal` 判定で
  field literal を、module-level Literal alias は `_value_literal` で抽出。`Tool`
  （Protocol class, 非 BaseModel）/`ApprovalHook`（Callable, `get_origin` 非 Literal）は
  **型ベースで自然にスキップ**（plan「型システムの責務」）。
- **比較（Req 2.3 の3集合）**: クラス集合 / フィールド集合 / Literal 語彙の3テスト +
  one-class-one-README 不変条件テスト（README merge が二重定義でドリフトを隠す穴を封鎖）。

### TDD（RED→GREEN・憲法 I）

- README↔package は Task 1/2.1/2.2 で既に一致のため、新規テストは生まれながら GREEN。
  憲法 I の「赤を一度も見ていないテストは証拠でない」を満たすため、タスク指示どおり
  意図的ドリフトを一時注入して RED を成立させた。
  - RED: parallelization 正本の `variant: Literal["sectioning", "voting"]` から
    `"voting"` を一時除去 → `test_documented_literal_vocabularies_match_package` のみ
    FAILED（`{('ParallelResult','variant'): {'sectioning'}} != {... 'sectioning','voting'}`）。
    他3テストは PASSED = parser が空集合誤一致でなく**実データを抽出**しており、かつ
    `Route` alias 解決が README/package 両側で機能している証左（teeth 確認）。
  - GREEN: 注入を戻す（`git diff patterns/parallelization/README.md` 空 = 完全復元）→
    `4 passed`。

### 検証ゲート（実測, `patterns/contracts/` 配下）

- `uv run pytest tests/unit/test_contract_drift.py -q` → `4 passed in 0.06s`
- `uv run pyright`（strict / 3.13）→ `0 errors, 0 warnings, 0 informations`
- `uv run ruff check .` → `All checks passed!`
- `uv run ruff format --check .` → `8 files already formatted`
- `uv run pytest --cov` → `Total coverage: 100.00%`（floor 85% 充足。契約モジュールは
  宣言のみで import が全行を被覆）

### 計画からの逸脱・知見

- 逸脱なし（plan.md「contract drift guard」§ Owns: README パース + パッケージ
  introspect + 差分アサート。比較範囲も plan 明示の3集合に限定し Protocol/alias/
  signature を除外）。
- 知見: 当初 `import patterns_contracts` を pydantic より前に置き I001、heading 定数に
  `（正本）` を含め RUF001/002（fullwidth paren ambiguous）、`_readme_shape` が C901
  （複雑度12>10）に抵触。修正 — import 順を third-party→first-party へ、heading は
  `（正本）` を落とした ASCII-safe prefix `## パターン契約` で照合（kana/kanji は
  ambiguous 非該当のため RUF 不発火、かつ前方一致で一意特定）、`_readme_shape` を
  `_collect_named_literals` / `_collect_model` へ分割。
- 知見: pyright strict で `getattr(...)` 結果を `member: object` と明示し、
  `isinstance(member, type)` ブロック末尾で `continue` する構造にすると、フォール
  スルー時の型が `object`（`type[Unknown]` を含まない）に narrowing され
  `reportUnknownArgumentType` を回避できる（issubclass を isinstance 内へネスト）。

## Task 2.4 — 旧 root クロス複製ドリフトテストの削除（検知の単一点化）

### 実施内容

- `tests/unit/test_patterns_contract_sync.py` を `git rm` で削除。旧テストは3レーンの
  `contracts.py` 複製を `ast` で相互比較（クラス集合・フィールド集合の一致）し、Route
  Literal 語彙 `["billing", "technical", "general"]` の各レーン存在を検査する root-venv
  テストだった（Spec 005 の AD-3 由来）。Task 2.3 の単一点ドリフトテスト
  （`patterns/contracts/tests/unit/test_contract_drift.py`、README 正本↔パッケージ実体）が
  これを置換済みのため、redundant な旧テストを除去（Req 2.2）。

### TDD（RED→GREEN・憲法 I）

- 削除タスクのため新規 test は生まれない。憲法 I の「赤を見ていない検知は証拠でない」を
  満たすべく、**置換 = 検知喪失でない**ことを生存検知器の teeth 実証で担保した。
  - baseline GREEN: 生存検知器 `test_contract_drift.py` → `4 passed`。
  - RED（teeth 実証）: 削除直前に parallelization 正本（`patterns/parallelization/README.md`
    L22）の `variant: Literal["sectioning", "voting"]` から `"voting"` を一時除去 →
    `test_documented_literal_vocabularies_match_package` のみ FAILED
    （`{('ParallelResult','variant'): {'sectioning'}} != {... 'sectioning','voting'}`、
    他3 PASSED）。単一点に検知力がある証左。
  - GREEN: `git checkout -- patterns/parallelization/README.md`（diff 空 = 完全復元）→
    `4 passed`。その後 `git rm` で旧テスト削除。

### 検証ゲート（実測）

- `git ls-files --error-unmatch tests/unit/test_patterns_contract_sync.py` → tracked
  （削除前確認）。削除後 `ls` → `No such file or directory`、`git status` → `D`（staged）。
- `uv run pytest --collect-only -q`（root）→ `281 tests collected`、dangling 参照ゼロ
  （削除モジュールへの import 残存なし）。
- `mise run cov`（root 完全スイート + カバレッジゲート）→ `277 passed, 4 skipped`、
  `Total coverage: 98.83%`（floor 98% 充足）。旧テストは src/ を import せず `ast` 解析
  のみのため、削除による root カバレッジ低下はゼロ（想定どおり）。
- 生存検知器 `test_contract_drift.py`（contracts venv）→ `4 passed`。

### 計画からの逸脱・知見

- 逸脱なし（plan.md File Structure Plan: `tests/unit/test_patterns_contract_sync.py` =
  Delete、R2.2「単一点ドリフトテストへ置換」どおり）。
- 削除順序の妥当性: 旧テストは Task 3 で削除される各レーン `contracts.py` を読むため、
  置換器（2.3）確立後・レーン複製削除（3）前の本タスクが正しい削除点。今削除しないと
  Task 3 で旧テストが `FileNotFoundError` で赤化する。
- **境界外 stale 参照の申し送り**: `patterns/README.md:50-51` が旧テスト名と「契約は
  レーン間で複製」という旧アーキテクチャを記述。当該ファイルは Task 11.2 の境界
  （「contracts パッケージを注記する」）に属するため本タスクでは無改変とし、11.2 で
  集約パッケージ + 単一点ドリフトテストへの書換えを申し送り（境界規律遵守。Task 2.2 が
  routing README から旧 sync-test 参照を除去しつつ本体削除を 2.4 へ申し送ったのと対称）。
- これで Major Task 2（契約ドリフト検知の単一点化）の全サブタスク（2.1〜2.4）完了。

### Task 2.3 — adversarial-review 指摘の修正（one-README 不変条件の teeth 化）

- **指摘（HIGH）**: `test_each_package_model_is_documented_in_exactly_one_readme` が
  「同一クラスを2 README に記載した場合を検知する」と名称・コメントで明言する一方、
  `_OWNERS` が `dict[str,str]` のため重複キーが潰れ、`set(_OWNERS) == _PACKAGE.classes`
  は二重ドキュメントに対し不変 = **検知できない**ことを実証（`Branch` を
  evaluator-optimizer README へ複製注入 → 4テスト全 PASS）。
- **修正**: `_readme_shape` の `owners` を `list[tuple[str,str]]` へ変更し全
  `(class, pattern)` ペアを保持。不変条件テストを `Counter` ベースの重複検出
  （`count > 1` を列挙）+ set 一致の2段アサートへ書換え。`collections.Counter` を import。
- **RED→GREEN（憲法 I）**: 修正後に同一注入を再投入 → 当該テストのみ FAILED
  （`{'Branch': ['evaluator-optimizer', 'parallelization']}`、他3 PASSED）= teeth 確認。
  注入を `git restore` で完全除去（diff 空）→ `4 passed`。
- **検証ゲート（contracts）**: ruff All checks passed / format 8 files clean /
  pyright(strict,3.13) 0 errors / coverage 100%（floor 85%）/ pytest 4 passed。
  境界（`patterns/contracts/tests/`）内のみ改変、README 6件は無改変。

### Task 3.1 — pydantic-ai レーン契約配線（patterns_contracts パス依存）

- **RED（憲法 I）**: 「契約複製の不在」を直接実証する順序を採用。先に5 import 面
  （`__init__`/`routing`/`orchestrator_workers`/`test_routing`/`test_ollama_e2e`）を
  `patterns_contracts` へ差替 + `contracts.py` を `git rm` → 依存未配線のまま
  `uv run --no-sync pytest` → 全 collection が
  `ModuleNotFoundError: No module named 'patterns_contracts'`（5 errors）。
  旧 `patterns_pydantic_ai.contracts` も既に消えているため、緑化は新パッケージ配線
  以外では達成不能 = RED の妥当性が担保される。
- **GREEN**: `dependencies += "patterns-contracts"` + `[tool.uv.sources]
  patterns-contracts = { path="../../contracts", editable=true }` を pyproject へ追加
  → `uv lock`（72 packages resolved, `Added patterns-contracts v0.1.0`）+
  `uv sync --all-groups`（editable install）→ `uv run pytest --no-cov` →
  11 passed / 2 skipped（baseline と同一スコア = 回帰なし）。
- **import 整列の根本理解**: `patterns_contracts` は lane の `known-first-party`
  （= `patterns_pydantic_ai`）に含まれないため isort 上 third-party 扱い。
  `patterns_contracts` < `pydantic*` でソートされ third-party 群先頭、
  first-party `patterns_pydantic_ai.*` は空白行で分離。手動配置の1件ズレ
  （test_ollama_e2e.py の余分な空白行）は `ruff check --fix` で正規化。
- **境界外修正の根本原因対応（py.typed）**: pyright strict が consumer 側で
  `reportMissingTypeStubs` を5件報告。症状（lane pyright 設定の緩和 = 憲法 II 違反）
  ではなく原因を修正 — `patterns_contracts` が PEP 561 `py.typed` マーカーを欠く
  （Task 1.1 骨組みの潜在欠陥。contracts 自身の pyright は src 直読のため未検出、
  初の consumer 配線で顕在化）。`patterns/contracts/src/patterns_contracts/py.typed`
  を新設（空ファイル1点）。hatchling `packages=["src/patterns_contracts"]` が wheel へ
  自動同梱、editable では pyright が src を直読するため即時解決。Task 1 境界だが
  3.2/3.3 も同一原因でブロックされるため逐次（lazy）修正とし、tasks.md 注記で透明化。
- **検証ゲート**: pyright 0 errors / ruff All checks passed / format 11 files clean /
  coverage 95.77%（floor 85%）/ pytest 11 passed・2 skipped。
- **申し送り**: beeai（3.2）/ llamaindex（3.3）は同一手順。py.typed は本タスクで解決済み
  のため両レーンの pyright は追加対応不要（パス依存配線 + import 再ポイントのみ）。

### Task 3.2 — beeai レーン契約配線（patterns_contracts パス依存）

- **RED（憲法 I）**: 3.1 と同一順序で「契約複製の不在」を直接実証。5 import 面
  （`__init__`/`routing`/`orchestrator_workers`/`test_routing`/`test_ollama_e2e`）を
  `patterns_contracts` へ差替 + `contracts.py` を `git rm` → 依存未配線のまま
  `uv run --no-sync pytest` → 全 collection が
  `ModuleNotFoundError: No module named 'patterns_contracts'`（5 errors）。
- **GREEN**: `dependencies += "patterns-contracts"` + `[tool.uv.sources]
  patterns-contracts = { path="../../contracts", editable=true }`（beeai は元々
  `[tool.uv]` 無し → sources セクションを新規挿入）→ `uv lock`（99 packages,
  `Added patterns-contracts v0.1.0`）+ `uv sync --all-groups` →
  `uv run pytest` → 12 passed / 2 skipped（baseline 同一 = 回帰なし）。
- **import 整列**: 3.1 と同型。`patterns_contracts` は third-party 扱いで
  `beeai_framework` < `patterns_contracts` < `pydantic` にソート、first-party
  `patterns_beeai.*` は空白行で分離。今回は手置きで正順配置済み → `ruff check`
  追加 fix 不要。
- **lock メタの stale 補正（根本原因）**: `uv lock` が
  `[options] prerelease-mode = "allow"` を除去。beeai の pyproject は pydantic-ai と
  異なり `prerelease = "allow"` を宣言しないため、旧 lock の当該オプションは pyproject
  と乖離した残存メタ（過去の prerelease 許可文脈で生成された痕跡）。再生成で pyproject
  と整合する正へ補正された。パッケージ版の churn ゼロ（patterns-contracts 追加のみ）で
  NFR-1 を毀損しない — `uv lock --check`（99 packages, exit 0）/
  `uv sync --all-groups --locked`（Checked 98, exit 0）で二重確認。
- **py.typed 不要の確認**: 3.1 で新設した `patterns_contracts/py.typed` が editable
  consumer の pyright を充足するため、本レーンで境界外修正は発生せず（3.1 申し送り通り）。
- **検証ゲート**: pyright(strict,3.13) 0 errors / ruff All checks passed /
  format 10 files clean / coverage 97.32%（floor 85%）/ pytest 12 passed・2 skipped。
- **申し送り**: llamaindex（3.3）も同一手順。lock の prerelease-mode 残存有無は
  llamaindex 側でも確認推奨（同根の stale メタなら同様に補正されるが churn ゼロを検証）。

### Task 3.3 — llamaindex レーン契約配線（patterns_contracts パス依存）

- **RED（憲法 I）**: 3.1/3.2 と同一順序で「契約複製の不在」を直接実証。5 import 面
  （`__init__`/`routing`/`orchestrator_workers`/`test_routing`/`test_ollama_e2e`）を
  `patterns_contracts` へ差替 + `contracts.py` を `git rm` → 依存未配線のまま
  `uv run --no-sync pytest` → 全 collection が
  `ModuleNotFoundError: No module named 'patterns_contracts'`（5 errors）。旧
  `patterns_llamaindex.contracts` も既に消えているため緑化は新パッケージ配線以外で
  達成不能 = RED の妥当性が担保される。
- **GREEN**: `dependencies += "patterns-contracts"` + `[tool.uv.sources]
  patterns-contracts = { path="../../contracts", editable=true }`（llamaindex は beeai
  同様 `[tool.uv]` 無し → sources セクションを `[tool.hatch.build.targets.wheel]` 直後へ
  新規挿入）→ `uv lock`（103 packages resolved, `Added patterns-contracts v0.1.0`）+
  `uv sync --all-groups`（editable install）→ `uv run pytest --no-cov` →
  12 passed / 2 skipped（baseline と同一スコア = 回帰なし）。
- **import 整列（lane 固有の並び）**: `patterns_contracts` は lane の
  `known-first-party`（`patterns_llamaindex`）非該当 = third-party 扱い。src では
  `llama_index.*` < `patterns_contracts` のため workflow import 直後へ配置（first-party
  `patterns_llamaindex.*` は空白行で分離）、test では `import pytest` <
  `from patterns_contracts` < `from pydantic` の順。手置きで正順配置済 → `ruff check`
  追加 fix 不要。
- **lock メタの stale 補正（3.2 と同根）**: `uv lock` が
  `[options] prerelease-mode = "allow"` を除去。llamaindex pyproject も pydantic-ai と
  異なり `prerelease = "allow"` を宣言しないため、旧 lock の当該オプションは pyproject と
  乖離した残存メタ。`uv lock` が `allow` vs `if-necessary-or-explicit` の差を検知し
  pyproject 整合の正へ補正。パッケージ版 churn は patterns-contracts 追加のみで NFR-1 を
  毀損しない — `uv lock --check`（103 packages, exit 0）/
  `uv sync --all-groups --locked`（Checked 103, exit 0）で二重確認。
- **py.typed 不要の確認**: 3.1 で新設した `patterns_contracts/py.typed` が editable
  consumer の pyright を充足するため、本レーンで境界外修正は発生せず（3.1 申し送り通り）。
- **検証ゲート**: pyright(strict,3.13) 0 errors / ruff All checks passed /
  format 10 files clean / coverage 97.64%（floor 85%）/ pytest 12 passed・2 skipped。
- これで Major Task 3（レーン契約配線とパッケージ移行）の全サブタスク（3.1〜3.3）完了。
  3レーンとも旧 `contracts.py` を排除し `patterns_contracts` パス依存へ統一（Req 1.4/1.5）。

### Task 4.1 — pydantic-ai ターン列フェイク基盤（Req 7.1/7.2, 4.3, 5.3/5.4）

- **対象**: `patterns/frameworks/pydantic-ai/tests/support/model_fakes.py`（境界は
  本ファイル単独）。既存 `scripted_model`（schema 分岐モード）は温存し、Task 5–8 の
  pydantic-ai レーンが消費する4つの決定論モードを追加。
- **設計判断（factory 分割）**: 4モードを単一 `_respond` に詰めると mccabe C901≤10 を
  超過するため、モード毎に独立 factory（`turn_sequenced_model` / `voting_model` /
  `verdict_sequenced_model` + 値クラス `ToolTurn`/`FinalTurn` + `StubTool`）へ分割。
  - `turn_sequenced_model`: 履歴中の `ToolReturnPart` 数を turn index に採用。完了済
    ツール呼出が必ず1件 `ToolReturnPart` を残すため、ループ駆動方式（手動 / `Agent`）に
    非依存で同一台本を再現（Req 7.2）。各 turn の `tokens` を `RequestUsage(output_tokens=)`
    へ載せ、autonomous-agent の予算シーム（`ModelResponse.usage` トークン和＝
    `total_tokens`）を決定論発火可能に。台本超過は `AssertionError`（loud fail）。
  - `voting_model`: 呼出カーソルで i 回目の呼出に `branch_outputs[i]` を返却。voting
    変種が同一 prompt で全会一致になる問題を回避し分裂票（例 `["a","a","b"]`→2:1）を供給
    （Req 4.3）。同期 `_respond` は内部 await 無しのため event loop 単線上で increment は
    race-free。index↔呼出順の対応は consumer（Task 6.1）の責務として docstring に明記。
  - `verdict_sequenced_model`: 既存 `scripted_model` の schema 分岐方式を踏襲し、output
    schema に `verdict` プロパティが有れば verdict cursor（`ToolCallPart`）、無ければ
    generator text cursor（`TextPart`）。`revise→…→pass` 遷移を hermetic 再現し
    `stop_reason="passed"`（Req 5.4）と feedback 反映（Req 5.3）を offline 検証可能に。
  - `StubTool`: contracts `Tool` Protocol 準拠の決定論スタブ（`run` は canned observation）。
- **RED→GREEN（憲法 I, 境界に test 無し）**: 正規 consumer は Task 5–8 のため、Task 1.x/2.x
  と同じアドホック RED→GREEN ゲートを採用。
  - RED: 新シンボル import が `ImportError: cannot import name 'turn_sequenced_model'`（exit 1）。
  - GREEN: 4モードを決定論アサート。turn=progression(0→search/1→read/2→done)+usage(5/7/3)+
    exhaustion、voting=`["a","a","b"]`、verdict=gen`["c1","c2"]`/verdict`["revise","pass"]`、
    StubTool=run 冪等 → **ALL GREEN**。
- **根本原因対応1件（テストハーネス）**: `model.request(msgs, None, None)` が
  `prepare_request → _prepare_return_schemas` で `NoneType has no attribute 'function_tools'`。
  原因は `model_request_parameters=None`。`ModelRequestParameters()` を渡して解消（fake 本体
  でなく検証スクリプト側の誤り）。
- **境界外修正1件（pyright）**: 当初の Protocol 準拠ガードを関数形
  `def _assert_stubtool_is_tool(...) -> Tool` で書いたところ pyright strict が
  `reportUnusedFunction`。`if TYPE_CHECKING: _stubtool_is_tool: type[Tool] = StubTool`
  の module-level typed 代入へ変更し、未使用警告を出さずに構造的準拠を静的検証
  （StubTool がドリフトすれば pyright がここで失敗）。
- **coverage 非影響の確認**: `model_fakes.py` は `tests/support/` 配下で
  `[tool.coverage.run] source = ["src/patterns_pydantic_ai"]` の対象外。新コードは
  coverage 値に寄与せず 95.77%（Task 3.1 と同値）を維持。
- **検証ゲート**: ruff All checks passed / format clean / pyright(strict,3.14) 0 errors /
  pytest 11 passed・2 skipped（baseline 同一＝既存テスト無回帰）/ coverage 95.77%（floor 85%）。
- **申し送り（Task 4.2/4.3）**: beeai は `ScriptedChatModel._create` の呼出カーソル、
  llamaindex は `CustomLLM.complete/chat` の呼出カーソルで同一4モードを実装（pydantic-ai は
  履歴 `ToolReturnPart` 数、他2レーンは呼出カーソルで turn 進行＝plan 行165 の差分）。
  `verdict` 判定の output schema 形は Task 7（evaluator-optimizer）の評価器出力型に依存 —
  generator=plain text / evaluator=`verdict` プロパティ構造化、を前提とした（Task 7 で
  形が変われば微調整）。

### Task 4.2 — beeai ターン列フェイク基盤（Req 7.1/7.2, 4.3, 5.3/5.4）

- **対象**: `patterns/frameworks/beeai/tests/support/fake_chat_model.py`（境界は本ファイル
  単独）。既存 `ScriptedChatModel`（schema 分岐モード）は温存し、Task 5–8 の beeai レーンが
  消費する4モード（ターン列 / index→出力マップ / verdict cursor / ツールスタブ）を追加。
- **設計判断（クラス分割）**: beeai は `ChatModel` がクラス基底（pydantic-ai の
  `FunctionModel` factory とは異なる）。4モードを単一 `_create` に詰めると C901≤10 超過 +
  状態（cursor）共有が崩れるため、モード毎に独立クラスへ分割し共通ボイラープレートを
  `_BaseScriptedChatModel` へ集約:
  - `_BaseScriptedChatModel`: `model_id`/`provider_id`/`_create_stream`（`_create` へ委譲＝
    stream 要求時もカーソル前進が1回に固定）/ structured 既定拒否（loud-fail）を共有。
    `_create` のみ各サブクラスで実装し分岐数を C901 内に保持。
  - `TurnSequencedChatModel`: **呼出カーソル**で turn 進行（plan 行165 差分。beeai は
    pydantic-ai の `ToolReturnPart` 相当の履歴をモデル境界に露出しない）。ToolTurn→
    `AssistantMessage([MessageToolCallContent(id=f"call-{i}", tool_name, args)])`、FinalTurn→
    plain text。各 turn の `tokens` を `ChatModelUsage(total_tokens=)` に載せ autonomous-agent
    予算シームを決定論発火可能に。台本超過は `AssertionError`（loud fail）。
  - `VotingChatModel`: 呼出カーソルで i 回目に `branch_outputs[i]` を返却。voting 変種の
    全会一致問題を回避し分裂票（`["a","a","b"]`→2:1）を供給（Req 4.3）。呼出順↔branch index
    の対応は consumer（Task 6.2）の責務として docstring 明記（4.1 と同方針）。
  - `VerdictSequencedChatModel`: generator=`_create`（candidate cursor / 末尾 clamp）、
    evaluator=`_create_structure`（verdict cursor）の**メソッド分岐**で dispatch。
    `revise→…→pass` 遷移を hermetic 再現し `stop_reason="passed"`（Req 5.4）と feedback 反映
    （Req 5.3）を offline 検証可能に。output schema 形に非依存（4.1 申し送りの schema-property
    脆さを回避 — Task 7 の評価器型確定に頑健）。
  - `StubTool`: contracts `Tool` Protocol 準拠の決定論スタブ。Protocol 準拠は
    `if TYPE_CHECKING: _stubtool_is_tool: type[Tool] = StubTool` で静的保証（4.1 同様）。
- **RED→GREEN（憲法 I, 境界に test 無し）**: 正規 consumer は Task 5–8 のため 4.1 と同じ
  アドホックゲート。
  - RED: 新シンボル import が `ImportError: cannot import name 'TurnSequencedChatModel'`（exit 1）。
  - GREEN: 4モード＋既存 `ScriptedChatModel` 回帰を `create()`/`create_structure()` で
    決定論アサート。turn=progression(search/read/answer)+usage(5/7/3)、voting=`["a","a","b"]`、
    verdict=gen`["c1","c2"]`/verdict`["revise","pass"]`+clamp、StubTool=run 冪等、base=structured
    拒否 → **ALL GREEN**。
- **根本原因対応1件（テストハーネス）**: 当初 exhaustion を `create()` 経由で
  `AssertionError` 捕捉しようとしたが、beeai の `Run` ハンドラが `_create` 内 `AssertionError`
  を `ChatModelError` に変換（`__cause__` に元例外を連鎖）。fake 本体は正しく loud-fail
  しており検証スクリプト側の期待型が誤り。exhaustion 検証は `_create`/`_create_structure`
  直叩き（pydantic-ai 4.1 の「`model.request` 直叩き」と同方針）へ変更し解消。consumer
  視点でも `ChatModelError`（cause=AssertionError）で fail-loud は担保される。
- **coverage 非影響の確認**: `fake_chat_model.py` は `tests/support/` 配下で coverage source
  （`src/patterns_beeai`）対象外。新コードは coverage 値に非影響、floor 85% 維持。
- **検証ゲート**: ruff All checks passed / format 10 files clean /
  pyright(strict,3.13) 0 errors / pytest 12 passed・2 skipped（baseline 同一＝既存テスト
  無回帰）/ coverage floor 85% 維持。
- **申し送り（Task 4.3）**: llamaindex は `CustomLLM.complete`/`chat` の呼出カーソルで同一
  4モードを実装（beeai と同じく履歴非依存のカーソル方式 — plan 行165）。verdict は beeai と
  同様にメソッド分岐 dispatch が候補だが、llamaindex の structured 出力 API
  （`as_structured_llm` 等）の形に合わせ調整。Major Task 4 は 4.1（pydantic-ai）/
  4.2（beeai）完了、残 4.3（llamaindex）のみ。

### Task 4.3 — llamaindex ターン列フェイク基盤（Req 7.1/7.2, 4.3, 5.3/5.4）

- **対象**: `patterns/frameworks/llamaindex/tests/support/fake_llm.py`（境界は本ファイル
  単独）。既存 `ScriptedLLM`（schema 分岐モード）は温存し、Task 5–8 の llamaindex レーンが
  消費する4モード（ターン列 / index→出力マップ / verdict cursor / ツールスタブ）を追加。
- **API 前提の venv 実測**: `CustomLLM` の抽象は `complete`/`stream_complete`/`metadata`
  の3点。`acomplete`/`achat`/`astructured_predict`/`apredict` はすべて sync `complete`
  から base が導出（実測: `acomplete` がカーソルを正しく1回前進、`.raw` を透過）。
  → **completion シーム1点**で全 entry を駆動できる（`chat` 等を個別実装する必要なし）。
  `astructured_predict(Verdict,...)` の prompt は出力 schema を埋め込み quoted `"verdict"`
  を含む（実測）→ prompt 内容分岐が成立。
- **設計判断（クラス分割 + 共通基底）**: beeai と同型で、`_BaseScriptedLLM(CustomLLM)` に
  `metadata`（non-function-calling）と `stream_complete`（`self.complete` へ委譲＝stream
  要求時もカーソル前進1回固定）を集約し、`ScriptedLLM` を含む全フェイクをこの基底へ収容。
  各モードは独立サブクラスで `complete` のみ実装（C901≤10 内）。状態は Pydantic
  `PrivateAttr`（カーソル）+ `__init__` で台本データを格納。
  - `TurnSequencedLLM`: **呼出カーソル**で turn 進行（plan 行165 差分。pydantic-ai の
    `ToolReturnPart` 履歴に相当するものをモデル境界に持たない）。ToolTurn→
    `{"tool":...,"args":...}` JSON テキスト、FinalTurn→plain text。各 turn の `tokens` を
    `CompletionResponse.raw["usage"]["total_tokens"]` に載せ予算シーム決定論化。台本超過は
    `AssertionError`（loud fail）。
  - `VotingLLM`: 呼出カーソルで i 回目に `branch_outputs[i]`（分裂票 `["a","a","b"]`→2:1、
    Req 4.3）。呼出順↔branch index は consumer（Task 6.3）の責務として docstring 明記。
  - `VerdictSequencedLLM`: 全出力が `complete` 経由のため **prompt 内容分岐**で dispatch
    （quoted `"verdict"` 有→verdict cursor / 無→generator candidate cursor、末尾 clamp）。
    beeai の method-dispatch は llamaindex に method 二系統が無いため不採用。既存
    `ScriptedLLM` の `"route"`/`"subtasks"` ヒューリスティックと同型 = lane 内一貫。
    `revise→…→pass` を hermetic 再現（Req 5.3/5.4）。
  - `StubTool`: contracts `Tool` Protocol 準拠の決定論スタブ（`if TYPE_CHECKING:
    _stubtool_is_tool: type[Tool] = StubTool` で静的保証、4.1/4.2 同様）。
- **tool-call シーム規約（Task 8.3 への申し送り）**: CustomLLM は native tool-call part を
  持たないため、completion テキストに JSON action `{"tool":...,"args":...}` を載せ、Task 8.3
  の自律ループが「`"tool"` キーを持つ object に json.loads 可能なら tool 呼出、それ以外を
  最終回答」と解釈する規約を fake docstring + tasks.md で明示。実 Ollama 経路（8.3/10.3）でも
  同 action を出すよう loop 側がモデルに指示する前提。
- **RED→GREEN（憲法 I, 境界に正規 test 無し）**: 4.1/4.2 と同じアドホックゲート。
  - RED: 新シンボル import → `ImportError: cannot import name 'TurnSequencedLLM'`（exit≠想定）。
  - GREEN: 4モードを実 API（`acomplete`/`apredict`/`astructured_predict`）経由で決定論
    アサート — turn=progression(search/read/done)+raw usage(5/7/3)+exhaustion、
    voting=`["a","a","b"]`+exhaustion、verdict=gen`["c1","c2"]`(clamp) / verdict
    `["revise","pass"]`+exhaustion、StubTool=run 冪等、`ScriptedLLM` 回帰
    （route/subtasks/text）→ **ALL GREEN**。
- **根本原因対応2件（pyright strict, loose stubs 起因）**: 症状（lane pyright 緩和＝憲法 II
  違反）でなく原因（型情報供給）を修正。
  1. `Turn = ToolTurn | FinalTurn`（値ユニオン）→ `type Turn = ...`（真の型エイリアス）。
     値ユニオンだと PrivateAttr `list[Turn]` 宣言が partially-unknown。
  2. list PrivateAttr の `default_factory=list`（bare）→ **型付きファクトリ**
     （`list[Turn]`/`list[dict[str, object]]`/`list[str]`）。LlamaIndex `CustomLLM` の
     loose stubs を通すと bare `list` が base 経由で `list[Unknown]` に降格する
     （lane venv 実測: bare=`partially unknown` error / `default_factory=list[Turn]`=OK /
     `PrivateAttr()` no-default=OK / `list[str]` のみ bare でも通る＝element 依存の degrade）。
  3. verdict 格納を `dict[str, Any]`→`dict[str, object]` とし stored attr から `Any` を排除
     （reportUnknownVariableType 回避。param は I/O 境界だが concrete dict 渡しゆえ object で十分）。
- **coverage 非影響の確認**: `fake_llm.py` は `tests/support/` 配下で coverage source
  （`src/patterns_llamaindex`）対象外。新コードは coverage 値に非影響。
- **検証ゲート（実測, lane 配下）**: `uv run ruff check .` → All checks passed /
  `ruff format --check` → 10 files already formatted / `pyright`（strict, 3.13）→
  0 errors, 0 warnings / `pytest --cov` → 12 passed・2 skipped（baseline 同一＝無回帰）、
  Total coverage 97.64%（floor 85%）。6 warnings は openinference 計装の既存 Pydantic
  deprecation で本変更と無関係。
- これで Major Task 4（ターン列フェイク基盤の拡張）の全サブタスク（4.1〜4.3）完了。
  3レーンとも turn-sequenced / voting / verdict / StubTool の4モードを備え、Task 5–8 の
  各パターン実装が消費する決定論シームが揃った。

### Task 5.1 — pydantic-ai prompt-chaining 実装（Req 3.1/3.2/3.3, 7.3, 9.1/9.2, NFR-2）

- **対象**: `src/patterns_pydantic_ai/prompt_chaining.py`（新規）+
  `tests/unit/test_prompt_chaining.py`（新規）+ lane `__init__.py` 再エクスポート追記。
  契約は `patterns_contracts`（`ChainStep`/`GateOutcome`/`ChainResult`）を import、定義
  しない（NFR-3）。
- **設計判断（チェーン構成）**: Anthropic taxonomy の「outline → ゲート → document」を
  outline → draft → **gate** → finalize の3 `agent.run` 直列で実装。各ステップ出力を次
  ステップ prompt に注入（`draft` 入力 = outline 出力 / `finalize` 入力 = draft 出力）し
  Req 3.2 の「逐次連結」を構造で満たす。`steps` は **ゲート前**（outline, draft）のみ記録、
  `final_output` がゲート後の答 — 契約 docstring「steps executed before the gate decision」
  に literal 準拠。
- **ゲート（program verification）**: LLM ではなく決定論関数 `_gate(draft)`。draft の語数が
  `GATE_MIN_WORDS=3` 以上で `passed=True`。不合格時は `final_output=None` を返し finalize
  `agent.run` に**到達しない**（Req 3.3 silent 継続禁止）。退化した中間成果に2本目の LLM
  コストを払わない、という現実的な検証ゲートにした（min-words はプレースホルダではなく
  正の閾値であることを `test_gate_threshold_is_a_positive_word_count` で固定）。
- **instrument 適用**: routing/orchestrator と同一の `instrument_model(model, instrumentation)`
  DI seam。`instrumentation=None` で無計装、`InstrumentationSettings` 注入で gen_ai スパン。
- **RED→GREEN（憲法 I）**:
  - RED: `from patterns_pydantic_ai.prompt_chaining import ...` →
    `ModuleNotFoundError: No module named 'patterns_pydantic_ai.prompt_chaining'`（collection error）。
  - GREEN: 実装後 4 tests pass。
- **テスト設計（フェイク選択）**: ローカル `_recording_model`（call cursor + 受領 prompt 記録）を
  test 境界に定義。`scripted_model` の定数テキストでは検証できない2点を担保:
  (1) **連鎖（3.2）** = step n の prompt が step n-1 の出力を含むことをアサート、
  (2) **早期終了（3.3）** = ゲート不合格時にモデル呼出が pre-gate 2回のみ（finalize 未呼出）で
  あることをアサート（「継続しない」を推論でなく観測で証明）。span test（9.2）は `scripted_model(
  text="alpha beta gamma")`（3語＝ゲート通過）で finalize まで走らせ `InMemorySpanExporter` に
  gen_ai スパン≥1 を確認（9.3: 末端 LLM スパン存在のみ）。
- **境界順守の補正（validate-impl 指摘）**: 当初 lane `__init__.py` に `run_prompt_chain`
  + 契約3型を再エクスポート追加したが、Task 5.1 の `_Boundary:_` は `prompt_chaining.py` /
  `test_prompt_chaining.py` の2ファイルのみ。`__init__.py` は境界外 → CRITICAL（out-of-bounds）
  のため revert。再エクスポートは非 load-bearing（test/consumer は
  `from patterns_pydantic_ai.prompt_chaining import ...` で直 import、root 再エクスポート未使用）
  ゆえ機能影響なし。公開面追加が必要なら別途スコープしたタスクで実施する。
- **検証ゲート（実測, lane 配下、revert 後）**: `ruff check` → All checks passed /
  `pyright`（strict, 3.14）→ 0 errors, 0 warnings / `pytest --cov` → 15 passed・2 skipped
  （integration gated、baseline 同一＝無回帰）、`prompt_chaining.py` 100% カバー、
  Total 97.09%（floor 85%）。
- **申し送り（Task 5.2/5.3）**: beeai は Workflow（Pydantic state）逐次ステップ、llamaindex は
  `@step` 直列で同一契約を実装。ゲートは LLM でなく decode 後のプログラム検証である点（語数閾値は
  一例）と `final_output=None`/`gate.passed=False` の早期終了規約を3レーン同一に保つ。連鎖・
  早期終了の観測アサート（呼出回数 = pre-gate ステップ数）も各レーンの fake シームで再現すること。

### Task 5.2 — beeai prompt-chaining 実装（Req 3.1/3.2/3.3, 7.3, 9.1/9.2, NFR）

- **対象**: `src/patterns_beeai/prompt_chaining.py`（新規）+
  `tests/unit/test_prompt_chaining.py`（新規）の2ファイル（境界どおり）。契約は
  `patterns_contracts`（`ChainStep`/`GateOutcome`/`ChainResult`）を import、定義しない。
- **設計判断（Workflow ステートマシン）**: routing/orchestrator-workers と同型に BeeAI
  `Workflow[_ChainState, str]` を構築し `outline → draft → finalize` の3ステップを逐次連結
  （Req 3.2 = BeeAI は Workflow with Pydantic state）。各ステップ出力を `_ChainState.steps` へ
  append し次ステップ prompt に注入（draft 入力 = outline 出力 / finalize 入力 = draft 出力）。
  `steps` は**ゲート前**（outline, draft）のみ、`final_output` がゲート後の答 — 契約 docstring
  「steps executed before the gate decision」に literal 準拠（pydantic-ai 5.1 と同一意味論）。
- **早期終了の構造化（Req 3.3）**: ゲート判定を draft ステップ内に置き、不合格時は
  `return Workflow.END`（`Final[Literal["__end__"]]`）で finalize へ遷移せず即停止。`final_output`
  は `_ChainState` 既定の `None` のまま。LLM ではなく決定論関数 `_gate(draft)`（語数 ≥
  `GATE_MIN_WORDS=3`）が進行可否を決める。ステートマシン上で「不合格→次ステップへ進まない」を
  遷移で表現するため silent 継続が構造的に不能。GATE_MIN_WORDS は3レーン共通値を維持。
- **手動スパン（Req 9.1, plan §9 R-3）**: pydantic-ai（`instrument_model` 注入）/ llamaindex
  （OpenInference）と異なり、beeai はパターン関数に instrumentation 引数を持たせず呼出側が
  `observability.traced(provider, span_name, awaitable)` でラップ（routing/orchestrator と同方式）。
  span test は `test_observability.py` の routing 流儀を踏襲し pattern-level span（`"pattern.
  prompt_chaining"`）の存在のみ確認（Req 9.3: 末端スパン存在に留め集計はしない）。
- **RED→GREEN（憲法 I）**:
  - RED: `from patterns_beeai.prompt_chaining import GATE_MIN_WORDS, run_prompt_chain` →
    `ModuleNotFoundError: No module named 'patterns_beeai.prompt_chaining'`（collection error, 実測）。
  - GREEN: 実装後 4 tests pass（`uv run --no-sync pytest tests/unit/test_prompt_chaining.py` → 4 passed）。
- **テスト設計（フェイク選択）**: 連鎖（3.2）・早期終了（3.3）の観測は constant-text の
  `ScriptedChatModel` では不可能なため、test 境界に `_RecordingChatModel`（`ChatModel` 直接
  subclass、call cursor で distinct 出力 + 受領 prompt 記録）をローカル定義。pydantic-ai 5.1 の
  `_recording_model`（`FunctionModel` ベース）と対称で、beeai は `FunctionModel` 相当が無いため
  最小サーフェス（`model_id`/`provider_id`/`_create`/`_create_stream`/`_create_structure`）を実装。
  `Message.text` で UserMessage 本文を抽出し step n の prompt が step n-1 出力を含むことをアサート
  （連鎖）。呼出回数アサート（happy=3 / gate-fail=2）で finalize 未到達を観測（早期終了を推論でなく観測）。
  support `fake_chat_model.py`（Task 4.2 境界）は無改変。
- **検証ゲート（実測, lane 配下）**: `uv run ruff check .` → All checks passed /
  `ruff format --check` → 12 files already formatted / `pyright`（strict, 3.13）→
  0 errors, 0 warnings, 0 informations / `pytest --cov` → 16 passed・2 skipped
  （baseline 12 passed/2 skipped + 4 新規 = 無回帰）、`prompt_chaining.py` 100% カバー、
  Total coverage 98.20%（floor 85%）。
- **ruff 修正2件（境界内・根本対応）**: ① 実装 docstring の ASCII 分岐図に backslash →
  D301（`r"""` 要求）。backslash を含まない散文表現（`outline -> draft -> finalize`）へ書換え。
  ② test の `_create_stream` 戻り値を `Any` + 不要 noqa（ANN401 非有効）→ support と同型の
  `AsyncGenerator[ChatModelOutput]`（`collections.abc` を TYPE_CHECKING import）へ。いずれも
  ルール緩和でなく型/記法の正で解消。
- **境界順守**: Task 5.1 の validate-impl 指摘（`__init__.py` 再エクスポートは境界外）を踏まえ、
  本タスクでも lane `__init__.py` は無改変（境界は prompt_chaining.py / test_prompt_chaining.py の
  2ファイルのみ）。consumer/test は `from patterns_beeai.prompt_chaining import ...` で直 import。
- **申し送り（Task 5.3）**: llamaindex は `@step` 直列 + OpenInference 計装で同一契約を実装。
  ゲートのプログラム検証性・`final_output=None`/`gate.passed=False` の早期終了規約・GATE_MIN_WORDS=3 を
  3レーン共通に保つ。連鎖・早期終了の観測アサートは llamaindex の `complete` シーム（prompt 記録）で再現。
  これで Major Task 5 は 5.1（pydantic-ai）/ 5.2（beeai）完了、残 5.3（llamaindex）のみ。

### Task 5.3 — llamaindex prompt-chaining 実装（Req 3.1/3.2/3.3, 7.3, 9.1/9.2）

- **対象**: `src/patterns_llamaindex/prompt_chaining.py`（新規）+
  `tests/unit/test_prompt_chaining.py`（新規）の2ファイル（境界どおり）。契約は
  `patterns_contracts`（`ChainStep`/`GateOutcome`/`ChainResult`）を import、定義しない。
- **設計判断（event-driven `@step` 直列連鎖）**: routing/orchestrator-workers と同型に
  `PromptChainWorkflow(Workflow)` を構築し、**イベントで出力を連結** — `outline(StartEvent)
  → _DraftEvent → draft → _FinalizeEvent | StopEvent → finalize → StopEvent`。各ステップが
  「次ステップが消費する唯一のイベント」を emit することで直列鎖を成す（Req 3.2 = llamaindex は
  `@step` 直列）。draft 入力 = outline 出力 / finalize 入力 = draft 出力をイベント payload で運搬。
  `steps` は**ゲート前**（outline, draft）のみ、`final_output` がゲート後の答（契約 docstring
  「steps executed before the gate decision」に literal 準拠、pydantic-ai/beeai と同一意味論）。
- **早期終了の構造化（Req 3.3）**: ゲート判定を draft ステップ内に置き、不合格時は **終端
  `StopEvent`（`final_output=None`）を直接 emit** し `_FinalizeEvent` を発行しない＝finalize
  ステップへイベントが到達しない。union-return `_FinalizeEvent | StopEvent` で beeai の
  `Workflow.END` 相当をイベント駆動で表現（orchestrator `synthesize` の `StopEvent | None`
  と同型の union-return）。LLM ではなく決定論関数 `_gate(draft)`（語数 ≥ `GATE_MIN_WORDS=3`）が
  進行可否を決める。ステートマシン上で silent 継続が構造的に不能。GATE_MIN_WORDS は3レーン共通維持。
- **全ステップ plain-text**: prompt-chaining は structured-output 不要のため全ステップ
  `llm.acomplete`（routing の `astructured_predict` / `acomplete` 併用とは異なり completion 一本）。
  `PromptTemplate` で instruction + 前ステップ出力を埋め込む（routing/orchestrator の template 流儀）。
- **計装（Req 9.1, plan §9）**: OpenInference の **process-global** `LlamaIndexInstrumentor`
  （pydantic-ai 5.1 の `instrument_model` per-model 注入・beeai 5.2 の手動 `traced` ラップとは
  異なるレーン固有方式）。パターン関数に instrumentation 引数は持たせない（routing/orchestrator と同様）。
  span test は `test_observability.py` の routing 流儀を踏襲: `instrument_llamaindex` 設置 → run →
  `finally` で `uninstrument_llamaindex` detach（計装は process-global ゆえテスト隔離に必須）。
  末端 LLM span（`"llm"`/`"complete"` 名）の存在のみ確認（Req 9.3: 集計はしない）。
- **RED→GREEN（憲法 I）**:
  - RED: `from patterns_llamaindex.prompt_chaining import GATE_MIN_WORDS, run_prompt_chain` →
    `ModuleNotFoundError: No module named 'patterns_llamaindex.prompt_chaining'`（collection error, 実測）。
  - GREEN: 実装後 `uv run --no-sync pytest tests/unit/test_prompt_chaining.py` → 4 passed。
- **テスト設計（フェイク選択）**: 連鎖（3.2）・早期終了（3.3）の観測は constant-text の
  `ScriptedLLM` では不可能なため、test 境界に `_RecordingLLM`（`CustomLLM` 直接 subclass、call
  cursor で distinct 出力 + 受領 prompt 記録、`PrivateAttr` で状態保持）をローカル定義。pydantic-ai
  5.1 の `_recording_model` / beeai 5.2 の `_RecordingChatModel` と対称。`complete` シーム1点で
  `acomplete` 由来の全 workflow ステップを駆動（`CustomLLM` の async 導出を利用）。step n prompt が
  step n-1 出力を含むことをアサート（連鎖）、呼出回数アサート（happy=3 / gate-fail=2）で finalize
  未到達を観測（早期終了を推論でなく観測）。span test のみ既存 `ScriptedLLM`（constant text
  "alpha beta gamma" = 3 語でゲート通過）を流用。support `fake_llm.py`（Task 4.3 境界）は無改変。
- **検証ゲート（実測, lane 配下）**: `uv run ruff check .` → All checks passed /
  `ruff format --check` → 12 files already formatted / `pyright`（strict, 3.13）→
  0 errors, 0 warnings, 0 informations / `pytest --cov` → 16 passed・2 skipped
  （baseline 12 passed/2 skipped + 4 新規 = 無回帰）、`prompt_chaining.py` 100% カバー、
  Total coverage 98.35%（floor 85%）。境界外修正・ruff 追加修正ともゼロ（型注釈・docstring を
  既存レーン流儀で初版から正に記述）。
- **境界順守**: Task 5.1/5.2 と同様 lane `__init__.py` は無改変（境界は prompt_chaining.py /
  test_prompt_chaining.py の2ファイルのみ）。consumer/test は
  `from patterns_llamaindex.prompt_chaining import ...` で直 import。
- **完了**: これで Major Task 5（prompt-chaining 3レーン）の全サブタスク（5.1〜5.3）完了 —
  3レーンとも outline→draft→gate→finalize の同一契約・GATE_MIN_WORDS=3 共通・`final_output=None`
  早期終了規約を、各 FW 固有の計装方式（注入 / 手動 traced / OpenInference）で実装。
