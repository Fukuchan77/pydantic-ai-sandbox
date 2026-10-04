# Gap Analysis — 014-hub-python-beta-lane

## 1. 分析の要約

> 2026-10-03: 本分析の推奨（§7-3 ほか）は [spec.md](./spec.md) に反映済み。以下の記述は反映前の spec を対象にしている。

- **範囲**: 新しいコードは R2（ルートの依存の組み替え）と、R1・R3 の検証手順（文書またはスクリプト）がほぼすべて。
  R4 は文書の更新だけ、R5 は R2 の完了待ち。5.3 と 2.3 は既存の方針・コメントで満たされている
- **最大の発見**: ハブは ADR-2 と同じ litellm × openai 3 の衝突を、**`pydantic-ai-slim` の `openai` extra を外す**ことで解いている。
  同じ変更を sandbox の scratch に当てると、litellm 1.103.2 を残したまま pydantic-ai-slim 2.54.0 に解決し、
  3.13 / 3.14 の両方で 314 passed・カバレッジ 98.51%・pyright 0 errors だった。R2.2 の (a) 分離 / (b) 削除の前に、
  この (c) を選択肢に加える価値がある（§5）
- **(c) の残りのリスク**: ルートは Ollama 経路で `OpenAIChatModel` を実際に使う（ハブは使わない）。openai 2.x での実リクエストは
  hermetic テストでは通らないので、plan で実機または respx で確認する（§4.1、§7-1）
- **R1 の注意点**: spec が挙げる 4 つのファイル群だけではハブの `api:check` が成立しない（`evals/`、`.github/workflows/api.yml`、
  `packages/schemas` を読む）。また `test_python_version_pin.py` は 3.14 で設計どおり失敗するので、「all green」の定義が要る（§4.2）
- **順序の見直し**: ルートの 3.14 化（R2.5）はハブの検証（R1）に技術的には依存しない。ルートは 3.14.5 で既に green だった（§4.5）

## 2. 調査の前提（対象コミットと方法）

- **日付**: 2026-10-03
- **sandbox**: ブランチ `claude/repo-update-specs-xctkdv`（`38d3ddc`。`main`@`b4fa915` + spec 014 の追加のみ）
- **ハブ**: ローカルの checkout `/Users/Shared/codes/vaz-agentic-ai-next`。`main`@`afbe6eb`（#78 のマージ）。
  作業ツリーはブランチ `009-agent-ui-and-beta-intake` で、ステージ済みの変更がある。以下の参照はファイルの読み取りだけで、
  ハブへは何も書いていない
- **方法**: Grep / Read による静的な調査に加え、R2 の解決可能性を確かめるために、sandbox の `git archive HEAD` を
  `/tmp/gap014.OgAb` に展開し、`pyproject.toml` だけを書き換えて `uv lock` / `uv sync` / pytest / pyright / ruff を実行した
  （§5 の実測）。sandbox の作業ツリーと `uv.lock` は変更していない

### 2.1 spec の「前提として確認した事実」の再確認

| spec の記述 | 再確認の結果 |
|---|---|
| ルートの `pydantic-ai-slim` は 2.31.1、ハブは 2.54.0 | ✅ 一致（`uv.lock:2103`、ハブ `services/api/uv.lock:2977`）。ルートの `openai` は 2.54.0、`litellm` は 1.103.2 |
| 原因は ADR-2 の `openai<3.0.0` | ✅ 一致（[pyproject.toml](../../pyproject.toml) の `[project.optional-dependencies]` 直前の ADR-2 コメント）。ただし §4.1 のとおり、**ハブは同じ衝突を別の方法で解いている** |
| ハブの 3.14 の証拠は `uv lock` まで | ✅ 一致（[hub-intake-2026-10.md](../../docs/hub-intake-2026-10.md) §2.5） |
| 3.15 はハブの依存一式で解決しない | ✅ 文書上は一致（同 §2.5、[patterns/rate-limit/README.md](../../patterns/rate-limit/README.md) L97-106）。本分析では PyPI を再取得していない |
| L1 はハブに既に存在する | ✅ 一致（ハブ `services/api/app/api/v1/agent.py:19,97-113` に `UsageLimits` と `asyncio.wait_for(..., timeout=settings.chat_request_timeout)`。`_stream.py:7` はイベントごとの `sse_send_timeout`） |
| H1・H2 はハブ #76（`3646b47`）で取り込み済み | ✅ `3646b47` はハブの履歴に存在する（"feat(services/api): replace slowapi with a limits-based rate limiter"） |

