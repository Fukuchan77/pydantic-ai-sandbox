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

---

### Task 6.1 — pydantic-ai parallelization 実装（Req 4.1/4.2/4.3/4.4, 7.3, 9.1, NFR-2）

#### 実施内容

- `src/patterns_pydantic_ai/parallelization.py` 新設: `run_parallelization(task, *,
  variant: Literal["sectioning","voting"], model, n=3, instrumentation=None) ->
  ParallelResult`（Req 4.1）。単一契約 + `variant` 切替。両 variant とも
  `asyncio.gather` で n ブランチを fan-out（Req 4.4）。`instrument_model` 適用は
  routing/orchestrator/prompt-chaining と同一シーム。
- **aggregate**: sectioning = ブランチ出力を index 昇順 join（Req 4.2）、voting =
  `Counter` 多数決。strict `>` 比較で同数候補は first-seen（=最小 index）を保持＝
  index 昇順タイブレーク（Req 4.3）。
- **ガード**: `n<1` は `ValueError`（zero/negative fan-out の空走を封鎖、orchestrator
  の `max_workers` バリデーションと対称）。

#### TDD（RED→GREEN・憲法 I）

- RED: `from patterns_pydantic_ai.parallelization import run_parallelization` →
  `ModuleNotFoundError`（collection error, 実測）。
- GREEN 過程で**設計上の根本問題が顕在化**（下記「知見」）→ 修正後 6 passed、
  5連続実行で安定（決定論確認）。

#### 計画からの逸脱・知見（根本原因と対処）

- **`gather` 到達順 ≠ spawn 順（スケジューラ依存の安定置換）**: `Branch.index` を
  `range(n)` 固定にすると、共有カーソルの `voting_model` がブランチにシャッフルした
  出力を配り、タイブレークが非決定になる。実測で n=4 のモデル到達順は恒等でなく
  `0,2,1,3`（`["red","blue","red","blue"]` が `["red","red","blue","blue"]` に化けた）。
  - **根本対処**: `index` を「**モデル応答が返った瞬間に共有カウンタから取得**」
    （完了順）に変更。同期 `FunctionModel` は応答〜`agent.run` 完了間に reorder yield を
    挟まないため**完了順 = カーソル消費順**となり、`index k ↔ cursor[k]` が置換に依らず
    決定論化。probe スクリプト2本で「完了カウンタが cursor 順を回復する」ことを実証。
  - voting prompt は**同一を維持**（Req 4.3「同一タスクを n 回」への忠実性）。差別化は
    instructions（sectioning=「自分の担当部分のみ」/ voting=「独立に全体を解く」）と
    aggregation のみ。
- **`n=0` テストの test-authoring バグ（RED が教えた）**: 当初
  `run_parallelization(...).close()` で組んだが、coroutine 関数の呼出は body を実行せず
  `close()` も走らない → DID NOT RAISE。バリデーションは await 駆動が必須のため
  `async def` + `await ... pytest.raises(ValueError)` へ修正。
- **フェイク選択**: `voting_model`（Task 4.1 support）を split-vote(2:1)/tie-break(2:2)/
  order-restoration 全テストで使用。span テストは prompt-chaining 流儀
  （`InMemorySpanExporter` + `configure_tracing` + `InstrumentationSettings`、`gen_ai`
  属性存在のみ確認、Req 9.2/9.3）。support `model_fakes.py`（Task 4.1 境界）は無改変。

#### 検証ゲート（実測, lane 配下）

- `uv run ruff check .` → All checks passed
- `uv run ruff format --check .` → 15 files（parallelization.py を format 後）clean
- `uv run pyright`（strict, 3.13）→ 0 errors, 0 warnings, 0 informations
- `uv run pytest --cov` → 21 passed・2 skipped（baseline 15+2 + 6 新規、うち 9.x/10.x
  系は別タスク。回帰なし）、`parallelization.py` coverage 100%、Total 97.95%（floor 85%）

#### 境界順守

- 境界は `parallelization.py` / `test_parallelization.py` の2ファイルのみ。lane
  `__init__.py` 再エクスポートは本タスク境界外のため無改変（Task 5.x と同様）。
  consumer/test は `from patterns_pydantic_ai.parallelization import ...` で直 import。

---

### Task 6.2 — beeai parallelization 実装（Req 4.1/4.2/4.3/4.4, 7.3, 9.1, 9.2）

#### 実施内容

- `patterns/frameworks/beeai/src/patterns_beeai/parallelization.py`: 6.1 と同一の
  単一契約 + `variant` 切替で `run_parallelization` を実装。両 variant とも
  `asyncio.gather` で fan-out（Req 4.4）、aggregate は sectioning=index 昇順 join /
  voting=`Counter` 多数決（strict `>` で同数 first-seen 保持＝index 昇順タイブレーク,
  Req 4.3）、`n<1`→`ValueError`。モデル境界は `llm.create(messages=[System,User])` →
  `output.get_text_content()`（pydantic-ai の `agent.run` に対応する beeai シーム）。
- 観測は**手動スパン方式**: パターン関数に instrumentation 引数を持たせず、呼出側が
  `traced(provider, "pattern.parallelization", ...)` でラップ（prompt-chaining/routing と
  同方式。pydantic-ai 6.1 の `instrument_model` 注入とは異なるレーン固有方式）。
- `test_parallelization.py`: 6 テスト（sectioning fan-out / voting split-vote 2:1 /
  tie-break 2:2 / order-restoration n=5 / `n=0` reject / span 存在）。

#### TDD（RED→GREEN・憲法 I）

- RED: `from patterns_beeai.parallelization import run_parallelization` →
  `ModuleNotFoundError`（collection error, 実測）。
- GREEN: 実装後 6 passed。

#### 計画からの逸脱・知見（根本原因と対処）

- **完了順 index-claiming の beeai への転写は自明でない → 実機 probe で検証**: 6.1 の
  「モデル応答が返った瞬間に共有カウンタから index 取得」設計は、beeai の
  `ChatModel.create` が `_create`（cursor 消費）と return の間に emitter `emit` /
  `cache.set` / `Retryable` 等の複数 `await` を挟むため、cursor 消費順と完了順が割れる
  リスクがあった（pydantic-ai の同期 `FunctionModel` には無い差分）。
  - **根本対処（仮定でなく実機確認）**: 憲法に従い probe スクリプトで 500 試行 × 2 ケース
    （n=5 順序復元 `["b0".."b4"]` / n=4 タイブレーク `["red","blue","red","blue"]`）を実行
    → 全試行が単一の正出力（`('b0','b1','b2','b3','b4')` / `('red','blue','red','blue')`）に
    収束。根本理由は `VotingChatModel` フェイクに真の suspension point が無く、`gather` 下で
    各 coroutine が spawn 順に走り切る（cursor 消費順＝完了順＝spawn 順）こと。完了順
    index-claiming を確信して採用。
  - voting prompt は**同一を維持**（Req 4.3「同一タスクを n 回」忠実）。差別化は
    instructions と aggregation のみ（6.1 と同方針）。
- **フェイク選択**: `VotingChatModel`（Task 4.2 support）を split-vote/tie-break/order
  全テストで使用。span テストは prompt-chaining 流儀（`InMemorySpanExporter` +
  `traced` ラップ + span 名 `pattern.parallelization` 存在、Req 9.2/9.3）。support
  `fake_chat_model.py`（Task 4.2 境界）は無改変。

#### 検証ゲート（実測, lane 配下）

- `uv run ruff check .` → All checks passed
- `uv run ruff format --check .` → 14 files clean
- `uv run pyright`（strict, 3.13）→ 0 errors, 0 warnings, 0 informations
- `uv run pytest --cov` → 22 passed・2 skipped（回帰なし）、`parallelization.py`
  coverage 100%、Total 98.54%（floor 85%）

#### 境界順守

- 境界は `parallelization.py` / `test_parallelization.py` の2ファイルのみ。lane
  `__init__.py` 再エクスポートは本タスク境界外のため無改変。consumer/test は
  `from patterns_beeai.parallelization import ...` で直 import。

---

### Task 6.3 — llamaindex parallelization 実装（Req 4.1/4.2/4.3/4.4, 7.3, 9.1, 9.2）

#### 実施内容

- `patterns/frameworks/llamaindex/src/patterns_llamaindex/parallelization.py`: 6.1/6.2 と
  同一の単一契約 + `variant` 切替で `run_parallelization(task, *, variant, llm, n=3,
  timeout=120.0) -> ParallelResult` を実装。aggregate は sectioning=index 昇順 join /
  voting=`Counter` 多数決（strict `>` で同数 first-seen=最小 index 保持＝index 昇順
  タイブレーク, Req 4.3）、`n<1`→`ValueError`。
- **fan-out は LlamaIndex Workflows ネイティブの worker-pool 機構**（6.1/6.2 の bare
  `asyncio.gather` とは異なるレーン差分）: `dispatch(StartEvent)` が `ctx.send_event` で
  n 件の `_BranchEvent` を発行 → `run_branch`（`@step(num_workers=_FANOUT_WORKERS=8)`）が
  並行消費し `acomplete` → `collect` が `ctx.collect_events(ev, [_BranchDoneEvent]*n)` で
  全 n をバリア収集（未充足時は `None` を返してバッファ継続）。routing/prompt-chaining の
  `@step` ワークフロー流儀と同型。
- 観測は OpenInference の process-global `LlamaIndexInstrumentor`（パターン関数に
  instrumentation 引数を持たせず、呼出側が `instrument_llamaindex` 設置）。
- `test_parallelization.py`: 6 テスト（sectioning fan-out / voting split-vote 2:1 /
  tie-break 2:2 / order-restoration n=5 / `n=0` reject / span 存在）を beeai 6.2 と対称に
  構成。span テストのみ既存 `ScriptedLLM`（constant text）を流用し process-global instrumentor
  を `try/finally` で設置→detach、末端 LLM span（`"llm"`/`"complete"` 名）存在を確認（Req 9.3）。

#### TDD（RED→GREEN・憲法 I）

- RED: `from patterns_llamaindex.parallelization import run_parallelization` →
  `ModuleNotFoundError: No module named 'patterns_llamaindex.parallelization'`
  （collection error, 実測）。
- GREEN: 実装後 `uv run --no-sync pytest tests/unit/test_parallelization.py` → 6 passed。

#### 計画からの逸脱・知見（根本原因と対処）

