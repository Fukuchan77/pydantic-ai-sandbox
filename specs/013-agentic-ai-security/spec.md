# 013-agentic-ai-security

## Project Description

012-agentic-ai-design が新設する HITL レーン(`patterns/hitl/`)のセキュリティ強化を仕様化する。
012 はレビュー
[specs/document-review/agentic-ai-design-v2-review.md](../document-review/agentic-ai-design-v2-review.md)
の B 節(セキュリティ検証)と SSRF/egress 強化を**明示的に将来フェーズ**とした。本 spec がその
将来フェーズであり、012 の停止・承認・再開ハーネスに対する**純加算**として、
セッション衛生・承認監査証跡・信頼できない入力の遮断・SSRF/egress 方針・依存フロアの
文書化とゲート化・OWASP マッピングを要件化する。

レビュー B 節が確定した事実(本 spec の根拠):

- pydantic-ai には v1 系に 3 件の公開アドバイザリがある —
  **CVE-2026-25580**(URL ダウンロード SSRF、<1.56.0)、
  **CVE-2026-46678**(IPv6 遷移形式によるメタデータブロックリスト迂回、<1.99.0)、
  **CVE-2026-61437**(Web UI パストラバーサル→Stored XSS、<1.51.0)。
  **v2 系(2.x)には既知アドバイザリなし**。2.9.0 は SSRF 対策の `safe_download` 経路
  (プライベート IP・クラウドメタデータ帯域の遮断、IPv6 遷移形式の埋め込み IPv4 検査)を同梱する。
- SSRF 2 件の攻撃経路は「**信頼できない `message_history` / URL 入力**を Agent 実行へ流し込める
  構成」である。HITL API はまさに停止・再開のために `message_history` を持ち回るため、
  この経路を設計段階で遮断する必要がある。
- 2026-07 の daily CVE cron 失敗(nltk / PYSEC-2026-597、fix 未提供)は、
  「fix のないアドバイザリ」への標準運用手順と、**新レーンの lockfile がスキャン対象に
  登録されていること**の検証が必要であることを示した。

既存のセキュリティ資産([patterns/SECURITY-NOTES.md](../../patterns/SECURITY-NOTES.md) の
「CVE 根拠と依存フロア」表と OWASP マッピング節、`security.yml` の pip-audit / gitleaks レーン、
dependabot watchlist)へ**対称に追記**し、新規の仕組みは増やさない。

## Clarifications

### Session 2026-07-11

- Q: 本 spec の位置付けは? → A: 012 の HITL レーンに対するセキュリティ強化フェーズ(012 実装への依存を持つ純加算。012 の spec / 実装には手を入れない)
- Q: 承認者の認証・認可(authn/authz)は含めるか? → A: 含めない。MVP はプロセス内デモであり、認証は API ゲートウェイ / IdP の責務として設計ノートに明記するのみ
- Q: SSRF/egress はコード実装まで行うか? → A: HITL レーンが URL 取得ツールを持つ場合のみ実装要件(WHERE 条件)。MVP のツールセットに URL 取得がなければ、方針の文書化 + 将来ツール追加時のゲートとして機能する
- Q: /resume の消費セマンティクス(二重実行・HTTP マッピング)は 012 と 013 のどちらか? → A: 013(012 レビューで未規定と指摘された箇所を本 spec が要件化する)

## Scope

- In scope:
  - HITL API のセッション識別子の衛生(CSPRNG 生成・列挙不能・存在秘匿)
  - `/resume` の消費セマンティクス(承認結果の一回限り消費、二重 resume の `409`、
    usage-limit 超過の `429` マッピング)
  - 承認監査証跡(approve / deny / override_args の構造化イベント記録と機微値マスキング)
  - 信頼できない入力の遮断(`message_history` はサーバー側ストアが正本 —
    クライアント供給を受理しない設計の要件化)
  - SSRF/egress 方針(URL 取得ツール追加時の `safe_download` 必須・`allow-local` 禁止)
  - 依存フロアの文書化とゲート化(v1 併用時 `>=1.99.0`、`SECURITY-NOTES.md` への HITL 行追加)
  - OWASP Agentic AI Top 10 / LLM Top 10 マッピングの HITL レーン節追加(既存レーン規約と対称)
  - fix 未提供アドバイザリの運用 runbook(`--ignore-vuln` + 期限 + issue 追跡)
  - HITL レーン lockfile の CVE スキャン到達性検証(`security.yml` matrix / dependabot 登録)
