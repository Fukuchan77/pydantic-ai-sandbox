# 012-agentic-ai-design — PDCA Do Phase

実装の進捗・試行錯誤・根本原因分析を継続記録する。

---

## Task 1.1 — HITL 契約形状の失敗テスト先行作成

**日付**: 2026-07-12
**Boundary**: `patterns/contracts/tests/unit/test_hitl_contract.py`
**Requirements**: 2.2, 2.3

### RED

`test_hitl_contract.py` を新規作成(`test_rag_contracts.py` を雛形に、rag が
`patterns_contracts` 直下の application-layer 契約として最も近い先例)。

- `from patterns_contracts import ActionType, ResolutionAction, SupportOutput`
  — 3 名とも未実装/未エクスポートのため import 時点で赤化する設計。
- `test_hitl_models_reexport_from_package_root`: `__all__` 登録の検証(R2.1)。
- `test_resolution_action_field_set` / `test_support_output_field_set`:
  `ResolutionAction{action_type, target_id, amount_usd}` /
  `SupportOutput{summary_of_issue, reasoning, requires_human_approval,
  action_plan}` の厳密フィールド集合(R2.2, 2.3)。
- `test_action_type_accepts_closed_vocabulary` (parametrize DISCOUNT/UPGRADE/
  ESCALATE) と `test_action_type_rejects_value_outside_vocabulary`
  ("REFUND" → `ValidationError`): `ActionType` 閉語彙(R2.2)。
- `test_resolution_action_rejects_negative_amount` /
  `_accepts_zero_amount`: `amount_usd` の `ge=0` 境界(R2.2)。
- `test_support_output_roundtrips_nested_action_plan`: dict payload から
  `list[ResolutionAction]` への coercion。
- `test_support_output_requires_human_approval_must_be_bool` /
  `_missing_required_field_rejected`: 4 フィールド必須・型検証(R2.3)。

確認コマンドと結果:

```
$ cd patterns/contracts && uv run pytest tests/unit/test_hitl_contract.py -v
ImportError: cannot import name 'ActionType' from 'patterns_contracts'
Interrupted: 1 error during collection
```

赤を確認(collection-time `ImportError` — `hitl.py` 未実装・`__init__.py` 未
エクスポートの両方が原因であり、Task 1.2 の GREEN 対象と一致する)。

### VERIFY(Task 自身のスコープ)

| Gate | Cmd | 結果 |
|---|---|---|
| test(新規ファイル) | `uv run pytest tests/unit/test_hitl_contract.py -v` | RED: `ImportError` で collection 中断(設計どおり) |
| test(既存スイート) | `uv run pytest --no-cov -q --ignore=tests/unit/test_hitl_contract.py` | 54 passed(既存契約への回帰なし) |
| lint | `uv run ruff check tests/unit/test_hitl_contract.py` | All checks passed(初回は `ActionType` の F401 未使用 import → parametrize 引数注釈に用いて解消) |
| format | `uv run ruff format --check tests/unit/test_hitl_contract.py` | already formatted |

### 範囲外(Task 1.2 へ)

`hitl.py` の実装・`__init__.py` への re-export 追加は本タスクのスコープ外。
本タスクは失敗テストの先行作成と赤確認のみ。

---

## Task 1.2 — `hitl.py` 契約実体の実装 + `__init__.py` 再エクスポート

**日付**: 2026-07-12
**Boundary**: `patterns/contracts/src/patterns_contracts/hitl.py`,
`patterns/contracts/src/patterns_contracts/__init__.py`
**Requirements**: 2.1, 2.2, 2.3

### GREEN

- `hitl.py` を新規作成(`rag.py` を雛形)。
  - `ActionType = Literal["DISCOUNT", "UPGRADE", "ESCALATE"]`
    — col-0 名前付きエイリアス(research.md I-3、drift parser 対称)。
  - `ResolutionAction(BaseModel)`: `action_type: ActionType` /
    `target_id: str` / `amount_usd: float = Field(ge=0)`。
  - `SupportOutput(BaseModel)`: `summary_of_issue: str` / `reasoning: str` /
    `requires_human_approval: bool` / `action_plan: list[ResolutionAction]`。
  - `__all__ = ["ActionType", "ResolutionAction", "SupportOutput"]`。
- `__init__.py`: `from patterns_contracts.hitl import ActionType,
  ResolutionAction, SupportOutput` を eval_graders と live_ollama の import 行
  の間に(既存のモジュール名アルファベット順を維持)追加し、3 名を `__all__`
  へアルファベット順で挿入(`ActionType` → Agent* の直前、`ResolutionAction`
  → ResearcherStartedEvent の直後、`SupportOutput` → SubTask の直後)。

### VERIFY(Task 自身のスコープ)

| Gate | Cmd | 結果 |
|---|---|---|
| test(対象ファイル) | `uv run pytest tests/unit/test_hitl_contract.py -v --no-cov` | **12 passed** |
| lint | `uv run ruff check src/patterns_contracts/hitl.py src/patterns_contracts/__init__.py` | All checks passed |
| format | `uv run ruff format --check src/patterns_contracts/hitl.py src/patterns_contracts/__init__.py` | already formatted |
| typecheck | `uv run pyright src/patterns_contracts/hitl.py src/patterns_contracts/__init__.py` | 0 errors, 0 warnings |
| test(全体ゲート) | `mise run patterns:test` | `hitl.py` 100% coverage / **4 failed, 62 passed**(下記) |

### 既知の意図的赤(→ Task 2 で緑化、設計どおりの中間状態)

Task 1 の Implementation Notes(tasks.md)が明示する通り、`__all__` への
3 名追加は `test_contract_drift.py` の 4 件を意図的に赤化する
(README 側に `hitl` が未登録のため「package に存在するが正本に記載なし」):

- `test_documented_class_set_matches_package`
- `test_documented_field_sets_match_package`
- `test_documented_literal_vocabularies_match_package`
- `test_each_package_model_is_documented_in_exactly_one_readme`

いずれも `ResolutionAction` / `SupportOutput` が package 側にのみ存在する
ことを検出している(011/010 と同型の sequenced-red)。Task 2.1(README 正本
作成)+ Task 2.2(`_README_PATHS` へ `hitl` 登録)の完了で緑化する — 本タスク
の VERIFY はスコープ外として扱う。

---

## Task 2.1 — `patterns/hitl/README.md` レーン正本の作成

**日付**: 2026-07-12
**Boundary**: `patterns/hitl/README.md`
**Requirements**: 2.1, 13.1, 13.2, 13.3

### 実装

- `patterns/hitl/README.md` を新規作成(sse レーン README の構成を雛形)。
- `## パターン契約(正本)` 直後の python fence に Task 1.2 と同一の正本ブロックを
  記載: `ActionType` col-0 名前付きエイリアス、`action_type: ActionType` は alias
  参照、`amount_usd: float = Field(ge=0)`(research.md I-7 で parser 受理を実測済み
  の形をそのまま採用)。
- 別節に必須ノート 4 種を独立記載:
  - 停止・承認・再開フロー解説(`DeferredToolRequests` / `DeferredToolResults` /
    `isinstance` 型分岐 / usage 通算)。
  - Durable Execution(公式統合 = Temporal / DBOS / Prefect、Restate は Restate 側
    SDK、実装しない)— R13.1。
  - セキュリティ(v1 併用時 `>=1.99.0` フロア、信頼できない `message_history`/URL の
    SSRF リスク、`safe_download` 経路 — egress 強化は実装しない、013 スコープ)— R13.2。
  - 検証基準版(pydantic-ai-slim 2.9.0 / 2026-07-11、pyproject フロア `>=2.9.0`)— R13.3。

### VERIFY(Task 自身のスコープ)

本タスクの「赤」は Task 1.2 が作った sequenced-red(package に hitl 契約が存在するが
登録済み README が未 documented)。`_README_PATHS` への登録は Task 2.2 の境界のため、
drift 4 テストは 2.2 まで赤のまま(設計どおりの中間状態)。よって 2.1 の「緑」=
**正本ブロックが package 実体と一致すること**を、drift parser の実関数を hitl README に
直接適用する使い捨てスクリプト(`contracts` venv, `uv run python`, 実行後削除)で検証:

| 面 | 結果 |
|---|---|
| classes | `['ResolutionAction', 'SupportOutput']` == package ✓ |
| named_literals | `ActionType = ['DISCOUNT', 'ESCALATE', 'UPGRADE']` == package ✓ |
| field_literals | `{('ResolutionAction','action_type'): {DISCOUNT,UPGRADE,ESCALATE}}` == package ✓ |
| fields | 両モデルとも `model_fields` と一致 ✓ |

→ 出力 `OK: hitl README normative block matches package on all four surfaces`。

sequenced-red の確認: `cd patterns/contracts && uv run pytest --no-cov
tests/unit/test_contract_drift.py -q` → `4 failed`(`SupportOutput` /
`ResolutionAction` が "Extra items in the right set" = package にあるが未登録 README)。
Task 2.2 の `_README_PATHS` 1 行追加で緑化する。

### 学び

- drift parser は fence 内の col-0 assignment(`ActionType = Literal[...]`)と
  インラインコメント付き AnnAssign を正しく拾う。README 側 alias 解決とパッケージ側
  `Literal` 展開が対称一致するため、`action_type: ActionType` は alias 参照で記述して
  問題ない(research.md I-7 の実測を追認)。
- 2.1 単体の緑判定は「正本ブロック == package」。drift 全体の緑は 2.2 の責務
  (純加算の sequenced-red 設計)。

---

## Task 2.2 — `_README_PATHS` へ `hitl` 登録(sequenced-red の緑化)

**日付**: 2026-07-12
**Boundary**: `patterns/contracts/tests/unit/test_contract_drift.py`
**Requirements**: 2.4

### GREEN

Task 1.2 が作った sequenced-red(drift 4 テストが赤)を、Task 2.1 の README 正本を
`_README_PATHS` に登録することで緑化する。parser は無改修 — dict へ 1 行追加のみ:

```python
"deep-research": _PATTERNS_DIR / "deep-research" / "README.md",
"hitl": _PATTERNS_DIR / "hitl" / "README.md",   # ← 追加(応用レーン群に配置)
"eval-graders": _PATTERNS_DIR / "EVAL-GRADERS.md",
```

配置は応用レーン(rag / sse / deep-research)群の直後、cross-cutting の eval-graders の
直前。

### VERIFY

| Gate | Cmd | 結果 |
|---|---|---|
| test(drift) | `uv run pytest --no-cov tests/unit/test_contract_drift.py -q` | **4 passed**(1.2 起点の sequenced-red が閉じた) |
| test(全体+cov) | `uv run pytest --cov -q` | **66 passed** / coverage **100%**(floor 85)。`hitl.py` 100%。1.2 時点の `4 failed, 62 passed` から回帰なしで緑化 |
| lint | `uv run ruff check tests/unit/test_contract_drift.py` | All checks passed |
| format | `uv run ruff format --check tests/unit/test_contract_drift.py` | already formatted |
| typecheck | `uv run pyright tests/unit/test_contract_drift.py` | 0 errors, 0 warnings |