- **決定論の根本検証（実機 probe, 6.2 と同手法）**: 6.1/6.2 の「`acomplete` 応答が返った
  瞬間に共有カウンタから `index` を claim（呼出〜claim 間に `await` を挟まない）」を踏襲。
  worker pool の到達順はスケジューラ依存の置換だが、`VotingLLM.complete` が同期（真の
  suspension point 無し）かつ cursor 消費（`complete` 内）〜index claim（`acomplete` 直後）
  間に `await` が無いため **cursor 消費順 = 完了 index claim 順**。憲法（仮定でなく実機確認）
  に従い 500試行 × 2ケース（n=5 順序復元 `["b0".."b4"]` / n=4 タイブレーク 2:2
  `["red","blue","red","blue"]`）を probe → 全試行が単一の正出力（`(b0..b4, 0..4)` /
  `(red,blue,red,blue, "red")`）に収束。`collect_events` は完了順返却 → `index` で明示
  ソートし復元を pin（Req 4.4）。
- **`num_workers` の静的キャップ（レーン差分の明示）**: LlamaIndex は step 並行度を
  `num_workers`（decorator 定数）で律速する＝`asyncio.gather` の無制限 fan-out と異なる
  真の機構差。`_FANOUT_WORKERS=8` を module 定数化し既定 `n=3` とテスト fan-out（最大 n=5）を
  被覆。n>8 でも正しく完走（worker が空くと残ブランチが走る）— in-flight 並行度のみ低下、と
  docstring に明記。
- **境界内 pyright 修正2件（症状でなく原因を修正）**:
  1. `@step(num_workers=...)`（factory 形）は bare `@step` と異なり
     `reportUntypedFunctionDecorator` を発火（routing/prompt-chaining の bare `@step` では
     未発火）→ 当該行に inline `# pyright: ignore[reportUntypedFunctionDecorator]`
     （fake_llm の `@llm_completion_callback()` と同方式。ルール緩和でなく既知の untyped
     upstream decorator への scoped ignore）。
  2. `self._variant = variant`（`__init__` 引数は `Literal["sectioning","voting"]`）を
     pyright が**未注釈 mutable 属性へ格納された Literal を `str` へ widen** → `collect` の
     `ParallelResult(variant=self._variant)` が `ParallelResult.variant` の Literal と
     不一致（reportArgumentType）。`reveal_type` で属性経由の widen を切り分け、
     `self._variant: Literal["sectioning", "voting"] = variant` と明示注釈して解消
     （lane pyright 設定の緩和＝憲法 II 違反ではなく型注釈の正で対応）。
- **フェイク選択**: `VotingLLM`（Task 4.3 support）を split-vote/tie-break/order 全テストで
  使用。support `fake_llm.py`（Task 4.3 境界）は無改変。

#### 検証ゲート（実測, lane 配下）

- `uv run --no-sync ruff check .` → All checks passed!
- `uv run --no-sync ruff format --check .` → 14 files already formatted
- `uv run --no-sync pyright`（strict, 3.13）→ 0 errors, 0 warnings, 0 informations
- `uv run --no-sync pytest --cov` → 22 passed・2 skipped（baseline 16+2 + 6 新規 =
  無回帰）、`parallelization.py` coverage 100%、Total 98.81%（floor 85%）
- 決定論 probe: 500試行 × 2ケースとも単一の正出力に収束（上記「知見」）

#### 境界順守

- 境界は `parallelization.py` / `test_parallelization.py` の2ファイルのみ。lane
  `__init__.py` 再エクスポートは本タスク境界外のため無改変。consumer/test は
  `from patterns_llamaindex.parallelization import ...` で直 import。
- これで Major Task 6（parallelization 3レーン）の全サブタスク（6.1〜6.3）完了 —
  3レーンとも単一契約 + `variant` 切替・index 昇順復元・タイブレークを、各 FW 固有の
  fan-out 機構（`asyncio.gather` ×2 / Workflows worker-pool）と計装方式で実装。

---

## Task 7.1 — pydantic-ai: evaluator-optimizer 実装

### RED → GREEN

- **RED**: `test_evaluator_optimizer.py`（5テスト）を先行作成 → `uv run --no-sync
  pytest --no-cov tests/unit/test_evaluator_optimizer.py` → `ModuleNotFoundError:
  No module named 'patterns_pydantic_ai.evaluator_optimizer'`（collection error, 1 error）。
- **GREEN**: `evaluator_optimizer.py` 実装 → 同テスト 5 passed。lane 全体 26 passed・
  2 skipped（baseline 21+2 + 5 新規 = 無回帰）。

### 設計判断（知見）

- **generator/evaluator 2エージェント構成**: generator=`output_type=str`（plain text）、
  evaluator=`output_type=_Evaluation`（structured）。`_Evaluation{verdict: Literal["pass",
  "revise"], feedback: str}` は契約 `Iteration` ではなく**レーン内 private モデル** —
  evaluator は verdict/feedback のみ決定し、ループが `index` を stamp し generator の
  `candidate` と対にして `Iteration` を構築する責務分割。`_Evaluation` の JSON schema が
  `verdict` プロパティを露出することが Task 4.1 `verdict_sequenced_model` の
  generator/evaluator dispatch シームと一致（schema 分岐方式を契約に合わせて成立）。
- **stop_reason 二値の構造保証**: verdict=="pass" で即 `return ... stop_reason="passed"`、
  `for index in range(max_iterations)` exhaust で `stop_reason="max_iterations"`。Literal
  二値以外は到達不能（R5.4）。`max_iterations<1`→`ValueError`（parallelization の `n<1` と
  対称、候補未生成の silent 空ループを封鎖）。mccabe は if 2件のみで C901≤10 内。
- **Req 5.3 検証手段**: feedback の次反復反映は cursor フェイクの出力には現れないため、
  prompt_chaining 5.x の `_recording_model` 流儀を**テスト境界にローカル再現** — verdict
  dispatch（`info.output_tools`）+ generator prompt 記録を兼ねるフェイクで、2回目
  generator prompt が1回目 evaluator feedback（`NEEDS_CITATIONS`）+ 前 candidate
  （`first attempt`）を含むことをアサート。support `model_fakes.py`（Task 4.1 境界）は無改変。
- **pass 到達 / max_iterations**: support `verdict_sequenced_model` を使用。`candidate` は
  per-call cursor（`["draft one","draft two final"]` 等）で反復ごと別候補を供給し、
  iterations 記録・final_output・stop_reason を決定論検証。

### 検証ゲート（実測, lane 配下）

- `uv run --no-sync ruff check ...` → All checks passed!
- `uv run --no-sync ruff format --check ...` → 2 files already formatted
- `uv run --no-sync pyright`（strict, 3.13）→ 0 errors, 0 warnings, 0 informations
- `uv run --no-sync pytest --cov` → 26 passed・2 skipped（無回帰）、
  `evaluator_optimizer.py` coverage 100%、Total 98.38%（floor 85%）

### 境界順守

- 境界は `evaluator_optimizer.py` / `test_evaluator_optimizer.py` の2ファイルのみ。
  lane `__init__.py` 再エクスポートは本タスク境界外のため無改変。test は
  `from patterns_pydantic_ai.evaluator_optimizer import run_evaluator_optimizer` で直 import。

---

## Task 7.2 — beeai: evaluator-optimizer 実装

### RED → GREEN

- **RED**: `test_evaluator_optimizer.py`（5テスト）を先行作成 → `uv run --no-sync
  pytest tests/unit/test_evaluator_optimizer.py` → `ModuleNotFoundError: No module
  named 'patterns_beeai.evaluator_optimizer'`（collection error, 1 error）。
- **GREEN**: `evaluator_optimizer.py` 実装 → 同テスト 5 passed。lane 全体 27 passed・
  2 skipped（baseline 22+2 + 5 新規 = 無回帰）。

### 設計判断（知見）

- **ループ構成**: 7.1（pydantic-ai）と同型の generator→evaluator 逐次 `for` ループ。
  beeai は prompt-chaining/routing で Workflow を使うが、evaluator-optimizer は
  動的反復（pass 到達 or max_iterations）であり、parallelization が Workflow を
  強制せず plain `asyncio.gather` を採った判断に倣い plain `for` ループとした
  （手動ループの素直な実装、`stop_reason` 二値を早期 return で構造保証）。
- **generator/evaluator dispatch**: generator=`llm.create`（plain text）、
  evaluator=`llm.create_structure(schema=_Evaluation,...)`。`_Evaluation{verdict:
  Literal["pass","revise"], feedback}` は契約 `Iteration` ではなくレーン内 private
  モデル（evaluator は verdict/feedback のみ決定、ループが index を stamp し candidate
  と対に）。**メソッド分岐**（create vs create_structure）が Task 4.2
  `VerdictSequencedChatModel` の dispatch シームと一致（pydantic-ai 7.1 の
  schema-property 方式と異なる beeai 固有方式 — 4.2 申し送りどおり）。
- **契約再検証（Req 2.3 流儀）**: routing と同じく `_Evaluation.model_validate(
  evaluated.object)` で評価器出力を再検証し、語彙外 verdict を `ValidationError` で
  loud-fail（backend の structure 実装に依らず保証）。
- **stop_reason 二値の構造保証**: verdict=="pass" で即 `return ... stop_reason=
  "passed"`、`range(max_iterations)` exhaust で `stop_reason="max_iterations"`。
  `max_iterations<1`→`ValueError`（7.1/parallelization の `n<1` と対称）。
- **観測（手動スパン, Req 9.1）**: pydantic-ai（`instrument_model` 注入）/ llamaindex
  （OpenInference）と異なり、パターン関数に instrumentation 引数を持たせず呼出側が
  `observability.traced(provider, "pattern.evaluator_optimizer", awaitable)` で
  ラップ（routing/orchestrator/prompt-chaining/parallelization と同方式）。span test は
  pattern-level span の存在のみ確認（Req 9.3）。
- **Req 5.3 検証手段**: feedback の次反復反映は cursor フェイクの出力には現れない
  ため、prompt_chaining 5.2 の `_RecordingChatModel` 流儀をテスト境界にローカル再現
  — `_create`（generator）で受領 user prompt を記録 + candidate cursor、
  `_create_structure`（evaluator）で verdict cursor。2回目 generator prompt が1回目
  evaluator feedback（`NEEDS_CITATIONS`）+ 前 candidate（`first attempt`）を含むことを
  アサート。support `fake_chat_model.py`（Task 4.2 境界）は無改変。

### 検証ゲート（実測, lane 配下）

- `uv run ruff check .` → All checks passed!
- `uv run ruff format --check .` → 16 files already formatted
- `uv run pyright`（strict, 3.13）→ 0 errors, 0 warnings, 0 informations
- `uv run pytest --cov` → 27 passed・2 skipped（無回帰）、
  `evaluator_optimizer.py` coverage 100%、Total 98.74%（floor 85%）

### 境界順守