- Out of scope(将来フェーズ / 他 spec の責務):
  - 承認者の認証・認可(authn/authz)— API ゲートウェイ / IdP の責務として設計ノートのみ
  - Durable Execution(Temporal / DBOS / Prefect)— 012 と同様に将来フェーズ
  - 永続ストアの暗号化・外部キュー — MVP はインメモリ(012 の決定を踏襲)
  - HITL レーンの足場そのもの(mise / CI へのレーン登録は 012 Req 1 の責務。
    本 spec は「登録されていることの検証」のみを持つ)

## Glossary

| Term | Definition |
|------|------------|
| HITL lane | 012 が新設する `patterns/hitl/` 独立 uv レーン(本 spec の強化対象) |
| HITL API | ハーネスを露出する FastAPI アプリ(`POST /run` / `POST /resume`) |
| session | `/run` が発行し `/resume` が参照する再開可能な実行の識別子 |
| session store | session に `message_history` と累積 `usage` を紐付けるサーバー側インメモリストア(正本) |
| approval decision | 個々の `tool_call_id` に対する `ToolApproved`(`override_args` 含む)/ `ToolDenied` の判断 |
| audit event | 承認判断 1 件を記録する構造化イベント(logfire スパン / 構造化ログ) |
| safe_download | pydantic-ai v2 の SSRF 対策ダウンロード経路(`pydantic_ai._ssrf.safe_download`。プライベート IP・クラウドメタデータ帯域を遮断し、IPv6 遷移形式の埋め込み IPv4 を検査する) |
| advisory floor | 既知アドバイザリを回避するための依存パッケージ最低バージョン(例: pydantic-ai v1 系 `>=1.99.0`) |
| SECURITY-NOTES | [patterns/SECURITY-NOTES.md](../../patterns/SECURITY-NOTES.md) — patterns/ レーンの CVE 根拠・依存フロア・OWASP マッピングの正本 |

## Requirements

### Requirement 1: セッション識別子の衛生

session id が推測・列挙可能だと、第三者が他者の承認待ち実行を `/resume` で承認/拒否できる。
識別子自体を認可の最低ラインとして扱う(authn/authz は out of scope だが、
推測不能性はトランスポート層に依存しない基礎防御である)。

**Acceptance Criteria**

1.1 THE HITL API SHALL generate session identifiers from a cryptographically secure random source (`secrets` / UUIDv4), and SHALL NOT derive them from predictable values (sequence numbers, timestamps, prompt hashes).
1.2 WHEN `/resume` is called with an unknown session identifier, THE HITL API SHALL respond `404` with a body that does not reveal whether the identifier ever existed (no "expired" vs "never existed" distinction).
1.3 THE unit tests SHALL assert that two sessions created from identical prompts receive distinct, non-sequential identifiers.

### Requirement 2: /resume の消費セマンティクス

停止・再開の境界は「同じ承認の二回適用」「消費済み session の再利用」という
整合性・リプレイの問題を持つ。012 レビュー指摘 4(未規定)を本要件が確定する。

**Acceptance Criteria**

2.1 WHEN a `/resume` for a session completes (terminal `SupportOutput` or error), THE HITL API SHALL invalidate that session so a subsequent `/resume` with the same identifier responds `404`.
2.2 IF a resumed run returns a further `DeferredToolRequests`, THEN THE HITL API SHALL keep the session alive with the updated `message_history` and accumulated `usage`, and the prior approval decisions SHALL NOT be re-applicable to the new pending calls.
2.3 IF `/resume` supplies an approval decision for a `tool_call_id` that is not pending in that session, THEN THE HITL API SHALL reject the request with `409` and SHALL NOT execute any tool.
2.4 IF a run or resume terminates because a `UsageLimits` budget is exceeded, THEN THE HITL API SHALL respond `429` and invalidate the session.