### 学び

- 契約の単一点ドリフト検知は「正本 README を `_README_PATHS` に 1 行登録するだけ」で
  効く設計(research.md I-7 の実測どおり)。parser 改修は不要で、Task 2(2.1+2.2)により
  Task 1 起点の中間赤が設計どおり解消した。
- これで Section 1〜2 完了。次は Section 3(レーン足場: 独立 uv プロジェクト、3.14、
  ゲート設定)— 本コンテナは 3.14 ローカル実行不可のため赤・緑確認は CI(hitl ジョブ)へ
  委譲する運用(tasks T3.2 / M-2)。

---

## Task 3.1 — レーン足場(`pyproject.toml` / `.python-version` / `__init__.py` + `py.typed`)

**日付**: 2026-07-12
**Boundary**: `patterns/hitl/pyproject.toml`, `patterns/hitl/uv.lock`, `patterns/hitl/.python-version`
**Requirements**: 1.1, 1.2, 1.3, 1.5, 10.1

### 実装(非 TDD — スキャフォールディングタスク、tasks.md に「赤を確認する」記載なし)

- `patterns/hitl/.python-version` = `3.14`(sse レーンと同一ピン)。
- `patterns/hitl/pyproject.toml` を sse レーンの雛形に(research.md I-2)新規作成。
  - `dependencies`: `patterns-contracts`(path dep)、`pydantic-ai-slim[openai]>=2.9.0`、
    `fastapi>=0.136`、`logfire`(tasks.md 3.1 の記載どおり、`beeai-framework` /
    `llamaindex` は宣言しない)。
  - `dependency-groups.dev`: `httpx` / `pip-audit` / `pyright` / `pytest` /
    `pytest-asyncio` / `pytest-cov` / `ruff`。
  - ゲート設定: ruff は root/sse と同一 select セット、`pyright strict`
    (`pythonVersion = "3.14"`)、`asyncio_mode = "auto"`、`fail_under = 98`。
  - `readme = "README.md"`(Task 2.1 で正本作成済みのため、sse 当時のように
    `readme` 宣言を先送りする必要はない)。
  - `[tool.uv.sources] patterns-contracts = { path = "../contracts", editable = true }`。
- `src/patterns_hitl/__init__.py` + `src/patterns_hitl/py.typed`(PEP 561 マーカー)を作成。

### 環境上の訂正(do.md 末尾の前提を更新)

Task 2.2 ログ末尾は「本コンテナは 3.14 ローカル実行不可」としていたが、本タスク実行時に
`uv python list` で `cpython-3.14.5-macos-aarch64-none` がローカル導入済みと判明
(sse レーンの既存 `.venv` が同バージョンを使用済み)。したがって Task 3.1 の
`uv lock` / `uv sync` / ruff / pyright はローカルで直接実行し、CI 委譲は不要だった
(Task 3.2 のテスト実行時点で再度ローカル実行可能性を確認する)。

### VERIFY(Task 自身のスコープ)

| Gate | Cmd | 結果 |
|---|---|---|
| lock | `cd patterns/hitl && uv lock` | `Using CPython 3.14.5` / `Resolved 79 packages in 917ms` |
| lock 内容 | `grep -c "beeai\|llama-index\|llamaindex" uv.lock` | `0`(禁止依存の混入なし) |
| sync | `uv sync --all-groups` | 79 パッケージ導入(`patterns-contracts` / `patterns-hitl` editable 含む) |
| lint | `uv run ruff check .` | `All checks passed!` |
| format | `uv run ruff format --check .` | `1 file already formatted` |
| typecheck | `uv run pyright` | `0 errors, 0 warnings, 0 informations` |
| 既存契約への回帰 | `cd patterns/contracts && uv run pytest --no-cov -q` | `66 passed`(Task 2.2 時点から変化なし) |

### 学び

- sse レーンとの差分は「README が先行済み」の一点(Task 2.1 が正本を先に作った順序の
  違い)。`readme` フィールドを宣言できるため sse のような hatchling ビルド破損回避コメントは
  不要。
- 3.14 のローカル可用性は環境依存で変わりうる(mise/uv キャッシュの状態次第)。次タスク
  (3.2 のテスト実行)でも都度確認し、不可なら tasks.md M-2 の CI 委譲手順に切り替える。

---

## Task 3.2 — `conftest.py` の hermetic 強制 + スモークテスト(赤→緑)

**日付**: 2026-07-12
**Boundary**: `patterns/hitl/tests/unit/conftest.py`, `patterns/hitl/tests/unit/test_smoke.py`
**Requirements**: 10.1

### 環境確認(M-2 の CI 委譲判定)

Task 3.1 に続き 3.14 がローカル実行可能(`cpython-3.14.5`)なことを再確認。したがって
本タスクの赤・緑確認もローカルで直接行い、CI(hitl ジョブ)への委譲は不要だった。

### RED

`tests/unit/test_smoke.py` を新規作成(conftest.py はまだ置かない)。3 テスト:

- `test_patterns_hitl_imports`: `import patterns_hitl` が通ること。
- `test_hitl_contract_importable_via_path_dependency`: `patterns_contracts` から
  `ActionType` / `ResolutionAction` / `SupportOutput` を import し、path dependency
  経由で契約が使えることを確認(`SupportOutput(action_plan=[ResolutionAction(...)])`
  を構築)。
- `test_hermetic_guard_blocks_real_model_requests_by_default`: 未実装時点では
  `pydantic_ai.models.ALLOW_MODEL_REQUESTS` の既定値が `True`(事前に
  `uv run python -c "from pydantic_ai import models; print(models.ALLOW_MODEL_REQUESTS)"`
  で確認済み)なので、`is False` 検査は失敗する設計。

確認コマンドと結果:

```
$ uv run pytest --no-cov tests/unit/test_smoke.py -v
tests/unit/test_smoke.py::test_patterns_hitl_imports PASSED
tests/unit/test_smoke.py::test_hitl_contract_importable_via_path_dependency PASSED
tests/unit/test_smoke.py::test_hermetic_guard_blocks_real_model_requests_by_default FAILED
  assert True is False
1 failed, 2 passed
```

赤を確認(hermetic guard 未設定分のみが赤 — 設計どおり)。

### GREEN

`tests/unit/conftest.py` を新規作成(`patterns/frameworks/pydantic-ai` レーンの
既存 conftest を雛形にそのまま踏襲 — tasks.md 3.2 の指定どおり):

```python
if os.environ.get("RUN_INTEGRATION_PATTERNS") != "1":
    models.ALLOW_MODEL_REQUESTS = False
```

### VERIFY(Task 自身のスコープ)

| Gate | Cmd | 結果 |
|---|---|---|
| test(対象ファイル、緑化後) | `uv run pytest --no-cov tests/unit/test_smoke.py -v` | **3 passed** |
| lint | `uv run ruff check .` | 初回 `I001`(import 未整列)→ `ruff check --fix .` で解消 → `All checks passed!` |
| format | `uv run ruff format --check .` | `3 files already formatted` |
| typecheck | `uv run pyright` | `0 errors, 0 warnings, 0 informations` |
| test+coverage(レーン全体) | `uv run pytest --cov -q` | `3 passed` / `src/patterns_hitl` **100%** カバレッジ(floor 98 達成) |
| 既存契約への回帰 | `cd patterns/contracts && uv run pytest --no-cov -q` | `66 passed`(変化なし) |
| ルート回帰 | `mise run check` | `282 passed, 4 skipped`(変化なし、patterns/ は root ゲート対象外のため無影響) |

### 学び

- `ruff` の isort は `patterns_contracts` を third-party 扱いする(このレーンの
  `known-first-party` は `patterns_hitl` のみ)。`pydantic_ai` と `patterns_contracts`
  の import 順は `--fix` に委ねればよく、手で並べ替える必要はない。
- Section 3(レーン足場)完了。次は Section 4(`agent.py` + ポリシーセンサー、
  4.1 の失敗テスト先行作成)。

---

## Task 4.1 — `agent.py` 失敗テスト先行作成(`test_output_validator.py` + `test_agent_tools.py`)

**日付**: 2026-07-12
**Boundary**: `patterns/hitl/tests/unit/test_output_validator.py`, `patterns/hitl/tests/unit/test_agent_tools.py`
**Requirements**: 3.5, 10.3

### API 事実確認(実装前の一次調査 — venv 直接確認、research.md I-1 の追認)

ローカル `.venv`(pydantic-ai-slim 2.9.0 相当)で import パスを実測した:

- `DeferredToolRequests` / `DeferredToolResults` / `ToolApproved` / `ToolDenied` /
  `ApprovalRequired` / `ModelRetry` / `UnexpectedModelBehavior` / `ModelMessage` /
  `ModelResponse` / `ToolCallPart` は `pydantic_ai` トップレベルから re-export 済み。
  `FunctionModel` / `AgentInfo` は `pydantic_ai.models.function` のみ(トップレベル
  未 export)。`TestModel` は `pydantic_ai.models.test`。
- `@agent.output_validator` は `DeferredToolRequests` が出力候補から除外された後の
  構造化出力のみを受け取る(`_output.py:476-478` で `outputs` から事前に取り除かれる)
  — 検証対象を `SupportOutput` 1 本に限定してよい根拠。
- `TestModel._JsonSchemaTestData._int_gen`: `minimum` のみ設定時は
  `minimum + seed`(既定 `seed=0`)を返す。`amount_usd: float = Field(ge=0)` なら
  自動生成値は常に `0.0` — 既定閾値(50.0)を下回ることが決定論的に保証される
  (`apply_discount` 低額 path のテストが乱数に依存しない根拠)。
- `Agent` の既定 `retries`(output 用)は `1`。`ModelRetry` は 1 回まで許容され、
  2 回目の違反で `output_retries_used > 1` となり `UnexpectedModelBehavior` に
  変換される — 追加の `retries=` 指定なしで枯渇 path を組める。

### RED

- `test_agent_tools.py`: `patterns_hitl.agent` から `HitlDeps` / `build_agent` を
  import(未実装のため設計どおり赤化)。
  - `test_approval_not_required_tool_terminates_with_support_output`:
    `TestModel(call_tools=["search_customer_context"])` で承認不要ツールのみを
    呼ばせ、`result.output` が `SupportOutput` になることを検証(R10.3)。
  - `test_apply_discount_below_threshold_executes_without_approval`:
    `TestModel(call_tools=["apply_discount"])`。上記の `_int_gen` 事実により
    生成される `amount_usd=0.0` は既定閾値未満 → `ApprovalRequired` が発生せず
    `SupportOutput` 終端することを検証(R5.4)。
