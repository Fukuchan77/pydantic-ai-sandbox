# 013-agentic-ai-security — 実装ギャップ分析

承認済み要件(spec.md)を **実装・マージ済みの 012 HITL レーン**の現状コードへ突き合わせ、
plan.md / tasks.md(生成済み・tasks 未承認)の前提を検証する。決定ではなく情報と選択肢を提示する。
出力言語 `ja`、コード識別子は英語。

> 本分析は plan/research/tasks が生成された **後**に実行されている。したがって主眼は「白紙からの設計」ではなく、
> **012 が merge されたことで前提がどう変わったか**の検証にある。結論を先に述べると:
> plan の骨子(012 拡張 + 対称文書追記)は妥当だが、**複数要件が 012 で既充足**でありスコープを縮小でき、
> **R9 の "赤先行" 前提が陳腐化**している。

## 分析サマリ

- **スコープ縮小の余地**: R6.2(依存フロア)/ R6.3(検証基準版)/ R9.1(security.yml 登録)/ R9.2(dependabot 登録)は
  **012 実装で既に充足済み**。plan.md の FloorConstraint / ScanReachabilityGuard は "新規実装" ではなく "検証(ガード化)" が実体。
- **真の新規実装は 2 コンポーネント**: R2(消費セマンティクスの状態機械 + HTTP 写像)と R3(監査証跡 `audit.py`)のみが
  未着手のロジック。他は「文書追記」「スキーマ 1 行」「grep ガードテスト」といった低リスク差分。
- **R9 の TDD 前提が陳腐化**: research.md AD-5 / tasks 実装ノートは「012 Task 7.2 未完了で赤 → 同一 PR 系列で導入」を仮定するが、
  012 は merge 済みで `hitl` が security.yml matrix(L162)・dependabot(L91)の両方に登録済み。
  ガードテストは **初回作成時点で緑**になる。TDD の "赤" を別手段で示す必要がある(下記 approach で詳述)。
- **既存の軽微な要件違反が 1 件**: 現行 app.py の 404 本文は `f"unknown session_id: {exc.args[0]}"` で
  **session id を漏洩し理由を明示**しており(app.py:202)、R1.2(存在秘匿・理由非区別)に反する。R1/R2 実装で必ず是正する。
- **README の SSRF/CVE ノートは "013 でやる" の記述**: 既に足場はあるが CVE ID 引用がなく、013 完了後の文面へ書き換えが要る(R4.4/R5.3)。

## 要件別ギャップ表