### Requirement 3: 承認監査証跡

「誰が・いつ・どのツール呼び出しを・どう判断したか」の記録は HITL の存在理由である
(監査証跡のない承認ゲートは事後検証できない)。可観測性の仕組みは 012 Req 9
(logfire fail-soft)を再利用し、新規基盤は導入しない。

**Acceptance Criteria**

3.1 WHEN an approval decision is applied on `/resume`, THE HITL lane SHALL emit one structured audit event per decision, carrying at least: session identifier, `tool_call_id`, tool name, decision (`approved` / `approved_with_override` / `denied`), the denial message when present, and a timestamp.
3.2 WHERE a decision is `ToolApproved(override_args=...)`, THE audit event SHALL record which argument keys were overridden without logging the overridden values verbatim.
3.3 THE audit event SHALL NOT include raw tool arguments; argument payloads SHALL be represented by their key set (masking) so secrets in arguments cannot leak into logs.
3.4 THE audit emission SHALL be fail-soft, consistent with 012 Requirement 9.1: an unconfigured or failing exporter SHALL NOT block or fail the resume.
3.5 THE unit tests SHALL assert audit events for both the approve path and the deny path with zero real exporter I/O.

### Requirement 4: 信頼できない入力の遮断(message_history はサーバー正本)

CVE-2026-25580 / CVE-2026-46678 の攻撃経路は「外部から供給された `message_history` を
Agent 実行に流し込める構成」だった。HITL API は再開のために履歴を持ち回るため、
履歴の正本をサーバー側ストアに固定し、クライアント供給を設計で遮断する。

**Acceptance Criteria**

4.1 THE `/resume` request schema SHALL accept only the session identifier and approval decisions, and SHALL NOT accept a client-supplied `message_history`, `usage`, or model identifier.
4.2 WHEN resuming, THE HITL API SHALL source `message_history` and accumulated `usage` exclusively from the server-side session store.
4.3 IF a `/resume` request body contains unknown fields, THEN THE HITL API SHALL reject it with a validation error (`extra="forbid"` semantics) rather than silently ignoring the fields.
4.4 THE lane README SHALL document this design as the mitigation for the CVE-2026-25580 class of SSRF (untrusted message history), with the advisory IDs cited.

### Requirement 5: SSRF / egress 方針(URL 取得ツールの条件付き要件)

MVP の HITL ツールセットは URL 取得を含まない想定だが、レーンにツールが追加された時点で
SSRF 面が開く。将来のツール追加をゲートする WHERE 条件要件として置く。

**Acceptance Criteria**

5.1 WHERE the HITL lane adds any tool that fetches a URL or downloads external content, THE tool SHALL route the fetch through pydantic-ai v2's `safe_download` path (or an equivalent egress guard blocking private ranges and cloud-metadata endpoints, including IPv6 transition forms).
5.2 WHERE such a tool exists, THE lane SHALL NOT enable `force_download='allow-local'` or an equivalent bypass in production code paths.
5.3 THE lane README SHALL document this policy, citing CVE-2026-46678 (the IPv6 transition-form bypass) as the rationale for requiring embedded-IPv4 inspection.

### Requirement 6: 依存フロアの文書化とゲート化

**Acceptance Criteria**

6.1 THE SECURITY-NOTES "CVE 根拠と依存フロア" table SHALL gain rows for the three pydantic-ai advisories (CVE-2026-25580 / CVE-2026-46678 / CVE-2026-61437) as they apply to the HITL lane, stating that the lane builds on a v2 line with no known advisories and that a `>=1.99.0` floor is mandatory WHERE pydantic-ai v1 is used alongside.
6.2 THE HITL lane `pyproject.toml` SHALL constrain `pydantic-ai-slim` to the v2 line (`>=2.<verified-minor>`), so a downgrade below the advisory-clean line fails dependency resolution loudly.
6.3 THE lane README SHALL record the verification baseline (pydantic-ai-slim version + date) for the security claims, consistent with 012 Requirement 13.3.

### Requirement 7: OWASP マッピング(既存レーン規約との対称)