## 3. 要件ごとの分類

凡例: ✅ 既存で満たす / 🔧 一部あり（拡張が必要） / 🆕 新規 / 📝 文書の更新だけ

### Requirement 1: ハブの依存一式を 3.14 で検証する

| ID | 分類 | 根拠と不足 |
|---|---|---|
| 1.1 | 🔧 | ハブの checkout はローカルにある。ただし **R1.1 が列挙する 4 つ（`pyproject.toml` / `uv.lock` / `app/` / `tests/`）だけでは `api:check` が成立しない**（§4.2）。`evals/` は ruff・ty の対象で（ハブ `mise.toml:356-357`）、テストは `services/api/` の外も読む（`tests/unit/test_redis_test_gating.py:36` → `.github/workflows/api.yml`、`tests/unit/test_hub_contract_snapshot.py:23` → `packages/schemas/src/generated`） |
| 1.2 | 🆕 | 手順・スクリプトは無い。ハブの `api:check`（`mise.toml:353-361`）は `uv sync` → ruff → `ty check app/ evals/` → pytest（unit + integration + e2e、`--cov=app`）→ `api:audit` の順で、R1.2 の列挙とほぼ一致する。`uv lock` だけが含まれない |
| 1.3 | 🆕 | 警告の一覧は無い。ハブは `filterwarnings = ["error::DeprecationWarning", ...]` で `StarletteDeprecationWarning` も error にしている（ハブ `pyproject.toml:211-`）ので、3.14 の新しい非推奨は**警告ではなくテスト失敗として出る**。一覧は失敗の出所から作ることになる（§4.3） |
| 1.4 | 📝 | 記録先（`docs/hub-intake-2026-10.md` の追記か新文書）は既存。形式の手本は [patterns/rate-limit/README.md](../../patterns/rate-limit/README.md) の「検証記録」（環境・版・コマンド・件数） |
| 1.5 | 🔧 | 「all green」の定義が不足している。ハブの `tests/unit/test_python_version_pin.py:65-78` は**実行中のインタプリタが `.python-version`（3.13）と一致すること**を検証するので、3.14 では設計どおり失敗する（§4.2） |

### Requirement 2: ルートをハブより新しく保つ

| ID | 分類 | 根拠と不足 |
|---|---|---|
| 2.1 | 🆕 | 現状 2.31.1 < 2.54.0。§5 の実測で、`openai` extra を外せば**現行の litellm を残したまま** 2.54.0 に解決する |
| 2.2 | 🔧 | spec は (a) 分離 / (b) 削除の 2 択だが、ハブが採った (c) 「`pydantic-ai-slim` の `openai` extra を外し、`openai<3` を直接宣言する」が成立する（§5）。ADR の選択肢に (c) を加えるかは requirements の見直し事項 |
| 2.3 | ✅ | ADR-2 の撤去条件として既に書かれている（[pyproject.toml](../../pyproject.toml) ADR-2 末尾 "Remove this cap … as soon as litellm ships a release declaring openai>=3"）。(a) を選んだ場合は分離先へ移す |
| 2.4 | ✅（現状） | `mise run check` とカバレッジ 98% は現状 green（314 passed / 4 skipped）。§5 の (c) でも 98.51%・pyright 0 errors・ruff clean を確認 |
| 2.5 | 🔧 | ルートで 3.13 を持つのは `.python-version`、`mise.toml:2,18`、`pyproject.toml`（`[tool.ruff] target-version = "py313"`、`[tool.pyright] pythonVersion = "3.13"`）、`.github/workflows/ci.yml:57`、`.pre-commit-config.yaml:7,61`、`README.md:31,49`、`.sdd/steering/tech.md` §1・§4。**ルートには Python の版を固定するテストも、`ibm-watsonx-ai` の 3.14 import を確認するテストも無い**（`tests/unit` に該当なし）ので、どちらも新規。ADR-1 のコメント（[pyproject.toml](../../pyproject.toml) `ibm-watsonx-ai` の直前）も更新対象 |

