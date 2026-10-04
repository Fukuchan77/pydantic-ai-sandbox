# 014-hub-python-beta-lane — Discovery & Research Log

## Discovery type

**Extension (light discovery)**。既存のルート依存管理、独立 uv レーン、`mise` 品質ゲート、
ハブ intake 文書を拡張する。新しい production subsystem や runtime dependency は導入しないが、
ハブ全体の scratch 検証、ルート Python 3.14 化、依存衝突の解消、3.15 blocker 追跡が横断するため、
外部互換性と既存ゲート面を追加調査した（確認日: 2026-10-03）。

## Investigations

### I-1: ハブ検証の実体はリポジトリ全体の commit archive

- **Question**: `services/api/` だけを複製して Python 3.14 を検証できるか。
- **Findings**: できない。ハブの `api:check` は `evals/` を検査し、テストは
  `.github/workflows/api.yml` と `packages/schemas/src/generated` を読む。対象は作業ツリーではなく
  特定 commit の `git archive` とし、scratch 以外へ書き込まない。ハブ側の品質定義を複製せず、
  scratch 内でハブ自身の `mise run api:check` を呼ぶ（audit は同 task が `api:audit` へ委譲）。
- **Evidence**: `spec.md:43-58`; `gap-analysis.md:45-53`;
  `/Users/Shared/codes/vaz-agentic-ai-next/mise.toml:193-238,328-362`。

### I-2: ハブの Python 3.14 判定には移行差分が必要

- **Question**: Python 3.14 でコマンドを実行するだけで「all green」になるか。
- **Findings**: ならない。ハブの interpreter pin test は 3.13 を正しく固定しているため、scratch に
  spec 009 R7.2 相当の `services/api/.python-version`、期待 series、Ruff target の差分を当てた後に判定する。
  元 commit と適用差分は evidence に併記する。
- **Evidence**: `spec.md:55-58`; hub `specs/009-agent-ui-and-beta-intake/tasks.md:191-208`。

### I-3: ルート依存衝突の最小解は `openai` extra の分離

- **Question**: `litellm` を安全な最新版に保ったまま `pydantic-ai-slim` をハブ以上へ上げられるか。
- **Findings**: scratch 実測では、`pydantic-ai-slim` の `openai` extra を外し、
  `openai>=2.20.0,<3.0.0` を直接宣言すると、`litellm 1.103.2` のまま
  `pydantic-ai-slim 2.54.0` に解決し、Python 3.13/3.14 の既存 suite が green になった。
  追加の隔離実測では `pydantic-ai-slim 2.54.0` + `openai 2.54.0` の
  `OllamaProvider → OpenAIChatModel → Agent.run()` が模擬 `/v1/chat/completions` へ POST し、
  通常応答と timeout 指定を処理した。ただし 2.54.0 の公式 `openai` extra は `openai>=3.19.0` であり、
  この組合せは upstream の公式サポート範囲外である。従って request-path 回帰テストを継続保守し、
  lock された OpenAI SDK 版を evidence に残す必要がある。
- **Note (2026-10-04, task 2.2 第 2 回 VDD review 対応)**: 上記 `openai>=2.20.0,<3.0.0` の
  下限は訂正済み（`>=2.47.0,<3.0.0`、httpx2 transport 対応下限）。AD-2 下の
  Amendment ブロックに訂正の全文と、`litellm` 側に独立 floor（`>=1.96.2`）が
  必要と判明した理由を記録する。
- **Evidence**: `gap-analysis.md:157-190`; `pyproject.toml:18-60`;
  `src/pydantic_ai_sandbox/llm/providers/ollama.py:45-84`;
  `https://pypi.org/pypi/pydantic-ai-slim/2.54.0/json`;
  `https://github.com/pydantic/pydantic-ai/releases/tag/v2.32.0`;
  `https://github.com/pydantic/pydantic-ai/pull/7351`。

### I-4: Python 3.14 設定は複数面へ分散している

- **Question**: ルート baseline の更新対象はどこか。
- **Findings**: `.python-version`、`mise.toml`、`pyproject.toml` の `requires-python` / Ruff /
  Pyright、`.github/workflows/ci.yml`、`.pre-commit-config.yaml`、README、ADR-1 コメントへ分散する。
  interpreter と設定値の同期、および Watsonx `ModelInference` import を unit test で固定する。