- `test_output_validator.py`: `patterns_hitl.agent` に加え `patterns_hitl.settings`
  から `HitlSettings` を import(同様に未実装で赤化)。
  - `_final_result_call()`: `ToolCallPart("final_result", {...SupportOutput
    フィールド...})` を組み立てる共通ヘルパー(research.md I-1 の検証済み終端形)。
  - `test_output_validator_retries_on_policy_violation_then_succeeds`:
    `FunctionModel` 台本(`nonlocal calls` カウンタで phase 判定 — 5.1 の
    `len(messages)` 判定とは独立の、この検証専用の単純な形)。1 回目は
    `amount_usd = threshold + 50.0` かつ `requires_human_approval=False` で
    ポリシー違反終端 → `ModelRetry` 想定 → 2 回目で `requires_human_approval=True`
    に訂正した終端 → 成功。`calls == 2` で実際に 1 回リトライされたことを検証(R3.5)。
  - `test_output_validator_exhausts_retry_budget_and_raises`: 台本が常に違反終端を
    返し続け、`pytest.raises(UnexpectedModelBehavior)` で枯渇 path を検証(R3.5)。
  - 違反額は `HitlSettings().risk_threshold_usd + 50.0` として算出(既定値 50.0 を
    テストにハードコードせず、settings 側の変更に追従できるようにした)。

確認コマンドと結果:

```
$ .venv/bin/python3 -m pytest tests/unit/test_output_validator.py tests/unit/test_agent_tools.py -v --no-cov
ModuleNotFoundError: No module named 'patterns_hitl.agent'
Interrupted: 2 errors during collection
```

赤を確認(collection-time `ModuleNotFoundError` — `agent.py` / `settings.py` 未実装が
原因であり、Task 4.2 の GREEN 対象と一致する。1.1 / 3.2 と同型の sequenced-red)。

### VERIFY(Task 自身のスコープ)

| Gate | Cmd | 結果 |
|---|---|---|
| test(新規ファイル) | `.venv/bin/python3 -m pytest tests/unit/test_output_validator.py tests/unit/test_agent_tools.py -v --no-cov` | RED: `ModuleNotFoundError` で collection 中断(設計どおり) |
| test(既存スイート) | `.venv/bin/python3 -m pytest --no-cov -q --ignore=tests/unit/test_output_validator.py --ignore=tests/unit/test_agent_tools.py` | **3 passed**(既存スモークテストへの回帰なし) |
| lint | `.venv/bin/ruff check tests/unit/test_output_validator.py tests/unit/test_agent_tools.py` | 初回 `All checks passed!` |
| format | `.venv/bin/ruff format --check ...` → `--fix` 相当 | 初回 `test_output_validator.py` が未整形 → `ruff format` で解消 → 再チェック `2 files already formatted` |
| typecheck(sequenced-red の追認) | `.venv/bin/pyright tests/unit/test_output_validator.py tests/unit/test_agent_tools.py` | `reportMissingImports`(`patterns_hitl.agent` / `patterns_hitl.settings`)を根に 30 件のカスケード型エラー — 未実装に起因する想定内の赤 |

### 範囲外(Task 4.2 へ)

`patterns_hitl/agent.py`(`HitlDeps` / `build_agent` / 3 ツール /
`@output_validator`)と `patterns_hitl/settings.py`(`HitlSettings`)の実装は本タスクの
スコープ外。本タスクは失敗テストの先行作成と赤確認のみ。

### 学び

- `TestModel` の `_JsonSchemaTestData._int_gen` の決定論性(`minimum` のみ →
  `minimum + seed`)を使うと、ツール引数を乱数に依存させずに「閾値未満」を保証できる
  — `apply_discount` のような条件付き承認ツールを `TestModel(call_tools=[...])` で
  テストする際の再利用可能なパターン。
- `@agent.output_validator` は union `output_type=[SupportOutput,
  DeferredToolRequests]` のうち `DeferredToolRequests` を通過させない(フレームワーク
  側で事前フィルタ)。検証関数の型を `SupportOutput` 単体に絞れる。
- 次は Task 4.2(`agent.py` + `settings.py` の実装、本タスクの赤の緑化)。

---

## Task 4.2 — `settings.py` + `agent.py` の実装(Task 4.1 の赤の緑化)

**日付**: 2026-07-12
**Boundary**: `patterns/hitl/src/patterns_hitl/agent.py`, `patterns/hitl/src/patterns_hitl/settings.py`
**Requirements**: 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 5.4, 12.1

### 依存追加(実装前提)

`HitlSettings` に `pydantic_settings.BaseSettings`(root `pydantic_ai_sandbox.config.Settings` と
同じ fail-fast パターン)を採用。レーンにこの依存が無かったため `pyproject.toml` へ
`pydantic-settings>=2` を追加し `uv lock`(→ `pydantic-settings 2.14.2` / `python-dotenv 1.2.2`
解決)+ `uv sync --all-groups` を実行(範囲: LaneScaffold の依存面のみ、他レーン無影響)。

**境界の遡及修正(2026-07-12, `/sdd-validate-impl` 指摘)**: 上記の依存追加は
`patterns/hitl/pyproject.toml` / `uv.lock` を変更するが、これらは元の tasks.md では
Task 3.1(レーン足場)の `_Boundary:_` にのみ列挙されていた。Task 4 の設計契約
(agent.py/settings.py のみ)に対する実態逸脱のため、tasks.md の Task 4(見出し)と
4.2 の `_Boundary:_` へ `pyproject.toml` / `uv.lock` を追記し契約を実態に一致させた
(下流タスクへの影響なし — 純加算の依存追加であり既存契約を壊していない)。

### GREEN

- `settings.py`: `HitlSettings(BaseSettings)`、`model_config =
  SettingsConfigDict(env_prefix="HITL_")`、`risk_threshold_usd: float = 50.0`、
  `model_name: str | None = None`(`HITL_RISK_THRESHOLD_USD` / `HITL_MODEL_NAME`、
  plan.md Data Model の env 名と一致)。
- `agent.py`: `HitlDeps`(`customer_directory: Mapping[str, str] =
  field(default_factory=dict[str, str])`)。ツール・output_validator は
  **モジュールレベル定義 or ファクトリが返す関数**とし、`build_agent` 内の
  decorator-closure にはしない — root `pydantic_ai_sandbox.agents.chat_agent`
  と同型の理由(decorator でしか使われない local 関数は pyright strict の
  `reportUnusedFunction` に引っかかる。`tools=[...]` へ渡す/`return` する形なら
  明確に「使用されている」)。
  - `search_customer_context(ctx, customer_id) -> str`: 承認不要、
    `ctx.deps.customer_directory` のフェイク検索。
  - `_make_apply_discount(risk_threshold_usd) -> Callable`: 返り値の
    `apply_discount(ctx, target_id, amount_usd)` が `amount_usd >
    risk_threshold_usd and not ctx.tool_call_approved` で
    `raise ApprovalRequired`(R5.4 — 条件付き承認、静的 `requires_approval=True`
    ではない)。
  - `escalate_to_legal(ctx, target_id, reason) -> str` を `Tool(escalate_to_legal,
    requires_approval=True)` として `tools=[...]` に登録(R3.3 の必須ツール)。
  - `_make_approval_policy_validator(risk_threshold_usd) -> Callable`: 返り値
    `enforce_approval_policy` を `agent.output_validator(...)` へ**関数呼び出しで**
    渡す(decorator 構文ではなく)。`action_plan` のいずれかが閾値超過かつ
    `requires_human_approval=False` なら `ModelRetry`(R3.5)。
  - `build_agent(model)`: `Agent(model, deps_type=HitlDeps,
    output_type=[SupportOutput, DeferredToolRequests], instructions=...,
    tools=[...])` + `agent.output_validator(...)`。`instrument=True` は渡さない
    (R3.2)。`instructions`(`system_prompt` 不使用、R3.4)。

### 型安全上のトラブルシュート(pyright strict, 3 ラウンド)

1. **`reportUnusedFunction`**(ツール 3 種 + validator を `build_agent` 内の
   `@agent.tool` / `@agent.output_validator` デコレータ closure として定義した
   初版で発生): decorator で登録するだけの関数は pyright から見て
   「定義後に一度も参照されない」ため dead code 判定される。
   → 上記のモジュールレベル関数 + ファクトリ関数(`return` で使用が明示される)
   構成へ再設計して解消。
2. **`reportCallIssue` / `reportArgumentType`**(`agent.output_validator` の
   オーバーロードが `Callable[[OutputDataT], OutputDataT]` を要求 —
   `OutputDataT` は `Agent[HitlDeps, SupportOutput | DeferredToolRequests]` の
   型パラメータであり `SupportOutput` 単体ではない): validator の型注釈を
   `SupportOutput | DeferredToolRequests` に広げ、`isinstance(output,
   DeferredToolRequests)` で早期 return するガードを追加(実行時に到達しない
   ことは Task 4.1 の do.md で確認済みの事実 — `_output.py` が
   `DeferredToolRequests` を検証対象出力から事前除外するため。ガードは静的な
   契約適合のためだけに存在し、`# pragma: no cover` を付して意図を明示)。
3. **`reportUnknownVariableType`**(`HitlDeps.customer_directory` の
   `field(default_factory=dict)` — bare `dict` は `dict[Unknown, Unknown]` に
   推論される): `field(default_factory=dict[str, str])` へ変更(PEP 585 の
   subscripted builtin をファクトリとして直接渡す)して解消。
4. `Mapping` / `Model` / `Callable` はアノテーション専用(`from __future__
   import annotations` 下で実行時未使用)のため `if TYPE_CHECKING:` ブロックへ
   移動(ruff `TC002`/`TC003` の指示どおり)。

テスト側(`test_output_validator.py`)も同じ理由で 1 箇所修正: `result.output`
は `SupportOutput | DeferredToolRequests` 型のため、`requires_human_approval`
へ直接アクセスする前に `assert isinstance(result.output, SupportOutput)` で
型を narrowing する行を追加。

### VERIFY(Task 自身のスコープ)

| Gate | Cmd | 結果 |
|---|---|---|
| test(Task 4.1 対象ファイル) | `.venv/bin/python3 -m pytest tests/unit/test_output_validator.py tests/unit/test_agent_tools.py -v --no-cov` | **4 passed**(Task 4.1 の赤が緑化) |
| test(レーン全体) | `.venv/bin/python3 -m pytest -v --no-cov` | **7 passed**(既存 `test_smoke.py` 3 件へ回帰なし) |
| lint | `.venv/bin/ruff check .` | `All checks passed!`(3 ラウンドの `reportUnusedFunction` 対応後、I001 import 整列を 2 回 `--fix`) |
| format | `.venv/bin/ruff format --check .` → `ruff format .` | `7 files already formatted` |
| typecheck | `.venv/bin/pyright` | `0 errors, 0 warnings, 0 informations` |
| 既存契約への回帰 | `cd patterns/contracts && uv run pytest --no-cov -q` | `66 passed`(変化なし) |

### 既知の意図的なカバレッジ未達(→ Task 5 で緑化、設計どおりの中間状態)

`.venv/bin/python3 -m pytest --cov -q` → `93.33%`(floor 98 未達、`agent.py` 92%
— 未カバー行 2 箇所):

