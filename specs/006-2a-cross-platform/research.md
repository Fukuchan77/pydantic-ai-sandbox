# 006-2a-cross-platform — Discovery & Research Log

`/sdd-plan` 生成。承認済み要件（spec.md R1–R13）を design に落とすための調査・
意思決定・リスクを記録する。一次情報は 005 の実装コード・`research.md`・
steering（tech.md / structure.md §8）であり、外部 Web 調査は新規依存が無い
ため実施しない（唯一の runtime 依存は `pydantic`）。

## Discovery type

**Extension (light)** — 005-cross-platform のレーン足場（フェイク基盤 /
`configure_tracing` / テスト三層 / mise・CI / pre-commit ガード）を拡張する。
統合点の大半は 005 で確立済み。真の新規性は2点に集中する:

1. 依存ゼロの契約専用パッケージ `patterns/contracts/` の昇格（配線・lock 連鎖）。
2. autonomous-agent のツールループ（4ガードレール契約 + 台本フェイクのターン列駆動）。

この2点のみ深掘りし、残りは 005 規律のクローン適用とする。

## Investigations

### 契約パッケージのクロス Python バージョン install

- **Question**: `requires-python >=3.13` のパス依存パッケージを、3.14 レーン
  （pydantic-ai）と `>=3.13,<3.14` レーン（beeai / llamaindex）の両方から
  install できるか（R1.2）。
- **Findings**: 標準セマンティクスで成立する。`requires-python >=3.13` は下限
  のみの宣言で上限を持たないため、3.13 系・3.14 系いずれのインタプリタでも
  install 可能。パッケージ**ソース自体は 3.13 互換構文に限定**する必要がある
  （3.14 専用構文を使うと 3.13 レーンで実行不能）。pyright は
  `pythonVersion = "3.13"` で固定し、3.14 専用機能の混入を機械的に拒否する。
- **Evidence**: tech.md §1（beeai/llamaindex を `>=3.13,<3.14` に固定）/
  各レーン pyproject `requires-python`（pydantic-ai=`>=3.14`、他=`>=3.13,<3.14`）。

### パス依存の配線方式（`tool.uv.sources`）

- **Question**: 各レーンが `patterns/contracts/` を import する配線（R1.4）と
  uv.lock / `--locked` CI との整合。
- **Findings**: 各レーン pyproject に `dependencies += ["patterns-contracts"]` と
  `[tool.uv.sources] patterns-contracts = { path = "../../contracts", editable = true }`
  を追加する。`editable = true` によりソース編集が即時反映され、契約の単一正本
  運用と両立する。`uv sync` がパス依存を editable install するため、4プロジェクト
  （3レーン + contracts）すべての uv.lock を再生成する。CI は `uv sync --locked`
  なので lock 不整合は検出されるが、`cache-dependency-glob` がパス依存先
  （contracts）の変更を取りこぼし得る点はキャッシュ鮮度のみの問題で `--locked` が拾う。
- **Evidence**: gap-analysis.md 統合上の課題1–2 / 各レーン pyproject（現状は
  `[tool.uv.sources]` 未使用）/ patterns-ci.yml の `--locked` 方針（tech.md §8）。
- **相対パス検証**: レーンは `patterns/frameworks/<fw>/`、契約は
  `patterns/contracts/`。`../../contracts` で到達（`..`→frameworks、
  `../..`→patterns、`../../contracts`→contracts）。

### autonomous-agent のループ実装（最優先・高リスク）

- **Question**: 3フレームワークのネイティブ agent 抽象（PydanticAI
  `Agent`+tools / BeeAI `ReActAgent`・`ToolCallingAgent` / LlamaIndex
  `FunctionAgent`）を使うか、chat プリミティブ上の手動一様ループを使うか。
  4ガードレール（max_iterations / allowed_tools / approval_hook / budget）と
  `stop_reason` Literal をどこで確定するか（R6 / R7.2 / R10.3）。
- **Findings**: **手動一様ループ（lane code が駆動）を採用**。理由3点:
  (a) 4ガードレールと `stop_reason` の停止経路を3レーンで同一に保証するには、
  ループ制御をレーンコードが所有する必要がある。ネイティブ executor は停止
  語彙・予算記録の粒度がフレームワーク毎に異なり、同一契約に揃えにくい。
  (b) 既存フェイクは chat レベル（FunctionModel=`ModelResponse` 返却 /
  ScriptedChatModel=`_create` / CustomLLM フェイク=`complete`）。これらを
  「呼出回数で進むターン列」に拡張する方が、ネイティブ agent executor を
  決定論駆動するより遥かに容易（R7.2）。(c) Anthropic「simple, composable
  patterns」原則（patterns/README.md 逐語引用）と pyright strict に整合。
