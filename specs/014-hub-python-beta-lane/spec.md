# 014-hub-python-beta-lane

## Project Description

2026-10-03 に、本リポジトリは統合ハブ `vaz-agentic-ai-next` の **Python ベータ検証レーン**になった
（[README](../../README.md)「Role: the Python beta-verification lane」）。ハブの `services/api/` が
FastAPI + Pydantic AI レーンの正本で（ハブ ADR-0007）、新しい Python・pydantic-ai のベータ機能・ハブが据え置く依存は
ここで先に試す。結果はハブの `docs/dependency-policy.md` §8 の手順でだけハブへ届く。

最初の取り込みは完了した。[`docs/hub-intake-2026-10.md`](../../docs/hub-intake-2026-10.md) の H1・H2
（slowapi を `limits` 直結の実装に置き換え、starlette の `--ignore-vuln` 5 件を削除）は、本リポジトリの
[`patterns/rate-limit/`](../../patterns/rate-limit/README.md)（PR #40）で検証し、ハブの #76 で取り込まれた。

本 spec は、この役割を続けるための次の作業を定める。散文は日本語、識別子・パス・コードは英語。

### 前提として確認した事実（2026-10-03、`main`@`b4fa915`）

- **本リポジトリのルートは、ベータレーンなのにハブより古い pydantic-ai を使っている。**
  ルートの `uv.lock` は `pydantic-ai-slim` 2.31.1、ハブの `services/api/uv.lock` は 2.54.0。
  原因は `pyproject.toml` の ADR-2 で、litellm が openai 3.x に対応していないため `openai<3.0.0` で固定し、
  その結果 pydantic-ai-slim が 2.31 系に留まっている（2.32.0 以降の `openai` extra は `openai>=3.0.0` を要求する）。
- ハブの Python 3.13 固定の解除について、ハブ §8.1 が求める証拠は「3.14 で `uv sync` と `api:check` が green であること」。
  `hub-intake-2026-10.md` §2.5 の時点では、ハブの依存一式で `uv lock` が 3.14 で解決することまでしか確認していない。
- 3.15 は、ハブの依存一式では解決しない。`chromadb<1.0` → `onnxruntime` と `sentence-transformers` → `torch` に
  cp315 の wheel も sdist も無い（2026-10-03 の PyPI）。
- `hub-intake-2026-10.md` の L1（`UsageLimits` と全体タイムアウト）は、ハブ側に既に存在することを確認した
  （ハブ spec `009` の「前提として確認した事実」）。L2〜L4 の確認はハブ spec `009` R6 が行う。

---

## Requirements

既定の主語は THE sandbox。[E]=Event-driven / [U]=Ubiquitous / [S]=State-driven。

### Requirement 1: ハブの依存一式を Python 3.14 で検証する（ハブの H3 の証拠）

1.1 [U] The sandbox SHALL verify the hub's `services/api` dependency set on CPython 3.14 in a scratch copy
（ハブの `pyproject.toml` / `uv.lock` / `app/` / `tests/` をハブの特定コミットから取り出す。本リポジトリへはコミットしない）。
1.2 [U] 検証 SHALL run `uv lock`、`uv sync`、ruff、`ty check`、pytest（unit + integration + e2e）、pip-audit を 3.14 で実行し、
結果（件数・失敗・警告）を記録する。
1.3 [U] 3.14 で新たに出る非推奨警告（`DeprecationWarning` と、`UserWarning` 派生の `StarletteDeprecationWarning` の両方）
SHALL be listed with their origin package。`hub-intake-2026-10.md` §2.3 の罠 2・3 が 3.14 でどうなるかを含める。
1.4 [U] 記録 SHALL be written as a dated section of `docs/hub-intake-2026-10.md`（または `docs/hub-intake-YYYY-MM.md` の新しい文書）
with the hub commit verified, the versions, and the commands。
1.5 [E] WHEN 1.2 is all green, the record SHALL state that the hub's §8.1 evidence for Python 3.14 is satisfied
（ハブ spec `009` R7 の起動条件）。

