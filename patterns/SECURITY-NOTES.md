# SECURITY-NOTES — patterns/ レーン（Spec 005 Req 7.1）

検証日: 2026-06-11（Web 一次情報。詳細は specs/005-cross-platform/research.md）

## CVE 根拠と依存フロア

| CVE | 対象 | 状態 | 本リポジトリの対応 |
|---|---|---|---|
| CVE-2026-25580 | pydantic-ai < 1.56.0 — URL ダウンロードの SSRF（クラウドメタデータ窃取） | 修正済 v1.56.0（GHSA-2jrp-274c-jhv3） | pydantic-ai レーンは `>=2.0.0b6`。2.x ベータ系は v1.99.0 修正の**後継**であり影響なし |
| CVE-2026-46678 | pydantic-ai 1.56.0–1.98.x — IPv4-mapped IPv6 等でブロックリスト迂回（前項の不完全修正） | 修正済 v1.99.0（GHSA-cqp8-fcvh-x7r3） | 同上。**1.x を使う場合は >=1.99.0 必須** |
| CVE-2025-1793 | llama-index-core <=0.12.21 のベクトルストア統合 8 種 — SQL インジェクション | 修正済 v0.12.28 | 本イテレーションはベクトルストア**不使用**。Docling RAG イテレーション着手時のゲート条件として記録 |
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

## 既知の制約（Accepted Risk）

| 項目 | リスク | 受容根拠 / 見直し条件 |
|---|---|---|
| pydantic-ai v2 Beta 採用 | API 破壊変更 | 検証目的の意図的採用（ユーザー決定）。ルートアプリと同一フロアで追従。**v2 GA 時に見直し** |
| beeai フェイクの内部 API 依存 | バンプで破損 | 公式モック不在（upstream #750）。厳密ピン + スモークテストのドリフト検知で受容。**公式テスト API 公開時に移行** |
| BeeAI の手動スパン計装 | LLM 呼び出し粒度のスパン欠落 | 0.1.x に依存可能な公式 OTel API がない。パターン粒度のスパンで Req 6.2 を満たす。**上流の計装 API 安定時に見直し** |