- **Evidence**: model_fakes.py（`_respond` が `info.output_tools` で分岐）/
  fake_chat_model.py（`_create` 返却）/ patterns/README.md 中核主張 /
  gap-analysis.md 研究項目1・選択肢 A3。

### 台本フェイクのターン列駆動

- **Question**: 単発分岐型の既存フェイクを「ツール呼出→環境FB→最終回答」の
  ターン列を返す形へどう拡張するか（R7.2）。
- **Findings**: メッセージ履歴または呼出カーソルで進行させる。
  - PydanticAI `FunctionModel`: `_respond(messages, info)` が**履歴中の
    tool-return 数**で現在ターンを決定（`ToolCallPart` で次ツール、最終は
    `TextPart`）。履歴駆動なので再呼び出しに対し決定論的。
  - BeeAI `ScriptedChatModel`: `_create` 内に呼出カーソルを持ち、ターン列を
    順に返す（既存の `__init__` 状態保持パターンを踏襲）。
  - LlamaIndex `CustomLLM` フェイク: 同じくカーソル方式で `complete` /
    `chat` がターンを返す。
  ツールは決定論的インメモリスタブ（固定入力→固定観測）。
- **Evidence**: model_fakes.py 19–73 / fake_chat_model.py 33–70 /
  gap-analysis.md 統合上の課題3。

### parallelization の variant 表現と順序復元

- **Question**: sectioning / voting の2変種を単一契約で表現し、`branches` の
  順序を決定論復元する方式（R4.4）。
- **Findings**: 単一契約 + `variant: Literal["sectioning","voting"]`。fan-out
  機構は orchestrator-workers の実証済み手法を流用:
  PydanticAI/BeeAI=`asyncio.gather`（入力順保持）、LlamaIndex=`send_event` +
  `collect_events` → **index でソート復元**（orchestrator_workers.py の
  `synthesize` step が既に同手法）。sectioning は task を n 個の index 付き
  section プロンプトに分割して並列実行し集約、voting は同一 task を n 回並列
  実行し多数決集約。プランナー LLM は不要（決定論性とテスト容易性を優先）。
- **Evidence**: llamaindex orchestrator_workers.py 107–122（collect_events +
  sort by index）/ spec.md Clarifications（単一契約 + variant 切替）。

### ドリフトテストの正本パース戦略（単一点化）

- **Question**: README 正本とパッケージの一致を1点で検証する読取方式と設置
  場所（R2.1–2.3）。
- **Findings**: **import 方式 + contracts パッケージ内設置**を採用。
  `patterns/contracts/tests/unit/test_contract_drift.py` が
  (a) 各 `patterns/<pattern>/README.md` の ```python fenced block を `ast` で
  パースしクラス名・フィールド名・`Literal` 値集合を抽出、(b)
  `patterns_contracts` を import し `model_fields` / `typing.get_args` で実体を
  introspect、(c) 両者のクラス集合・フィールド集合・Literal 語彙を比較する。
  contracts パッケージ venv は pydantic + 当該パッケージのみを持つため import が
  自然に成立し、「パッケージのみ参照」（R2.2）を満たす。既存の root
  `tests/unit/test_patterns_contract_sync.py`（3レーン AST 相互比較）は**削除**。
- **Evidence**: test_patterns_contract_sync.py（現行 AST 相互比較）/
  routing/README.md（```python 正本ブロックが既に存在）/ gap-analysis.md
  統合上の課題5・subdecision A2。

## Existing patterns to reuse

