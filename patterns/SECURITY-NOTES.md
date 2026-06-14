# SECURITY-NOTES — patterns/ レーン（Spec 005 Req 7.1）

検証日: 2026-06-11（Web 一次情報。詳細は specs/005-cross-platform/research.md）

## CVE 根拠と依存フロア

| CVE | 対象 | 状態 | 本リポジトリの対応 |
|---|---|---|---|
| CVE-2026-25580 | pydantic-ai < 1.56.0 — URL ダウンロードの SSRF（クラウドメタデータ窃取） | 修正済 v1.56.0（GHSA-2jrp-274c-jhv3） | pydantic-ai レーンは `>=2.0.0b6`。2.x ベータ系は v1.99.0 修正の**後継**であり影響なし |
| CVE-2026-46678 | pydantic-ai 1.56.0–1.98.x — IPv4-mapped IPv6 等でブロックリスト迂回（前項の不完全修正） | 修正済 v1.99.0（GHSA-cqp8-fcvh-x7r3） | 同上。**1.x を使う場合は >=1.99.0 必須** |
| CVE-2025-1793 | llama-index-core <=0.12.21 のベクトルストア統合 8 種 — SQL インジェクション | 修正済 v0.12.28 | RAG レーンは **in-memory `SimpleVectorStore` 既定のみ**を能動的に明示構築し、脆弱な外部ベクタ DB 統合 8 種を**混入させない**（`indexing.py` で `isinstance` 固定・上流既定変化を回帰検知）。外部ベクタストア採用時は `>=0.12.28` フロアを必須ゲートとする |
| CVE-2025-1752 | llama-index-readers-web <=0.3.5 — KnowledgeBaseWebReader の無制限再帰 DoS | 修正済 0.3.6 | **非依存**。採用時は `llama-index-readers-web>=0.3.6` フロア + max_depth 制御を必須とする |
| CVE-2024-50050 | llama-stack <0.0.41 — pyzmq/pickle 経由のデシリアライズ RCE | 修正済 v0.0.41 | **llama-stack は採用禁止**（本パターン集に不要。導入提案は本ノートの更新を伴うこと） |

運用: 各レーンの uv.lock に対し `mise run patterns:audit`（pip-audit）を
ローカル/CI（patterns-ci.yml）で実行。dependabot が3レーンを週次監視
（pydantic-ai / beeai-framework は個別 PR 化）。

## OWASP Agentic AI Top 10（2025-12）/ LLM Top 10 2025 マッピング

| リスク | 本パターン集での緩和策 |
|---|---|
| 過剰なエージェンシー / Insecure Tool Use | routing: 経路語彙を `Literal` で固定し、語彙外は ValidationError（silent fallback 禁止、Req 2.3）。orchestrator-workers: `max_workers` 上限でプランナ出力の暴走を遮断し、切り捨てを `truncated` で可視化（Req 3.2） |
| Unbounded Consumption | ワーカー数上限 + Workflow タイムアウト（llamaindex レーン）。結合テストは出力長に依存しない契約レベルアサーション |
| プロンプトインジェクション（LLM01） | 本イテテーションは外部データ取り込みなし。RAG イテレーションで Docling 取り込み層に入力検証を実装予定。OWASP 公式の通り RAG/fine-tuning は緩和を完結しない（"research shows that they do not fully mitigate prompt injection vulnerabilities"）前提で多層防御を設計する |
| サプライチェーン | レーン毎 lockfile + pip-audit + dependabot。beeai-framework は内部 API 依存（テストフェイク）のため**厳密ピン**。litellm / ibm-watsonx-ai のルート watchlist 運用を踏襲 |
| 機微情報漏洩 | gitleaks pre-commit はリポジトリ全域（patterns/ 除外なし、Req 7.4）。モデル ID ハードコード禁止ガードも同様 |

### autonomous-agent ガードレール → OWASP Agentic AI マッピング（Spec 006 Req 10.1）

autonomous-agent は唯一の「Agent」型パターンで OWASP Agentic AI Top 10 の主戦場。
契約 `AgentRunResult.stop_reason`（`Literal["completed", "max_iterations",
"budget_exceeded", "denied"]`、`test_contract_drift.py` で語彙固定）が、どの
ガードレールでループが止まったかを型レベルで記録する。4ガードレールは全3レーン
（pydantic-ai / beeai / llamaindex）で契約レベル共通化されている
（[autonomous-agent/README.md](autonomous-agent/README.md) §セキュリティ）。

