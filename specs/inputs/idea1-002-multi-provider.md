# Idea: Spec 002 — Multi-provider Real Implementations

- 起票準備日: 2026-05-24 (PDCA Act Next Action #7)
- 前提: `001-agentic-platform` 完了 (50 unit + 1 integration GREEN, coverage 98%, Constitution 5 原則準拠)
- ねらい: ModelFactory の 3 つの stub (watsonx / anthropic / bedrock) を **本実装に昇格**、`LLM_PROVIDER` の Literal 集合を変えずに `_MVP_STUB_PROVIDERS` を空 frozenset にする。

---

## 1. スコープ (要約)

| Provider | Pydantic AI integration | 主要環境変数 | 備考 |
|---|---|---|---|
| **watsonx.ai** | `LiteLLMProvider` (`watsonx/...` モデル文字列) または `pydantic_ai.models.Model` 派生 (ibm-watsonx-ai SDK 直叩き) | `WATSONX_API_KEY`, `WATSONX_PROJECT_ID`, `WATSONX_URL`, `WATSONX_MODEL_ID`, `WATSONX_TRANSPORT={sdk,litellm}` | LiteLLM ルートが速いが `litellm` を 1 段増やすため supply-chain-watch dependabot ラベル必須 |
| **Anthropic 直** | `AnthropicModel` + `AnthropicProvider` | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_BETAS` (任意 / `1m-context-2025` 等) | day-0 機能対応。1M context Beta は header 経由でオプトイン |
| **AWS Bedrock** | `BedrockConverseModel` + `BedrockProvider` | `AWS_REGION`, `BEDROCK_MODEL_ID`, AWS credential 系 (env / IRSA / `~/.aws/credentials`) | **必ず Cross-Region Inference Profile ID** (`us.` / `eu.` / `jp.` / `global.` prefix) を使う。base ID は `ValidationException` |

---

## 2. 要件案 (EARS 形式の素案)

### Req 1 — provider 拡張
- 1.1 `LLMProvider = Literal["ollama","watsonx","anthropic","bedrock","fallback"]` の語彙は **不変**。`_MVP_STUB_PROVIDERS` を空 frozenset にする。
- 1.2 `build_model("watsonx" | "anthropic" | "bedrock")` は対応する Model インスタンスを返し、`NotImplementedError` を一切 raise しない。
- 1.3 各 provider の構築関数は **I/O ゼロ** (Req 2.6 継承)。実 API 呼び出しは Agent.run 時のみ。
- 1.4 認証情報未設定時は **構築時に明示的な ValueError** で fail-fast (例: `WATSONX_API_KEY 未設定`、`AWS credential が解決できない`、`ANTHROPIC_API_KEY 未設定`)。
- 1.5 ハードコード model ID 禁止 (Req 1.5 継承)。Bedrock の Cross-Region Inference Profile ID プレフィックス (`us.`, `eu.`, `jp.`, `global.`) は禁止語彙には含めない (env から流入するため)。

### Req 2 — テスト
- 2.1 `tests/unit/test_factory_dispatch.py` の "NotImplementedError 期待" 3 ケースを **成功 assert** に反転させる。
- 2.2 各 provider に対し `httpx.{Client,AsyncClient}.send` パッチで I/O ゼロを再証明 (Req 2.6 のテスト継承)。
- 2.3 `LiteLLMProvider` ルートを採る場合は `RESPX` 等で外部 API を mock した unit test を別途追加。
- 2.4 実 API 結合テスト (`tests/integration/`) はそれぞれ `RUN_INTEGRATION_WATSONX=1` / `RUN_INTEGRATION_ANTHROPIC=1` / `RUN_INTEGRATION_BEDROCK=1` ゲートで gating。`/healthz` 200 + `/chat` 200 + ChatResponse の最小契約のみ。

### Req 3 — observability
- 3.1 各 provider の Agent.run span に `gen_ai.system` (もしくは `gen_ai.provider.name` 新仕様) と `gen_ai.request.model` が出ること。
- 3.2 認証エラーは Logfire span に `error.class` 属性で残し、機微情報をスクラブ (default + `extra_patterns=["prompt","tool_input","tool_output"]` 既存設定で吸収)。

### Req 4 — CI / セキュリティ
- 4.1 `litellm` を依存に追加する場合 dependabot.yml の supply-chain-watch labels 対象に登録。
- 4.2 各 provider の API key を CI シークレットに登録、結合テスト workflow (`integration-watsonx.yml` 等) に paths-filter + cache + concurrency を踏襲。
- 4.3 fail-fast: 結合テスト workflow は default では走らず、`workflow_dispatch` または paths マッチ時のみ。

### Req 5 — マイグレーション
- 5.1 `001-agentic-platform` の `_MVP_STUB_PROVIDERS` 関連テスト (`test_mvp_stub_providers_lock` 等) は **同 PR で削除 or 内容を反転**。
- 5.2 `tasks.md` T4 / T5 の「stub」表現を更新。`_build_fallback` の silent-drop ロジックは新 provider が有効化されると自然消滅する (フィルタ対象が空集合になる) — テストは存続させ "silent drop は何も起きない" を assert で確かめる。

---

## 3. 設計上のキーポイント

### 3.1 watsonx の二系統サポート
- `WATSONX_TRANSPORT=litellm` → `LiteLLMProvider("watsonx/...")` で高速着手。
- `WATSONX_TRANSPORT=sdk` → `pydantic_ai.models.Model` 直派生で `ibm-watsonx-ai.foundation_models.Model.generate_text_stream` を使用。SDK ルートのほうが retry / pagination 制御が安定だが実装コスト大。
- 両ルートのテストを揃える (parametrize)。

### 3.2 Bedrock Cross-Region Inference Profile
- 単純 base ID (`anthropic.claude-sonnet-4-6`) を渡すと on-demand 利用が `ValidationException`。プレフィックス + ID (例 `us.anthropic.claude-sonnet-4-6`) を使う必要がある。
- env で受け取った文字列に `.` が含まれることを `Settings._check_provider_constraints` で軽くバリデート (詳細チェックは AWS 側に委譲)。

### 3.3 認証情報スクラブ
- `extra_patterns` に `api_key` / `aws_secret_access_key` / `WATSONX_API_KEY` を **追加しない** (default scrubbing がカバー)。Logfire ScrubbingOptions のデフォルト挙動を信頼。

### 3.4 FallbackModel 連携
- `FALLBACK_ORDER=ollama,watsonx,anthropic,bedrock` のような順序が初めて全 real-provider chain として意味を持つ。failover の挙動 (T5.3 と同じ FunctionModel テスト) を multi-provider 化。

---

## 4. リスク

| リスク | 緩和策 |
|---|---|
| `litellm` の supply chain | dependabot labels + pip-audit / gitleaks の通常運用で吸収。代替に SDK 直叩き選択肢を残す。 |
| API キーの mis-configuration がテストで検出されない | unit テストは I/O ゼロを保つ + 結合テストで実呼び出し。CI シークレット未設定時は `pytest.fail` (T11 と同じ) で **明示失敗**。 |
| Anthropic の Beta header 取り扱い | `ANTHROPIC_BETAS` を comma-separated env で受け取り、構築時に `provider.client.beta_headers` に注入。設計は `001` 側の env hygiene パターン継承。 |
| Bedrock model ID の drift | Cross-Region Inference Profile ID も env 経由のみ、ハードコードしない (Req 1.5 継承)。 |

---

## 5. /sdd-init 起動時の追加質問候補

1. watsonx は `litellm` ルートで先行着手しますか? それとも SDK 直派生を本命にしますか?
2. Anthropic 1M context Beta header は MVP に含めますか?
3. Bedrock のリージョン (us / eu / jp / global) はどれを既定にしますか?
4. 結合テストのシークレットは GitHub Environment 単位で管理しますか?

---

## 6. 参考

- `001-agentic-platform/spec.md`、`plan.md` §2.x、`pdca/act.md` Pattern A
- [.sdd/patterns/env-driven-modelfactory.md](../../.sdd/patterns/env-driven-modelfactory.md) — 新 provider 追加時の 4 箇所更新パターン
- `specs/inputs/idea0.md` — 元設計に Bedrock Cross-Region Inference Profile の制約が記載
- CLAUDE.md — `WATSONX_TRANSPORT=sdk|litellm` 切替方針