- `escalate_to_legal` の本体(l.73): `requires_approval=True` ツールが**承認され
  実行される**経路は harness の resume(Task 5.2)を経ないと到達しない。
- `apply_discount` の `raise ApprovalRequired`(l.93): 閾値超過額を未承認で呼ぶ
  経路(Task 5.1 の `test_stop_approve_resume.py` が FunctionModel 台本で直接
  駆動する)。

いずれも dead code ではなく、Task 5(ハーネス + 停止・承認・再開テスト)が
実際に踏む経路 — tasks.md 完了ゲートの「カバレッジ fail_under = 98」は
「全タスク後」に定義されており(Task 1.2 の `4 failed, 62 passed` 中間状態と
同型の sequenced-gap)、本タスクの GREEN 対象(Task 4.1 の 4 テスト)は全て
緑化済み。`isinstance(output, DeferredToolRequests)` 分岐のみ、実行時に
到達しないことを Task 4.1 の一次調査(`_output.py:476-478`)で確認済みのため
`# pragma: no cover` を付与し、真に閾値未達なのは上記 2 行のみに絞った。

### 学び

- pydantic-ai の `@agent.tool` / `@agent.output_validator` は「デコレータで
  登録するだけ」の使い方だと pyright strict の `reportUnusedFunction` と
  相性が悪い。root `chat_agent.py` が採用したモジュールレベル関数 +
  `tools=[...]` 明示リストのパターンは、closure で設定値を閉じ込める必要が
  ある場合でも「ファクトリ関数が返す」形にすれば同様に型安全に保てる
  (このレーンの再利用可能な設計判断)。
- `Agent[Deps, A | B]` の `output_validator` はオーバーロード解決上
  「`A | B` を受けて `A | B` を返す」関数を要求する — 実行時に `B` が
  除外される(`DeferredToolRequests` のような sentinel)ことをフレームワークが
  保証していても、静的型はそれを知らない。`isinstance` ガード +
  `# pragma: no cover` が両立点。
- 次は Task 5(`harness.py` + `store.py` + `test_stop_approve_resume.py` —
  本タスクで未カバーの 2 行を含む停止・承認・再開の全経路)。

## Task 5.1 — `test_stop_approve_resume.py` + `function_model_scripts.py` の失敗テスト先行作成

### API 事実確認(実装前の一次調査 — venv 直接確認)

Task 4.2 で実装済みの `build_agent` を実際の `FunctionModel` 台本で動かし、
harness/store が要求する挙動を **実行で確認**してから型を確定した
(research.md I-1 の2フェーズ台本はそのまま転用できるが、e/f ケースは
未検証だったため):

- 停止: `result.output` が `DeferredToolRequests(approvals=[ToolCallPart(
  tool_name='apply_discount', args={...}, tool_call_id='pyd_ai_...')])`。
- 承認再開: `deferred_tool_results=DeferredToolResults(approvals={id:
  ToolApproved()})` + `message_history=result.all_messages()` → 終端
  `SupportOutput`。
- `ToolApproved(override_args={...})` → 実行される `ToolReturnPart.content`
  が上書き後の引数を反映(`"applied $5.00 discount to cust-1"` — 提案時の
  `$100.00` ではない)。
- `ToolDenied(message=...)` → 対応する `ToolReturnPart` は
  `outcome='denied'` かつ `content` がそのまま拒否理由文字列(ツール本体は
  未実行)。モデルはこの拒否理由を受けて別の終端応答を返す。
- 再 defer: 再開後の1呼び出しが再び `requires_approval` ツール
  (`escalate_to_legal`)を提案すると、2回目も `DeferredToolRequests` で
  停止する(`len(messages)` 依存ではなく呼び出し順依存の
  `call_counting_script` で3フェーズ化しても同じ挙動を再現)。
- usage 通算: `UsageLimits(total_tokens_limit=80)` で 1 run 目
  (`usage≈58 tokens`)は通るが、`usage=r1.usage` を注入した 2 run 目は
  累積 132 tokens で `pydantic_ai.exceptions.UsageLimitExceeded` を raise
  する(実測)。harness はこれを `HitlBudgetExceededError` へ変換する
  (plan.md AD-4 / R7.3)。

### RED

`patterns_hitl.harness` / `patterns_hitl.store` は Task 5.2 まで未実装の
ため、テストファイル作成時点で import エラーによる収集失敗を確認した:

```
$ .venv/bin/python3 -m pytest --no-cov tests/unit/test_stop_approve_resume.py -q
ImportError while importing test module '.../tests/unit/test_stop_approve_resume.py'.
tests/unit/test_stop_approve_resume.py:34: in <module>
    from patterns_hitl.harness import (
E   ModuleNotFoundError: No module named 'patterns_hitl.harness'
Interrupted: 1 error during collection
```

### 設計(このタスクで確定 — Task 5.2 が実装する API 面)

テストが先行して harness/store の公開面を確定させる(plan.md の記述は
「`start(prompt)` / `resume(session_id, decisions)`」までで、具体的な
コンストラクタ形状・戻り値の型は本タスクで決める):

- `HitlHarness(agent, store, *, usage_limits: UsageLimits = LIMITS)` —
  「app 内部で (agent, store) から組み立てる」(plan.md AD-8)を体現する
  コンストラクタ。`usage_limits` はテストが低い予算を注入して(f)を
  決定論化するための keyword-only 上書き点。
- `PendingResult(session_id, approvals: list[ToolCallPart], history,
  usage)` / `TerminalResult(session_id, output: SupportOutput, history,
  usage)` — `approvals` は `ToolCallPart` をそのまま持つ(`tool_name` /
  `args` / `tool_call_id` が既に露出済みのため、独自の `PendingApproval`
  相当を harness 層で再定義しない — それは `app.py` の HTTP 境界写像の
  責務)。`history` を両方に持たせることで (c)/(d) のツール実行結果検証を
  harness の戻り値だけで完結させ、store の内部実装に依存しないテストにした。
- `HitlBudgetExceededError` — `UsageLimitExceeded` の変換先(R7.3)。
- 再 defer(e)は「同一 `session_id` で 2 回目の `PendingResult`」を assert
  することで、store が `create` ではなく `update` で既存セッションを
  更新する契約を先行ロックする。

`tests/support/function_model_scripts.py` は `len(messages)` 分岐ではなく
呼び出し回数(`state["calls"]`)で phase を進める `call_counting_script(
*phases)` を新設 — 2フェーズの研究済み台本をそのまま3フェーズ(再 defer)
まで一般化でき、`messages` の中身を検査するコードを一切書かずに済む。

### VERIFY(Task 自身のスコープ)

| Gate | Cmd | 結果 |
|---|---|---|
| RED 確認 | `.venv/bin/python3 -m pytest --no-cov tests/unit/test_stop_approve_resume.py -q` | `ModuleNotFoundError: No module named 'patterns_hitl.harness'`(収集失敗 — 意図した赤) |
| 既存テストへの回帰なし | `.venv/bin/python3 -m pytest --no-cov tests/unit -q --ignore=tests/unit/test_stop_approve_resume.py` | `7 passed` |
| lint(新規2ファイル) | `.venv/bin/ruff check tests/unit/test_stop_approve_resume.py tests/support/function_model_scripts.py` | `All checks passed!` |
| format(新規2ファイル) | `.venv/bin/ruff format --check tests/unit/test_stop_approve_resume.py tests/support/function_model_scripts.py` | `2 files already formatted` |

pyright / レーン全体のカバレッジは harness/store が存在しない現時点では
意味を持たない(import 未解決)ため、Task 5.2 の GREEN 後に実施する。

### 範囲外(Task 5.2 へ)

`harness.py`(`HitlHarness` / `PendingResult` / `TerminalResult` /
`HitlBudgetExceededError` / `LIMITS`)と `store.py`(`SessionStore` /
`SessionRecord`)の実装本体。

### 学び

- FunctionModel 台本を「`len(messages)` で phase 判定」から
  「呼び出し回数で phase 判定」に一般化すると、2フェーズの研究済み台本を
  書き換えずに3フェーズ(re-defer)へ拡張できる — 台本のロジックを
  `messages` の構造に結合させないほうが、将来の追加ケース(4フェーズ以上)
  にも耐える。
- harness の戻り値に `history`(`result.all_messages()` 相当)を含めておくと、
  override_args や denial のような「ツール実行の副作用」をテストが
  store の内部状態を覗かずに検証できる — store はあくまで
  session id → 永続状態のマッピングに専念させ、テスト用のフックを
  store 側に増設せずに済んだ。
- 次は Task 5.2(`harness.py` + `store.py` の実装で本タスクの赤を緑化)。

## Task 5.2 — `harness.py` + `store.py` の実装(Task 5.1 の赤の緑化)

### GREEN

Task 5.1 で確定した公開面をそのまま実装した:

- `store.py`: `SessionRecord`(`history` / `usage` の frozen dataclass)+
  `SessionStore`(`dict[str, SessionRecord]` バッキング)。`create` は
  `uuid4()` で id 生成、`get`/`update` は未知 id で `KeyError` を raise する
  (`app.py` の 404 写像は Task 6 の責務)。
- `harness.py`: `LIMITS = UsageLimits(request_limit=8, tool_calls_limit=10,
  total_tokens_limit=20_000)`、`HitlBudgetExceededError`、
  `PendingResult`/`TerminalResult`(いずれも frozen dataclass、`history` /
  `usage` を持たせて (c)/(d) のツール実行結果検証を harness の戻り値だけで
  完結させる設計)、`HitlHarness(agent, store, *, usage_limits=LIMITS)`。
  `start`/`resume` はともに `try: await self._agent.run(...) except
  UsageLimitExceeded as exc: raise HitlBudgetExceededError(str(exc)) from
  exc` で捕捉・変換し、`isinstance(output, DeferredToolRequests)` で
  `_to_result` が `PendingResult`/`TerminalResult` に分岐する。

Task 5.1 の6ケース(`test_stop_approve_resume.py`)は**初回実装で全て一発合格**
(`.venv/bin/python3 -m pytest --no-cov tests/unit/test_stop_approve_resume.py
-v` → `6 passed`)。Task 5.1 の事前 API 実行検証(venv 直接確認)が効いた。

### 型安全上のトラブルシュート(pyright strict)

1. **`reportArgumentType`**(`DeferredToolResults(approvals=decisions)`):
   `decisions: dict[str, ToolApproved | ToolDenied]` を pydantic-ai 側の
   `approvals: dict[str, DeferredToolApprovalResult | bool]` へそのまま渡すと
   `dict` の値型不変性(invariance)で型エラー。`Mapping` への変更は
   相手側(pydantic-ai)のパラメータ型が `dict` 固定のため無意味 —
   呼び出し箇所で `dict(decisions.items())` として**新規の dict リテラル式**
   を構築し直すことで、呼び出し先の期待型に対する双方向推論
   (bidirectional inference)を効かせて解消(ruff `C416` が推奨する書き方と
   一致)。