- 境界は `evaluator_optimizer.py` / `test_evaluator_optimizer.py` の2ファイルのみ。
  lane `__init__.py` 再エクスポートは本タスク境界外のため無改変（5.1 の out-of-bounds
  是正に倣う）。test は `from patterns_beeai.evaluator_optimizer import
  run_evaluator_optimizer` で直 import。
- **申し送り（Task 7.3）**: llamaindex は OpenInference 計装 + `@step`/Workflow か
  plain ループで同一契約を実装。verdict dispatch は llamaindex が method 二系統を
  持たないため Task 4.3 `VerdictSequencedLLM` の **prompt 内容分岐**（quoted
  `"verdict"`）を使う点に注意（4.3 申し送り）。`_Evaluation` 相当を
  `astructured_predict` 等で取得し `model_validate` 再検証する流儀は共通。

---

## Task 7.3 — llamaindex: evaluator-optimizer 実装

### RED → GREEN

- **RED**: `test_evaluator_optimizer.py`（5テスト）を先行作成 → `uv run --no-sync
  pytest tests/unit/test_evaluator_optimizer.py` → `ModuleNotFoundError: No module
  named 'patterns_llamaindex.evaluator_optimizer'`（collection error, 1 error）。
- **GREEN**: `evaluator_optimizer.py` 実装 → 同テスト 5 passed。lane 全体 27 passed・
  2 skipped（baseline 22+2 + 5 新規 = 無回帰）。

### 設計判断（知見）

- **ループ構成（plain `for`、初の非 Workflow llamaindex パターン）**: 7.1/7.2 と同型の
  generator→evaluator 逐次 `for` ループ。routing/prompt-chaining/parallelization は
  LlamaIndex `Workflow` だが、evaluator-optimizer は fan-out 無しの純逐次反復で
  イベント機構が契約価値を足さない → 7.2 beeai 判断 + parallelization の「Workflow
  非強制」判断に整合し plain `for` を採用。`stop_reason` 二値は早期 return で構造保証。
- **generator/evaluator dispatch**: generator=`llm.acomplete`（plain text）、
  evaluator=`llm.astructured_predict(_Evaluation, _EVALUATOR_TEMPLATE, ...)`。後者は
  routing の `astructured_predict(RouteDecision, ...)` と同じく **Pydantic 検証済みの
  `_Evaluation` インスタンスを直接返す** → beeai の `create_structure`（raw object で
  `model_validate` 再検証が必要）と異なり再検証は不要というレーン差分。語彙外 verdict は
  astructured_predict 内部の parser が `ValidationError` で loud-fail。
- **verdict cursor シーム（4.3 申し送り採用）**: Task 4.3 `VerdictSequencedLLM` の
  **prompt 内容分岐**を踏襲 — `astructured_predict` の prompt は `_Evaluation` schema を
  埋め込み quoted `"verdict"` を含むため verdict cursor、それ以外（generator の
  `acomplete`）は candidate cursor。generator instructions の `verdict='pass'`
  （single-quote）は `'"verdict"'`（double-quote）非該当で誤検知しない（pydantic-ai 7.1 の
  schema-property dispatch / beeai 7.2 の method 分岐の llamaindex 版）。
- **Req 5.3 検証手段**: feedback の次反復反映は cursor フェイクの出力には現れないため、
  prompt_chaining 5.3 の `_RecordingLLM` 流儀をテスト境界にローカル再現 — `complete` で
  prompt 内容により verdict/generator を分岐し、generator prompt のみ記録。2回目 generator
  prompt が1回目 evaluator feedback（`NEEDS_CITATIONS`）+ 前 candidate（`first attempt`）を
  含むことをアサート。support `fake_llm.py`（Task 4.3 境界）は無改変。
- **観測（OpenInference, Req 9.1）の差分**: Workflow を使わないが、`acomplete` /
  `astructured_predict` の leaf LLM span が LlamaIndex dispatcher 経由で
  auto-instrument されるため Workflow 不在でも span≥1 が出ることを span test で実証
  （span 名 `"llm"`/`"complete"`、prompt_chaining/parallelization 流儀）。

### 検証ゲート（実測, lane 配下）

- `uv run ruff check .` → All checks passed!
- `uv run ruff format --check .` → 16 files already formatted
- `uv run pyright`（strict, 3.13）→ 0 errors, 0 warnings, 0 informations
- `uv run pytest --cov` → 27 passed・2 skipped（無回帰）、
  `evaluator_optimizer.py` coverage 100%、Total 98.94%（floor 85%）

### 境界順守

- 境界は `evaluator_optimizer.py` / `test_evaluator_optimizer.py` の2ファイルのみ。
  lane `__init__.py` 再エクスポートは本タスク境界外のため無改変。test は
  `from patterns_llamaindex.evaluator_optimizer import run_evaluator_optimizer` で
  直 import。
- これで Major Task 7（evaluator-optimizer 3レーン）の全サブタスク（7.1〜7.3）完了。
  次は Task 8（autonomous-agent 3レーン・ガードレール契約）。

## Task 8.1 — pydantic-ai: autonomous-agent 実装（Req 6.1-6.6, 7.2/7.3, 9.1, 10.3, NFR-2）

### Plan（このタスクで実装するもの）

- `run_autonomous_agent(goal, *, model, max_iterations, allowed_tools,
  approval_hook, budget, instrumentation=None) -> AgentRunResult` を chat
  プリミティブ上の**手動一様ループ**で実装。4ガードレール（max_iterations /
  allowed_tools / approval_hook / budget）と `stop_reason` 4値 Literal を確定。
- 境界2ファイル: `src/patterns_pydantic_ai/autonomous_agent.py` /
  `tests/unit/test_autonomous_agent.py`。

### Do（実装の要点と判断）

- **Agent ではなく `Model.request` 直叩き**: 本パターンは初の非 Agent レーンコード。
  ループが `await resolved.request(messages, None, ModelRequestParameters())` を
  反復し、応答の `ToolCallPart`（→ツール呼出）/ `TextPart`（→最終回答）を解釈。
  `ModelRequestParameters()` 必須（Task 4.1 申し送り: `None` だと `prepare_request`
  で AttributeError）。ターン進行は `turn_sequenced_model` が履歴 `ToolReturnPart` 数で
  index 化するため、ループは各反復で `ModelRequest(parts=[ToolReturnPart(...)])` を
  履歴へ append して次ターンを駆動。
- **ガードレール境界の非対称設計**: `max_iterations`(R6.3)/`denied`(R6.5)/
  `budget_exceeded`(R6.6) は**ループ停止**だが、`allowed_tools` 違反(R6.4) は
  **per-call refusal**（非実行＋拒否 observation を feedback して継続）とした。
  根拠は `stop_reason` 語彙（`completed/max_iterations/budget_exceeded/denied`）に
  "forbidden" 系が無く、6.4 のみ「実行せず拒否」で stop_reason 未割当という非対称性
  ＝契約が per-call 拒否を意図する証左。
- **予算会計シームの単一点化**（plan「決定論性の核心」）: `_budget_spent(response)
  -> int = response.usage.total_tokens`（input+output 和）の1関数に閉じ込め。
  `total_budget_spent` は **AgentStep 単位**の累積（最終回答ターンは tool 反復でない＝
  非計上、R6.6「各反復」に忠実）。超過は strict `total > budget`（== は継続）。
  全試行（executed/refused/denied）を steps へ記録＝監査証跡が silent empty にならない
  （R10.3 多層防御）。
- **`_args_text` 正規化**: `ToolCallPart.args`（`str | dict | None`）を `Tool.run` が
  受ける str へ正規化（dict→sorted-json / None→""）。実モデルが dict/None 引数を
  emit する整合性経路（Task 10 Ollama）に必要。

### エラーと根本原因（盲目的 retry なし）

- **pyright `reportUnknownVariableType`**: テストの `_RecordingTool.received` が
  `field(default_factory=list)` で `list[Unknown]` に降格（Task 4.3 と同根の loose
  factory）→ `default_factory=list[str]` の**型付きファクトリ**で解消。
- **dict/None 引数テストが `budget_exceeded` で fail**: custom `FunctionModel` が
  usage 未指定だと**入力履歴トークンを自動集計**し budget=100 を踏んだ（症状でなく
  根本: 予算シームが実 usage を読む正しい挙動の証左）→ 台本フェイク同様
  `usage=RequestUsage(output_tokens=1)` を明示供給して決定論化（fix forward でなく
  原因＝usage 供給の欠落を修正）。

### 検証ゲート（実測, lane 配下）

- `uv run ruff check .` → All checks passed!
- `uv run ruff format --check .` → 19 files already formatted
- `uv run pyright`（strict）→ 0 errors, 0 warnings, 0 informations
- `uv run pytest --cov` → 35 passed・2 skipped（無回帰）、
  `autonomous_agent.py` coverage 100%、Total 98.85%（floor 85%）

### 境界順守

- 境界は `autonomous_agent.py` / `test_autonomous_agent.py` の2ファイルのみ。
  lane `__init__.py` 再エクスポートは本タスク境界外（5.1/6.1/7.1 と同じく無改変＝
  lane `__init__` は 005 契約のみ再export）。test は
  `from patterns_pydantic_ai.autonomous_agent import run_autonomous_agent` で直 import。
- 次は Task 8.2（beeai autonomous-agent, `_budget_spent`=`ChatModelOutput.usage`）。

---

## Task 8.2 — beeai autonomous-agent

### Plan（このタスクで実装するもの）

- `run_autonomous_agent(goal, *, llm, max_iterations, allowed_tools,
  approval_hook, budget) -> AgentRunResult` を beeai chat プリミティブ
  （`ChatModel.create`）上の**手動一様ループ**で実装。8.1（pydantic-ai）と同型の
  4ガードレール（max_iterations / allowed_tools / approval_hook / budget）と
  `stop_reason` 4値 Literal を確定。`_budget_spent` は `ChatModelOutput.usage`。
- 境界2ファイル: `src/patterns_beeai/autonomous_agent.py` /
  `tests/unit/test_autonomous_agent.py`。

### Do（実装の要点と判断）

- **chat プリミティブ = `ChatModel.create(messages=...)` 直叩き**（8.1 の
  `Model.request` 相当）。ツール呼出は `output.get_tool_calls()`
  （→`MessageToolCallContent`: `tool_name`/`args`/`id`）、最終回答は
  `output.get_text_content()`（tool-call のみのターンは `""`、venv 実測）で判別。
  フィードバックは `output.messages` を履歴 extend + `ToolMessage(
  MessageToolResultContent(result, tool_name, tool_call_id))` を append。