- **Evidence**: `.python-version:1`; `mise.toml:1-18`; `pyproject.toml:6-16,87-89,147-155`;
  `.pre-commit-config.yaml:1-8,60-67`; `.github/workflows/ci.yml:57-67`; `README.md:26-58`。

### I-5: Python 3.15 は 2026-10-03 時点で正式版未公開

- **Question**: rate-limit レーンを 3.15.0 正式版へ更新できるか。
- **Findings**: できない。Python 3.15.0rc3 が 2026-10-02 に公開され、公式 release page は
  3.15.0 final を 2026-10-07 予定としている。従って本 feature では rc2 記録を rc3 実測へ更新し、
  正式版対応は公開後の同じ契約で行う。
- **Evidence**: `https://www.python.org/downloads/release/python-3150rc3/`;
  `patterns/rate-limit/README.md:82-90`。

### I-6: cp315 blocker は固定事実ではなく月次 evidence

- **Question**: `onnxruntime`、`torch`、`pydantic-core` の状態をどう管理するか。
- **Findings**: ハブ lock の `onnxruntime 1.30.0` と `torch 2.14.1` は cp315 wheel も sdist もなく
  hard blocker。`pydantic-core 2.46.5` は cp315 wheel がなく sdist build になるが、2.49.0 には
  cp315 wheel がある。従って「最新版」ではなく**ハブが実際に lock する版**の file tag を判定する。
  CI の security workflow に外部 PyPI polling job を混ぜず、intake の単一表へ package、locked version、
  必要 tag、確認日、状態、根拠 URL を記録する。月次 dependency refresh では表の全行を再確認する。
- **Evidence**: `spec.md:83-90`; `gap-analysis.md:208-210`;
  `tests/unit/test_ci_usage_policy.py:137-150`;
  `https://pypi.org/pypi/onnxruntime/1.30.0/json`;
  `https://pypi.org/pypi/torch/2.14.1/json`;
  `https://pypi.org/pypi/pydantic-core/2.46.5/json`;
  `https://pypi.org/pypi/pydantic-core/2.49.0/json`。

### I-7: beta feature の実験場所は更新後のルートで足りる

- **Question**: pydantic-ai 系 4 レーンを同時に 2.54 以上へ上げる必要があるか。
- **Findings**: Requirement 2 完了後のルートがハブ以上になるため、Requirement 5 の先行検証場所を
  確保できる。4 レーンの lock/CI/audit を同時更新する価値はなく、BeeAI/LlamaIndex の凍結境界も
  維持する。個別レーン固有機能を試す時だけ別 feature で更新する。
- **Evidence**: `spec.md:99-109`; `patterns/frameworks/pydantic-ai/pyproject.toml:20-25`;
  `patterns/sse/pyproject.toml:52-55`; `patterns/hitl/pyproject.toml:26-29`;
  `patterns/deep-research/pyproject.toml:33-35`; `README.md:16-18`。


## Existing patterns to reuse

| Pattern | Location | Why reuse |
|---|---|---|
| `scripts/` + `mise` wrapper | `scripts/pre-push-ollama.sh`, `mise.toml:85-88` | shell の複雑さを task 名で隠蔽し、実行入口を一つにする |
| commit archive scratch | `gap-analysis.md:21-28` | user worktree を汚さず、検証対象 SHA を再現可能にする |
| upstream gate delegation | hub `mise.toml` の `api:check`（`api:audit` を内包） | sandbox 側で ruff/ty/pytest/audit の定義を複製しない |
| dated evidence section | `patterns/rate-limit/README.md:82-106`, `docs/hub-intake-2026-10.md` | commit、版、コマンド、件数、警告、判断を同じ形式で残す |
| rules-as-tests | `tests/unit/test_ci_usage_policy.py`, `test_no_hardcoded_model_ids.py` | Python pin と依存契約の文章ドリフトを機械検知する |
| independent uv lane | `patterns/*/{.python-version,pyproject.toml,uv.lock}` | option (c) 失敗時の option (a) に限って再利用する |
| manual-only integration workflow | `.github/workflows/integration-ollama.yml` | live Ollama は optional evidence とし、hermetic root gate を壊さない |

## External dependencies

新規 dependency は追加しない。既存 dependency の宣言と解決を変更する。