2. **テスト側 `reportUnknownParameterType`**(`_harness(*phases, ...)` の
   `*phases` に型注釈がなかった): `*phases: ToolCallPart` を追加。
3. **テスト側 `reportAttributeAccessIssue`**(`getattr(part, "part_kind",
   None) == "tool-return"` で分岐した後に `part.tool_name` / `part.content`
   / `part.outcome` へアクセス — pyright は文字列比較によるナローイングを
   認識しない): `isinstance(part, ToolReturnPart)` へ置き換えて解消
   (union 全体から具体型への静的ナローイングが効くようになった)。

### カバレッジ ratchet(fail_under=98)を閉じるための追加テスト

実装直後のカバレッジは **95.73%**(4行未達 — `agent.py:73`
`escalate_to_legal` 本体、`harness.py:119-120` の `start()` 内
`UsageLimitExceeded` 捕捉分岐、`store.py:91` の `update()` 内 `KeyError`
分岐)。Task 4.2 の do.md で「Task 5 が緑化する」と予告した
`escalate_to_legal` 本体が、Task 5.1 の再defer ケース(e)が
「2度目の `PendingResult` が出ること」までしか検証しなかったため
未達のまま残っていた。以下を追加して **100.00%** に到達させた
(実装コードの変更なし、テストのみ):

- (e) を拡張: 2度目の `PendingResult`(`escalate_to_legal`)をさらに
  `ToolApproved()` で resume し、`TerminalResult` まで完走させる
  アサーションを追加(`harness.py:73` 相当と `escalate_to_legal` 本体を
  両方カバー)。
- 新規 `test_start_over_budget_raises_dedicated_error`: `total_tokens_limit=1`
  で **最初の** `start()` 自体が予算超過になる経路を検証
  (`harness.py` の `start()` 内 `except UsageLimitExceeded` 分岐)。
- 新規 `tests/unit/test_store.py`: `SessionStore` を harness を介さず直接
  駆動し、`create`→`get` の往復、`update` の上書き、`get`/`update` それぞれの
  未知 session id での `KeyError` を検証。harness は「解決済みの id にしか
  `get`/`update` を呼ばない」ため、この2つの `KeyError` 経路は harness 経由
  のテストからは原理的に到達不能 — store 自身の公開契約(未知 id サイレント
  無視ではなく loud に fail)として直接ロックした。

これらはコードの赤→緑ではなく既存 GREEN コードの網羅性テスト追加のため、
厳密な RED 先行ではない(store.py/harness.py 自体は Task 5.1 の失敗テストに
対して既に GREEN 化済み)。追加前にどのテストも通っていた実装を変更しては
いないことを diff で確認済み。

### VERIFY(Task 自身のスコープ)

| Gate | Cmd | 結果 |
|---|---|---|
| test(レーン全体) | `.venv/bin/python3 -m pytest --no-cov -v` | **18 passed**(Task 5.1 の6件 + 追加4件 + 既存8件、回帰なし) |
| lint | `.venv/bin/ruff check .` | `All checks passed!`(`C416` 指摘を dict() 再構築で解消) |
| format | `.venv/bin/ruff format --check .` | `12 files already formatted` |
| typecheck | `.venv/bin/pyright` | `0 errors, 0 warnings, 0 informations` |
| coverage | `.venv/bin/python3 -m pytest --cov -q` | `Required test coverage of 98.0% reached. Total coverage: 100.00%` |
| 既存契約への回帰 | `cd patterns/contracts && uv run pytest --no-cov -q` | `66 passed`(変化なし) |

### 学び

- pydantic-ai の `DeferredToolResults.approvals` のような「外部ライブラリが
  `dict[K, V]` を要求するパラメータ」に自分の狭い union 型の `dict` 変数を
  そのまま渡すと、値型の不変性で必ず型エラーになる。`Mapping` へ切り替える
  提案は「自分の関数の引数型」にしか効かず、相手のパラメータ型が `dict`
  固定なら無意味 — 呼び出し箇所で dict を再構築(`dict(x.items())` や
  dict comprehension)し、双方向型推論に相手の期待型を見せるのが実質唯一の
  直し方。
- 文字列の `part_kind` 比較でユニオン型を絞り込むコードは実行時には正しく
  動いても pyright はそれを型ナローイングとして認識しない —
  `isinstance(part, ToolReturnPart)` のような nominal type チェックに
  置き換えるべきで、これは一般に「discriminated union を `Literal` 文字列
  フィールドで判別する外部ライブラリの型」を扱うときに繰り返し出てくる
  パターン(このレーンでは `agent.py` の `DeferredToolRequests`
  `isinstance` ガードと同型)。
- カバレッジ ratchet は「そのタスクで書いたテストが対象コードの全分岐を
  ちょうど1回叩くか」に敏感 — 再defer ケースのように「型ガードの確認」だけ
  を目的にしたテストは、承認後の実行経路(escalate_to_legal 本体)を
  意図せず素通りさせがちで、都度「このテストで新しく踏んでいない分岐は
  何か」を coverage report で確認する運用が有効だった。
- 次は Task 6(`app.py` + `observability.py` — FastAPI app-factory と
  `/run`・`/resume` エンドポイント)。

---

## Task 6.1 — `test_api.py` + `test_observability.py` の失敗テスト先行作成

**日付**: 2026-07-12
**Boundary**: `patterns/hitl/tests/unit/test_api.py`, `patterns/hitl/tests/unit/test_observability.py`
**Requirements**: 8.6, 9.1

### API 事実確認(実装前の一次調査 — venv 直接確認)

`patterns/hitl/pyproject.toml`(Task 3.1)は意図的に `logfire`(bare、
`logfire[fastapi]` extra なし)のみを宣言している。venv 内を直接検証すると
`opentelemetry-instrumentation-fastapi` が未導入で、`logfire.instrument_fastapi()`
が確実に `RuntimeError` を raise することを確認した:

```
$ .venv/bin/python -c "
import logfire
from fastapi import FastAPI
logfire.configure(send_to_logfire=False)
logfire.instrument_pydantic_ai()
logfire.instrument_fastapi(FastAPI())
"
RuntimeError: The `logfire.instrument_fastapi()` method requires the
`opentelemetry-instrumentation-fastapi` package.
```

この事実により、Task 6.1(b) の「exporter/logfire 未設定環境で起動が失敗し
ない」を、現行環境で**決定論的に** `enable_observability() is False` として
ロックできる(将来 extra を追加すれば挙動が変わる想定内の環境依存だが、
現行のレーン依存構成では確実に再現する)。

### RED

`patterns_hitl.app` / `patterns_hitl.observability` は Task 6.2 まで未実装の
ため、収集時点で import エラーとなることを確認した:

```
$ uv run pytest tests/unit/test_api.py tests/unit/test_observability.py -q
ModuleNotFoundError: No module named 'patterns_hitl.app'
Interrupted: 2 errors during collection
```

### 設計(このタスクで確定 — Task 6.2 が実装する API 面)

plan.md の `create_app(*, agent, store=None, instrument=True)` /
`enable_observability(app=None) -> bool` をそのままテストの呼び出し面として
固定した:

- `test_api.py`: `build_agent(FunctionModel(call_counting_script(*phases)))` +
  `SessionStore()` を `create_app(..., instrument=False)` へ注入(観測性は
  Task 6.1(b) の関心事であり、このファイルの対象外 — plan.md Task 6.2 注記
  どおり)。Task 5.1 で確立済みの `function_model_scripts` 台本(
  `apply_discount_call` / `final_result_call` / `call_counting_script`)を
  そのまま再利用し、HTTP 境界だけを新たに検証する。
  - `/run` 承認不要 → `{"status": "completed", "output": {...}}`。
  - `/run` 承認要 → `{"status": "pending_approval", "session_id", "approvals":
    [{"tool_call_id", "tool_name", "args"}]}`。
  - `/resume` 承認(`{"approved": true}`)→ completed。
  - `/resume` 拒否(`{"approved": false, "message": ...}`)→ completed(代替案)。
  - `/resume` 未知 session → 404。
  - `/resume` の `Decision` 相互排他違反(`approved=True` + `message`)→ 422
    (FastAPI の pydantic validation error、ハンドラ到達前)。
- `test_observability.py`: `enable_observability(FastAPI())` を直接呼び、
  `LOGFIRE_TOKEN` 未設定 + fastapi extra 未導入の環境で `False` を返し例外を
  raise しないことを検証。加えて `create_app(agent=..., instrument=True)` を
  `with TestClient(app):` へ通し、観測性初期化失敗が起動・リクエスト処理を
  一切ブロックしないこと(R9.1)を実請求で検証。

### lint 対応(TC002)

初版は `ToolCallPart`(test_api.py)と `pytest`(test_observability.py)を
通常 import していたが、いずれも型注釈のみでの使用だったため ruff `TC002`
が検出(`from __future__ import annotations` 下では実行時未使用)。sse レーン
の `test_observability.py` が既に採用している `if TYPE_CHECKING: import
pytest` の形に揃えて `TYPE_CHECKING` ブロックへ移動し解消。

### VERIFY(Task 自身のスコープ)

| Gate | Cmd | 結果 |
|---|---|---|
| RED 確認 | `uv run pytest tests/unit/test_api.py tests/unit/test_observability.py -q` | `ModuleNotFoundError: No module named 'patterns_hitl.app'`(収集失敗 — 意図した赤) |
| lint(新規2ファイル) | `uv run ruff check tests/unit/test_api.py tests/unit/test_observability.py` | 初回 `TC002` 2件 → `TYPE_CHECKING` へ移動して解消 → `All checks passed!` |
| format(新規2ファイル) | `uv run ruff format --check tests/unit/test_api.py tests/unit/test_observability.py` | `2 files already formatted` |

pyright / レーン全体のテスト実行・カバレッジは `app.py`/`observability.py`
が存在しない現時点では意味を持たない(import 未解決)ため、Task 6.2 の
GREEN 後に実施する。

### 範囲外(Task 6.2 へ)

`app.py`(`create_app` / `RunRequest` / `CompletedResponse` /
`PendingResponse` / `ResumeRequest` / `Decision` / lifespan)と
`observability.py`(`enable_observability`)の実装本体。

### 学び

- レーンが意図的に `logfire[fastapi]` extra を宣言していない構成は、
  「観測性初期化が実際に失敗する」経路をモックなしで検証できる好条件になる
  — fail-soft パスを検証するテストにとって、依存を絞ったレーン構成自体が
  ちょうどよい負荷試験環境として働く。
- 次は Task 6.2(`app.py` + `observability.py` の実装、本タスクの赤の緑化)。

---

## Task 6.2 — `app.py` + `observability.py` の実装(Task 6.1 の赤の緑化)

**日付**: 2026-07-12
**Boundary**: `patterns/hitl/src/patterns_hitl/app.py`, `patterns/hitl/src/patterns_hitl/observability.py`
**Requirements**: 5.2, 5.3, 8.1, 8.2, 8.3, 8.5, 8.6, 9.1