- **引数正規化不要（レーン差分）**: beeai `MessageToolCallContent.args` は `str`
  固定（venv 実測）。8.1 の `_args_text`（dict/None→str）は不要で、ループは args を
  そのまま `Tool.run` へ渡す。代わりに args 転送テスト（`_RecordingTool`）で str 直通を実証。
- **観測は手動スパン（レーン差分）**: パターン関数に instrumentation 引数を持たせず、
  呼出側が `traced(provider, "pattern.autonomous_agent", ...)` でラップ（beeai 全
  パターン共通方式。8.1 の `instrument_model` 注入と異なる）。signature は `model`→`llm`、
  `instrumentation` 引数なし（evaluator_optimizer 5.2/7.2 と整合）。
- **予算シームの単一点化**: `_budget_spent(output) = output.usage.total_tokens
  if output.usage else 0`。beeai `ChatModelOutput.usage` は `Optional`（8.1 は必須）の
  ため None ガードを seam 内へ閉込め。`TurnSequencedChatModel`（Task 4.2）の
  `ChatModelUsage(total_tokens=...)` を決定論集計。ガードレール境界
  （max_iterations/denied/budget_exceeded=停止、allowed_tools=per-call refusal 継続）と
  steps 全記録（executed/refused/denied）は 8.1 と完全同一。

### エラーと根本原因（盲目的 retry なし）

- 特筆すべき失敗なし。実装前に venv で beeai API（`get_tool_calls`/`get_text_content`/
  `usage` Optional・`MessageToolCallContent.args` str・`ToolMessage`/
  `MessageToolResultContent` の構築）を実測確認してから着手したため、RED→GREEN は一発緑。
- `ruff format` が新規ファイル1件を再整形（長い `MessageToolResultContent(...)` 行の畳み）
  → 適用して clean 化。憲法ルール緩和なし。

### 検証ゲート（実測, lane 配下）

- `uv run ruff check .` → All checks passed!
- `uv run ruff format --check .` → 18 files already formatted
- `uv run pyright`（strict, 3.13）→ 0 errors, 0 warnings, 0 informations
- `uv run pytest --cov` → 36 passed・2 skipped（無回帰）、
  `autonomous_agent.py` coverage 100%、Total 98.99%（floor 85%）

### 境界順守

- 境界は `autonomous_agent.py` / `test_autonomous_agent.py` の2ファイルのみ。
  lane `__init__.py` 再エクスポートは本タスク境界外（5.2/6.2/7.2 と同じく無改変）。
  test は `from patterns_beeai.autonomous_agent import run_autonomous_agent` で直 import。
- 次は Task 8.3（llamaindex autonomous-agent, `_budget_spent`=`CompletionResponse.raw`
  の usage、`{"tool":...,"args":...}` JSON テキストの tool-call 規約 = Task 4.3 申し送り）。

---

### Task 8.3 — llamaindex autonomous-agent 実装（Req 6.1-6.6, 7.2/7.3, 9.1/9.2, 10.3）

#### 実施内容

- **対象**: `src/patterns_llamaindex/autonomous_agent.py`（新規）+
  `tests/unit/test_autonomous_agent.py`（新規）の2ファイル（境界どおり）。契約は
  `patterns_contracts`（`AgentRunResult`/`AgentStep`/`Tool`/`ApprovalHook`）を import。
- **設計（8.1/8.2 と同型の手動ループ）**: `Agent` でなく `llm.acomplete(transcript)` 直叩きの
  chat プリミティブ手動一様ループ。4ガードレール境界は3レーン完全同一 —
  `max_iterations`/`denied`/`budget_exceeded` = ループ停止、`allowed_tools` 違反 = per-call
  refusal で継続（`stop_reason` に "forbidden" 系が無い非対称性が根拠、8.1 申し送り）。steps は
  executed/refused/denied 全記録（R10.3 多層防御で監査証跡 silent empty 不可）。

#### レーン差分（3点）

- ① **tool-call チャネル = JSON 規約**: CustomLLM は completion-only で native tool-call part が
  無いため、Task 4.3 が確立した規約「完了テキストが `{"tool":...,"args":...}` object に parse
  できれば tool 呼出、それ以外（非 JSON / scalar / `"tool"` キー無し object）は最終回答」を
  `_parse_action(text) -> tuple[str,str] | None` に1点化。`args` は str で `Tool.run` へ直通
  （8.2 beeai 同様 dict/None 正規化不要、8.1 pydantic-ai の `_args_text` 不要）。フィードバックは
  履歴オブジェクトでなく **transcript 文字列**を `Action:/Observation:` で累積（completion-only
  ゆえ。実機 Ollama で次ターン条件付け、フェイクは prompt 無視で cursor 進行）。
- ② **予算シーム = `CompletionResponse.raw`**: `_budget_spent(response) =
  response.raw["usage"]["total_tokens"]`。`raw: Optional[Any]`（venv 実測）= opaque provider
  payload のため `_as_mapping(value) -> dict[str,object] | None` で I/O 境界 narrow。usage 欠落
  （raw=None / "usage" キー無し）は 0 寄与（8.2 の `if output.usage else 0` 相当を nested dict で）。
- ③ **観測 = OpenInference process-global**: パターン関数に instrumentation 引数を持たせない
  （eval/parallelization/prompt-chaining と同方式。8.1 の `instrument_model` per-model 注入・
  8.2 の手動 `traced` ラップとは異なるレーン固有方式）。span test は `instrument_llamaindex` 設置 →
  run → `finally` で `uninstrument_llamaindex` detach（計装 process-global ゆえテスト隔離に必須、
  test_evaluator_optimizer.py 流儀）。末端 `acomplete` span（`"llm"`/`"complete"` 名）存在のみ確認。

#### 根本対応（pyright strict・憲法 II）

- `_budget_spent`/`_parse_action` が opaque JSON（`raw: Any` / `json.loads -> Any`）を読むため、
  pyright strict が `.get` で `reportUnknownMemberType` + `reportUnknownArgumentType` を5件報告。
  bare `isinstance(x, dict)` は `dict[Unknown, Unknown]` を生む（`.get` が unknown member）ため、
  ルール緩和ではなく **`isinstance` → `cast("dict[str,object]", x)`** の narrow を `_as_mapping`
  ヘルパに1点集約して解消（憲法 II: `Any` は I/O 境界で narrow、内側へ carry しない）。

#### RED→GREEN（憲法 I）

- RED: `from patterns_llamaindex.autonomous_agent import run_autonomous_agent` →
  `ModuleNotFoundError: No module named 'patterns_llamaindex.autonomous_agent'`（collection error,
  9 tests, 実測）。
- GREEN: 実装後 `uv run --no-sync pytest tests/unit/test_autonomous_agent.py` → 9 passed。
- **カバレッジ補完**: `_budget_spent` の防御分岐（raw=None / usage 欠落）と JSON-非tool-object の
  最終回答分岐は support `TurnSequencedLLM`（raw 固定供給）では到達不能。境界内ローカルフェイク
  `_RawScriptedLLM`（`(text, raw)` ペア台本、prompt_chaining/eval の `_RecordingLLM` 流儀）で
  1テスト追加し pattern.py を 91%→**100%**（8.1 の dict/None 正規化テスト追加と対称）。最終 10 tests。

#### テスト設計

- plan の4契約違反ケースを各個に網羅 — 正常完了（completed）/ 許可リスト違反（refused→継続→
  completed, "not in allowed_tools" observation）/ 承認拒否（denied, final_output=None, canned
  observation 非出現で非実行実証）/ 予算超過（3+3 tokens で budget=5 を2反復目に超過,
  budget_exceeded）/ max_iterations 打切 + `max_iterations<1`・`budget<0` の loud ValueError +
  args 転送（`_RecordingTool`）+ span≥1 + budget-seam 防御（`_RawScriptedLLM`）。

#### 境界順守

- 境界は `autonomous_agent.py` / `test_autonomous_agent.py` の2ファイルのみ。lane `__init__.py`
  再エクスポートは本タスク境界外（8.1/8.2 と同じく無改変）。test は
  `from patterns_llamaindex.autonomous_agent import run_autonomous_agent` で直 import。

#### 検証ゲート（実測, lane 配下 `uv run --no-sync`）

- `ruff check .` → All checks passed / `ruff format --check` → 18 files already formatted /
  `pyright`（strict, 3.13）→ 0 errors, 0 warnings, 0 informations / `pytest --cov` →
  **37 passed・2 skipped**（baseline 27 + autonomous 10 = 無回帰）、`autonomous_agent.py` **100%**、
  Total coverage **99.20%**（floor 85%）。境界外修正ゼロ。

#### 完了

- これで Major Task 8（autonomous-agent 3レーン・ガードレール契約）の全サブタスク（8.1〜8.3）完了 —
  3レーンとも4ガードレール（max_iterations / allowed_tools / approval_hook / budget）+ `stop_reason`
  Literal 同一、`_budget_spent` シーム1点化で予算会計を決定論化。各 FW 固有の chat プリミティブ
  （`Model.request` / `ChatModel.create` / `llm.acomplete`）・観測方式（注入 / 手動 traced /
  OpenInference）で実装。次は Task 9（可観測性検証, 依存 5/6/7/8 充足）または Task 10（Ollama 結合）。

#### 集約クロスレーン検証ゲート（Task 8 確定, `mise run patterns:check` 実測）

- 各サブタスクの per-lane ゲートに加え、3レーン同時の集約ゲートを実行し最終確定 — `lint`
  全レーン All checks passed / `format` 19+18+18 files already formatted / `typecheck`
  全レーン 0 errors, 0 warnings, 0 informations / `test`:
  pydantic-ai **35 passed・2 skipped**（total 98.85%）、beeai **36 passed・2 skipped**
  （total 98.99%）、llamaindex **37 passed・2 skipped**（total 99.20%）。3レーンとも
  `autonomous_agent.py` **coverage 100%**、`test_autonomous_agent.py` 9+9+10=28 tests 全緑。
  floor 85% を全レーン充足、無回帰を確認。

---

## Task 9.1 — pydantic-ai: 新4パターンの span≥1 検証（test_observability.py）

#### スコープ / 境界

- 境界は `patterns/frameworks/pydantic-ai/tests/unit/test_observability.py` のみ（テスト専用）。
  本ファイルは既に routing の span≥1 を検証済み。新4パターン（prompt-chaining /
  parallelization / evaluator-optimizer / autonomous-agent）の span≥1 検証を集約追加。
  src/ 実装は Task 5.1〜8.1 で既に span を発行するため**プロダクトコード変更ゼロ**。

#### RED→GREEN（憲法 I — テスト専用タスクでも teeth を実証）

