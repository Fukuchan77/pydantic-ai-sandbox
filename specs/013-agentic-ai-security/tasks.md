# 013-agentic-ai-security — Implementation Tasks

plan.md(design 承認済み)をタスクへ分解する。012 の HITL レーン実装(tasks 完了)を
前提とする純加算。TDD(赤 → 緑)を各境界で徹底する。

Conventions:
- `- [ ]` pending, `- [x]` done, `- [ ]*` optional/deferrable test.
- `(P)` = safe to run in parallel (no dependency, disjoint boundary).
- Every task (major and sub) declares `_Boundary:_` and `_Depends:_`.
- Requirement coverage lists numeric IDs only, comma-separated.
- 前提: specs/012-agentic-ai-design/tasks.md の全タスク完了(`patterns/hitl/` が存在し全ゲート緑)。

---

## 1. セッション状態機械と識別子衛生(`store.py` 拡張)

_Boundary:_ `patterns/hitl/src/patterns_hitl/store.py`, `patterns/hitl/tests/unit/test_session_hygiene.py`, `patterns/hitl/tests/unit/test_consumption.py`
_Depends:_ none(012 完了後)
_Requirements:_ 1.1, 1.2, 1.3, 2.1, 2.2

- [ ] 1.1 失敗テストを先行作成する。(a) `test_session_hygiene.py`: 同一 prompt で 2 session → 異なる非連続 id(接頭辞・連番・時刻由来でない)、id 生成が `new_session_id()` 一点に集約されている。(b) `test_consumption.py`(store 層): `claim()` は未知 id と consumed id で**同一の** `UnknownSessionError`(区別情報なし)、終端 `consume()` 後の `claim()` 失敗、再 defer の `settle_pending()` で pending 集合が新しい `tool_call_id` 群へ置換され旧 id が無効。**赤を確認する。**
  _Boundary:_ `patterns/hitl/tests/unit/test_session_hygiene.py`, `patterns/hitl/tests/unit/test_consumption.py`
  _Depends:_ none
  _Requirements:_ 1.2, 1.3, 2.1, 2.2
- [ ] 1.2 `store.py` を拡張しテストを緑化する。`new_session_id()`(`uuid.uuid4()` 一元化)、`SessionRecord` に `state: Literal["pending", "consumed"]` と `pending_call_ids: frozenset[str]` を追加、`claim()` / `settle_pending()` / `consume()` の状態遷移を実装(research.md AD-1 / AD-2)。並行 resume は `claim()` の同期区間で先勝ちにする。
  _Boundary:_ `patterns/hitl/src/patterns_hitl/store.py`
  _Depends:_ 1.1
  _Requirements:_ 1.1, 1.2, 2.1, 2.2

---

## 2. 消費セマンティクスの HTTP 写像(`app.py` 拡張)

_Boundary:_ `patterns/hitl/src/patterns_hitl/app.py`, `patterns/hitl/tests/unit/test_consumption.py`
_Depends:_ 1
_Requirements:_ 1.2, 2.1, 2.3, 2.4

- [ ] 2.1 失敗テストを追加する(API 層、`with TestClient(app):`)。(a) 終端後の再 `/resume` → 404、404 本文が「未知」と「消費済み」を区別しない固定文言、(b) pending 集合外の `tool_call_id` を含む decisions → 409 + **どのツールも実行されない**(スパイで確認)+ 1 件でも不整合なら全体拒絶、(c) 低 limit 注入で resume 中に予算超過 → 429 + 以後同 session は 404、(d) 再 defer 応答後に旧 `tool_call_id` の判断を再送 → 409。**赤を確認する。**
  _Boundary:_ `patterns/hitl/tests/unit/test_consumption.py`
  _Depends:_ 1.2
  _Requirements:_ 1.2, 2.1, 2.3, 2.4
- [ ] 2.2 `app.py` の `/resume` ハンドラへ写像表(research.md AD-2)を実装しテストを緑化する: `UnknownSessionError` → 404(固定本文)、pending 外判断 → 409(実行前拒絶)、`HitlBudgetExceededError` → 429 + `consume()`、再 defer → 200 `PendingResponse` + `settle_pending()`。
  _Boundary:_ `patterns/hitl/src/patterns_hitl/app.py`
  _Depends:_ 2.1
  _Requirements:_ 1.2, 2.1, 2.3, 2.4

---

## 3. 承認監査証跡(`audit.py` 新設 + 注入シーム)