### GREEN

- `observability.py`: `enable_observability(app: FastAPI | None = None) -> bool` —
  `logfire.configure(send_to_logfire="if-token-present")` + `instrument_pydantic_ai()` を
  常に実行し、`app is not None` のときのみ `instrument_fastapi(app)` を追加実行(Task 6.1(b)
  の一次調査どおり、この環境では extra 未導入のため `app` 付き呼び出しは確実に失敗する —
  `app=None` は「エージェント計装のみ欲しい/まだ app が無い」呼び出し元向けの部分計装パス
  として設計)。root `logging_setup.configure_observability` と同型の bare `except Exception`
  fail-soft(`# noqa: BLE001` + 理由コメント)。
- `app.py`: `create_app(*, agent, store=None, instrument=True) -> FastAPI` — `harness =
  HitlHarness(agent, store or SessionStore())` を関数内で構築(plan.md AD-8)。
  - リクエスト/レスポンス型: `RunRequest` / `PendingApproval`(`ToolCallPart` を
    `tool_call_id`/`tool_name`/`args` へ写像)/ `CompletedResponse` / `PendingResponse` /
    `Decision`(`model_validator(mode="after")` で `approved=True`+`message` と
    `approved=False`+`override_args` の両方を `ValueError` → FastAPI が 422 化)/
    `ResumeRequest`。
  - `_to_deferred_result(decision)`: `approved` → `ToolApproved(override_args=...)`、
    `not approved` → `message` があれば `ToolDenied(message)`、なければ `ToolDenied()`
    (デフォルトメッセージは pydantic-ai 側の既定文言に委ねる)。
  - `POST /run`: `harness.start(prompt)` → `isinstance(result, PendingResult)` で
    `PendingResponse`/`CompletedResponse` へ分岐。
  - `POST /resume`: `body.decisions` を `_to_deferred_result` で辞書変換し
    `harness.resume(session_id, decisions)`。`except KeyError` を捕捉して
    `HTTPException(404, ...)` に変換(R8.5 — store の `KeyError` を素通りさせない)。
  - lifespan(`@asynccontextmanager async def _lifespan(app) -> AsyncGenerator[None]`)は
    `instrument` が真のときだけ `enable_observability(app)` を呼び、戻り値は無視して
    `yield`(観測性初期化の成否がリクエスト処理を一切ブロックしない、R9.1)。

Task 6.1 の8テストは**初回実装で全て一発合格**
(`uv run pytest tests/unit/test_api.py tests/unit/test_observability.py -v --no-cov` →
`8 passed`)。

### lint/typecheck 対応

1. **`TC002`(`patterns_contracts.SupportOutput`)**: `CompletedResponse.output: SupportOutput`
   は pydantic フィールドのため実行時解決に実体 import が必要 — ruff は annotation-only
   使用と誤検出する。`patterns/contracts/src/patterns_contracts/deep_research.py` の
   既存の抑制パターン(`# noqa: TC001  # reused, not redefined` + 直前の説明コメント)を
   `TC002` に変えてそのまま踏襲し、「pydantic がクラス定義時に実体 import を要求する」旨の
   コメントを追加して解消。
2. **`reportDeprecated`(pyright)**: `@asynccontextmanager` 付き関数の戻り値注釈を
   `AsyncIterator[None]` としていたところ、pyright が `AsyncGenerator[None]` への変更を
   要求(バージョン特有の非推奨警告)。root `main.py` の `_lifespan` が既に
   `AsyncGenerator[None]` を使っている実例と一致させて解消。

### カバレッジ ratchet(fail_under=98)を閉じるための追加テスト

初回実装直後は **95.89%**(app.py 92% / observability.py 87% — 4行 + 1行未達)。
Task 5.2 と同型の「実装は変更せず、踏んでいない分岐をテストで閉じる」対応:

- `observability.py:47`(`return True`)— Task 6.1(b) のテストは常に `app` 付きで呼んで
  いたため、この環境で確実に失敗する `instrument_fastapi` 経路しか踏んでいなかった。
  新規 `test_enable_observability_without_an_app_returns_true`: `enable_observability()`
  (app なし)は `instrument_fastapi` を呼ばないため成功し `True` を返すことを検証。
- `app.py:109-110`(`Decision` の `approved=False` + `override_args` 分岐)— Task 6.1 は
  `approved=True` + `message` の組しか検証していなかった。新規
  `test_resume_decision_denied_with_override_args_is_rejected_as_422` を追加。
- `app.py:140`(`_to_deferred_result` の `return ToolDenied()` — message なし denial)—
  既存テストは常に `message` 付きの denial だった。新規
  `test_resume_with_bare_denial_and_no_message_still_completes` を追加。
- `app.py:205`(`resume` ハンドラ内の再 defer 分岐 `_to_pending_response`)— 既存テストは
  `/resume` が必ず completed で終わるケースのみだった。新規
  `test_resume_can_re_defer_a_second_pending_approval`(Task 5.1(e) と同じ3フェーズ台本を
  HTTP 境界で再現)を追加し、2回目の `/resume` が `pending_approval` を返すことを検証。

これらはコードの赤→緑ではなく既存 GREEN コードの網羅性テスト追加(Task 5.2 と同型)。

### VERIFY(Task 自身のスコープ)

| Gate | Cmd | 結果 |
|---|---|---|
| test(Task 6.1 対象ファイル) | `uv run pytest tests/unit/test_api.py tests/unit/test_observability.py -v --no-cov` | **8 passed**(初回実装で一発合格) |
| test(レーン全体+cov、追加後) | `uv run pytest --cov -q` | **30 passed** / `Total coverage: 100.00%`(floor 98 到達) |
| lint | `uv run ruff check .` | 初回 `TC002` 1件 → 抑制コメント追加で解消 → `All checks passed!` |
| format | `uv run ruff format --check .` | 初回 `test_api.py` 1件未整形(追加テストの折返し)→ `ruff format` で解消 → `16 files already formatted` |
| typecheck | `uv run pyright` | 初回 `reportDeprecated` 1件(`AsyncIterator`→`AsyncGenerator`)→ 解消 → `0 errors, 0 warnings, 0 informations` |
| 既存契約への回帰 | `cd patterns/contracts && uv run pytest --no-cov -q` | `66 passed`(変化なし) |

### 学び

- 「bare `logfire`(fastapi extra 無し)」というレーン依存構成そのものが、
  `instrument_fastapi` の fail-soft パスを**モックなしで**決定論的に踏める好条件になる
  一方、`enable_observability()` の *成功* パス(`return True`)を踏むには「app を渡さない
  呼び出し」という別の入口が必要だった — fail-soft 関数のカバレッジ 100% には
  「失敗させる入力」と「成功させる入力」の両方を明示的に用意する設計(`app: FastAPI |
  None`)が効いた。
- ruff の `TC002`/`TC003` は「pydantic `BaseModel` のフィールド注釈は実行時に解決される」
  ことを認識しない既知の盲点 — `patterns_contracts` 側で既に確立していた
  `# noqa: TC00x  # <理由>` + 直前コメントの抑制パターンをそのまま app.py にも適用でき、
  レーンをまたいで再利用可能な運用として機能した。
- Section 6(`app.py` + `observability.py`)完了。次は Section 7((P) mise / patterns-ci /
  security.yml / dependabot への登録、7.1〜7.3)。

---

## Task 7.1 — `mise.toml` へ `patterns/hitl` の列挙面登録 + `patterns:test:integration:hitl` 新設

**日付**: 2026-07-12
**Boundary**: `mise.toml`
**Requirements**: 1.4, 11.1, 11.2

### 実装(非 TDD — 設定ファイルの列挙面追加タスク、tasks.md に「赤を確認する」記載なし)

sse/deep-research と同型の列挙面追加(コード変更なし、config-only)。

- コメントブロック(`patterns:setup` 直前)に deep-research の次段として hitl の
  独立レーン注記(Python 3.14、sse/pydantic-ai レーンと同系)を追加。
- `patterns:{setup,lint,format,typecheck,test,audit}` の 6 task 本体それぞれに
  `echo "== <verb> patterns/hitl"; (cd patterns/hitl && uv ... )` を、既存の
  deep-research 行の直後に 1 行追加(contracts → frameworks glob → rag → sse →
  deep-research → hitl の順序を維持)。
- `patterns:test:integration`(aggregate)にも deep-research 行の直後に hitl 行を追加。
- `patterns:test:integration:hitl`(per-lane)を新設:
  `RUN_INTEGRATION_PATTERNS=1 EXPECT_LIVE_TESTS=2 uv run pytest tests/integration`
  — `EXPECT_LIVE_TESTS=2` は Task 8.1(未実装)が置く e2e 2 本(承認経路 1 本 + 拒否経路
  1 本)と一致させ、空振り緑を決定論的に赤化する設計(tasks.md 記載どおり)。
  `patterns/hitl/tests/integration/` はまだ存在しない(Task 8.1 の境界)ため、この task
  自体は現時点では実行すると `tests/integration` 収集エラーになるが、それは意図した
  sequenced 状態であり(`patterns:test:integration` aggregate も同様)、gated task なので
  `patterns:check` / 通常の `mise run test` には含まれず現状の緑に影響しない。

### VERIFY(Task 自身のスコープ)

`patterns/hitl` は Task 3〜6 で既に実装済みのレーンのため、新設した列挙面が実際に
正しく動くことをそのまま実行検証できた:

| Gate | Cmd | 結果 |
|---|---|---|
| lint | `mise run patterns:lint` | 5 レーン(contracts/frameworks×3/rag/sse/deep-research/hitl)すべて `All checks passed!`(hitl 追加後も既存レーンに影響なし) |
| format | `mise run patterns:format` | `patterns/hitl` `16 files already formatted`(他レーンも変化なし) |
| typecheck | `mise run patterns:typecheck` | `patterns/hitl` `0 errors, 0 warnings, 0 informations`(他レーンも変化なし) |
| test(+cov) | `mise run patterns:test` | `patterns/hitl` `30 passed`、`Total coverage: 100.00%`(floor 98 到達、他レーンも変化なし) |
| audit | `mise run patterns:audit` | `No known vulnerabilities found`(`patterns-hitl` 自身は PyPI 未公開のため audit スキップ — `patterns-contracts` と同型の既知の自己参照スキップ、脆弱性検出には影響しない) |
| 既存ガードへの回帰 | `uv run pytest tests/unit/test_ollama_ci_workflows.py -q` | `5 passed`(root workflow ガードテストへの影響なし — このタスクは `mise.toml` のみを変更し `.github/workflows/*.yml` は Task 7.2 の境界) |

### 学び

- 列挙面タスク(mise.toml のみの追加)は、対象レーンが既に実装済み(Task 3〜6 完了後)
  であれば「追加した行をそのまま実行して green を確認する」ことが実質的な TDD 相当の
  検証になる — 新規コードを書かないため red 相当の状態は存在しない。