| Pattern | Location | Why reuse |
|---------|----------|-----------|
| 並列 fan-out + index 順序復元 | `patterns/frameworks/llamaindex/src/patterns_llamaindex/orchestrator_workers.py:95-122` | parallelization の collect_events 順序復元にそのまま適用 |
| `asyncio.gather` fan-out | `patterns/frameworks/pydantic-ai/.../orchestrator_workers.py:105-110` | parallelization（PydanticAI/BeeAI）の並列実行 |
| schema 分岐フェイク | 各レーン `tests/support/{model_fakes,fake_chat_model,fake_llm}.py` | ターン列駆動への拡張ベース |
| `configure_tracing()` + InMemorySpanExporter | 各レーン `observability.py` / `tests/unit/test_observability.py` | 新4パターンの span≥1 検証に流用 |
| 必須4セクション README 雛形 | `patterns/routing/README.md` | 新4パターン README の構成 |
| レーン pyproject 規律 | `patterns/frameworks/pydantic-ai/pyproject.toml` | contracts パッケージ pyproject の ruff/pyright ミラー |
| ```python 正本ブロック | `patterns/routing/README.md:13-23` | ドリフトテストのパース対象フォーマット |

## External dependencies

| Dependency | Version | Purpose | Verified |
|------------|---------|---------|----------|
| pydantic | `>=2` | `patterns/contracts/` の唯一の runtime 依存 | ✅ 全レーン既存 |
| （新規 runtime 依存なし） | — | 4パターンは既存フレームワーク依存のみで実装 | ✅ |
| hatchling | build only | contracts パッケージの build-backend（レーンと同一） | ✅ レーン既存 |

## Architecture decisions

### ADR-1: contracts パッケージ構造（パターン別サブモジュール + フラット再エクスポート）

- **Context**: 6パターン分の契約を1パッケージに集約する（R1.3）。フラット
  単一 `contracts.py` か、パターン別サブモジュールか。
- **Decision**: パッケージ名 `patterns-contracts`（import 名 `patterns_contracts`）。
  内部は**パターン別サブモジュール**（`routing.py` / `orchestrator_workers.py` /
  `prompt_chaining.py` / `parallelization.py` / `evaluator_optimizer.py` /
  `autonomous_agent.py`）で責務純度を保ち、`__init__.py` が全モデル・型エイリアスを
  **フラット再エクスポート**する。レーンの import 面は
  `from patterns_contracts import RouteDecision, ChainResult, ...` で安定。
- **Alternatives**: フラット単一 `contracts.py`（6パターンで肥大・責務混在、却下）。
- **Consequences**: レーン内のモジュール=責務粒度（structure.md §8 原則2）と一貫。
  ドリフトテストの走査対象がサブモジュール横断になるが、`__init__` 再エクスポート
  経由の introspect で吸収。

### ADR-2: パス依存配線（editable path source）

- **Context**: レーン→契約の import を複製なしで実現する（R1.4 / NFR-3）。
- **Decision**: 各レーン pyproject に `dependencies` 追加 + `[tool.uv.sources]` の
  `path = "../../contracts", editable = true`。レーン→レーンの import は引き続き禁止
  （契約共有はパッケージ経由のみ、NFR-3）。
- **Alternatives**: PyPI 公開（過剰）/ コピー継続（R1 と矛盾、却下）。
- **Consequences**: 4プロジェクトの uv.lock 再生成。CI `--locked` 整合は維持。

### ADR-3: ドリフトテスト = import 方式・contracts パッケージ内設置（単一点）

- **Context**: README 正本とパッケージ実体の一致を1点で保証（R2）。
- **Decision**: `patterns/contracts/tests/unit/test_contract_drift.py` が README
  fenced block（`ast`）と `patterns_contracts`（import introspect）を比較。root の
  `test_patterns_contract_sync.py` は削除。
- **Alternatives**: root 設置 + AST のみ（3.14 root に >=3.13 パッケージ install
  が要る／パッケージ非参照で R2.2 に反する、却下）。
- **Consequences**: ドリフト検知が contracts venv に内包され、`patterns:test` の
  contracts ステップで実行。レーン間 AST 相互比較は消滅（R2.2 充足）。

### ADR-4: autonomous-agent = 手動一様ループ（chat プリミティブ上）

- **Context**: 4ガードレール + `stop_reason` を3レーン同一契約で強制（R6 / R10.3）。
- **Decision**: ネイティブ agent executor を使わず、各レーンが chat/LLM
  プリミティブ上で手動ループを駆動。停止経路（`stop_reason`）・予算記録・
  許可リスト・承認フックはすべてレーンコードが確定する。
- **Alternatives**: ネイティブ `ReActAgent`/`FunctionAgent` 駆動（停止語彙・予算
  粒度がフレームワーク毎に異なり契約統一が困難、フェイク決定論駆動が難、却下）。
- **Consequences**: ループ制御コードがレーン間で構造的に近似。フェイクの
  ターン列駆動が容易になる。各 fw の usage/token API から `budget_spent` を取得。

### ADR-5: 台本フェイクのターン列拡張

- **Context**: ツールループの決定論化（R7.2）。
- **Decision**: 既存3フェイクに「ターン列」モードを追加。PydanticAI=履歴の
  tool-return 数で進行、BeeAI/LlamaIndex=呼出カーソルで進行。各ターンは
  「ツール呼出 or 最終回答」。ツールは決定論的インメモリスタブ。
- **Alternatives**: 新規フェイク基盤の総入替（005 資産破棄、却下）。
- **Consequences**: support/ フェイクが Modify 対象。既存 routing/orchestrator
  テストとの後方互換を保つ（schema 分岐モードは温存）。

### ADR-6: parallelization = 単一契約 + variant、order 復元は既存手法流用

- **Context**: 2変種を単一契約で、順序を決定論復元（R4）。
- **Decision**: `variant: Literal["sectioning","voting"]`。fan-out は
  orchestrator-workers の `asyncio.gather` / `collect_events`+index sort を流用。
  プランナー LLM は使わず決定論的に section/vote を構成。
- **Consequences**: 新規 fan-out 機構の発明不要。リスク低。

### ADR-7: autonomous-agent のツール抽象（contract Protocol）

- **Context**: エントリ signature は `allowed_tools` / `approval_hook` を取る
  （R6.1）が、危険操作分類とツール実行をどこに置くか（R6.4–6.6）。
- **Decision**: contracts パッケージに `Tool` Protocol（`name: str` /
  `dangerous: bool` / 同期 `run(args: str) -> str`）と型エイリアス
  `ApprovalHook = Callable[[str, str], bool]`（tool 名・args → 承認可否）を定義。
  `allowed_tools: Sequence[Tool]`。危険分類は Tool 側が保持し、ループは
  `dangerous` なら `approval_hook` を呼ぶ。`budget_spent` は各反復のモデル usage
  トークン（`int`）。エントリ signature は spec 6.1 に厳密一致。
- **Alternatives**: ツール callable を Pydantic フィールドに格納（callable は
  シリアライズ不可、却下）/ danger を別引数（signature 逸脱、却下）。
- **Consequences**: contracts は pydantic + `typing`/`collections.abc` のみで
  Protocol を表現（runtime 依存増やさず）。

### ADR-8: mise / CI への contracts パッケージ組込

- **Context**: contracts は `patterns/frameworks/*/` glob の外（R12 / R13.1）。
- **Decision**: `patterns:setup/lint/format/typecheck/test` の各タスク先頭に
  contracts パッケージ手順を明示追加（lane ループの前に実行）。`patterns:audit`
  にも contracts の `pip-audit` を追加。patterns-ci.yml は paths に
  `patterns/contracts/**` を追加し、contracts 用ジョブ（または matrix 拡張）で
  lint/typecheck/test+ドリフトを実行。patterns-integration-ollama.yml は
  `mise run patterns:test:integration` 経由で新パターン結合を実行。root の
  ci.yml / integration-ollama.yml / security.yml は無変更（R12.3 / R13.2）。
- **Consequences**: mise タスクが glob ループ + 固定 contracts ステップの混成に。

## Risks & open questions

- ⚠️ **uv.lock 連鎖再生成**（4プロジェクト）— mitigation: 各プロジェクトで
  `uv lock` を実行し、CI `--locked` で整合を担保。タスク順序を
  「contracts setup → lane setup」に固定。
- ⚠️ **契約パッケージの 3.13 構文制約** — mitigation: pyright
  `pythonVersion="3.13"` と `.python-version`=3.13 ピンで 3.14 専用構文を拒否。
- ⚠️ **autonomous-agent ネイティブ executor への誘惑** — mitigation: ADR-4 で
  手動ループを明文化。impl 時の逸脱は design 違反として扱う。
- ⚠️ **フェイク後方互換** — mitigation: ターン列モードを追加機能として実装し、
  既存 schema 分岐モード（routing/orchestrator テスト）を温存。
- ❓ **steering の更新**（structure.md §8 原則1 / tech.md §8 が「契約はレーン複製
  + クロス AST ドリフト」と記述）— 本フィーチャで前提が変わる。plan では steering を
  変更せず、`/sdd-reflect` 時に更新する（Golden Rule: 新パターン確立時のみ追記）。
- ❓ **contracts の pip-audit 必要性**（R10.2）— 依存が pydantic のみで限定的だが、
  pydantic CVE 追従のため dev 依存に含め `patterns:audit` で実行する（低コスト）。