_Boundary:_ `patterns/hitl/src/patterns_hitl/audit.py`, `patterns/hitl/src/patterns_hitl/app.py`, `patterns/hitl/tests/unit/test_audit_trail.py`, `patterns/hitl/tests/support/in_memory_audit.py`
_Depends:_ 2
_Requirements:_ 3.1, 3.2, 3.3, 3.4, 3.5

- [ ] 3.1 失敗テスト `test_audit_trail.py` を先行作成する(`InMemoryAuditEmitter` 注入、実エクスポータ I/O ゼロ)。(a) approve / deny / override の各 path で判断 1 件 = イベント 1 件、(b) イベントに `session_id` / `tool_call_id` / `tool_name` / `decision` / `denial_message` / `timestamp` が載る、(c) `override_args={"amount_usd": 30.0, "reason": "x"}` で `overridden_keys == ("amount_usd", "reason")` かつイベント全体をシリアライズしても値 `30.0` / `"x"` が現れない、(d) emitter が例外を投げても resume は成功する。**赤を確認する。**
  _Boundary:_ `patterns/hitl/tests/unit/test_audit_trail.py`, `patterns/hitl/tests/support/in_memory_audit.py`
  _Depends:_ 2.2
  _Requirements:_ 3.1, 3.2, 3.3, 3.4, 3.5
- [ ] 3.2 `audit.py`(`AuditEvent` — 引数生値フィールドなし、`AuditEmitter` Protocol、`LogfireAuditEmitter` — fail-soft)を実装し、`create_app(audit_emitter=...)` に注入シーム(既定 = logfire 実装)を追加してテストを緑化する。送出は `/resume` の判断適用点で行う。
  _Boundary:_ `patterns/hitl/src/patterns_hitl/audit.py`, `patterns/hitl/src/patterns_hitl/app.py`
  _Depends:_ 3.1
  _Requirements:_ 3.1, 3.2, 3.3, 3.4

### Implementation Notes

- フェイルソフト境界(plan.md Error Handling): 監査送出の失敗は握って続行、
  消費セマンティクス(Task 2)の失敗は loud に HTTP エラー。テストで両方向を固定する。

---

## 4. (P) 履歴のサーバー正本化(resume スキーマ強制)

_Boundary:_ `patterns/hitl/src/patterns_hitl/app.py`, `patterns/hitl/tests/unit/test_resume_schema.py`
_Depends:_ none(012 完了後)
_Requirements:_ 4.1, 4.2, 4.3

- [ ] 4.1 失敗テスト `test_resume_schema.py` を先行作成する。`/resume` body に `message_history` / `usage` / `model` / 任意の未知フィールドを含めると 422、正当 body は通る、`/run` も同様に未知フィールド拒否。再開が store の履歴のみを使うこと(リクエスト由来の履歴が実行に影響しない)をスパイで検証。**赤を確認する。**
  _Boundary:_ `patterns/hitl/tests/unit/test_resume_schema.py`
  _Depends:_ none
  _Requirements:_ 4.1, 4.2, 4.3
- [ ] 4.2 `RunRequest` / `ResumeRequest` / `Decision` に `model_config = ConfigDict(extra="forbid")` を設定しテストを緑化する(履歴系フィールドは定義しない — 定義しないこと自体が要件)。
  _Boundary:_ `patterns/hitl/src/patterns_hitl/app.py`
  _Depends:_ 4.1
  _Requirements:_ 4.1, 4.3

---

## 5. (P) SSRF/egress ポリシーゲートと README セキュリティ節

_Boundary:_ `patterns/hitl/tests/unit/test_egress_policy.py`, `patterns/hitl/README.md`
_Depends:_ none(012 完了後)
_Requirements:_ 4.4, 5.1, 5.2, 5.3, 6.3

- [ ] 5.1 `test_egress_policy.py` を作成する。レーン `src/` 全体を走査し `allow-local` / `force_download` が出現しないことを assert(WHERE 条件が発火するまでの番人 — 将来 URL 取得ツールを追加する実装者への red シグナル)。README に `safe_download` ポリシー節と R4 設計根拠節が存在することの存在検査も含める。
  _Boundary:_ `patterns/hitl/tests/unit/test_egress_policy.py`
  _Depends:_ none
  _Requirements:_ 5.1, 5.2