| ガードレール | OWASP Agentic AI リスク項目 | 緩和メカニズムと契約面 |
|---|---|---|
| ツール許可リスト（`allowed_tools`、最小権限） | 過剰エージェンシー / Insecure Tool Use | 許可外ツールは**実行せず**、拒否 observation を feedback して**ループ継続**（per-call refusal）。停止語彙に "forbidden" 系を持たない非対称性に整合し、試行は `steps` に記録（Req 6.4） |
| 危険操作のヒューマン承認フック（`approval_hook`） | Human-in-the-loop bypass / 過剰エージェンシー | `dangerous=True` ツールは呼出前に承認要求、否認で**ループ停止**・`stop_reason="denied"`・`final_output=None`（Req 6.5） |
| ループ毎予算消費記録（`budget`） | Unbounded Consumption（無制限消費） | `_budget_spent(response)` をレーン毎1点に閉じ込めトークンを決定論集計、`total_budget_spent > budget` で**ループ停止**・`stop_reason="budget_exceeded"`（Req 6.6） |
| 最大反復数（`max_iterations`） | Unbounded Consumption（無制限消費） | 反復上限到達で**ループ停止**・`stop_reason="max_iterations"`。暴走ループ／無限エージェンシーの上界を契約で固定（Req 6.3） |

多層防御（Req 10.3）: 実行 / 拒否（refused）/ 否認（denied）の全試行を
`AgentRunResult.steps` に記録し、監査証跡が silent empty にならないことを契約で
保証する（Repudiation / Untraceability の緩和）。予算は非負整数トークン
（`int`）で会計し、コスト換算は将来イテレーションに委ねる（spec Req 6 注記）。
fan-out は無く逐次ツールループのため、本パターンの無制限消費対策はワーカー数
上限ではなく `max_iterations` ＋ `budget` の二重上界で構成する（routing /
orchestrator-workers の `max_workers` とはレーン横断で対称）。

### RAG 応用レイヤ → OWASP LLM Top 10 マッピング（Spec 007 Req 9.1）

RAG（`patterns/rag/`）は検索済みコンテキストを LLM 生成へ供給する応用レイヤで、
ワークフローパターンとは別系統のリスク面を持つ。RAG 固有リスクを OWASP LLM
Top 10（2025）へマッピングし、契約レベルの緩和策と対応づける。

| RAG 固有リスク | OWASP LLM Top 10（2025） | 本レーンでの緩和策と契約面 |
|---|---|---|
| **インデックス汚染**（信頼できない文書がコーパスに混入し、汚染チャンクが検索される） | LLM08 Vector and Embedding Weaknesses ／ **過度の依存**（汚染された検索結果の無批判な信頼） | 取り込みは固定資産（`sample.docling.json`、ADR-3）に限定し変換器を CI 経路外へ。`chunk_id` 序数導出 + golden スナップショット（`golden_chunks.json`）で**チャンク境界の改変を回帰検知**。本番取り込み層の入力検証は後続イテレーションで多層防御として実装 |
| **引用なりすまし**（dangling citation: 検索されていない `chunk_id` を指す捏造引用） | **過度の依存**（Misinformation / Overreliance） | `validate_citations` が各 `Citation.chunk_id` の検索済み集合メンバシップを検証し、未検索 id は `DanglingCitationError` で **loud-fail**（R4.3/R9.3）。引用ゼロは `EmptyCitationError`。引用は飾りでなく**接地を契約で強制** |
| **PII を含むチャンクの露出**（個人情報を含むチャンクが検索・引用され回答へ漏出） | LLM02 **データ漏洩**（Sensitive Information Disclosure） | in-memory `SimpleVectorStore` 既定で外部ベクタ DB へ PII を流出させない（CVE-2025-1793 回避）。コーパスの PII 除去は取り込み層の責務として後続イテレーションで実装。gitleaks がリポジトリ全域（RAG 固定資産を含む）を走査し、秘匿情報のコミットを遮断 |

**pre-commit 不変条件（Req 9.4）**: `gitleaks` と `forbid-hardcoded-model-ids`
の2フックは **`exclude: ^patterns/` を持たず、RAG レーンを含む patterns/ 全域を
走査する**（`.pre-commit-config.yaml`）。レーン品質ゲート（ruff/format/typecheck）
の3フックは `mise run patterns:check` と patterns-ci.yml へ委譲するため
`exclude: ^patterns/` を持つが、**秘匿情報スキャンとモデル ID ハードコード禁止は
リポジトリ全域の不変条件**として RAG レーンも例外なく対象に含む。

## 既知の制約（Accepted Risk）

| 項目 | リスク | 受容根拠 / 見直し条件 |
|---|---|---|
| pydantic-ai v2 Beta 採用 | API 破壊変更 | 検証目的の意図的採用（ユーザー決定）。ルートアプリと同一フロアで追従。**v2 GA 時に見直し** |
| beeai フェイクの内部 API 依存 | バンプで破損 | 公式モック不在（upstream #750）。厳密ピン + スモークテストのドリフト検知で受容。**公式テスト API 公開時に移行** |
| BeeAI の手動スパン計装 | LLM 呼び出し粒度のスパン欠落 | 0.1.x に依存可能な公式 OTel API がない。パターン粒度のスパンで Req 6.2 を満たす。**上流の計装 API 安定時に見直し** |
