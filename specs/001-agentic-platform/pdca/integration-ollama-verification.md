# integration-ollama レーン 初回実機検証プラン

- 文脈: PDCA Act Next Action #6 — `001-agentic-platform` Task 12 で投入した `.github/workflows/integration-ollama.yml` の paths-filter / cache / concurrency 設定を、最初の実 PR で発火させて挙動を観測する。
- 関連 Req: Req 6.2 (V2 Beta 実 daemon 結合テスト)、Plan §R-7 (paths-filter + cache + concurrency 採用方針)。
- 想定実行者: メンテナ (PR 作成者) + reviewer。

---

## 0. 事前確認

```bash
# 該当 workflow が存在し、paths-filter が宣言されていること
grep -n "paths:" .github/workflows/integration-ollama.yml
# concurrency: cancel-in-progress: true が入っていること
grep -n "concurrency:\|cancel-in-progress" .github/workflows/integration-ollama.yml
# actions/cache キーが granite4.1-8b 等のモデル ID で構成されていること
grep -n "actions/cache\|hashFiles" .github/workflows/integration-ollama.yml
```

3 つすべてヒットすれば検証準備完了。

---

## 1. トリガ確認 (paths-filter 発火条件)

`integration-ollama.yml` は以下のいずれかでトリガ:

1. **pull_request** で `paths` フィルタにマッチ:
   - `src/pydantic_ai_sandbox/llm/**`
   - `src/pydantic_ai_sandbox/agents/**`
   - `src/pydantic_ai_sandbox/schemas/**`
   - `tests/integration/**`
   - `pyproject.toml`
2. **workflow_dispatch** (Actions タブからの手動起動)。

検証手順:

| Phase | 操作 | 期待される観測 |
|---|---|---|
| 1.1 | 現状 main の HEAD で Actions → integration-ollama を `workflow_dispatch` 起動 | 1 ジョブ実行、`granite4.1:8b` の pull 後 `RUN_INTEGRATION_OLLAMA=1 pytest tests/integration` が `1 passed` で完了 (timeout はおおむね 5 分以内) |
| 1.2 | `src/pydantic_ai_sandbox/llm/factory.py` を 1 行コメント追加するだけの **トリガ目的の小 PR** を作成 | PR check に `integration-ollama` ジョブが現れる (`ci` と並列で 2 ジョブ) |
| 1.3 | 同 PR で `README.md` を編集する push を追加 | paths-filter により integration-ollama は **再実行されない** (ci のみ走る)。これが正しい挙動。 |
| 1.4 | 同 PR で再度 `src/pydantic_ai_sandbox/llm/factory.py` を編集して push | concurrency.cancel-in-progress により前回の integration-ollama ジョブが **キャンセル** されて新ジョブが開始 |

---

## 2. キャッシュ挙動 (Ollama モデル blob)

| Phase | 操作 | 期待される観測 |
|---|---|---|
| 2.1 | 1.1 の初回ジョブ完了後、再度 workflow_dispatch を起動 | キャッシュヒット — `granite4.1:8b` の pull が "model already exists" で skip されジョブ全体が短縮 (初回 ~3 分 → 2 回目 ~1 分目安) |
| 2.2 | `pyproject.toml` の依存バージョンを上げる PR を作成 | `hashFiles('**/pyproject.toml')` が変わるためキャッシュキーがミス、再 pull が走る (期待される動作) |

---

## 3. ゲート無効化検証

| Phase | 操作 | 期待される観測 |
|---|---|---|
| 3.1 | `RUN_INTEGRATION_OLLAMA` が **未設定**な状態で `pytest tests/integration` を Actions runner 内で実行 (workflow を一時改変して実験) | テストは `pytest.fail` ではなく `pytest.skip` で 1 skipped — ローカル開発環境と同じゲート挙動を CI 上でも再現 |
| 3.2 | `RUN_INTEGRATION_OLLAMA=1` を設定したが Ollama daemon が起動していない状態 | `pytest.fail("Ollama daemon at ... is not reachable on /v1/models")` で job が **赤** で終わる (skip ではなく fail。これは意図的設計) |

---

## 4. 観測すべきログ・成果物

- `pytest` の `1 passed in N s` 行 (実機呼び出しが成立した証拠)
- Ollama サーバプロセスの `granite4.1:8b` 推論アクセスログ (Actions runner では一過性)
- ジョブの "Restore cache" / "Save cache" ステップの hit/miss 表示
- ジョブ終了時の cancellation ステータス (1.4 の検証)

---

## 5. 失敗時の切り分け checklist

| 症状 | 第一に疑うべき設定 |
|---|---|
| 全 PR で integration-ollama が走る | paths-filter の `paths-ignore` 誤用、もしくは `**/*` で網羅されている |
| paths にマッチしてもジョブが起動しない | branch protection / path filter の `pull_request_target` vs `pull_request` 取り違え |
| Ollama daemon にアクセスできない (`/v1/models` 404) | OLLAMA_BASE_URL に `/v1` 接尾辞が抜けている (T11 で踏んだ罠) |
| キャッシュが毎回ミス | キーの `hashFiles` 入力に変動するファイル (lock など) が混入、ID 識別子の指定漏れ |
| 同時実行で前ジョブが走り続ける | `concurrency.cancel-in-progress: true` が無効、または `group` キーが PR 別に分離していない |

---

## 6. 完了判定

以下が観測できた時点で本検証は **DONE**。spec.json amendments に観測結果を 1 行 (実行 URL とジョブ ID) で記録する。

- [ ] §1.1 manual trigger で 1 passed を確認
- [ ] §1.2 paths-filter 発火を確認
- [ ] §1.3 paths-filter 非発火を確認
- [ ] §1.4 concurrency cancel を確認
- [ ] §2.1 キャッシュヒットによる短縮を確認

未完了項目があれば Mistake として `.sdd/mistakes/` に再記録。