- RED: 4テストを `instrumentation` 未配線（既定 `None`）で追加 → 末端 span が一切流れず
  `assert spans`（`assert ()`）で **4 failed, 2 passed**（実測）。これにより各アサーションが
  「可観測性の配線そのもの」を検証していることを実証（vacuous でない）。
- GREEN: 各 `run_*` 呼出に `instrumentation=settings` を配線 → **6 passed**（baseline 2 +
  新規 4）。leaf `gen_ai` span 存在のみ確認（Req 9.3、トークン集計は backend 責務＝二重計上回避）。

#### テスト設計（フェイク流用 — 各パターンの実証済み台本を踏襲）

- prompt-chaining: `scripted_model(text="alpha beta gamma")`（3語で `GATE_MIN_WORDS=3` を通過し
  finalize まで到達）。parallelization: `voting_model(["x","x","y"])` の voting/n=3。
  evaluator-optimizer: `verdict_sequenced_model([{verdict:pass}], candidate="answer")` で1反復 pass。
  autonomous-agent: `turn_sequenced_model([FinalTurn("done")])` + `allowed_tools=[]` +
  `_approve_all`（必須引数だが dangerous tool 不在ゆえ未行使）+ budget=10。
- 各パターン固有テストファイルにも span テストは存在するが、本ファイルは「可観測性」専用集約スイート
  （routing を既に内包）として設計（plan.md「observability 適用」セクション準拠）。重複ではなく
  関心分離 — 境界外の pattern テストファイルは無改変。

#### 検証ゲート（実測, lane 配下 `uv run --no-sync`）

- `ruff check .` → All checks passed / `ruff format --check .` → 19 files already formatted
  （formatter が parallelization/evaluator 呼出を1行へ整形、適用済み）/ `pyright`（strict, 3.13）
  → 0 errors, 0 warnings, 0 informations / `pytest --cov` → **39 passed・2 skipped**
  （baseline 35 + observability 新規 4 = 無回帰）、Total coverage **98.85%**（floor 85%）。
  境界外修正ゼロ。次は 9.2（beeai）/ 9.3（llamaindex）。

## Task 9.2 — beeai: 新4パターンの span≥1 検証（test_observability.py）

#### スコープ / 境界

- 境界は `patterns/frameworks/beeai/tests/unit/test_observability.py` のみ（テスト専用）。
  本ファイルは既に routing の span≥1 を検証済み。新4パターン（prompt-chaining /
  parallelization / evaluator-optimizer / autonomous-agent）の span≥1 検証を集約追加。
  src/ 実装は Task 5.2〜8.2 で既に手動スパン経由 span を発行するため**プロダクトコード変更ゼロ**。

#### レーン差分（span 源 = 手動スパン fallback, Req 9.1）

- pydantic-ai 9.1 は各 `run_*` へ `instrumentation=settings` を注入し leaf `gen_ai`
  span を流す。beeai は first-party OTel instrumentation API 不在のため、呼出側が
  `traced(provider, "pattern.<name>", coroutine)` でラップして単一 `pattern.<name>`
  span を開く方式（plan §8 R-3、routing 既存テストと同型）。アサートは span 名一致のみ。

#### RED→GREEN（憲法 I — テスト専用タスクでも teeth を実証）

- RED: 4テストを `traced` 未ラップ（coroutine を直接 await）で追加 → 手動 span が一切
  流れず `assert spans`（`assert ()`）で **4 failed・2 passed**（実測）。これにより各
  アサーションが「可観測性の配線そのもの（`traced` ラップ）」を検証する＝vacuous でない
  ことを実証。
- GREEN: 各 `run_*` 呼出を `traced(provider, "pattern.<name>", ...)` でラップ →
  **6 passed**（baseline 2 + 新規 4）。`pattern.<name>` span 存在のみ確認（Req 9.3、
  トークン集計は backend 責務＝二重計上回避）。

#### テスト設計（フェイク流用 — 各パターンの実証済み台本を踏襲）

- prompt-chaining: `ScriptedChatModel(text="alpha beta gamma")`（3語で `GATE_MIN_WORDS`
  を通過し finalize 到達）。parallelization: `VotingChatModel(["x","x","y"])` の
  voting/n=3。evaluator-optimizer: `VerdictSequencedChatModel([{verdict:pass}],
  candidate="answer")` で1反復 pass。autonomous-agent:
  `TurnSequencedChatModel([FinalTurn("done", tokens=1)])` + `allowed_tools=[]` +
  `_approve_all` + budget=10。各パターン固有テストにも span テストは存在するが、本
  ファイルは可観測性専用集約スイート（routing 内包）として関心分離（9.1 と同判断）。

#### 検証ゲート（実測, lane 配下 `uv run --no-sync`）

- `ruff check .` → All checks passed / `ruff format --check .` → 18 files already
  formatted / `pyright`（strict, 3.13）→ 0 errors, 0 warnings, 0 informations /
  `pytest` → **40 passed・2 skipped**（baseline 36 + observability 新規 4 = 無回帰）、
  coverage floor 85% 満たす（observability は test 専用 = coverage source 対象外）。
  境界外修正ゼロ。次は 9.3（llamaindex）。

---

## Task 9.3 — llamaindex: 新4パターンの span≥1 検証（test_observability.py）

#### スコープ / 境界

- 境界は `patterns/frameworks/llamaindex/tests/unit/test_observability.py` のみ（テスト専用）。
  本ファイルは既に routing の span≥1 を検証済み。新4パターン（prompt-chaining /
  parallelization / evaluator-optimizer / autonomous-agent）の span≥1 検証を集約追加。
  src/ 実装は Task 5.3〜8.3 で既に OpenInference 経由 span を発行するため**プロダクトコード変更ゼロ**。

#### レーン差分（span 源 = OpenInference process-global instrumentor, Req 9.1）

- pydantic-ai 9.1 は `instrumentation=settings` 注入で leaf `gen_ai` span、beeai 9.2 は
  手動 `traced` ラップで `pattern.<name>` span。llamaindex は **process-global instrumentor** —
  `instrument_llamaindex(provider)` install → run → `finally` で `uninstrument_llamaindex`
  detach（process-global state は test 間で隔離必須、routing 既存テストと同型）。アサートは
  leaf LLM span 存在のみ（span 名に `"llm"`/`"complete"` 含有、token 集計は不問＝Req 9.3）。

#### RED→GREEN（憲法 I — テスト専用タスクでも teeth を実証）

- RED: 4テストを instrumentor 未 install（`configure_tracing(exporter)` のみで run）で追加 →
  process-global span が一切流れず `assert spans`（`assert ()`）で **4 failed**（実測）。
  これにより各アサーションが「可観測性の配線そのもの（instrumentor install）」を検証する＝
  vacuous でないことを実証。
- GREEN: 各 `run_*` 呼出を `instrument_llamaindex`/`uninstrument_llamaindex` の try/finally で
  囲む → **6 passed**（baseline 2 + 新規 4）。leaf LLM span 存在のみ確認（Req 9.3、トークン
  集計は backend 責務＝二重計上回避）。

#### テスト設計（フェイク流用 — 各パターンの実証済み台本を踏襲）

- prompt-chaining: `ScriptedLLM(text="alpha beta gamma")`（3語で gate 通過し finalize 到達）。
  parallelization: `ScriptedLLM(text="answer")` の voting/n=3（同一出力で全会一致＝集計から
  span アサートを分離）。evaluator-optimizer: `VerdictSequencedLLM([{verdict:pass}],
  candidate="answer")` で1反復 pass。autonomous-agent:
  `TurnSequencedLLM([FinalTurn("done", tokens=1)])` + `allowed_tools=[]` + `_approve_all` +
  budget=10。各パターン固有テストにも span テストは存在するが、本ファイルは可観測性専用
  集約スイート（routing 内包）として関心分離（9.1/9.2 と同判断）。

#### 検証ゲート（実測, lane 配下 `uv run --no-sync`）

- `ruff check` → All checks passed / `ruff format --check` → 1 file already formatted /
  `pyright`（strict, 3.13）→ 0 errors, 0 warnings, 0 informations / `pytest` →
  **41 passed・2 skipped**（baseline 37 + observability 新規 4 = 無回帰）、coverage floor 85%
  満たす（observability は test 専用 = coverage source 対象外）。境界外修正ゼロ。これで
  Major Task 9（可観測性検証 3レーン）の全サブタスク（9.1〜9.3）完了。次は Task 10
  （Ollama 結合テスト 3レーン）。

---

### Task 10.1 — pydantic-ai: 新4パターンの契約レベル Ollama 結合ケース

**境界**: `patterns/frameworks/pydantic-ai/tests/integration/test_ollama_e2e.py` のみ（src 無改変）。
**依存**: 5.1/6.1/7.1/8.1（実装済）。Req 8.1（ゲート）/8.2（契約レベル）/8.3（env 由来モデル）。

#### RED → GREEN（test-only タスクの位置づけ）

- src は Task 5–8 で実装済みのため RED は「収集差分」: 追記前 integration 2 ケース →
  追記後 6 ケース。オフライン（`RUN_INTEGRATION_PATTERNS` 未設定）で `pytest tests/integration`
  → **6 skipped**（import 解決・gate 機能・無回帰を実証）。
- GREEN（実モデル実測）: `RUN_INTEGRATION_PATTERNS=1 OLLAMA_MODEL_NAME=granite4.1:8b
  uv run --no-sync pytest tests/integration --no-cov` → **6 passed in 342.53s**
  （baseline 2 + 新規 4）。ローカル Ollama 実機（granite4.1:8b）に対する生実行。

#### テスト設計（契約レベルのみ — 厳密文字列を一切アサートしない, Req 8.2）

- prompt-chaining: `len(steps) >= 1` かつ各 step.output 非空（final_output は gate 委任で不問）。
- parallelization: variant="sectioning", n=2 で `len(branches) == n` かつ `aggregate.strip()` 非空。
- evaluator-optimizer: `stop_reason in get_args(OptimizationResult.model_fields["stop_reason"]
  .annotation)`（語彙を契約から導出＝ハードコード回避）かつ `final_output.strip()` 非空。
- autonomous-agent: `stop_reason in get_args(AgentRunResult.model_fields["stop_reason"]
  .annotation)` かつ `total_budget_spent >= 0`。tool schema 未登録のため実モデルは tool call
  ではなく最終回答を返す → `completed` 経路。required 引数充足のため最小 `_NoopTool` +
  `_approve_all` + budget=1_000_000 を注入。
- モデル ID は `OLLAMA_MODEL_NAME`/`OLLAMA_BASE_URL` の env 由来のみ（Req 8.3、ハードコード無）。

#### 検証ゲート（実測, lane 配下 `uv run --no-sync`）