| Dependency / tool | Target | Purpose | Verified |
|---|---|---|---|
| CPython | root 3.14; rate-limit 3.15 prerelease | beta baseline / 3.15 smoke | root scratch 3.14 green; 3.15 rc3 は正式版延期を確認 |
| `pydantic-ai-slim` | hub 以上（計画時 2.54.0） | beta API と Ollama model integration | dependency resolve と既存 suite は green; HTTP path test は実装フェーズの採用ゲート |
| `openai` | `>=2.47.0,<3.0.0`（実測 2.54.0。当初 `>=2.20.0` としたが httpx2 transport 対応下限不足で訂正、AD-2 amendment 1 参照） | Ollama-compatible client + litellm coexistence | 2.54.0 request path は確認、upstream 公式範囲外 |
| `litellm` | `>=1.96.2`（PYSEC-2026-4066 の fix 版。`openai` 下限単独では vulnerable 1.83.0 への rollback を拒否できないため独立 floor が必要、AD-2 amendment 2 参照） | optional Watsonx transport | 1.96.2・現行 lock 1.103.2 とも pip-audit clean を確認（2026-10-04） |
| `ibm-watsonx-ai` | 現行 floor を維持 | Python 3.14 import contract | import test を実装フェーズで固定 |
| `uv`, `mise` | 既存宣言 | reproducible lock/sync/gates | repository と hub の既存 task を再利用 |

一次資料: Pydantic AI / LiteLLM の package metadata、Python.org release pages、PyPI JSON API、
hub `services/api/uv.lock`。版は implementation 時の lock 結果を正本とし、この表の数値へ固定しない。

## Architecture decisions

### AD-1: ハブ検証は local scratch runner と upstream gate delegation

- **Context**: R1 は再現可能である必要があり、R3.3 でも 3.15 に差し替えて再実行する。一方、
  private/別 repository checkout を CI に持ち込むと credential と外部状態が増える。
- **Decision**: `scripts/verify-hub-python.sh` を `mise run hub:verify -- ...` で包む。
  local hub path、commit、Python series、output directory を明示引数にし、`git archive` した scratch へ
  migration patch を当て、hub の `api:check` を呼ぶ（同 task が `api:audit` を内包）。CI workflow は追加しない。
- **Alternatives**: 手順書だけは再実行時の drift が大きい。GitHub Actions は secret と cost policy を増やす。
- **Consequences**: script の引数検証、scratch cleanup、source/hub 非書き込みを contract test で固定する。

### AD-2: 依存衝突は option (c) を compatibility test 条件で採用

- **Context**: `pydantic-ai-slim[openai]` と litellm の OpenAI SDK range が交差しない。
- **Decision**: `openai` extra を外し、`pydantic-ai-slim[logfire]>=2.54.0`（target hub commit が更新された場合はその lock 版以上） と
  `openai>=2.20.0,<3.0.0` を root runtime dependency として直接宣言する。respx による
  OpenAI-compatible Chat Completions request-path test が、実際に lock された SDK 版で green であることを
  採用条件とする。公式サポート外であることを ADR に明記し、live Ollama は追加 evidence とする。
- **Alternatives**: option (a) の独立 lane は compatibility test が失敗した時だけ使う。option (b) の
  transport 削除は既存 capability を失うため採らない。
- **Consequences**: ADR-2 は「pydantic-ai を古く保つ」から「SDK extra を分離し、安全な litellm を保つ」へ更新する。
  litellm が OpenAI 3 を宣言した時の撤去条件は残す。