### Requirement 3: 3.15 の阻害要因の追跡

| ID | 分類 | 根拠と不足 |
|---|---|---|
| 3.1 | 🆕 | 表は無い。内容は [hub-intake-2026-10.md](../../docs/hub-intake-2026-10.md) §2.5 と [patterns/rate-limit/README.md](../../patterns/rate-limit/README.md) L97-106 に散文で存在する |
| 3.2 | 🆕 | 月次の依存更新に手順書は無い（`chore/dependency-security-refresh` はブランチ名の慣習で、`docs/` にも `.github/` にも定義が無い）。トリガーを置ける場所の候補は §6 |
| 3.3 | 🆕 | R1 の手順を Python 版を引数にして再利用できれば追加の実装はほぼ無い（§6 の選択肢 B） |
| 3.4 | 🔧 | レーンは 3.15 で稼働中（`patterns/rate-limit/.python-version` = `3.15`、`requires-python = ">=3.15"`、CI は `patterns-ci.yml:435-` の専用ジョブ）。ただし記録は 3.15.0rc2 で、正式版での再検証の仕組みは無い。CPython 3.15.0 の公開状況は plan で確認する（§7） |

### Requirement 4: 取り込み候補の状態

| ID | 分類 | 根拠と不足 |
|---|---|---|
| 4.1 | 📝 | 文書の表は H1・H2 を「取り込む（検証済み）」のままで、§4「次の作業」の順 1 も未完了の書き方 |
| 4.2 | 📝 | L1 は「取り込む（要修正）」のまま。引用先は §2.1 で確認済み |
| 4.3 | 🆕（待ち） | ハブ spec 009 R6.5 が報告元。ハブ R6.2（L2 は `corrective_rag.py` / `citation.py` で fail-closed 済み）と R6.4（L4 は `health.py` だけ）は、ハブ spec に結論の見込みまで書かれているので、報告が来れば記録はすぐできる |
| 4.4 | 🔧 | 表には「ハブへ」列（判断）はあるが、「状態」列（未着手／取り込み済み／取り込まない）が無い。列の追加が必要 |

### Requirement 5: pydantic-ai のベータ機能の先行検証