- `ruff check`（対象ファイル）→ All checks passed / `ruff format --check` → 1 file already
  formatted / `pyright`（strict, 3.13）→ 0 errors, 0 warnings, 0 informations。
- オフライン無回帰: `pytest --cov` → **39 passed・6 skipped**、coverage 98.85%（floor 85% 満たす；
  integration は test 専用 = coverage source 対象外）。境界外修正ゼロ。
- 次は 10.2（beeai）/10.3（llamaindex）。

---

### Task 10.2 — beeai: 新4パターンの契約レベル Ollama 結合ケース

**境界**: `patterns/frameworks/beeai/tests/integration/test_ollama_e2e.py` のみ（src 無改変）。
**依存**: 5.2/6.2/7.2/8.2（実装済）。Req 8.1（ゲート）/8.2（契約レベル）/8.3（env 由来モデル）。

#### レーン差分（DI シーム = `llm=` キーワード, 10.1 の `model=` と非対称）

- beeai 全パターン関数は `llm: ChatModel` キーワード引数（pydantic-ai は `model=`）。既存
  `_ollama_chat_model()` helper（litellm-backed `OllamaChatModel`、`OLLAMA_BASE_URL` の `/v1`
  を `removesuffix` で剥がす daemon-root 規約）を全 4 ケースへ注入。`# type: ignore[arg-type]`
  は helper が `object` を返す既存スタイルを踏襲。
- autonomous の引数充足ヘルパ（`_NoopTool`/`_approve_all`）は 10.1 と同型を移植。beeai は
  `MessageToolCallContent.args` が str 固定（8.2 ノート）のため引数正規化は不要だが、tool
  schema 未登録で実モデルは最終回答 → `completed` 経路に到達するのは 10.1 と同じ。

#### RED → GREEN（test-only タスクの位置づけ）

- src は Task 5–8 で実装済みのため RED は「収集差分」: 追記前 integration 2 ケース →
  追記後 6 ケース。オフライン（`RUN_INTEGRATION_PATTERNS` 未設定）で
  `pytest tests/integration/test_ollama_e2e.py --co` → 2 → 6 collected、`pytest` → **6 skipped**
  （import 解決・gate 機能・無回帰を実証）。
- GREEN（実モデル）: Ollama 常駐環境で `RUN_INTEGRATION_PATTERNS=1
  OLLAMA_MODEL_NAME=granite4.1:8b uv run --no-sync pytest tests/integration` 実行時に到達。
  本セッション環境は Ollama 非常駐のため gate により skip（10.1 が実機 6 passed で経路実証済）。

#### テスト設計（契約レベルのみ — 10.1 と完全同一, Req 8.2）

- prompt-chaining: `len(steps) >= 1` かつ各 step.output 非空（final_output は gate 委任で不問）。
- parallelization: variant="sectioning", n=2 で `len(branches) == n` かつ `aggregate.strip()` 非空。
- evaluator-optimizer: `stop_reason in get_args(OptimizationResult.model_fields["stop_reason"]
  .annotation)`（語彙を契約から導出＝ハードコード回避）かつ `final_output.strip()` 非空。
- autonomous-agent: `stop_reason in get_args(AgentRunResult.model_fields["stop_reason"]
  .annotation)` かつ `total_budget_spent >= 0`。`_NoopTool` + `_approve_all` + budget=1_000_000 注入。
- モデル ID は `OLLAMA_MODEL_NAME`/`OLLAMA_BASE_URL` の env 由来のみ（Req 8.3、ハードコード無）。

#### 検証ゲート（実測, lane 配下 `uv run --no-sync`）

- `ruff check`（対象ファイル）→ All checks passed / `ruff format --check` → 1 file already
  formatted / `pyright`（strict, 3.13）→ 0 errors, 0 warnings, 0 informations。
- オフライン無回帰: lane 全体 `pytest --cov` → **40 passed・6 skipped**（baseline 40 passed・
  2 skipped + 新規 4 gated）、coverage 98.99%（floor 85% 満たす；integration は test 専用 =
  coverage source 対象外）。境界外修正ゼロ。
- 次は 10.3（llamaindex）。

---

### Task 10.3 — llamaindex: 新4パターンの契約レベル Ollama 結合ケース

**境界**: `patterns/frameworks/llamaindex/tests/integration/test_ollama_e2e.py` のみ（src 無改変）。
**依存**: 5.3/6.3/7.3/8.3（実装済）。Req 8.1（ゲート）/8.2（契約レベル）/8.3（env 由来モデル）。

#### レーン差分（DI シーム = `llm=` キーワード, beeai と同型 / 10.1 の `model=` と非対称）

- llamaindex 全パターン関数は `llm: LLM` キーワード引数（beeai と同じ、pydantic-ai は `model=`）。
  既存 `_ollama_llm()` helper（`llama_index.llms.ollama.Ollama`、`OLLAMA_BASE_URL` の `/v1` を
  `removesuffix` で剥がす daemon-root 規約、`request_timeout=180.0`）を全 4 ケースへ注入。
  `# type: ignore[arg-type]` は helper が `object` を返す既存スタイルを踏襲。
- autonomous の引数充足ヘルパ（`_NoopTool`/`_approve_all`）は 10.1/10.2 と同型を移植。llamaindex も
  args は str 直通（8.3 ノート）で正規化不要。tool schema 未登録で実モデルは最終回答 → `completed`
  経路に到達するのは 10.1/10.2 と同じ。

#### RED → GREEN（test-only タスクの位置づけ）

- src は Task 5–8 で実装済みのため RED は「収集差分」: 追記前 integration 2 ケース →
  追記後 6 ケース。オフライン（`RUN_INTEGRATION_PATTERNS` 未設定）で
  `pytest tests/integration/test_ollama_e2e.py --co` → 2 → 6 collected、`pytest` → **6 skipped**
  （import 解決・gate 機能・無回帰を実証）。
- GREEN（実モデル）: Ollama 常駐環境で `RUN_INTEGRATION_PATTERNS=1
  OLLAMA_MODEL_NAME=granite4.1:8b uv run --no-sync pytest tests/integration` 実行時に到達。
  本セッション環境は Ollama 非常駐のため gate により skip（10.1 が実機 6 passed で経路実証済）。

#### テスト設計（契約レベルのみ — 10.1/10.2 と完全同一, Req 8.2）

- prompt-chaining: `len(steps) >= 1` かつ各 step.output 非空（final_output は gate 委任で不問）。
- parallelization: variant="sectioning", n=2 で `len(branches) == n` かつ `aggregate.strip()` 非空。
- evaluator-optimizer: `stop_reason in get_args(OptimizationResult.model_fields["stop_reason"]
  .annotation)`（語彙を契約から導出＝ハードコード回避）かつ `final_output.strip()` 非空。
- autonomous-agent: `stop_reason in get_args(AgentRunResult.model_fields["stop_reason"]
  .annotation)` かつ `total_budget_spent >= 0`。`_NoopTool` + `_approve_all` + budget=1_000_000 注入。
- モデル ID は `OLLAMA_MODEL_NAME`/`OLLAMA_BASE_URL` の env 由来のみ（Req 8.3、ハードコード無）。

#### 検証ゲート（実測, lane 配下 `uv run --no-sync`）

- `ruff check`（対象ファイル）→ All checks passed / `ruff format --check` → 1 file already
  formatted / `pyright`（strict, 3.13）→ 0 errors, 0 warnings, 0 informations。
- オフライン無回帰: lane 全体 `pytest --cov` → **41 passed・6 skipped**（baseline 41 passed・
  2 skipped + 新規 4 gated）、coverage 99.20%（floor 85% 満たす；integration は test 専用 =
  coverage source 対象外）。境界外修正ゼロ。
- これで Major Task 10（Ollama 結合テスト 3レーン）の全サブタスク（10.1〜10.3）完了。
  次は Task 11（README・タクソノミー・セキュリティドキュメント）。

---

## Task 11.1 — 新4パターン README の必須4セクション + フレームワーク差異比較（2026-06-13）

**境界**: `patterns/{prompt-chaining,parallelization,evaluator-optimizer,autonomous-agent}/README.md`（4本）
**Req**: 11.2（必須4セクション）/ 11.3（4軸の比較形式記載）

### アプローチ

各 README の既存 `## パターン契約（正本）` ブロック**直後**へ `## 3実装` 比較表 +
`## 必須4セクション`（型安全 / テスト / 可観測性 / セキュリティ）を追記。routing /
orchestrator-workers の確立スタイル（impl リンク + 3レーン差分表）を踏襲。Req 11.3 の
4軸を各 README で比較形式に網羅:

- **構造化出力方式** → 型安全セクション + 3実装表（prompt-chaining=plain text /
  parallelization=branch plain + 集約 / evaluator-optimizer=`_Evaluation` 取得3方式 /
  autonomous-agent=tool-call 検出3方式）。
- **fan-out 機構** → 3実装表（parallelization=`gather` vs Workflows ネイティブ /
  他3パターンは「fan-out 無し」を明記し連鎖・逐次・ツールループ機構を記載）。
- **フェイク台本化手段** → テストセクション（`voting_model`/`VotingChatModel`/`VotingLLM`、
  `verdict_sequenced_model`/…、`turn_sequenced_model`/… + 境界ローカル記録フェイク）。
- **固有リスク** → セキュリティセクション（silent 継続 / Unbounded Consumption /
  無制限反復 / OWASP Agentic AI 4ガードレール）。

内容は Task 5–8 の Implementation Notes と support フェイク実体から事実抽出（捏造ゼロ）。

### 重要制約 — ドリフト parser 非破壊

`test_contract_drift.py` は `## パターン契約` 見出し直下の**最初の** ```python fence を
抽出し**最初の閉じ fence**で停止する。よって追記は必ず契約ブロックの閉じ fence より後に
置き、新セクション内へ `## パターン契約` 見出し・```python fence を一切導入しない
（Task 2.3 の「Task 11 追加セクション混入に頑健」設計の前提）。

### TDD（RED→GREEN、Task 2.1 drift-mirror 先例に倣う）

throwaway アドホック検証（境界は README 4本のみのため commit せず）:

- **RED**: 4 README に `### 型安全/テスト/可観測性/セキュリティ`・4軸キーワード・
  3レーン名が不在 → **43 checks failed（exit 1）**。
- **GREEN**: 4 README 追記後 → **ALL PASS（exit 0）**。
- **回帰ガード**: drift test を編集前後で実行 — 編集前 **4 passed**（baseline）→
  編集後も **4 passed**（契約ブロック class/field/Literal 無改変を実証）。

### 検証ゲート（実測, contracts lane `uv run --no-sync`）

