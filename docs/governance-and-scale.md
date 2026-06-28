# Governance & Scale（Stage 5）— Identity / 規模 / デプロイ / OWASP

統一学習パス（[`learning-path.md`](learning-path.md)）の **Stage 5**。エージェントを
**本番・組織規模で安全に運用**するための論点を、公式（IBM）指針と本リポジトリの既存の
緩和策（OWASP マッピング）に結びつけて索引します。本ページは**ドキュメント**であり、
`patterns/` の凍結契約には手を入れません（実装の正本は各 README とコード）。

> 体裁は [`docs/README.md`](README.md) の方針に倣い、「公式が推奨 → 本リポのどこで扱うか」で読めます。

---

## 1. Agent identity & 認可 / Identity and access

**公式 / Source:** IBM [Agentic AI identity management](https://www.ibm.com/solutions/agentic-ai-identity-management)

エージェントは「人間に代わって**行動**する」ため、**誰の権限で・何を・どこまで**行えるかの
管理が生成 AI 以上に重要になります。要点：

- **エージェントに固有の ID** を与え、人間ユーザーと区別して監査する（誰が＝どのエージェントが
  採点/行動したかの監査証跡）。
- **最小権限**：ツール・データ・外部アクションへのアクセスを必要最小限に絞る。
- **委任と境界**：ユーザー権限の借用範囲、昇格の禁止、人間確認（human-in-the-loop）点の設計。

**本リポジトリでの接点 / Where this repo touches it:**
- `patterns/autonomous-agent` の **ツール許可リスト（`allowed_tools`、最小権限）** と
  `stop_reason="disallowed_tool"`（許可外ツールはハード停止）— 型レベルで「何を許したか」を固定。
  → [`patterns/SECURITY-NOTES.md`](../patterns/SECURITY-NOTES.md) の autonomous-agent → OWASP マッピング。
- 監査証跡の発想は [`patterns/EVAL-GRADERS.md`](../patterns/EVAL-GRADERS.md)（Spec 011・main マージ済）の
  **非空 `rationale` 必須**と **`judge_id`（judge 出自の最小メタ）** にも通底（誰が・なぜその判断をしたか）。

---

## 2. OWASP Agentic AI / LLM Top 10

**本リポジトリの正本:** [`patterns/SECURITY-NOTES.md`](../patterns/SECURITY-NOTES.md)

過剰エージェンシー / Insecure Tool Use・Unbounded Consumption・プロンプトインジェクション・
サプライチェーン・機微情報漏洩を、各パターンの緩和策（`Literal` 経路語彙・`max_workers`/
タイムアウト・lockfile + pip-audit + dependabot・gitleaks 全域）にマッピング済み。Stage 5 の
セキュリティはまずここを読むこと。自律性が上がるほど OWASP の主戦場（autonomous-agent）になります。

> 自律性レベルと有界性の関係は bootcamp 側 [`agent-types.md`](../../agentic-ai-bootcamp/docs/agent-types.md) §3 を参照。

---

## 3. エンタープライズ規模での採用 / Scaling adoption

**公式 / Source:** IBM [Scale agentic AI（IBV report）](https://www.ibm.com/thought-leadership/institute-business-value/en-us/report/scale-agentic-ai) ・
[Insights: agentic AI](https://www.ibm.com/think/insights/agentic-ai)

PoC から**規模化**へ進む際の組織的論点：ガバナンス体制・ROI と優先順位・標準化（共有契約/
プラットフォーム化）・人材と運用プロセス。

**本リポジトリでの接点:**
- **標準化＝単一ソースの契約**：`patterns/contracts` ＋ ドリフトテスト
  （`patterns/contracts/tests/unit/test_contract_drift.py`）が「正本（README）== 実体」を保証。
  規模化で効く「定義の散在を 1 点で防ぐ」考え方の実例。
- **再現性のあるプロセス**：SDD パイプライン（`specs/`）と CI（`.github/workflows/`）が、
  パターン追加を**監査可能な手順**に落とす。

---

## 4. デプロイ / Deployment

**公式 / Source:** IBM watsonx [Deploying agentic AI](https://www.ibm.com/docs/en/watsonx/saas?topic=applications-deploying-agentic-ai)

デプロイ時は、配信（ストリーミング）・可観測性・タイムアウト/上限・段階的ロールアウトが要点。

**本リポジトリでの接点:**
- **配信**：`patterns/sse`（型付きイベント → `EventSourceResponse` → 切断時の確実停止）。
  bootcamp の [Lesson 10 — Production](../../agentic-ai-bootcamp/lessons/10-production/README.md)（FastAPI + SSE）が入口。
- **可観測性**：各パターンの `observability.py`（OTel スパン）と [`docs/context-engineering.md`](context-engineering.md)。
  Spec 010 で **structured note-taking / compaction が deep-research のメインラインに昇格**（`ResearchNote` /
  `Finding.notes` を contracts 化）し、長時間実行の文脈肥大を本流で抑制する。
- **有界性**：`max_iterations` / `budget_exceeded` / タイムアウト（autonomous-agent 契約）。

---

## まとめ / Where to go
- セキュリティ詳細 → [`patterns/SECURITY-NOTES.md`](../patterns/SECURITY-NOTES.md)
- 評価の本番契約 → [`patterns/EVAL-GRADERS.md`](../patterns/EVAL-GRADERS.md)（`GradeReport` / `AxisScore` / `Judge[SubjectT]`、Spec 011）
- 学習パス全体 → [`learning-path.md`](learning-path.md) / bootcamp [`docs/learning-path.md`](../../agentic-ai-bootcamp/docs/learning-path.md)