- **Amendment (2026-10-04, task 2.2 実装後、独立 VDD review を契機に追記)**:
  - **httpx2 既定 transport の発見と openai 下限の訂正**: `pydantic-ai-slim>=2.54.0` の
    `OpenAICompatibleProvider._get_http_client()` は、呼び出し側が `http_client=` を渡さない場合に
    `httpx2.AsyncClient`（legacy `httpx` とは別の、ecosystem 移行期に共存する独立パッケージ）を既定で
    構築する。root の `OllamaProvider` 構築はこれを渡さないため、常に httpx2 を使う。openai SDK が
    `httpx2.AsyncClient` を `http_client=` として受理できるのは `openai>=2.47.0`（2.46.0 以前は
    `openai._httpx2` モジュール自体が無く、provider 構築時に `TypeError` を raise — 連番 venv install で実測確認）
    であるため、当初の `openai>=2.20.0,<3.0.0` 下限は不十分だった。下限を `>=2.47.0,<3.0.0` へ訂正し、
    実行可能契約（`tests/unit/test_ollama_openai_compat.py`）に `test_installed_openai_sdk_meets_httpx2_transport_floor`
    を追加した（pyproject.toml ADR-2 に詳細）。
  - **respx → `httpx2.MockTransport` への mocking 機構変更は本 AD の設計を変えない**:
    上記 httpx2 既定 transport の発見により、当初計画していた respx ベースの request-path test は
    実際には一度も意図通り動いていなかった（respx は legacy `httpx` しか patch できず、httpx2 経由の
    request を素通りさせる）。これは `research.md` の「Risks & open questions」に記した stop rule
    （compatibility test が failing なら plan amendment で option (a) へ）が想定した「openai SDK が
    pydantic-ai-slim の lock 版と動かない」という事態ではなく、*test 側の mock 機構が対象の HTTP stack を
    捉えていなかった* という、テスト実装の不備である。検証対象の性質（レスポンス透過・request body・
    `ModelSettings.timeout` 転送）は変わらず、mock 機構を httpx2 自身の `MockTransport`
    （`httpx.MockTransport` の httpx2 版、追加依存不要）に差し替えただけで全て green になった。
    よって stop rule は発火条件（SDK バージョン組み合わせの実行不能）に該当せず、plan amendment は不要と
    判断する。この判断自体を本追記として記録する。

- **Amendment 2 (2026-10-04, task 2.2 第 2 回 VDD review を契機に追記)**:
  - **`openai` 下限単独では litellm rollback を拒否できないと判明**: 上記 amendment で `openai` 下限を
    `>=2.47.0,<3.0.0` へ訂正したが、これは `litellm` の脆弱な巻き戻りを防ぐ目的の防御として機能しない。
    litellm 1.83.0 の宣言は `requires-python<4.0,>=3.9`（この project の 3.14 floor を排除しない）、
    `openai>=2.8.0`（上限なし——upstream 側の記載漏れ）であり、訂正後の range 内でも trivially 満たされる。
    pip-audit（2026-10-04、scratch venv）で 1.83.0 が 14 件の既知脆弱性
    （PYSEC-2026-388/391/2598/2599/2600/2601/2602/3476/3477/3479/3861/4066/4067/4070）を持つことを確認した
    （独立 2nd-pass VDD review の指摘と一致）。
  - **訂正（2026-10-04, task 2.2 第 3 回 VDD review を契機に再訂正）**: 直前の記述（本 Amendment 初版）は
    「reviewer が例示した `litellm 1.85.0` は PyPI 上に存在せず、reviewer の誤りだった」としていたが、これは
    *この記録自体の誤り* だったと判明したため訂正する。独立に再現したところ、`litellm 1.85.0` は PyPI の
    simple index（`https://pypi.org/simple/litellm/`）に yank されずに実在する——`uv lock`／
    `uv pip install --dry-run` のいずれも `litellm==1.85.0`（および `1.84.0`）を明示指定すれば解決・install
    対象として受理する（scratch repro, 2026-10-04）。先に「存在しない」と結論した根拠（
    `pip install litellm==1.85.0` の失敗、および `pip index versions litellm` の出力が `1.83.7` から
    `1.93.0` へ直接飛ぶように見えたこと）は、どちらも *この project を Python 3.14 で実行した pip 自身が
    `requires-python>=3.10,<3.14` と宣言するバージョンを「対象外」としてリストから除外する*
    という、実行環境依存のフィルタリングの副作用であって、PyPI 上の非存在を意味しない
    （`pip-audit` の `Ignored the following versions that require a different python version:` 出力に
    `1.85.0 Requires-Python >=3.10,<3.14` が明示的に列挙されているのが直接の証拠）。reviewer の指摘は
    正しく、本記録の以前の版が誤っていた。
  - **1.84.0〜1.92.x は「除外されている」のではなく「range 解決では到達しない」**: この中間系列
    （`PYSEC-2026-4066` の fix progression を一部含むが完全ではない）は `requires-python<3.14` を宣言するため、
    *この project の実際の依存グラフでの範囲（`>=`）解決* ではこの project の 3.14 floor から選ばれることは
    ない——実際、`litellm` floor を外した状態で project 全体の scratch copy を `uv lock` した再現では、
    bare `"litellm"` が直接 `1.103.2`（最新に近い clean 版）へ解決され、1.84.0〜1.92.x 系列には一度も
    触れなかった（2026-10-04 確認）。しかし *明示的な exact pin*（`litellm==1.84.0` のような手動指定や、
    手で編集された lockfile）であれば `uv` はこの requires-python 不一致を無視して受理する——これは
    `tests/unit/test_litellm_dependency_floor.py` の `test_installed_litellm_meets_vulnerability_floor` が
    「lock drift / 手動編集された lockfile」への defense-in-depth として既に想定していたまさにそのシナリオで
    あり、この floor test の存在理由を変えるものではない。
  - **採用した fix**: `litellm` の独立した version floor を明示的に宣言する——
    `litellm>=1.96.2`（14 件の脆弱性のうち最も fix が遅かった `PYSEC-2026-4066` の、litellm の並行
    maintenance branch 群における最早 fix 版。pip-audit で `1.96.2`・現行 lock の `1.103.2` 共に
    clean と確認済み、2026-10-04）。`pyproject.toml` の `[project.optional-dependencies] litellm` と
    `[dependency-groups] dev` の両方に反映し、`tests/unit/test_litellm_dependency_floor.py` で
    manifest 宣言と installed 版の両方を contract 化した。