- `ruff check .` → All checks passed
- `ruff format --check .` → 8 files already formatted
- `pyright`（strict, 3.13）→ 0 errors, 0 warnings, 0 informations
- `pytest --cov`（drift test）→ **4 passed**, coverage 100%（floor 85% 満たす）
- `forbid-hardcoded-model-ids` は `types: [python]` ゆえ markdown 非対象。新文に
  モデル ID リテラル無し（フレームワーク機構名のみ）。境界外修正ゼロ。

次は Task 11.2（`patterns/README.md` 二軸タクソノミー表 + contracts パッケージ注記）。

## Task 11.2 — patterns/README.md タクソノミー表 + contracts パッケージ注記

### 実施

- 二軸タクソノミー表（`patterns/README.md`）の新4パターン行を「将来イテレーション」
  から **✅実装済み + 各パターン README へのリンク**へ更新（routing/orchestrator-workers
  の確立スタイルに合わせパターン名を bold 化、IBM 粒度列にも実装済み行と同様の
  機構説明パレンを補完: prompt-chaining=逐次ステップ＋ゲート / parallelization=
  sectioning/voting fan-out / evaluator-optimizer=生成器⇄評価器ループ /
  autonomous-agent=ツールループ＋ガードレール。内容は spec 用語集から事実抽出）。
- 「レーン構成」節の **stale 参照を書換え**（Task 2.4 申し送り）— 旧「契約はレーン間で
  複製され、ルートの `test_patterns_contract_sync.py` がドリフトを検知する」を、
  shared-contracts パッケージ [contracts/](../../patterns/contracts/README.md) への集約 +
  `tool.uv.sources` パス依存 import（複製なし）+ 単一ドリフトテスト
  `test_contract_drift.py` 検知、へ更新（Req 1.5/2.2/NFR-5 の現アーキテクチャへ整合）。

### TDD（RED→GREEN、Task 11.1 throwaway アドホック先例に倣う）

境界が `patterns/README.md` 1本（doc）のため throwaway 検証スクリプト（commit せず）:

- **RED**: 現 README に対し 4パターン行の ✅/リンク/「将来イテレーション」除去・
  stale 参照除去・contracts リンク・drift test 注記を照合 → **16/20 FAIL（exit 1）**。
- **GREEN**: 編集後 → **20/20 PASS（exit 0）**。

### 検証ゲート（実測）

- 索引リンク解決: 6パターン README + contracts/README.md すべて存在（OK）。
- 非回帰: contracts lane drift test（`uv run --no-sync pytest test_contract_drift.py`）
  → **4 passed in 0.06s**。`patterns/README.md` は drift parser の対象外（読み込み
  対象は6パターン README の `## パターン契約` fence + パッケージ introspect のみ）の
  ため契約照合に無影響＝本編集は契約に非干渉であることを実証。

### 計画からの逸脱・知見

- 境界外修正ゼロ。Task 2.4 が 11.2 へ申し送った stale 参照（`patterns/README.md:51`）を
  本タスクで解消（2.2 が 2.4 へ削除を申し送ったのと対称の境界規律）。
- IBM 粒度の再分類（autonomous-agent を「唯一の Agent 型」へ動かす等）は Req 11.1 の
  範囲外（「実装済み表示 + 索引リンク」のみ）のため既存分類（全行 Agentic AI）を維持。

次は Task 11.3（`patterns/SECURITY-NOTES.md` の OWASP Agentic AI マッピング追記）。

## Task 11.3 — SECURITY-NOTES.md の autonomous-agent 4ガードレール → OWASP マッピング（2026-06-13）

**Boundary**: `patterns/SECURITY-NOTES.md` / **Req**: 10.1（10.3 多層防御を併記）

### 実施

- 既存 OWASP 節（routing/orchestrator-workers 表）の直後・`## 既知の制約` の直前へ、
  専用サブ節 `### autonomous-agent ガードレール → OWASP Agentic AI マッピング
  （Spec 006 Req 10.1）` を追記。4ガードレール→3リスク項目の**非対称写像**を表で記録:
  - `allowed_tools`（最小権限）→ **過剰エージェンシー / Insecure Tool Use**:
    許可外は実行せず拒否 observation を feedback して**ループ継続**（per-call
    refusal、停止語彙に "forbidden" 系を持たない非対称性に整合、Req 6.4）。
  - `approval_hook` → **Human-in-the-loop bypass / 過剰エージェンシー**:
    否認で**ループ停止** `stop_reason="denied"`・`final_output=None`（Req 6.5）。
  - `budget` → **Unbounded Consumption（無制限消費）**: `_budget_spent` 1点集計、
    `total_budget_spent > budget` で `stop_reason="budget_exceeded"`（Req 6.6）。
  - `max_iterations` → **Unbounded Consumption**: 上限到達で
    `stop_reason="max_iterations"`（暴走ループの上界、Req 6.3）。
- 多層防御（Req 10.3）: 実行/拒否/否認の全試行を `AgentRunResult.steps` に記録 →
  監査証跡が silent empty にならない（Repudiation / Untraceability の緩和）と明記。
  fan-out 無しの逐次ループゆえ `max_iterations`＋`budget` の二重上界が無制限消費対策
  （routing/orchestrator の `max_workers` とレーン横断で対称）と補足。

### OWASP リスク名の出典規律（捏造ゼロ）

- 本モデルで Web 検索が不可（`web_search` 非対応）、OWASP の landing ページも
  threat code（Tx）を露出しないため、**官製 Tx コードは導入しない**判断。
- 代わりにリポジトリ既存の正本語彙で写像 — `specs/005-cross-platform/research.md`
  R-7（過剰エージェンシー/Insecure Tool Use・Unbounded Consumption）、
  `autonomous-agent/README.md` §セキュリティ（Human-in-the-loop bypass）、既存
  OWASP 表の用語に整合。`stop_reason` 4値は drift-test 済み契約 `Literal` を引用。

### TDD（RED→GREEN、Task 11.1/11.2 throwaway 先例に倣う）

境界が markdown 1本（正規 test なし）のため throwaway 検証スクリプト（commit せず）:

- **RED**: 19 checks 中 **17 FAIL（exit 1）**。pass した2件は既存 routing 表の
  "Insecure Tool Use" / "Unbounded Consumption" セル（autonomous-agent 固有17件が欠落）。
- **GREEN**: 追記後 **ALL 19 PASS（exit 0）**。

### 検証ゲート（実測、contracts lane `uv run --no-sync`）

- ruff `All checks passed!` / format `8 files already formatted` /
  pyright(strict,3.13) `0 errors, 0 warnings` / pytest `4 passed` /
  coverage `Total coverage: 100.00%`（floor 85%）。
- 非回帰: `test_contract_drift.py` **4 passed in 0.06s**。SECURITY-NOTES.md は
  drift parser の対象外（6パターン README の `## パターン契約` fence のみ読む）＝
  契約照合に無影響を実証。

### 計画からの逸脱・知見

- 境界外修正ゼロ。autonomous-agent README（Task 11.1）が「詳細マッピングは
  SECURITY-NOTES.md（Task 11.3 で追記）」と申し送った参照を本タスクで実体化。
- これで Major Task 11（README・タクソノミー・セキュリティ）全サブタスク
  （11.1〜11.3）完了。残: Task 12（DX・CI・品質ゲート整合）。

---

## Task 12.1 — mise `patterns:*` に contracts パッケージ手順を統合

_Boundary:_ `mise.toml`（境界内のみ。lane/contracts の pyproject・CI は無変更）
_Requirements:_ 10.2, 13.1

### 設計判断

- contracts は lanes が `tool.uv.sources` で取り込む単一正本。ゆえに gate では
  **lane ループより前**に contracts を処理し、`set -e` で contracts 失敗が
  lanes 実行前に run を停止するよう配置（Req 10.2 / 13.1）。
- 6タスク（setup / lint / format / typecheck / test / audit）すべてに
  `echo "== <verb> patterns/contracts"; (cd patterns/contracts && uv …)` を
  ループ直前へ追加。`patterns:audit` は contracts の `pip-audit`（dev group）を含む。
- 各 verb の uv サブコマンドは lane と対称: setup=`uv sync --all-groups`,
  lint=`ruff check .`, format=`ruff format --check .`, typecheck=`pyright`,
  test=`pytest --cov`, audit=`pip-audit`。

### TDD（RED→GREEN、Task 11.x throwaway 先例に倣う）

境界が `mise.toml` 1本（正規 test なし）のため throwaway 検証スクリプト
（`/tmp/verify_task_12_1.py`、commit せず）で tomllib パースし「contracts 手順が
lane ループより前」「audit は pip-audit」を表明:

- **RED**: 6/6 FAIL（exit 1）— 全 `patterns:*` に `patterns/contracts` 手順なし。
- **GREEN**: 追記後 6/6 PASS（exit 0）。

### 検証ゲート（実測）

mise 経由で実タスクを実行し、contracts が lane より先に処理され green を確認:

- `mise run patterns:format` → exit 0。`== format patterns/contracts` →
  `8 files already formatted`、続けて beeai/llamaindex/pydantic-ai 各レーン clean。
- `mise run patterns:lint` → exit 0。`== lint patterns/contracts` →
  `All checks passed!`、3レーンも `All checks passed!`。
- `mise run patterns:typecheck` → exit 0。`== typecheck patterns/contracts` →
  `0 errors, 0 warnings, 0 informations`、3レーンも 0 errors。
- 3種の独立ツール（ruff / ruff format / pyright）が contracts venv に存在し
  green を実証。setup/test/audit は構造スクリプトで対称配置を確認（test は全 suite
  再実行、audit は脆弱性DB 通信を伴うため live 実行は次タスク以降の統合ゲートに委譲）。

### 計画からの逸脱・知見

- 境界外修正ゼロ（`mise.toml` のみ）。説明コメントに contracts-first の根拠
  （単一正本ゆえ lanes 依存の前に gate green が必要）を追記。
- 残: Task 12.2（patterns-ci.yml に contracts パス・ジョブ追加）、12.3、12.4。

---

## Task 12.2 — patterns-ci.yml に contracts 検証ジョブとパストリガを追加

_Boundary:_ `.github/workflows/patterns-ci.yml`（境界内のみ）
_Requirements:_ 12.1, 10.4

### 設計判断

- **paths トリガ**: `patterns/**` は既に `patterns/contracts/**` を包含するが、
  Req 12.1 の明示要求どおり `patterns/contracts/**` を push/pull_request 両方へ
  追加（contracts は lanes が取り込む単一正本＝first-class CI surface である旨を
  コメントで明記）。