既存レーン(autonomous-agent / RAG / SSE / Deep Research)は SECURITY-NOTES に
OWASP Agentic AI Top 10 / LLM Top 10 マッピング節を持つ(Spec 006 Req 10.1 / 007 Req 9.1 /
008 Req 8.1 / 009 Req 13)。HITL レーンも対称に追加する。

**Acceptance Criteria**

7.1 THE SECURITY-NOTES SHALL gain a "HITL 応用レイヤ → OWASP マッピング" section mapping the lane's mitigations, at minimum: the approval gate as the primary mitigation for Excessive Agency / Insecure Tool Use, `UsageLimits` accumulation (012 Req 7) for Unbounded Consumption, session hygiene + server-authoritative history (Req 1 / Req 4) for the untrusted-input surface, and the audit trail (Req 3) for accountability.
7.2 THE section SHALL follow the same table format as the existing per-lane OWASP sections.

### Requirement 8: fix 未提供アドバイザリの運用 runbook

nltk / PYSEC-2026-597(fix 未提供のまま daily cron を赤化)の教訓を標準手順化する。

**Acceptance Criteria**

8.1 THE SECURITY-NOTES SHALL document a runbook for advisories without an upstream fix: (a) confirm no fixed release exists, (b) assess exploitability in the affected lane, (c) if suppression is justified, add `--ignore-vuln <ID>` scoped to the affected lane's audit invocation with an expiry comment and a tracking issue, (d) remove the suppression when the fix lands.
8.2 THE runbook SHALL state that suppression entries without an expiry comment and tracking reference are not permitted.

### Requirement 9: CVE スキャン到達性の検証

レーン足場の登録(mise / CI)は 012 Req 1 の責務。本 spec は「登録が実際に行われ、
daily CVE cron の死角になっていない」ことの検証を持つ(nltk 事案の再発防止)。

**Acceptance Criteria**

9.1 THE repository SHALL verify—by test or documented checklist—that the HITL lane's lockfile is enumerated in the `security.yml` `patterns-pip-audit` matrix, so the daily cron audits it even when no PR touches the lane.
9.2 THE repository SHALL verify that the HITL lane is covered by dependabot monitoring consistent with the existing lanes.
9.3 IF the HITL lane exists but is absent from the `patterns-pip-audit` matrix, THEN the verification SHALL fail red (not warn).

## Non-Functional Requirements

- **Hermeticity**: 本 spec が追加するテスト(session 衛生、消費セマンティクス、監査イベント、
  スキーマ拒否)はすべて `TestModel` / `FunctionModel` / インメモリストアで駆動し、
  外部ネットワーク・プロセス・ファイルシステム I/O ゼロで実行する。
- **既存ゲートの維持**: レーンのカバレッジフロア(`fail_under = 98`)、pyright strict、
  ruff ルールセット(`S` 含む)は 012 の値を弱めない。
- **監査イベントの機微情報**: audit event はツール引数の生値・プロンプト本文・モデル出力本文を
  含めない(キー集合と判断メタデータのみ)。
- **フェイルソフト境界**: 可観測性(監査イベント送出)の失敗は業務フロー(承認・再開)を
  停止させない。逆に、整合性検査(Req 2)の失敗は loud に HTTP エラーで停止する。

## Out of Scope / Future Work

- 承認者の認証・認可(authn/authz)— API ゲートウェイ / IdP の責務。レーン README に
  「session id は認可トークンではない。本番配置では認証境界の内側に置くこと」を設計ノートとして記す。
- Durable Execution(Temporal / DBOS / Prefect)— 012 と同じく将来フェーズ。
- 永続ストア(外部 DB / キュー)とその暗号化・TTL 失効 — MVP はインメモリ(プロセス生存期間)。
- レート制限・DoS 対策(セッション数上限等)— 本番配置時のゲートウェイ責務として設計ノートのみ。
- 他フレームワーク(beeai / llamaindex)レーンへの HITL セキュリティ展開。

---

_Initialized: 2026-07-12T06:35:20+09:00_
_Requirements generated: 2026-07-12_
_Depends on: specs/012-agentic-ai-design(HITL レーン本体)_