- [ ] 5.2 `patterns/hitl/README.md` のセキュリティ節を拡充しテストを緑化する: R4 の設計根拠(履歴サーバー正本 = CVE-2026-25580 系経路の遮断、CVE ID 明記)、SSRF/egress ポリシー(`safe_download` 必須・`allow-local` 禁止、根拠 CVE-2026-46678)、authn/authz 設計ノート(「session id は認可トークンではない。本番は認証境界の内側に置く」)、検証基準版の再掲。
  _Boundary:_ `patterns/hitl/README.md`
  _Depends:_ 5.1
  _Requirements:_ 4.4, 5.3, 6.3

---

## 6. (P) SECURITY-NOTES 追記(CVE 行 / OWASP HITL 節 / runbook)

_Boundary:_ `patterns/SECURITY-NOTES.md`
_Depends:_ none(012 完了後)
_Requirements:_ 6.1, 7.1, 7.2, 8.1, 8.2

- [ ] 6.1 「CVE 根拠と依存フロア」表を更新する: CVE-2026-25580 / CVE-2026-46678 の既存行の対応列へ HITL レーンの対応(v2 フロア `pydantic-ai-slim>=2.9.0` + R4 スキーマ遮断)を追記し、CVE-2026-61437(Web UI XSS、<1.51.0)の行を新規追加する。
  _Boundary:_ `patterns/SECURITY-NOTES.md`
  _Depends:_ none
  _Requirements:_ 6.1
- [ ] 6.2 「HITL 応用レイヤ → OWASP マッピング(Spec 013)」節を既存 4 レーンと同一表形式で追加する: 承認ゲート(requires_approval / ApprovalRequired)→ Excessive Agency / Insecure Tool Use、`UsageLimits` 停止・再開通算 → Unbounded Consumption、セッション衛生 + サーバー正本履歴 → 信頼できない入力面(LLM01 の間接経路含む)、マスク済み監査証跡 → アカウンタビリティ / 機微情報漏洩。
  _Boundary:_ `patterns/SECURITY-NOTES.md`
  _Depends:_ 6.1
  _Requirements:_ 7.1, 7.2
- [ ] 6.3 「fix 未提供アドバイザリの運用」節を追加する: 手順 (a) 修正版の不在確認 → (b) 影響レーンでの悪用可能性評価 → (c) 正当なら**レーン限定**の `--ignore-vuln <ID>` + 期限コメント + 追跡 issue → (d) 修正着地で即撤去。期限・追跡なしの抑止エントリは禁止と明記。実例として nltk / PYSEC-2026-597(2026-07、nltk 3.10.0 バンプで解消)を参照する。
  _Boundary:_ `patterns/SECURITY-NOTES.md`
  _Depends:_ 6.1
  _Requirements:_ 8.1, 8.2

---

## 7. CVE スキャン到達性ガード(root ユニットテスト)

_Boundary:_ `tests/unit/test_security_workflow_lanes.py`
_Depends:_ none(012 Task 7 の列挙面登録が前提)
_Requirements:_ 9.1, 9.2, 9.3

- [ ] 7.1 `tests/unit/test_security_workflow_lanes.py` を新規作成する(`test_ollama_ci_workflows.py` と同じ YAML パース手法)。(a) `security.yml` の `patterns-pip-audit` matrix include に `{lane: hitl, dir: patterns/hitl}` が存在、(b) `dependabot.yml` の pip `directories` に `/patterns/hitl` が存在 — 欠落は **fail red**(warn ではない)。将来レーンの追い漏れも拾えるよう、`patterns/` 直下 + `patterns/frameworks/` 直下の uv レーン(pyproject.toml 保有ディレクトリ)全列挙と matrix の集合一致で書く。
  _Boundary:_ `tests/unit/test_security_workflow_lanes.py`
  _Depends:_ none
  _Requirements:_ 9.1, 9.2, 9.3

### Implementation Notes

- 012 Task 7.2(列挙面登録)未完了の時点でこのテストは赤 — 012 と同一 PR 系列で導入する
  (research.md AD-5 の順序制約)。集合一致方式なら「hitl だけの一点検査」より汎用の
  再発防止ゲートになる(contracts は matrix に `contracts` 行が既存なので包含される)。

---

## 8. 完了ゲート(全タスク後)

- [ ] 8.1 レーン全ゲート緑(`mise run patterns:check` / `patterns:audit`、hitl の `fail_under = 98` 維持)+ root ユニット(`uv run pytest tests/unit/test_security_workflow_lanes.py`)緑。`pydantic-ai-slim>=2.9.0` フロアが lockfile に反映されていることを確認(R6.2)。
  _Boundary:_ 検証のみ(コード変更なし)
  _Depends:_ 1–7
  _Requirements:_ 6.2
