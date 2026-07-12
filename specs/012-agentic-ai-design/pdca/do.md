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