### AD-3: ルート Python 3.14 化はハブ evidence と独立して同 feature で行う

- **Context**: root closure には hub の ML wheel blocker がない。
- **Decision**: root の runtime/tooling/docs pin を 3.14 に同期し、interpreter/config consistency と
  Watsonx import を unit test で固定する。
- **Alternatives**: R1 後まで待つ順序には技術的依存がなく、beta lane が hub より先に進む目的に反する。
- **Consequences**: root gate、coverage、audit を 3.14 で再取得してから baseline を完了扱いにする。

### AD-4: blocker と intake 状態は単一 evidence ledger に集約

- **Context**: wheel 状態と hub intake 状態は時間で変わる。
- **Decision**: `docs/hub-intake-2026-10.md` に dated verification section、cp315 blocker table、
  H/L status table、beta-feature experiment template を置く。月次 refresh は表の確認日と evidence URL を更新する。
- **Alternatives**: security CI の PyPI polling は既存 scan-only policy と誤検知処理を増やすため採らない。
- **Consequences**: R3.2 は自動 gate ではなく、各 refresh commit に残る manual review evidence で統治する。

### AD-5: Requirement 5 の実験場所は更新済み root に限定

- **Context**: 4 pattern lane の一括更新は lock/CI/audit の変更量を増やす。
- **Decision**: 本 feature では root を hub 以上へ更新し、BeeAI/LlamaIndex および pydantic-ai 系 4 lane の
  dependency floor は変更しない。lane 固有 API の検証は別 spec とする。
- **Consequences**: frozen comparison lane の境界を維持し、R5 の最低限の実験場所だけ確保する。

### AD-6: rate-limit は現時点の 3.15 prerelease を再検証

- **Context**: 2026-10-03 時点で 3.15.0 final は延期され、rc3 が最新公開版。
- **Decision**: `patterns/rate-limit` を 3.15 series のまま rc3 で gate 実測し README 記録を更新する。
  final 公開後は同じ lane contract を再実行する。
- **Consequences**: 「正式版検証済み」とは記録せず、公開状態を正確に区別する。

## Risks & open questions

- ⚠️ **OpenAI SDK runtime incompatibility** — respx request-path test が失敗したら AD-2 を破棄し、
  option (a) の独立 uv lane を別 plan amendment として設計する。
- ⚠️ **hub task drift** — runner は個別 command を複製せず `api:check` を呼ぶ（同 task が `api:audit` を内包する）。
  記録には hub commit と task 名を必須化する。
- ⚠️ **warning census の欠落** — hub は warning-as-error のため、失敗ログから
  `DeprecationWarning` と `StarletteDeprecationWarning` を package origin 付きで分類する。
- ⚠️ **Python pin の部分更新** — version consistency test で `.python-version`、Ruff、Pyright、mise、
  pre-commit、CI の期待値を一括検証する。
- ⚠️ **外部 release 状態の陳腐化** — cp315 表と 3.15 release status は実装開始日に再確認し、
  2026-10-03 の調査値を盲目的に転記しない。
- ⚠️ **既存 user work の上書き** — `README.md`、`spec.json`、`spec.md` の未コミット差分を保持し、
  implementation は対象行だけを編集する。
- ❓ **hub 3.14 migration patch の最終内容** — hub spec 009 R7.2/R7.3 が実装前に変わった場合、
  runner の patch fixture ではなく指定 patch file を引数で受ける形を優先し、最新 hub plan と同期する。