- `patterns:test:integration` / `patterns:test:integration:hitl` は Task 8.1 が
  `tests/integration/` を作るまで実行不能(意図した sequenced 状態)。これらは gated
  task であり `patterns:check` 等のデフォルト経路に含まれないため、現時点の green には
  影響しない。
- 次は Task 7.2(`.github/workflows/patterns-ci.yml` / `security.yml` / `dependabot.yml`
  への hitl 登録)。

---

## Task 7.2 — CI 列挙面(`patterns-ci.yml` / `security.yml` / `dependabot.yml`)への hitl 登録

**日付**: 2026-07-12
**Boundary**: `.github/workflows/patterns-ci.yml`, `.github/workflows/security.yml`, `.github/dependabot.yml`
**Requirements**: 1.6

### 実装(非 TDD — CI 設定ファイルの列挙面追加タスク、tasks.md に「赤を確認する」記載なし)

sse/deep-research の既存ジョブ形状をそのまま鏡映(コード変更なし、config-only)。

- `patterns-ci.yml`: `push`/`pull_request` 両方の `paths` に、deep-research 行の直後
  (`mise.toml` の直前)へ `patterns/hitl/**` を追加。専用ジョブ `hitl` を `deep-research`
  ジョブの直後に新設 — sse ジョブと同型(Python 3.14、working-directory
  `patterns/hitl`、`uv lock --check` → `uv sync --all-groups --locked` → `ruff check` →
  `ruff format --check` → `pyright` → `pytest --cov --cov-report=term` → `pip-audit`)。
  コメントは sse/deep-research の記法に揃え、hitl の hermetic 機構が
  `conftest.py` の `models.ALLOW_MODEL_REQUESTS = False`(sse の block_network
  フィクスチャとは実装が異なる — Task 3.2 の実装事実に合わせて正確に記述)である旨と、
  live-Ollama e2e は `patterns-integration-ollama.yml`(Task 8.2、未実装)へ委譲する旨を
  記載。
- `security.yml`: `patterns-pip-audit` matrix の `include` に
  `{ lane: hitl, dir: patterns/hitl }` を deep-research 行の直後に追加。
- `dependabot.yml`: pip `directories`(pydantic-ai 依存レーン監視ブロック)に
  `/patterns/hitl` を追加。ブロックのコメントも「frameworks 3 レーン」→「4 レーン」に
  更新し、plan.md AD-9 の判定規則(rag/sse/deep-research の未監視は既知のスコープ外
  ギャップ、daily pip-audit cron が補完)を明記。既存の `groups.exclude-patterns`
  (`pydantic-ai*` / `beeai-framework`)はブロック全体に適用されるため無改修で
  hitl の `pydantic-ai-slim` 依存も個別レビュー対象になる(パターンマッチ確認済み)。

### VERIFY(Task 自身のスコープ)

| Gate | Cmd | 結果 |
|---|---|---|
| YAML 構文 | `uv run python -c "import yaml; ..."`(3 ファイルを safe_load) | 3 ファイルとも `OK`(パース成功) |
| 既存ガードへの回帰 | `uv run pytest tests/unit/test_ollama_ci_workflows.py -v` | **5 passed**(本タスクは `integration-ollama.yml`/`patterns-integration-ollama.yml`/security.yml の cron 部分を一切変更していないため無影響) |
| ルート回帰(全体) | `mise run check` | **282 passed, 4 skipped**(変化なし — patterns/ は root ゲート対象外) |
| hitl レーン回帰 | `cd patterns/hitl && uv run pytest --cov -q` | **30 passed** / `Total coverage: 100.00%`(CI 設定変更はレーンのソース/テストに触れないため不変を再確認) |

`patterns-ci.yml` の新規 `hitl` job 自体・`security.yml` の新規 matrix エントリは
GitHub Actions ランナー上でのみ実際に走る(ローカルではワークフロー実行系の
E2E 検証はできない)。YAML 構文検証 + 既存ガードテストの緑維持が本タスクの
決定論的な検証面(sse/deep-research 追加時と同型の検証範囲)。

### 学び

- `.github/workflows/test_ollama_ci_workflows.py` は `integration-ollama.yml` /
  `patterns-integration-ollama.yml` / `security.yml` の cron 配線のみを構造的に
  ピン留めしている — `patterns-ci.yml` 自体の構造(paths / job 追加)を検証する
  専用テストは存在しない。sse/deep-research 追加時も同様に「YAML 構文 + 既存ガード
  緑」までがローカルで確認可能な範囲であり、job の実際の動作確認は初回 PR の CI 実行
  (GitHub Actions)に委ねる運用が確立済み。
- dependabot の `groups.exclude-patterns` はブロック単位(directories 配列全体)で
  1 セットしか持てない — 新しいディレクトリを追加する際は既存の除外パターンが
  その新ディレクトリの依存名にも意図通りマッチするかを確認する必要がある
  (`pydantic-ai*` glob が `pydantic-ai-slim` にもマッチすることを確認済み)。
- 次は Task 7.3(モデル ID 二層ガードの第2層を `patterns/*/src` へ走査拡張)。

---

## Task 7.3 — モデル ID 二層ガード第2層の走査拡張(`tests/unit/test_no_hardcoded_model_ids.py`)

**日付**: 2026-07-12
**Boundary**: `tests/unit/test_no_hardcoded_model_ids.py`
**Requirements**: 12.2

### 事前調査(拡張前の既存レーンクリーン性確認)

tasks.md 7.3 の指示「既存レーン src が現状クリーンであることを事前 grep で確認してから
拡張する」に従い、禁止リテラル 5 種を全 8 レーン src(depth-1: contracts/deep-research/
hitl/rag/sse、frameworks/{beeai,llamaindex,pydantic-ai})に対して事前 grep:

```
$ for lit in "granite4.1:8b" "claude-sonnet-4-6" "claude-haiku-4-5-20251001-v1:0" \
    "llama3.2-vision:11b" "granite-4-h-small"; do
    grep -rn --include="*.py" -F "$lit" patterns/*/src patterns/frameworks/*/src
  done
```

→ 出力 0 件(全リテラル・全レーンでヒットなし)。拡張は既存レーンを赤化しない
ことを確認済み(gap-analysis H-1 の事前確認記載と一致)。

### 設計判断: 走査対象を `patterns/*/src` + `patterns/frameworks/*/src` の両方に拡張

tasks.md 本文は `patterns/*/src`(単一レベル glob)のみを明記するが、research.md AD-10
は「hitl 一点ではなく**全レーン走査**にすることで、将来レーンの追い漏れも防ぐ」と明記して
おり、gap-analysis H-1 も「第1層 pre-commit は `types: [python]` で **patterns 全体**を
走査済み(除外は `tests/**` / `src/**/config.py` のみ)」と対比している。第1層は
`patterns/frameworks/{beeai,llamaindex,pydantic-ai}/src`(depth-2)も走査対象であるため、
第2層をそこに揃えないと「新レーンは未スキャンゆえ自動 pass」というギャップの一部
(frameworks レーン)が残存する。したがって単一 glob の字面ではなく AD-10 の設計意図
(全レーンパリティ)を実現する形で実装した:

```python
src_dirs = [SRC_DIR, *PATTERNS_DIR.glob("*/src"), *PATTERNS_DIR.glob("frameworks/*/src")]
```

`Path.glob("*/src")` / `Path.glob("frameworks/*/src")` は固定セグメント数のみにマッチする
非再帰 glob のため、`patterns/<lane>/.venv/lib/.../licenses/src` のような各レーン `.venv`
配下に実在する深い `src` 名ディレクトリ(numpy/pip の licenses など、事前 `find` で確認済み)
を一切拾わない — `patterns/**/src` のような再帰 glob を使わなかった理由(venv 内の
サードパーティ `src` ディレクトリを誤って走査する事故を防ぐ)。

### RED(植え込みリテラルでの赤確認 — コミットしない一時ファイル)

拡張直後(まだ既存レーンはクリーンなため green のまま)、tasks.md の指示どおり
一時ファイルで禁止リテラルを植え込み、拡張が実際に効いていることを確認した:

```
$ cat > patterns/hitl/src/patterns_hitl/_tmp_red_check.py <<'EOF'
MODEL_NAME = "claude-sonnet-4-6"
EOF
$ uv run pytest --no-cov tests/unit/test_no_hardcoded_model_ids.py::test_no_hardcoded_model_ids_in_src -v
AssertionError: ... Offenders:
  patterns/hitl/src/patterns_hitl/_tmp_red_check.py:2 contains 'claude-sonnet-4-6'
1 failed
```

depth-1 レーン(hitl)側の赤化を確認後、frameworks レーン側の glob も独立に効くことを
確認するため、2本目の植え込みを追加:

```
$ cat > patterns/frameworks/pydantic-ai/src/_tmp_red_check2.py <<'EOF'
MODEL_NAME = "granite-4-h-small"
EOF
$ uv run pytest --no-cov tests/unit/test_no_hardcoded_model_ids.py::test_no_hardcoded_model_ids_in_src -v
AssertionError: ... Offenders:
  patterns/hitl/src/patterns_hitl/_tmp_red_check.py:2 contains 'claude-sonnet-4-6'
  patterns/frameworks/pydantic-ai/src/_tmp_red_check2.py:1 contains 'granite-4-h-small'
1 failed
```

両 glob パス(`*/src` と `frameworks/*/src`)がそれぞれ独立に違反を検出することを実測で
確認(赤を確認)。

### GREEN(一時ファイル撤去 → 恒久緑化)

```
$ rm patterns/hitl/src/patterns_hitl/_tmp_red_check.py \
     patterns/frameworks/pydantic-ai/src/_tmp_red_check2.py
$ uv run pytest --no-cov tests/unit/test_no_hardcoded_model_ids.py -v
2 passed
$ git status --short patterns/hitl patterns/frameworks/pydantic-ai
(出力なし — 一時ファイルの残留なし)
```

### VERIFY(Task 自身のスコープ + 完了ゲート先取り確認)

| Gate | Cmd | 結果 |
|---|---|---|
| test(対象ファイル、拡張直後) | `uv run pytest --no-cov tests/unit/test_no_hardcoded_model_ids.py -v` | **2 passed**(既存レーンへの回帰なし) |
| RED(hitl 植え込み) | `uv run pytest --no-cov .../test_no_hardcoded_model_ids.py::test_no_hardcoded_model_ids_in_src -v` | `1 failed`(意図した赤、`patterns/hitl/src/...` を検出) |
| RED(frameworks 植え込み追加) | 同上 | `1 failed`(2 件の offender、`patterns/frameworks/pydantic-ai/src/...` も検出 — 両 glob の独立動作確認) |
| GREEN(撤去後) | `uv run pytest --no-cov tests/unit/test_no_hardcoded_model_ids.py -v` | **2 passed**(恒久緑化) |
| 残留確認 | `git status --short patterns/hitl patterns/frameworks/pydantic-ai` | 出力なし(一時ファイルはコミット対象に現れない) |
| ルート回帰(全体) | `mise run check` | **282 passed, 4 skipped**(変化なし) |
| カバレッジ ratchet | `mise run cov` | `Required test coverage of 98.0% reached. Total coverage: 98.83%`(変化なし) |