- **contracts ジョブ**: lane は `frameworks/*` のマトリクスだが contracts は
  `patterns/contracts/` の単一 uv プロジェクト（Python 3.13＝レーン floor / NFR-5）
  ゆえ、マトリクス外の専用ジョブ `contracts` を追加し lane ゲートをミラー:
  uv sync --locked → ruff check → ruff format --check → pyright → pytest --cov
  → pip-audit。ADR-8（contracts もゲート対象）に整合。
- **ドリフト**: 専用ステップは設けず、pytest が
  `tests/unit/test_contract_drift.py`（README 正本 == パッケージ、Req 2.1/2.2）を
  実行することで「test + ドリフト」を 1 ステップで充足。
- **uv キャッシュ**: `cache-dependency-glob: patterns/contracts/uv.lock` でレーンと
  分離。

### Req 10.4 検証（除外設定が patterns/contracts/ を落とさないこと）

`.pre-commit-config.yaml` を読取検証（境界外＝編集なし）:

- `gitleaks`: exclude 無し＝リポジトリ全域（patterns/contracts/ を含む）。
- `forbid-hardcoded-model-ids`: `exclude: ^(tests/.*|src/.*/config\.py)$` ＝
  patterns/ を除外しない。
- `^patterns/` 除外は ruff-check / ruff-format-check / pyright の3フックのみ
  （レーンは独立 uv プロジェクトゆえ root venv ゲート対象外＝意図的。contracts も
  同様に patterns-ci.yml + mise で担保）。
→ 秘密情報・ハードコード model ID の repo-wide 不変条件は patterns/contracts/ を
  カバーしており Req 10.4 を満たす。

### TDD（RED→GREEN、Task 12.1 と同じ throwaway 先例）

境界が YAML 1本のため throwaway 構造検証スクリプト（`/tmp/verify_task_12_2.py`、
commit せず、PyYAML パース）で「paths に contracts」「contracts ジョブの
lint/format/typecheck/test/audit ステップ」「uv.lock キャッシュ」「Req 10.4 不変条件」を
表明:

- **RED**: 3 FAIL（exit 1）— push/pull_request paths に contracts 欠落 + contracts
  ジョブ不在。Req 10.4 チェックは当初から PASS（既存 pre-commit 設定が健全）。
- **GREEN**: 追記後 ALL PASS（exit 0）。

### 検証ゲート（実測）

- YAML 妥当性: `yaml.safe_load` がエラーなくパース（構造スクリプト内で実証）。
- actionlint: 未インストールのためスキップ（`⚠️ actionlint 不在`）。
- contracts ジョブ手順をローカル実行（`patterns/contracts/`、CI と同一コマンド）:
  ruff `All checks passed!` / format `8 files already formatted` /
  pyright `0 errors, 0 warnings` / pytest `4 passed`（drift 含む）coverage
  `100.00%`（floor 85）/ pip-audit `No known vulnerabilities found`
  （local `patterns-contracts` のみ PyPI 不在で skip＝想定どおり）。

### 計画からの逸脱・知見

- 境界外修正ゼロ（`patterns-ci.yml` のみ）。Req 10.4 は読取検証で充足、編集不要。
- 残: Task 12.3（patterns-integration-ollama.yml）、12.4（README・カバレッジフロア）。

---

## Task 12.3 — patterns-integration-ollama.yml に新4パターンを反映

_Boundary:_ `.github/workflows/patterns-integration-ollama.yml`（境界内のみ）
_Requirements:_ 12.2（spec の Req 番号）

### 設計判断（pre-existing 機構の上に最小の反映）

- 実行ステップ `mise run patterns:test:integration` は Spec 005 で既設。当該 mise
  タスクは **pattern-agnostic**（レーン毎に `tests/integration/` 全体を実行）ゆえ、
  Task 10 で各レーン `test_ollama_e2e.py` に追加された新4パターン
  （prompt_chain / parallelization / evaluator_optimizer / autonomous_agent）の
  e2e ケースは**追加ステップ無しで既に実行対象**。
- よって 006-2a の差分は「トリガ面と文書化スコープを6パターンへ反映」:
  1. **PR paths に `patterns/contracts/**` 追加** — 新4パターンは契約を共有
     パッケージから import し、e2e は契約レベル挙動を表明するため、契約変更が
     ライブゲートを再トリガするのが正（patterns-ci.yml / Task 12.2 と対称。push
     トリガは既に `patterns/**` で包含）。
  2. **ジョブ名/ヘッダコメントを6パターン×3レーンへ更新**（実スコープとの drift 解消）。
- timeout-minutes(45) は据置: 6パターン×3レーン=18 ライブ生成でも、モデル warm 後
  逐次実行＋単一 daemon の見積りで 45 分に余裕があり、投機的変更を避ける。

### Req 12.3 不変条件（既存ワークフロー無変更）

`git diff --name-only` で ci.yml / integration-ollama.yml / security.yml が
**untouched** を確認。変更は patterns-integration-ollama.yml のみ。

### TDD（RED→GREEN、throwaway 構造検証）

`/tmp/verify_task_12_3.py`（PyYAML、commit せず）で4点表明: (1) `patterns:test:integration`
ステップ存在（回帰）、(2) PR paths に `patterns/contracts/**`、(3) ジョブ名が6パターン
反映、(4) 各レーン integration ファイルが新4テスト関数を定義（Task 10 由来＝当初 green）。

- **RED**: 2 FAIL（exit 1）— PR paths に contracts 欠落 + ジョブ名が "3 lanes" のみ。
  (1)(4) は当初 PASS＝汎用ステップが既に新パターンを実行する事実を実証。
- **GREEN**: 追記後 ALL PASS（exit 0）。

### 検証ゲート（実測）

- YAML 妥当性: `yaml.safe_load` がエラーなくパース（`valid YAML`）。
- mise 解決: `mise tasks ls` に `patterns:test:integration` 登録を確認。
- collect-only（offline, pydantic-ai レーン）: `6 tests collected`（routing /
  orchestrator + 新4）＝import/構文エラー無し、ステップが6パターンを収集する実証。
  RUN_INTEGRATION_PATTERNS 未設定ゆえライブ呼出は skip（gated）。
- actionlint: 未インストール（`⚠️ スキップ`）。

### 計画からの逸脱・知見

- 境界外修正ゼロ。実行機構は既設のため、本タスクの本質は「トリガ/文書スコープの
  6パターン反映」と判断（adversarial 観点でも汎用ステップ＝新パターン実行は
  collect-only で裏取り）。残: Task 12.4（README・カバレッジフロア・ルート無変更）。

---

## Task 12.4 — レーン README 反映 + カバレッジ ratchet + ルート無変更検証

_Boundary:_ `patterns/frameworks/{pydantic-ai,beeai,llamaindex}/{README.md,pyproject.toml}`（6ファイル）
_Requirements:_ 13.3, 13.2, 12.3, 7.4, 7.5, NFR-4

### コマンド取り違えの確認

`/sdd-plan ... Task12.4` で起動されたが、引数がタスク番号かつパイプラインは
tasks-approved 済み・実装途上（12.1〜12.3 完）。plan 再生成は承認巻き戻しを招くため
AskUserQuestion で意図確認 → **「Task 12.4 を実装」** を選択。`/sdd-impl` 相当で続行
（spec.json 承認・plan.md は無変更）。

### 設計判断

- **README 鮮度修正**: レーン src から `contracts.py` は既に削除済み（Tasks 1–3 で
  共有 `patterns_contracts` のパス依存 import へ移行）。各 README の 構成表は
  「`contracts.py`（レーン間複製）」を載せた**陳腐化状態**だったため、当該行を
  「共有 `patterns_contracts` をパス依存 import（複製なし、NFR-3）」へ置換し、
  新4パターンファイル（prompt_chaining / parallelization / evaluator_optimizer /
  autonomous_agent）を `run_<pattern>` エントリ関数つきで追記。intro も
  「Spec 005 → 005/006-2a」「6パターン」「契約正本=各 pattern README・型実体=
  共有パッケージ（NFR-5）」へ更新。バージョン/ベータ注意は維持（Req 13.3）。
- **実行方法**: 全6パターンが `uv run pytest`（オフライン）/ 結合（live）で実行
  される旨と、`run_<pattern>` エントリ関数のモデル注入引数（PydanticAI=`model=`、
  BeeAI=`llm=ChatModel`、LlamaIndex=`llm=LLM`）を明記。
- **カバレッジ ratchet（Req 7.4 / NFR-4）**: 実測 pydantic-ai 98.85 / beeai 98.99 /
  llamaindex 99.20%。ルートアプリの確立水準（`fail_under=98`）に合わせ 3レーンとも
  `85 → 98` へ引上げ、達成済みカバレッジをロックイン。投機的な per-lane 99 は
  pydantic-ai のマージン不足（98.85）で脆くなるため回避し、ルート慣習の 98 に統一。

### TDD（RED→GREEN、throwaway 構造検証）

`/tmp/verify_task_12_4.py`（commit せず、tomllib + 文字列）でレーン毎4点表明:
(1) 新4 `run_<pattern>` を README が記載、(2) 共有 `patterns[_-]contracts` 参照かつ
陳腐化語「レーン間複製」消滅、(3) バージョン節維持、(4) `fail_under>=98`。

- **RED**: 12 FAIL（exit 1）= 4チェック×3レーン（バージョン節は当初から PASS）。
- **GREEN**: 6ファイル編集後 PASS 3 lanes（exit 0）。

### 検証ゲート（実測）

- `mise run patterns:test`（contracts + 3レーン、新フロア強制）→ exit 0:
  contracts `100.00%`(floor 85) / beeai `98.99%` / llamaindex `99.20%` /
  pydantic-ai `98.85%`（いずれも floor 98 到達）。全レーン pass、Req 7.5 の
  レーン内 `uv run pytest` 独立実行も成立。
- **Req 13.2** ルート `mise run check` → exit 0（`277 passed, 4 skipped`）。
  patterns/ 除外により本変更の影響なし＝無変更グリーン。
- **Req 12.3 / 13.2 不変条件**: `git diff HEAD` で ci.yml / integration-ollama.yml /
  security.yml / ルート pyproject.toml が **untouched OK**。
- スコープ: 12.4 の変更は境界6ファイルのみ（contract drift test は6パターン README
  のみ対象でレーン README 非対象＝drift 無影響、patterns:test の contracts 4 passed で実証）。

### 計画からの逸脱・知見

- 境界外修正ゼロ。README 陳腐化（削除済み `contracts.py` 行）を本タスクで是正＝
  新アーキテクチャ（共有契約パッケージ）と文書の整合を回復。
- **これで Major Task 12（DX・CI・品質ゲート整合）全サブタスク（12.1〜12.4）完了。**
  006-2a の全タスク（1〜12）完了見込み。次フェーズ: `/sdd-validate-impl`。
