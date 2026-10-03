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
  spec 009 R7.2 相当の `.python-version`、期待 series、Ruff target の差分を当てた後に判定する。
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
| `openai` | `>=2.20.0,<3.0.0`（実測 2.54.0） | Ollama-compatible client + litellm coexistence | 2.54.0 request path は確認、upstream 公式範囲外 |
| `litellm` | vulnerable 1.83.0 への rollback 禁止 | optional Watsonx transport | 1.103.2 resolve を scratch で確認 |
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