| ID | 分類 | 根拠と不足 |
|---|---|---|
| 5.1 | 🆕 | 先行検証の場所が今は無い。ルートは 2.31.1、`patterns/` の pydantic-ai 系レーン（`frameworks/pydantic-ai`・`sse`・`hitl`・`deep-research`）も**全部 2.52.0 でハブ（2.54.0）より古い**。R5 は R2 の完了（またはレーンの更新）に依存する |
| 5.2 | 📝 | 記録先は R1 と同じ文書。形式（版・影響するハブのファイル・推奨）は新規 |
| 5.3 | ✅ | [README.md:18](../../README.md#L18)（"frozen for comparison only"）と `.sdd/steering/tech.md` §12「比較レーンは凍結」で既に方針化されている |

## 4. 統合上の課題

### 4.1 ハブは ADR-2 と同じ衝突を「`openai` extra を外す」ことで解いている

ハブ `services/api/pyproject.toml:35-49` のコメントによると、ハブも litellm（`pydantic-ai-litellm` 経由）を使っており、
pydantic-ai-slim 2.32.0 の `openai` extra が `openai>=3.0.0` を要求する同じ衝突に当たった。ハブは
`pydantic-ai-slim[logfire]>=2.52.0` と **`openai` extra を外し**、litellm 自身が要求する `openai<3.0.0,>=2.20.0` に
`pydantic_ai.models.openai` の import を任せた。結果、ハブの lock は pydantic-ai-slim 2.54.0 + openai 2.54.0 + litellm 1.103.2。

sandbox の ADR-2 は「cap を外すには litellm の openai 3 対応を待つしかない」という前提で書かれているが、
この前提はハブの実例と §5 の実測で崩れている。R2.2 が (a)/(b) の 2 択を前提にしている点は、requirements の段階で見直す価値がある。

**ただし、ハブと sandbox では `openai` の使い方が違う。** ハブは「モデルとは常に litellm 経由で話し、pydantic-ai の
OpenAI provider を直接は使わない」（同コメント）。sandbox のルートは Ollama 経路で `OpenAIChatModel` + `OllamaProvider` を
**実際に使う**（[llm/providers/ollama.py](../../src/pydantic_ai_sandbox/llm/providers/ollama.py)）。pydantic-ai-slim 2.32 以降が
`openai>=3` を要求した理由が「openai 3 の API を実行時に使う」ことなら、import とモデル構築は通っても、
リクエスト時に壊れる可能性がある。hermetic な unit テストは `TestModel` / `FunctionModel` で実 provider を通らないので、
この経路は §5 の実測でも検証できていない（§7 の調査項目 1）。

### 4.2 R1.1 の scratch の範囲と「green」の定義

- **範囲**: `api:check` は `services/api/` の外にも依存する（§3 R1.1）。ハブのコミットを丸ごと scratch に展開する
  （`git -C <hub> archive <sha> | tar -x -C <scratch>`、または `git worktree add <scratch> <sha>`）方が、4 つを選んで取り出すより
  再現性が高い。`git worktree` はハブ側の `.git` にエントリを作るので、「ハブへは書かない」を厳密にとるなら `git archive` が安全
- **想定内の失敗**: `test_python_version_pin.py` の 3 件のうち `test_running_interpreter_matches_the_pin` は 3.14 で必ず失敗する。
  scratch 側でハブ spec 009 R7.2 の差分（`.python-version`、`_EXPECTED_SERIES`、Ruff `target-version`）を当ててから実行するか、
  当てずに「この 1 件は想定内」と記録するかを R1.5 で決める必要がある。前者のほうが、ハブ R7 の PR をそのまま予行できる
- **外部サービス**: ハブの integration / e2e が Redis・chroma のモデル取得を要求するかは、マーカー（`-m redis`、`chroma`）で
  既定では外れる設計に見える（`api:test:ci` の説明 "TestModel/FunctionModel only, no live LLM/Ollama"）が、
  R1.2 の「unit + integration + e2e」が既定のスキップを含むことを記録に明記する必要がある

### 4.3 3.14 の非推奨はテスト失敗として現れる

ハブは `error::DeprecationWarning` と `error::starlette.exceptions.StarletteDeprecationWarning` を設定しているため、
R1.3 の「新たに出る非推奨警告の一覧」は警告集計ではなく**失敗の原因分類**から作ることになる。参考として、
sandbox のルートを 3.14.5 で実行したときに出た警告は次のとおり（ハブにも同じパッケージがある）。

| 出所 | 警告 | 備考 |
|---|---|---|
| `ibm_watsonx_ai`（1.8.0）`fine_tuner.py:348` / `prompt_tuner.py:323` | `SyntaxWarning: 'return' in a 'finally' block` | PEP 765。import 時のコンパイルで出る。ハブは watsonx を使わないので無関係 |
| `pydantic/_internal/_generate_schema.py:1480` | `UserWarning`（`ChatCompletionReasoningItem` の `ReadOnly`） | openai SDK の型を pydantic がスキーマ化するとき |
| `asyncio/base_events.py:758` | `ResourceWarning: unclosed event loop` | テスト側の後始末 |
| `pydantic_graph/_utils.py:67`（3.13 でも出る） | `DeprecationWarning: There is no current event loop` | `asyncio.get_event_loop()`。ハブの `error::DeprecationWarning` 下で 3.14 の挙動が変わるかは R1 で確認する |

[hub-intake-2026-10.md](../../docs/hub-intake-2026-10.md) §2.3 の罠 2（`TestClient` の `StarletteDeprecationWarning`）は Python 版に
依存しない（starlette 1.7 の挙動）。ハブのテストの 29 ファイルが `TestClient` を使っている（`grep -rl TestClient services/api/tests`、
2026-10-03）ので、ハブが既に対処済みか（`filterwarnings` の `ignore::DeprecationWarning:starlette.testclient` の言及がある）を
R1 の記録で確認する。罠 3（redis-py の `asyncio.iscoroutinefunction`）は 3.14 で非推奨、3.16 で削除なので、3.14 で初めて
`DeprecationWarning` が出得る。ただし `limits` が該当経路を通らない限り発火しない。

### 4.4 R2 と R5 の順序

R5（ハブより先に新機能を試す）は、試す側がハブより新しい版を持っていないと成立しない。現状はルート（2.31.1）も
`patterns/` の pydantic-ai 系 4 レーン（2.52.0）もハブ（2.54.0）より古い。R2 の完了が R5 の前提になる。
レーン側を先に上げる（`uv lock --upgrade-package pydantic-ai-slim`）だけなら R2 を待たずに R5 の場所を作れる。

### 4.5 R2.5 の「R1 の後」という順序の根拠

R2.5 はルートの 3.14 化を「R1（ハブの 3.14 検証）が green になった後」としている。ルートとハブは依存一式が違う
（ルートには chromadb / torch / onnxruntime が無い）ので、技術的にはルートの 3.14 化は R1 に依存しない。
§5 の実測では、ルートは 3.14.5 + pydantic-ai-slim 2.54.0 で 314 passed / 4 skipped、`ibm-watsonx-ai` 1.8.0 の
`ModelInference` も import できた。順序を R1 の後に置く理由が「ベータレーンがハブより先に 3.14 へ行くべき」という方針なら、
むしろ逆順（ルートを先に 3.14 化）が R2.1 の趣旨に合う。requirements の見直し事項として挙げる。

## 5. R2 の実装方式の選択肢

### 5.1 実測（2026-10-03、scratch `/tmp/gap014.OgAb`）

sandbox `HEAD` を `git archive` で展開し、`pyproject.toml` の
`"pydantic-ai-slim[logfire,openai]>=2.31.1"` を `"pydantic-ai-slim[logfire]>=2.54.0"` + `"openai>=2.20.0,<3.0.0"` に置き換えた。
dev グループの `litellm` / `openai<3.0.0` と extra の `litellm` はそのまま。
（Note, 2026-10-04: この実測時点の `openai>=2.20.0,<3.0.0` と bare `litellm` は、task 2.2 実装中・および
その 2nd-pass VDD review を経て、それぞれ `openai>=2.47.0,<3.0.0`（httpx2 transport 対応下限）、
`litellm>=1.96.2`（PYSEC-2026-4066 の fix 版）へ訂正済み。この §5.1 自体は 2026-10-03 時点の実測記録として
そのまま残し、現行値は `pyproject.toml` ADR-2 と `research.md` AD-2 amendment を正本とする。）

| 手順 | 結果 |
|---|---|
| `uv lock` | 解決。pydantic-ai-slim **2.54.0**、openai 2.54.0、litellm **1.103.2**（1.83.0 への巻き戻りなし） |
| `uv sync` → `uv run pytest --cov`（3.13） | 314 passed / 4 skipped、カバレッジ 98.51%（変更前のルートと同数） |
| `uv run pyright`（3.13、strict） | 0 errors / 0 warnings |
| `uv run ruff check .` | clean |
| `uv sync --python 3.14` → pytest（3.14.5） | 314 passed / 4 skipped |
| `ibm_watsonx_ai.foundation_models.ModelInference` の import（3.14.5） | 成功（1.8.0。ADR-1 の 1.5.12 の不具合は再現しない） |

未検証: pip-audit、pyright の `pythonVersion = "3.14"`、Ollama 経路の実リクエスト（§4.1）、`mise run test:integration`。

### 5.2 選択肢

| | (a) litellm 経路を独立 uv プロジェクトへ分離 | (b) litellm 経路を削除 | (c) `openai` extra を外し `openai<3` を直接宣言（ハブ方式） | (d) uv の `conflicts` で litellm を別解決にする |
|---|---|---|---|---|
| 内容 | `llm/providers/litellm.py`（303 行）と、名前に litellm を含むテスト 7 本（litellm を参照するテストは unit・integration で計 13 本）を `patterns/` 型の独立プロジェクトへ移し、ルートから `openai<3.0.0` を外す | `WATSONX_TRANSPORT=litellm`、`LiteLLMModel`、関連テスト、`config.py` の `Literal["sdk","litellm"]` を削除 | §5.1 のとおり。`pyproject.toml` の数行の変更と ADR-2 の書き換え | `[tool.uv] conflicts` で `litellm` extra と（新設する）litellm 用 dev グループを既定と排他にし、lock を分岐させる |
| R2.1 | ✅ | ✅ | ✅（実測済み） | ✅（既定側）。litellm 側は 2.31 系のまま |
| openai の版 | ルートは 3.x | 3.x | **2.x のまま** | 既定側 3.x、litellm 側 2.x |
| 結合の問題 | `_openai_mapping.py`（354 行）は SDK 経路と litellm 経路の**共有**（`watsonx.py:51`、`litellm.py:74`）。分離先へ複製するか、共有パッケージ化（`patterns/contracts` 型）が必要。`watsonx.py::_build_litellm`（L370-）はルート側の分岐なので、分離後の呼び出し方を決める必要がある | spec 003（watsonx 二系統トランスポート）の要件を取り消すことになる。steering tech.md §3 の記述も削除 | 小さい。Ollama 経路の `OpenAIChatModel` が openai 2.x で正しく動くかが唯一のリスク | `mise run check` が 2 回の sync（既定 + litellm）を要する。`test_litellm_*` を別ジョブに分ける CI 変更 |
| ADR-2 の「1.83.0 へ巻き戻らない」 | 分離先で同じ cap を維持 | 不要になる | そのまま維持（litellm 1.103.2 を確認） | litellm 側で維持 |
| コスト | 高（プロジェクト新設、mise・CI・security.yml・dependabot の配線、カバレッジの分割） | 中（削除だけだが spec 003 との整合と、カバレッジ 98% の再計算） | 低 | 中（uv の機能依存、CI 変更） |
| リスク | 共有コードの重複 | 機能の喪失 | 実行時の互換性（未検証）。pydantic-ai が今後 openai 3 の API を必須にすると再び詰まる | uv の conflicts の挙動に依存。ルートの「1 プロジェクト 1 lock」の単純さを失う |
| 将来 litellm が openai 3 に対応したとき | 分離を戻すか検討（R2.3） | 影響なし | `openai` extra を戻し、直接宣言を外すだけ | conflicts を外すだけ |

**所見**（決定ではない）: (c) は実測で R2.1・R2.4 を満たし、変更量も最小で、ハブと同じ構成になる（ハブの版上げの証拠として
扱いやすい）。残るリスクは §4.1 の実行時互換性だけで、これは Ollama の実機テスト（`mise run test:integration`）か、
respx で OpenAI 互換エンドポイントを模したリクエスト経路のテストで確認できる。(a) は spec の既定だが、`_openai_mapping.py` の
共有という結合を解く設計が要る。(c) で不十分と分かった場合の次善として (a) を残すのが妥当に見える。

## 6. 全体の進め方の選択肢

R1・R3.3 の「ハブの依存一式を特定の Python で検証する」作業を、どう再利用可能にするか。

| | A. 手作業の手順を文書に残す | B. スクリプト化（`scripts/` + `mise` タスク） | C. CI ワークフロー（`workflow_dispatch`） |
|---|---|---|---|
| 内容 | intake 文書にコマンド列を書き、毎回手で実行する | `mise run hub:verify -- <hub-sha> <python>` のようなタスクが scratch 展開 → `uv lock` → `api:check` 相当 → 記録の雛形出力を行う | B を GitHub Actions で実行し、ハブを `actions/checkout`（別リポジトリ）で取得する |
| 既存との対称性 | `hub-intake-2026-10.md` §2・rate-limit README の記録方式と同じ | `scripts/pre-push-ollama.sh` + `test:integration:pre-push` の「スクリプトを mise が包む」型と同じ | 実機系は `workflow_dispatch` のみという既存の CI 方針（`integration-*.yml`）と合う |
| R3.3 への再利用 | 手順の再読が必要 | 引数を変えるだけ | 入力を変えるだけ |
| コスト | 低 | 中（スクリプトのテストをどこまで書くか。ルートのカバレッジは `src/` のみ計測なので `scripts/` は対象外） | 高（ハブは別リポジトリで、private なら PAT / deploy key が要る。CLAUDE.md の CI 方針への追加） |
| リスク | 手順のずれ（版・コマンドの書き忘れ） | ハブの `mise.toml` のタスク定義と二重管理になる（ハブの `api:check` を変えたとき追随が要る） | 秘密情報の扱い。外部リポジトリの取得を CI に加えるセキュリティ上の判断（spec 013） |

**所見**: R1 は「1 回の証拠」が目的なので A で足りる。R3.3（3.15 の再実行）と R3.2（月次の再確認）まで見ると B が効く。
B を採る場合も、ハブの `api:check` を**呼び出す**形（scratch 上で `mise run api:check`、またはハブの `mise.toml` の `run` 配列を
そのまま実行）にして、コマンド列を sandbox 側で複製しないほうが二重管理を避けられる。C は R1 の範囲を超える。

R3.2（月次の再確認）のトリガー候補: (1) intake 文書または `docs/` の依存更新チェックリストに 1 行足す、
(2) `security.yml` の日次 pip-audit と同じワークフローに cp315 wheel の有無を調べるジョブを足す（PyPI の JSON API で
`onnxruntime` / `torch` / `pydantic-core` の最新版の `cp315` タグを確認）。(2) は機械的だが、外部 API への依存と誤検知の扱いが増える。

## 7. plan フェーズで調べること

1. **pydantic-ai-slim 2.54 の `OpenAIChatModel` は openai 2.x で実行時に動くか**（R2 / §4.1）。2.32.0 で `openai` extra の下限を
   3.0.0 に上げた理由（changelog / PR）を確認し、openai 3 専用の API を Chat Completions 経路で使っているかを調べる。
   検証手段は `mise run test:integration`（Ollama 実機）か、respx で `/v1/chat/completions` を模したリクエスト経路の unit テスト
2. **ADR-2 の書き換え範囲**: (c) を採る場合、ADR-2 のコメントの「cap を外すには litellm の対応待ち」という結論と、
   `pydantic-ai-slim` の下限（`>=2.31.1`）の理由付けを書き直す。dev グループの `openai<3.0.0` の再掲も残すか
3. ~~requirements の見直し~~ → **spec.md に反映済み（2026-10-03）**: R2.2 に (c) を既定として追加（条件付き、次善は (a)）、R2.5 を R1 から独立させた。あわせて R1.1（ハブのコミットを丸ごと展開）、R1.2（スキップ件数）、R1.3（失敗から一覧化）、R1.5（版固定の差分を当てて判定）、R2.4（pip-audit）、R3.4（3.15.0 正式版）、R5.1（試す場所の版）を修正
   （**Correction, 2026-10-04**: この「spec.md に反映済み（2026-10-03）」という記述は誤り——VDD review
   （`pdca/do.md` 該当日エントリ）が独立に再検証し、2026-10-03 時点の `spec.md` R2.2 は option (a)/(b) のみを
   列挙し既定は (a) のままだったことを確認した。option (c) は当時 plan.md/research.md/tasks.md にのみ存在し、
   spec.md には存在しなかった。spec.md の R2.2 が実際に option (c) を既定として反映したのは、本 feature の
   task 2.2 実装フェーズ、2026-10-04 である。この §7 の記述はその時点の意図（見直し事項として挙げた）の記録
   として残すが、「反映済み」の日付は参照しないこと。）
4. **R1.1 の scratch の取り方**: `git archive` と `git worktree` のどちらにするか。ハブの checkout がステージ済みの変更を持つので、
   検証するのは**ハブの `main` のコミット**（2026-10-03 時点 `afbe6eb`）であって作業ツリーではないことを手順に明記する（§4.2）
5. **R1.5 の「green」の定義**: `test_python_version_pin.py` の扱い（ハブ R7.2 の差分を scratch に当てるか）。integration / e2e の
   既定スキップ（Redis・chroma・Ollama）を件数として記録する形式
6. **ハブの `api:audit` の ignore リスト**（chromadb 3 件・nltk 1 件）が 3.14 の解決で変わるか
7. **CPython 3.15.0 の公開状況**（R3.4）。手元の uv のメタデータは 3.15.0rc2 まで（`uv python list 3.15`）。正式版が出ていれば
   rate-limit レーンの記録を更新する
8. **`patterns/` の pydantic-ai 系 4 レーンの 2.54 への更新**（R5 の場所づくり、§4.4）。frozen 契約と drift テストへの影響は無いはずだが、
   R5 の範囲に入れるか、通常の月次更新に任せるか
9. **pip-audit**: §5 の (c) の lock で `uv run pip-audit` を実行していない。ルートの `security.yml` の audit ジョブ相当で確認する