### Requirement 2: ベータレーンのルートをハブより新しく保つ

2.1 [U] ルートの `pydantic-ai-slim` SHALL resolve to a version equal to or newer than the hub's `services/api`。
ベータレーンがハブより古い版で検証しても、ハブの版上げの証拠にならない。
2.2 [U] litellm の経路（`WATSONX_TRANSPORT=litellm`、`src/pydantic_ai_sandbox/llm/providers/litellm.py`）が 2.1 を妨げる間は、
次のどちらかを ADR として決める。
- (a) litellm 経路を独立した uv プロジェクト（`patterns/` のレーンと同じ形）へ分離し、ルートから `openai<3.0.0` を外す
- (b) litellm 経路を削除し、watsonx は SDK 経路だけにする
既定は (a)。litellm の脆弱版（1.83.0）へ巻き戻る解決を許さないという ADR-2 の制約は、分離先でも維持する。
2.3 [E] WHEN litellm ships a release declaring `openai>=3`, the separation SHALL be reconsidered and the cap removed（ADR-2 の既存の条件）。
2.4 [U] 2.1〜2.2 の変更後も、ルートの `mise run check` とカバレッジの下限（`fail_under` 98）SHALL pass。
2.5 [U] ルートの Python SHALL be raised from 3.13 to 3.14 after Requirement 1 is green
（`.python-version`・`mise.toml`・`pyproject.toml` の pyright 設定・CI）。`ibm-watsonx-ai` の 3.14 での import（ADR-1 の 1.5.12 の不具合）が
現行の下限で解消していることをテストで確認する。

### Requirement 3: Python 3.15 の阻害要因の追跡

3.1 [U] 3.15 の阻害要因 SHALL be tracked in one table（パッケージ、必要な wheel、確認日、状態）: `onnxruntime`、`torch`、
`pydantic-core`（cp315 wheel が無くソースビルド。CI で約 3 分）。
3.2 [U] 表 SHALL be re-checked at each monthly dependency refresh（`chore/dependency-security-refresh` の作業時）。
3.3 [E] WHEN all blockers in 3.1 have cp315 wheels, the sandbox SHALL repeat Requirement 1 on 3.15 and record the result.
3.4 [U] `patterns/rate-limit/` は 3.15 のまま維持し、3.15 の rc / 正式版の更新ごとに green を保つ。

### Requirement 4: 取り込み候補の状態を最新にする

4.1 [U] `docs/hub-intake-2026-10.md` SHALL mark H1・H2 as landed in the hub（#76、ハブ `main`@`3646b47`）。
4.2 [U] L1 SHALL be marked as already present in the hub, citing the hub files（`services/api/app/api/v1/agent.py`、`_stream.py`）。
4.3 [E] WHEN the hub reports the results of its spec `009` R6（L2〜L4）, the document SHALL record them.
4.4 [U] 取り込みが終わった項目と、取り込まないと決めた項目（L5・L6）は、表に残したまま状態列で区別する（削除しない）。

### Requirement 5: pydantic-ai のベータ機能の先行検証

5.1 [U] ハブが採る前の pydantic-ai の新機能（新しい `UsageLimits` の項目、ストリーミング API の変更、ツール承認関連の API など）
SHALL be tried in the root or a `patterns/` lane before the hub adopts them.
5.2 [U] 試した結果 SHALL be recorded with the pydantic-ai version, the hub file it would affect, and a recommendation
（取り込む／取り込まない／待つ）, in the same intake document as Requirement 1.
5.3 [U] BeeAI Framework と LlamaIndex のレーン（`patterns/frameworks/{beeai,llamaindex}`）は比較用として凍結したままにし、
本 Requirement で拡張しない（README の方針）。

## Out of Scope

- ハブのリポジトリへの直接の変更（ハブ側はハブ spec `009` が扱う）
- ハブの `services/api` を本リポジトリへコピーしてコミットすること（R1.1 は一時的なスクラッチでの検証）
- BeeAI Framework / LlamaIndex レーンの拡張