### 学び

- tasks.md の字面(`patterns/*/src`)と research.md の設計意図(AD-10「全レーン走査」)
  が食い違う場合、gap-analysis の元々の問題提起(第1層との走査範囲パリティ)に照らして
  意図を優先する判断をした — 第1層 pre-commit hook は `patterns/frameworks/*/src` も
  走査済みのため、第2層をそこだけ除外すると新設ギャップが残ってしまう。
- 非再帰 glob(`Path.glob("*/src")` / `Path.glob("frameworks/*/src")`)は固定セグメント数
  にしかマッチしないため、各レーンの `.venv/lib/.../licenses/src` のようなサードパーティ
  由来の深い `src` ディレクトリ(事前 `find` で実在確認済み)を安全に除外できる — この
  性質を確認してから再帰 glob(`**/src`)を避ける設計判断をした。
- 一時ファイルでの RED 確認は 2 段階(depth-1 レーン → frameworks レーン)に分けて行うと、
  拡張した 2 つの glob パスがそれぞれ独立に機能していることを取りこぼしなく検証できる。
- Section 7(mise / patterns-ci / security.yml / dependabot / モデル ID ガード)完了。
  次は Section 8(live 統合レーン、Task 8.1〜8.2)。

---

## Task 8.1 — Live 統合レーン(dispatch-only Ollama e2e)

**日付**: 2026-07-12
**Boundary**: `patterns/hitl/tests/integration/`
**Requirements**: 11.1, 11.2, 12.1

### 実装

`tests/integration/test_ollama_hitl_e2e.py` を新規作成(`patterns/sse/tests/integration/test_ollama_e2e.py`
を雛形に、研究ノート I-2 の直近前例)。`tests/integration/conftest.py` は sse と同じ
1 行再エクスポート(`patterns_contracts.pytest_live_guard`)。

- `create_app(agent=build_agent(_ollama_model()), store=SessionStore(), instrument=False)`
  を実 HTTP レイヤ(`httpx.ASGITransport`)経由で駆動 — Task 6 のハーメティックテストと
  同一 DI シームを再利用し、live モデルだけを実体に差し替える(plan.md HitlApp)。
- プロンプトは自由記述ではなく `apply_discount` を具体引数(`$500.00` — 既定閾値
  `$50` 超)で明示指示する形にした。ハーメティック `FunctionModel`/`TestModel` 系の
  スクリプト(`apply_discount_call`)と同じ「ツール呼び出しを強制しやすい」形。
  `escalate_to_legal`(条件なし承認必須)ではなく `apply_discount` を選んだのは、
  数値を含む具体的行動要求の方が live モデルのツール選択再現性が高いと判断したため。
  実測(下記)でも 1 回目の試行から両ケースとも安定して `pending_approval` に到達した。
- 承認経路 1 本 + 拒否経路 1 本(`EXPECT_LIVE_TESTS=2`, mise.toml Task 7.1 と一致)。
  再 defer(R6.1)に対する耐性として `_run_until_completed` に最大 5 往復の
  `/resume` ループを実装(model が複数ツールを連鎖させても loud に fail しない)。
- モデル文字列は `OLLAMA_MODEL_NAME` env のみ(R12.1、ハードコードなし)。

### RED → GREEN(実測)

このコンテナは通常 Python 3.14 を uv でダウンロードできない制約があるが(research.md
I-5)、`patterns/hitl/.venv` は既存タスクで 3.14 が実際に用意されていたため、ローカルで
直接 RED/GREEN を確認できた(CI 迂回は不要だった)。

```
$ cd patterns/hitl && uv run pytest tests/integration -v          # ゲート未設定 = 赤の代わりに確認すべき「安全な skip」
2 skipped                                                          # RUN_INTEGRATION_PATTERNS 未設定 → 収集は成功し、無条件 skip(false-green にならないことを確認)

$ RUN_INTEGRATION_PATTERNS=1 OLLAMA_MODEL_NAME=granite4.1:8b \
  uv run pytest tests/integration -v
2 passed in 55.51s                                                 # 実 Ollama デーモン(granite4.1:8b)に対し初回から green

$ OLLAMA_MODEL_NAME=granite4.1:8b RUN_INTEGRATION_PATTERNS=1 EXPECT_LIVE_TESTS=2 \
  uv run pytest tests/integration -v
2 passed in 72.66s                                                 # mise タスクと同じ環境変数構成でも green、EXPECT_LIVE_TESTS ガードも実行数 2 を検出して通過

$ mise run patterns:test:integration:hitl                          # OLLAMA_MODEL_NAME を明示しないタスク単体
KeyError: 'OLLAMA_MODEL_NAME'                                       # 想定内(タスクは CI/手動実行時に env で供給される前提、mise.toml に組み込み値なし)
```

再実行(フォーマット適用後の再確認、非決定性への耐性チェック):

```
$ OLLAMA_MODEL_NAME=granite4.1:8b RUN_INTEGRATION_PATTERNS=1 EXPECT_LIVE_TESTS=2 \
  uv run pytest tests/integration -v
2 passed in 70.91s                                                  # 2 回目も安定して green
```

### VERIFY

| Gate | Cmd | 結果 |
|---|---|---|
| lint | `uv run ruff check .` | All checks passed! |
| format | `uv run ruff format --check .` → 1 file reformat → 再確認 | reformat 後 `18 files already formatted` |
| typecheck | `uv run pyright` | 0 errors, 0 warnings, 0 informations |
| unit(回帰) | `uv run pytest --cov` | `30 passed, 2 skipped`、カバレッジ `100.00%`(unaffected) |
| pip-audit | `uv run pip-audit` | `No known vulnerabilities found` |
| live e2e(ゲート付き、2 回実測) | 上記 | 両方 `2 passed` |
| root モデル ID ガード回帰 | `uv run pytest --no-cov tests/unit/test_no_hardcoded_model_ids.py -q` | `2 passed` |
| workflow ガード回帰 | `uv run pytest --no-cov tests/unit/test_ollama_ci_workflows.py -q` | `5 passed`(Task 8.2 未着手のため hitl ジョブ言及なし、想定どおり無変化) |

### 学び

- Task 3.2 の実装ノートが想定していた「ローカル 3.14 実行不能」制約は、このコンテナの
  現状の `patterns/hitl/.venv` では解消済みだった — CI 迂回の記録要件（M-2）を機械的に
  適用する前に、まず実際にローカル実行を試すことで、実測の RED→GREEN 証跡を得られた。
- live e2e のツール強制は「意味的な指示」(legal risk を匂わせる)より「具体的な数値
  つきの行動要求」の方が再現性が高い、というハーメティックテスト側の設計判断
  (`apply_discount_call` が既定)をそのまま live プロンプトにも転用するのが妥当。
- Section 8 は Task 8.1 完了、Task 8.2(`patterns-integration-ollama.yml` への hitl ジョブ
  追加 + workflow ガードテスト緑化)が残タスク。

---

## Task 8.2 — `patterns-integration-ollama.yml` への hitl ジョブ追加

**日付**: 2026-07-12
**Boundary**: `.github/workflows/patterns-integration-ollama.yml`
**Requirements**: 11.3

### 実装(非 TDD — CI 設定ファイルの列挙面追加タスク、tasks.md に「赤を確認する」記載なし。Task 7.2 と同型)

`jobs.e2e.strategy.matrix.include` の `deep-research` 行の直後(既存 6 レーンの末尾)に
hitl エントリを追加(config-only、コード変更なし):

```yaml
- lane: hitl
  dir: patterns/hitl
  task: 'patterns:test:integration:hitl'
  embed: false
  timeout: 60
```

- `embed: false` — hitl は rag と異なり埋め込みモデルを使わない(sse/beeai/pydantic-ai/
  deep-research と同じ)。
- `timeout: 60` — 他の非 llamaindex レーンと同じ既定値。Task 8.1 のローカル実測
  (`EXPECT_LIVE_TESTS=2`、2 テスト計 55〜73 秒)から、CI のモデル pull ステップは
  別ステップ(タイムアウト対象外)であり、`mise run patterns:test:integration:hitl`
  自体の実行時間は 60 分の枠に十分収まる。
- ワークフロー冒頭のコメント(6 レーン言及、L7/L32)は変更していない — L7 は
  「redesign 前の旧 nightly 体制が 6 レーン走らせていた」という**過去の事実**の記述、
  L32 の「six contract-level e2e cases per framework lane」は frameworks/ 3 レーン限定の
  記述で、いずれも hitl 追加によって不正確化しない(事前に文脈を再読して確認)。
- ジョブレベル concurrency(`matrix.lane` キー)・per-lane cache key
  (`${{ matrix.lane }}` サフィックス)は既存の汎用式がそのまま hitl にも適用される
  ため、hitl 用の追記は不要(sse/deep-research 追加時と同じ)。

### VERIFY(Task 自身のスコープ)

| Gate | Cmd | 結果 |
|---|---|---|
| YAML 構文 + matrix 反映確認 | `uv run python -c "import yaml; ...; assert 'hitl' in lanes"` | `['beeai', 'pydantic-ai', 'llamaindex', 'rag', 'sse', 'deep-research', 'hitl']` / `OK` |
| workflow ガードへの回帰 | `uv run pytest --no-cov tests/unit/test_ollama_ci_workflows.py -v` | **5 passed**(`workflow_dispatch` 単一トリガー・concurrency 網羅の両方を維持したまま hitl 追加を許容) |
| ルート回帰(全体) | `mise run check` | **282 passed, 4 skipped**(変化なし) |

新設 `hitl` matrix エントリ自体(daemon 起動 → model pull → `mise run
patterns:test:integration:hitl` 実行)は GitHub Actions ランナー上でのみ実際に走る
(ローカルではワークフロー実行系の E2E 検証はできない、Task 7.2 と同じ制約)。YAML
構文検証 + 既存ガードテスト緑維持がローカルで確認可能な決定論的な検証範囲。

### 学び

- 既存の `test_ollama_ci_workflows.py` はレーン数に非依存な構造的invariant
  (トリガー種別・concurrency 網羅性)のみをピン留めしているため、matrix に
  レーンを追加するだけの変更では新規テストの追加(赤化)は要求されない —
  Task 7.2 で確立した「config-only 追加は YAML 構文 + 既存ガード緑で十分」という
  検証範囲の判断をそのまま踏襲した。
- ワークフロー冒頭のコメントに数値(「6 レーン」)が出てきても、それが現在の
  matrix サイズを指しているのか過去の体制を指しているのかを文脈で見極める必要が
  ある — L7 は past-tense の redesign 経緯、L32 は frameworks/ サブセット限定の
  記述であり、どちらも今回のレーン追加とは無関係だった。
- Section 8(live 統合レーン)完了。残タスクは Section 9(Task 9.1、ドキュメント
  索引同期)のみ。
