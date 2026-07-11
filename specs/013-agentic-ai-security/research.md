# 013-agentic-ai-security — Discovery & Research Log

012 の HITL レーンに対するセキュリティ強化(純加算)の調査記録。CVE 事実は
[specs/document-review/agentic-ai-design-v2-review.md](../document-review/agentic-ai-design-v2-review.md)
B 節(PyPI Advisory DB / GitHub Advisory 照会、2026-07-11)を一次ソースとする。

## Discovery type

既存セキュリティ資産(SECURITY-NOTES / security.yml / dependabot / 根ワークフロー
ガードテスト)への対称追記 + 012 コンポーネントの強化。新規の仕組みは導入しない。

## Investigations

### I-1: pydantic-ai の 3 アドバイザリと攻撃経路(確定事実)

- CVE-2026-25580(<1.56.0)/ CVE-2026-46678(<1.99.0)はいずれも SSRF 系で、
  攻撃経路は「**外部供給の `message_history` / URL 入力**を Agent 実行へ流し込める構成」。
  CVE-2026-61437(<1.51.0)は Web UI の XSS。v2 系に既知アドバイザリなし。
  2.9.0 は `_ssrf.safe_download`(プライベート帯域遮断 + IPv6 遷移形式の埋め込み
  IPv4 検査)を同梱 — ソースで確認済み。
- 帰結: HITL API は履歴を持ち回るのが本質のため、「履歴はサーバー正本・クライアント
  非受理」を**スキーマで**強制するのが最小で確実な遮断(R4)。

### I-2: 消費セマンティクスの既存前例はない(新規設計、ただし最小)

既存レーンにセッション概念がない(sse はステートレスストリーム)。012 の
`SessionStore` に状態機械(`pending → resuming → consumed`)を足すのが最小差分。
409 / 429 の写像は FastAPI の HTTPException で完結し、新規依存は不要(AD-2)。

### I-3: 監査イベントは 012 AD-5 の logfire シームに乗せる

新しい送出基盤を作らず、`logfire.span/info`(fail-soft ラッパー越し)で
1 判断 = 1 構造化イベント。テストは logfire 未設定でも通る必要があるため、
監査エミッタは**注入可能な Protocol**(既定 = logfire 実装、テスト = メモリ実装)に
する(AD-3)。既存レーンの「観測シームはレーン所有・注入可能」規約(sse
`configure_tracing(exporter=...)`)と同型。

### I-4: 「列挙面の登録漏れ」は根の workflow ガードテストで機械検証できる

`tests/unit/test_ollama_ci_workflows.py` が workflow YAML をパースして
トリガー・cron 文字列を検証する前例。同じ手法で `security.yml` の
`patterns-pip-audit` matrix と `dependabot.yml` の `directories` に
`patterns/hitl` が含まれることを assert できる(R9 — 「テストまたは checklist」の
うちテストを選ぶ。nltk 事案の再発防止として red で落ちる、R9.3)。

### I-5: SECURITY-NOTES の追記形式

- 「CVE 根拠と依存フロア」表: 既に pydantic-ai の 2 CVE 行が存在(frameworks レーン
  文脈)。HITL レーン行は**対応列にレーン固有の対応**(v2 フロア・R4 のスキーマ遮断)を
  書く追記で足りる。CVE-2026-61437(Web UI XSS)は行が無いため新規行。
- OWASP 節: 既存 4 レーン(autonomous-agent / RAG / SSE / Deep Research)と同じ
  表形式(リスク | 緩和策)で「HITL 応用レイヤ」節を追加(R7)。
- runbook(R8)は SECURITY-NOTES 末尾の「既知の制約(Accepted Risk)」の手前に
  独立節として置く。

### I-6: session id の生成は `uuid.uuid4()` で CSPRNG 要件を満たす

CPython の `uuid4` は `os.urandom` ベース。`secrets.token_urlsafe(32)` はより長いが、
UUID 形式は API スキーマ・ログ相関で扱いやすい。どちらでも R1.1 を満たす —
既定は `uuid4`、生成関数を 1 箇所(store)に集約して差し替え可能にする(AD-1)。

## Existing patterns to reuse

- `tests/unit/test_ollama_ci_workflows.py` — workflow YAML ガードテストの雛形(R9)。
- `patterns/SECURITY-NOTES.md` の表形式・節構成(R6, R7, R8)。
- 012 Observability(fail-soft logfire ラッパー)— 監査エミッタの土台(R3)。
- 012 SessionStore — 状態機械の拡張点(R1, R2)。
- pydantic `model_config = ConfigDict(extra="forbid")` — スキーマ遮断(R4.3)。

## External dependencies

追加なし(012 のレーン依存で完結。YAML ガードテストは root プロジェクトの既存
dev 依存 = pyyaml/pytest を使う)。

## Architecture decisions

### AD-1: session id 生成は store 集約の `uuid4`

`SessionStore.new_session_id()` に一元化。予測可能値(連番・時刻・prompt hash)禁止は
ユニットテストで「同一 prompt 2 回 → 異なる非連続 id」を検証(R1.3)。

### AD-2: 消費セマンティクスは SessionStore の状態機械 + HTTP 写像表

`SessionRecord.state: Literal["pending", "consumed"]` + pending `tool_call_id` 集合を保持。

| 事象 | HTTP |
|---|---|
| 未知 / consumed / 失効 session | 404(存在秘匿 — 理由は本文に書かない、R1.2, R2.1) |
| 判断対象の `tool_call_id` が pending 集合外 | 409(何も実行しない、R2.3) |
| `UsageLimits` 超過(012 harness の専用例外) | 429 + session 失効(R2.4) |
| 再 defer | 200 `PendingResponse` + pending 集合を更新(R2.2) |

### AD-3: 監査エミッタは Protocol 注入(既定 logfire、テスト用メモリ実装)

`AuditEmitter` Protocol(`emit(event: AuditEvent) -> None`)+
`LogfireAuditEmitter`(fail-soft)/ `InMemoryAuditEmitter`(テスト)。
`AuditEvent` は判断メタデータのみ: `session_id / tool_call_id / tool_name /
decision / denial_message / overridden_keys / timestamp`。
**引数の生値は持たない**(キー集合のみ、R3.2, R3.3)。

### AD-4: `/resume` スキーマは `extra="forbid"` + 履歴フィールド非定義

`ResumeRequest` に `message_history` / `usage` / `model` を**定義しない** +
`extra="forbid"` で未知フィールドは 422(R4.1, R4.3)。README に CVE ID 付きで
設計根拠を記す(R4.4)。

### AD-5: スキャン到達性は root ユニットテストで red 化

`tests/unit/test_security_workflow_lanes.py`(新規): security.yml を YAML パースし
matrix include に `patterns/hitl` 行があること、dependabot.yml の pip `directories`
に `/patterns/hitl` があることを assert(R9.1–9.3)。012 実装前は当然 red になるため、
**012 のレーン足場マージと同一 PR 系列で導入**する(実装順序の制約として tasks へ)。

### AD-6: SSRF/egress は WHERE 条件のガード(コードは書かない)

MVP ツールセットに URL 取得なし → 実装は発生しない。README のポリシー
(`safe_download` 必須・`allow-local` 禁止、CVE-2026-46678 根拠)+
レーン src に `force_download` / `allow-local` が出現しないことの grep ガードを
lint テストとして置く(R5 の将来ゲート化)。