| Req | 分類 | 証拠(file:line)と現状 |
|---|---|---|
| **1.1** CSPRNG id | 🔧 実質充足・要集約 | `store.py:60` が `str(uuid4())` を `create()` 内でインライン生成(CSPRNG)。plan の `new_session_id()` 一元化は未実施 |
| **1.2** 未知 id は 404・存在秘匿 | 🔧 **要是正** | `app.py:200-203` は 404 を返すが本文が `unknown session_id: <id>` で理由と id を漏洩。固定本文へ変更が必要 |
| **1.3** 同一 prompt → 非連続 id テスト | 🆕 欠落 | `test_session_hygiene.py` 不在(`tests/unit/` 未存在) |
| **2.1** 終端後 session 失効 | 🆕 欠落 | `store.py` に `state` / `consume()` なし。`update()`(L79)は永続的に session を生かし続ける |
| **2.2** 再 defer で旧判断再適用不可 | 🔧 部分 | `harness.resume()`(harness.py:125)は再 defer を `PendingResult` で返すが `pending_call_ids` 追跡なし。旧 `tool_call_id` の再送を弾けない |
| **2.3** pending 外 id → 409・実行なし | 🆕 欠落 | `app.py:194-199` は全 decisions を無検証で `DeferredToolResults` へ流す。pending 集合検証なし |
| **2.4** 予算超過 → 429 + 失効 | 🔧 基盤あり | `harness.py:37` に lane 所有 `HitlBudgetExceededError` あり(R2.4 写像の土台)。だが `app.py` の `/resume` は `KeyError` のみ捕捉(L200)、この例外は未捕捉 → 現状 500 に落ちる |
| **3.1–3.5** 承認監査証跡 | 🆕 全欠落 | `audit.py` 不在。`observability.py`(fail-soft logfire)が R3.4 の設計雛形として存在 |
| **4.1/4.3** `extra="forbid"` + 履歴非受理 | 🆕 欠落 | `RunRequest`(app.py:58)/`ResumeRequest`(L114)/`Decision`(L87)いずれも `ConfigDict(extra="forbid")` 未設定 → 未知フィールドを黙殺 |
| **4.2** 履歴はサーバー正本 | ✅ 既充足 | `harness.resume()`(harness.py:147-155)は `record.history` / `record.usage` のみ使用。`ResumeRequest` に履歴フィールドは元々ない |
| **4.4** README に CVE 根拠 | 🔧 部分 | `README.md:113-116` に SSRF ノートあるが CVE-2026-25580/46678 の **ID 引用なし** + 「egress 強化は 013 のスコープ(未実装)」の記述。013 完了後の文面へ要更新 |
| **5.1/5.2** `safe_download` 必須・`allow-local` 禁止 | 🆕 ガード欠落 | MVP に URL 取得ツールなし(WHERE 未発火)。`test_egress_policy.py` の grep 番人が未存在 |
| **5.3** README に CVE-2026-46678 根拠 | 🔧 部分 | R4.4 と同様、`safe_download` 言及はあるが CVE ID 引用なし(README.md:113-116) |
| **6.1** SECURITY-NOTES CVE 行 | 🔧 部分 | `SECURITY-NOTES.md:9-10` に 25580/46678 行あるが対応列が frameworks 文脈(`>=2.0.0b6`)。HITL 固有対応の追記が必要。CVE-2026-61437(Web UI XSS)行は **不在** |
| **6.2** pyproject フロア v2 | ✅ **既充足** | `pyproject.toml:29` が `pydantic-ai-slim[openai]>=2.9.0`。uv.lock も `specifier = ">=2.9.0"` 確認済み。downgrade は解決失敗で loud |
| **6.3** 検証基準版の記録 | ✅ **既充足** | `README.md:148-152` が「pydantic-ai-slim 2.9.0 / 2026-07-11」を明記(012 R13.3 で導入済み) |
| **7.1/7.2** OWASP HITL 節 | 🆕 欠落 | `SECURITY-NOTES.md` に autonomous/RAG/SSE/Deep Research の 4 節(L29-121)はあるが HITL 節なし |
| **8.1/8.2** no-fix advisory runbook | 🆕 欠落 | SECURITY-NOTES に該当節なし(末尾は Accepted Risk 表 L135-141) |
| **9.1** security.yml 登録の検証 | 🔧 **対象は既登録・検証未実装** | `security.yml:162` に `{lane: hitl, dir: patterns/hitl}` 既存。検証テスト `test_security_workflow_lanes.py` が未存在 |
| **9.2** dependabot 登録の検証 | 🔧 **対象は既登録・検証未実装** | `dependabot.yml:91` に `/patterns/hitl` 既存。検証テスト未存在 |
| **9.3** 欠落は fail red | 🆕 ガード欠落 | 上記テストが集合一致で赤化する仕組みが未実装 |

**分類集計**: ✅ 既充足 3(4.2, 6.2, 6.3) / 🔧 部分・要是正 9 / 🆕 新規 9。
純粋な新規ロジックは **R2 状態機械** と **R3 audit.py** の 2 つに集約される。

## アプローチ選択肢

plan.md は既に「012 拡張 + 対称文書追記」(全体方針)を選んでいる。分析の結果この骨子は妥当。
以下は **plan の前提が変わった 2 論点**についての選択肢である。

### 論点 A: R9 ガードテストの TDD "赤" をどう成立させるか(research.md AD-5 が陳腐化)

| 選択肢 | 適合条件 | コスト | リスク |
|---|---|---|---|
| **A1: 集合一致ガード + 「一時削除で赤確認」を PDCA に記録**(推奨) | 対象が既登録済み(=現状) | 低 | 赤の証跡が手動手順依存。PDCA ログに削除→赤→復元を明記すれば TDD 規律を満たす |
| A2: 「hitl 一点」でなく `patterns/` 全 uv レーン列挙 vs matrix の集合一致で書く | 将来レーンの追い漏れも拾いたい(tasks 7.1 が既に採用) | 低 | 現行 8 レーンの列挙が正確である必要。contracts 行の扱いに注意 |
| A3: R9 を「テストではなく documented checklist」で満たす(spec 9.1 は "test or checklist" を許容) | テストの赤先行が形骸化する場合 | 最低 | 機械ガードでなくなり nltk 事案の再発防止力が下がる。非推奨 |

推奨は **A1+A2 併用**(tasks 7.1 の集合一致方式を維持し、赤は一時削除で PDCA に記録)。
research.md AD-5 の「012 と同一 PR 系列」制約は **もはや不要**(012 merge 済み)——この記述は tasks 実装ノートから削除・訂正すべき。

