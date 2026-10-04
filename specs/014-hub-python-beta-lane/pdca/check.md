# Check Phase — 014-hub-python-beta-lane

PDCA Check: Plan / tasks の期待値と Do / `/sdd-ship` の実測結果を比較する。
`pdca/plan.md` は本 feature には存在しないため、`plan.md`、`tasks.md`、`pdca/do.md`、
`traceability.md` を正本として評価した。

## Expectations vs. Results

| Expectation (from plan/tasks) | Result (from do/ship) | Status |
|-------------------------------|-----------------------|--------|
| root を Python 3.14 baseline へ上げ、pin・metadata・Ruff・Pyright の整合を実行可能契約で固定する | `.python-version` / `requires-python` / Ruff `py314` / Pyright 3.14 を同期し、`test_python_baseline.py` 9 ケースで固定 | ✅ |
| root の `pydantic-ai-slim` を hub 以上へ上げ、LiteLLM と OpenAI SDK 2.x の共存を保つ | `pydantic-ai-slim>=2.54.0`、`openai>=2.47.0,<3.0.0`、`litellm>=1.96.2` を lock。Ollama request-path 6 ケースと LiteLLM floor 3 ケースで実行可能契約化 | ✅ |
| hub の immutable commit を full archive し、source tree を変更せず scratch だけを Python 3.14/3.15 へ migration する | `scripts/verify-hub-python.sh` と 29 件の hermetic contract tests を追加。full-repository sentinel、symlink、output 境界、interrupt cleanup、source 非変更を検証 | ✅ |
| required verdict と non-gating diagnostics を分離し、required failure 後も診断証拠を回収する | required=`uv lock` / `uv sync` / `api:check`、diagnostic=`api:lint` / typecheck discovery / `api:test:ci` / `api:audit`。最初の required 非ゼロを返しつつ diagnostics は完走 | ✅ |
| warning・JUnit・audit・resolved versions を再現可能な artifact と ledger に集約する | summarizer が schema、JUnit、skip、warning origin、audit、diagnostic divergence を集約。dated ledger §6 へ essentials と migration diff を転記 | ✅ |
| hub Python 3.14 の §8.1 判定を、結果を美化せず記録する | hub `3646b47` は lock/sync 成功、`api:check` 失敗。H3 を `proposed`、§8.1 を `not satisfied` のまま保持し、Ruff 4 件と dependency warning blocker を記録 | ✅ |
| Python 3.15 blocker と rate-limit sentinel を更新する | cp315 blocker table と monthly refresh checklist を正規化。rate-limit 3.15.0rc3 lane は 27 passed / 3 skipped / coverage 100% | ✅ |
| intake 候補と beta trial の状態を削除せず canonical ledger 化する | H1/H2、L1〜L6、H3、beta trial を status table に統合し、BeeAI/LlamaIndex 凍結と root trial ownership を明記 | ✅ |

## Test & Quality Outcomes

- Root aggregate gate: `mise run check` — **361 passed / 4 skipped**、Ruff clean、format 72 files、Pyright **0 errors / 0 warnings**。
- Coverage gate: `mise run cov` — **98.51%**（`fail_under = 98` を維持）。
- Targeted new contracts: hub runner / LiteLLM floor / Ollama OpenAI compatibility の **38 passed**。
- Hub runner contract: **29 passed**。shell runner の full archive、境界検証、失敗伝播、diagnostic 継続を subprocess で検証。
- Dependency audit: `uv run pip-audit` — known vulnerability なし（非公開の local project package のみ skip）。
- Pattern lanes: `mise run patterns:check` と `mise run patterns:audit` は全 lane green。rate-limit は 3.15.0rc3 で 27 passed / 3 skipped / coverage 100%。
- Immutable hub diagnostic: 1624 total / 1542 passed / 58 failed / 24 skipped / 0 errors、coverage 92.94%。これは sandbox gate の失敗ではなく、検証対象 hub commit の blocker 証拠。

## Requirements Coverage

- Traceability: **21/21 requirement IDs mapped (100%)**。
- Unmapped requirements: なし。
- Orphan tasks: なし。
- Conditional outcome: REQ-005 の sandbox 側責務（正しい判定・記録）は充足。hub 採用条件としての §8.1 は、immutable hub `api:check` が失敗したため意図どおり未充足。

## Deviations from Design

- **OpenAI SDK floor の改訂**: 当初案 `openai>=2.20.0` は pydantic-ai 2.54.0 が渡す `httpx2.AsyncClient` を旧 SDK が受理できず、実測で不正と判明。floor を最初の互換系列 `>=2.47.0` へ上げ、version test と request-path test を追加した。
- **LiteLLM floor の追加**: 古い 1.83.x 系の OpenAI exact pin が新 floor と衝突するため、`litellm>=1.96.2` を manifest-level contract にした。
- **hub repository shape の訂正**: fixture が root `.python-version` を仮定していたが、実 hub は `services/api/.python-version` を所有する。immutable run 前に contract fixture と migration path を実形状へ同期した。
- **hub green ではなく failed evidence で完了**: feature の目的は upstream を成功扱いにすることではなく、immutable commit の真の verdict を記録すること。`api:check` failure を受けても runner / ledger 実装は完成と判定した。

## Issues Encountered

| Issue | Root cause | Resolution |
|-------|-----------|------------|
| Ollama provider construction が旧 OpenAI SDK 2.x で `TypeError` | pydantic-ai 2.54.0 は既定で `httpx2.AsyncClient` を渡すが、旧 OpenAI SDK は `httpx.AsyncClient` のみ受理 | OpenAI floor を `>=2.47.0` へ上げ、構築・request-path・floor/ceiling を実行可能契約化 |
| LiteLLM 旧 patch release が OpenAI 旧版を exact pin | dependency range だけでは solver が非互換組合せを選べる | `litellm>=1.96.2` を明示し、floor test と lock evidence で固定 |
| fake mise trust path mismatch | runner の scratch 限定 trust と fake executable の観測前提がずれていた | `MISE_TRUSTED_CONFIG_PATHS`、isolated HOME、auto-install 抑止を contract として明示 |
| expectation identifier overlap | required / diagnostic の識別子が曖昧で summarizer の判定が false-positive になり得た | exact required-stage schema と diagnostic divergence を別検証に分離 |
| fixture が実 hub の Python pin 配置と不一致 | 設計 fixture が repository shape を誤って一般化 | hub commit の実形状へ fixture と migration path を同期し、3.14/3.15 の RED→GREEN→PROVE を再取得 |
| shell PROVE wrapper の `status` 変数で restore が中断 | zsh の readonly 変数名を使用 | backup を即時確認・復元し、以降は `rc` を使用。実装障害と検証 wrapper 障害を分離して記録 |

## Assessment

sandbox の Python beta-verification lane としては、21 要件を 100% trace し、root gate・coverage・audit・全 pattern lane が green で、immutable upstream failure を false-green にせず保存できている。**実装は production ready**。

一方、hub commit `3646b47` 自体の Python 3.14 採用は **not ready**。Ruff `UP037` 4 件と `llama-index-workflows` / Chroma の `asyncio.iscoroutinefunction` deprecation を解消した新 commit に対して同じ runner を再実行する必要がある。