### 論点 B: R6.2/6.3 が既充足のため FloorConstraint コンポーネントの実体をどう扱うか

| 選択肢 | 適合条件 | コスト | リスク |
|---|---|---|---|
| **B1: FloorConstraint を「新規制約」でなく「回帰ガードの確認」に格下げ**(推奨) | フロア・検証基準版が既に正しい(=現状) | 最低 | tasks 8.1 の「lockfile 反映確認」で足りる。plan の記述を実態に合わせる |
| B2: フロアを明示的に検証するユニットテストを追加(pyproject を読み `>=2.9.0` を assert) | フロアの意図しない緩和を機械検知したい | 低 | 過剰。downgrade は uv 解決が既に loud に失敗する |

推奨は **B1**。R6 の実装作業は実質「SECURITY-NOTES / README への CVE 追記(R6.1)」のみに縮小する。

## plan 前提とのズレ(訂正候補)

1. **research.md AD-5**「012 Task 7.2 未完了 → 赤 → 同一 PR 系列」: 012 merge 済みのため陳腐化。security.yml/dependabot は既登録。
2. **plan.md FloorConstraint**「`>=2.9.0` をフロアに」: **既に実装済み**(pyproject.toml:29)。新規作業ではない。
3. **plan.md ReadmeSecurityNotes / R6.3**「検証基準版の再掲」: **既に README.md:148-152 に存在**。013 では文面更新(013 完了の反映)にとどまる。
4. **既存違反**: app.py:202 の 404 本文が R1.2 に反する。tasks 1/2 で必ず是正対象に含める(tasks 2.1(a) の「固定文言」に対応)。
5. **SECURITY-NOTES 既存行の陳腐化**: L9-10 の対応列が `>=2.0.0b6`(beta)文脈、Accepted Risk 表 L139 も「v2 Beta 採用/GA 時に見直し」。HITL は `>=2.9.0`。R6.1 追記時にこの不整合の扱い(併記 or 更新)を判断する。

## plan フェーズで深掘りが要る領域

- **R2.3 の "実行前拒絶" の実装点**: pending 集合検証を `app.py`(harness 呼出前)で行うか `harness.resume` 入口で行うか。
  「どのツールも実行されない」をスパイで立証する必要(tasks 2.1(b))。harness は `DeferredToolResults` を組む前に検証する構造が自然。
- **R2.4 の 429 写像**: `app.py` の `/resume`(および `/run`)で `HitlBudgetExceededError` を捕捉し 429 + `consume()`。
  現状 `/run` も未捕捉のため、`/run` 側の予算超過(start 時)の HTTP 写像も 013 が拾うか要確認(spec 2.4 は "run or resume" と明記 → 両方)。
- **R2.1/R2.2 の状態機械の並行制御**: インメモリ MVP で同一 session への同時 `/resume` の先勝ち(plan は `claim()` 同期区間)。
  `asyncio` 単一イベントループ前提での "同期区間" の意味(await を挟まない claim→consume)を設計で確定する。
- **R3 の送出点とマスキング**: 1 判断 = 1 イベントを「判断適用の直前/直後」どちらで送るか、
  `override_args` のキー抽出を Decision→AuditEvent 変換のどこで行うか(生値がイベントに乗らない不変条件をテストで固定)。
- **R6.1 の既存行整合**: 上記ズレ 5。既存 25580/46678 行を HITL 文脈へ拡張する際の表構造(対応列にレーン別記述を併記する既存様式)を確認。

## Next Steps

- 本ギャップ分析は **plan/research/tasks の訂正材料**として機能する(通常の "plan 前" 実行ではなく事後検証のため)。
- 推奨アクション:
  1. tasks.md の R9 実装ノート(「012 と同一 PR 系列」「未完了で赤」)を **訂正**(論点 A / ズレ 1)。
  2. plan.md FloorConstraint / R6.3 の記述を「既充足の確認」へ **格下げ**(論点 B / ズレ 2・3)。
  3. tasks 1/2 に app.py:202 の 404 本文是正が含まれることを確認(ズレ 4)。
  4. 上記反映後、`spec.json` の `tasks.approved` を true にして `/sdd-impl 013-agentic-ai-security` へ進む。
- スコープ実体は **R2 状態機械 + R3 audit.py の 2 コンポーネント**に集約され、残りは低リスクな文書追記・スキーマ 1 行・grep/YAML ガードテスト。純加算・新規依存ゼロの plan 方針は維持できる。
