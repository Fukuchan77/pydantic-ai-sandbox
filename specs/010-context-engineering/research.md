# 010-context-engineering — Discovery & Research Log

`/sdd-plan` 中に作成。設計判断の根拠・調査・リスクを記録する。spec.md の ADR-1〜3
（Clarifications 確定済）を前提に、`gap-analysis.md` の選択肢を設計へ確定する。

## Discovery type

**Extension (light)**。compaction / structured note-taking のアルゴリズム（`notes.py`）は
既に実装・100% テスト済。本 spec のギャップは「アルゴリズム不在」ではなく **本線への DI シーム配線
＋ `ResearchNote` の契約昇格** に限定される。統合点（researcher reflect ループ・`patterns_contracts`・
deep-research README 正本・ドリフトテスト）の確認が discovery の主目的。

## Investigations

### digest seam の適用範囲（correctness 直結）

- **Question**: `_results_digest` を `digest_fn` シームへ差し替えるとき、reflect ループと compression
  ターンの両方に適用してよいか。
- **Findings**: `_results_digest` は **2 箇所**で呼ばれる。reflect ループ
  ([researcher.py:132](../../patterns/deep-research/src/patterns_deep_research/researcher.py#L132)) と
  compression ターン
  ([researcher.py:150](../../patterns/deep-research/src/patterns_deep_research/researcher.py#L150))。
  compression ターンの digest を compaction で縮約すると、citation 選択元の source が脱落し
  `map_citations` が `EmptyCitationError` / `DanglingCitationError` で loud-fail し得る。spec Req 1.1
  の文言（「reflect ループの digest 生成」）も reflect 限定を指す。
- **Decision**: **seam は reflect ループのみに適用**。compression ターンは full `_results_digest` を
  維持し citation grounding を保全する（→ ADR-A）。
- **Evidence**: [gap-analysis.md:49-53](gap-analysis.md)、[compression.py の map_citations 参照](../../patterns/deep-research/src/patterns_deep_research/researcher.py#L154)。

### 既定値の型反変（pyright strict）

- **Question**: seam 型 `Callable[[Sequence[SearchResult]], str]` の既定に `_results_digest` を据えられるか。
- **Findings**: 現状 `_results_digest(results: list[SearchResult])` は `list` 引数。Callable 引数は反変
  なので、`list` 引数の関数を `Sequence` 引数を要求する型へ代入すると pyright strict で不適合。
  `compact_digest` は既に `Sequence` 受け。
- **Decision**: `_results_digest` の引数型を `list[SearchResult]` → `Sequence[SearchResult]` へ**拡幅**
  （挙動不変・イテレートのみ）。`from collections.abc import Callable, Sequence` を `TYPE_CHECKING`
  ブロックへ追加。
- **Evidence**: [gap-analysis.md:54-56](gap-analysis.md)、[researcher.py:67](../../patterns/deep-research/src/patterns_deep_research/researcher.py#L67)。

### `ResearchNote` の dataclass → BaseModel 昇格波及

- **Question**: `notes.py` の frozen dataclass を `patterns_contracts` の Pydantic 契約へ移すと既存
  テスト・利用が壊れるか。
- **Findings**: 既存 `test_notes.py` は等値比較（Pydantic は `==` 対応）と kwargs 構築のみ（位置引数
  なし）で BaseModel 化に耐える。`frozen=True` を維持すればハッシュ可能性・不変性も保たれる。
  `notes.py` は契約から import する形へ変更。
- **Decision**: `ResearchNote` を `patterns_contracts.deep_research` の `BaseModel`（`frozen=True`）として
  定義し package root から再エクスポート。`notes.py` は再定義せず import 利用（NFR-3 / 案A）。
- **Evidence**: [gap-analysis.md:60-63](gap-analysis.md)、[test_notes.py:39](../../patterns/deep-research/tests/unit/test_notes.py#L39)。

### `notes` ハンドオフの carrier

- **Question**: sub-researcher → lead の「凝縮サマリ + ノート」ハンドオフを既存 `Finding` に載せるか、
  新規 carrier を作るか。
- **Findings**: `Finding` は既に summary + citations のみを運ぶハンドオフ実体で、生トランスクリプトは
  伝播しない（Req 2.2 の前半は既に満たされている）。新規 carrier は summary/citation の二重定義・
  契約数増・drift/README 追記の倍増を招く。
- **Decision**: **`Finding` に `notes: list[ResearchNote]`（既定 `[]`）を追加**。最小チャーンで Req 2.2
  を満たし、`Citation` を RAG が所有する既存判断と同型に `ResearchNote` を deep-research が所有（→ ADR-B）。
- **Evidence**: [gap-analysis.md:71-81](gap-analysis.md)（案 A 推奨）、[deep_research.py:109-123](../../patterns/contracts/src/patterns_contracts/deep_research.py#L109-L123)。

### ドリフトテストの自動適用

- **Question**: `ResearchNote` を README 正本へ追記すると Req 2.3（所有・ドリフト検証）は自動成立するか。
- **Findings**: `test_contract_drift.py` は `## パターン契約` 見出し下の `python` fence を `ast` 解析し、
  col-0 の `class X(BaseModel):` を全て拾い、**class set / field set / 1クラス=1README** を機械検証する。
  README 正本ブロックに `ResearchNote` を col-0 class として追記し、package 側に同フィールドで定義すれば
  Req 2.3 は追加コード無しで成立。`Finding` への `notes` 追記も field-set 検証が両側一致を強制。
- **Decision**: README 正本ブロックへ `ResearchNote` を `SearchResult` の直後に挿入し、`Finding` 定義へ
  `notes: list[ResearchNote]` 行を追記。
- **Evidence**: [test_contract_drift.py:91-108,239-285](../../patterns/contracts/tests/unit/test_contract_drift.py#L91-L108)、[README.md:34-92](../../patterns/deep-research/README.md#L34-L92)。

### `run_deep_research` への seam スルーパス

- **Question**: end-to-end で compaction を opt-in 有効化できるよう最上位エントリにも `digest_fn` を通すか。
- **Findings**: `run_deep_research` は内部で `run_subquestion` を呼ぶ
  ([research.py:122-130](../../patterns/deep-research/src/patterns_deep_research/research.py#L122-L130))。
  ここに `digest_fn` を通さないと、最上位から compaction を有効化する経路が無く Req 1.2 の end-to-end
  実証ができない。
- **Decision**: `run_deep_research` にも `digest_fn`（既定 `_results_digest` 相当の None スルー）を追加し、
  `run_subquestion` へ委譲する。既定は現挙動互換。
- **Evidence**: [gap-analysis.md:57-59,87](gap-analysis.md)。

## Existing patterns to reuse

| Pattern | Location | Why reuse |
|---|---|---|
| DI seam 規律（`SearchProvider` / `model` / `on_event`） | [researcher.py](../../patterns/deep-research/src/patterns_deep_research/researcher.py)、[research.py](../../patterns/deep-research/src/patterns_deep_research/research.py) | `digest_fn` を同じ「注入可能・既定で現挙動」シーム規律に揃える |
| 契約所有則（`Citation` は RAG 契約が所有） | [deep_research.py:44](../../patterns/contracts/src/patterns_contracts/deep_research.py#L44) | `ResearchNote` を deep-research README 所有で同型に追加 |
| 単一ドリフトテスト | [test_contract_drift.py](../../patterns/contracts/tests/unit/test_contract_drift.py) | README 正本＝package 一致を追加コード無しで Req 2.3 へ適用 |
| compaction アルゴリズム | [notes.py:76-155](../../patterns/deep-research/src/patterns_deep_research/notes.py#L76-L155) | dedup/score-cap/truncate/ValueError は実装・テスト済（Req 3.1-3.3）。そのまま流用 |
| hermetic テスト（`block_network` + 決定論フェイク） | [README.md:122-124](../../patterns/deep-research/README.md#L122-L124) | 新規 seam/契約テストも同方針（Req 4.1） |

## External dependencies

| Dependency | Version | Purpose | Verified |
|---|---|---|---|
| `patterns-contracts` | path dep | `ResearchNote` 契約の単一実体・再エクスポート | ✅ 既存パス依存 |
| pydantic | 既存 | `BaseModel(frozen=True)` で `ResearchNote` 昇格 | ✅ 既存 |

新規 runtime 依存の追加は **無し**（Library-First 原則充足、憲章 III）。

## Architecture decisions

### ADR-A: digest seam は reflect ループ限定（compression は full digest 維持）

- **Context**: `_results_digest` は reflect と compression の 2 箇所で使用。compression を縮約すると
  citation 選択元 source が脱落し grounding が壊れる。
- **Decision**: `digest_fn` シームを **reflect ループのみ**に適用。compression ターンは `_results_digest`
  full 出力を維持。
- **Alternatives**: reflect+compression 両適用 → `EmptyCitationError`/`DanglingCitationError` を誘発し
  citation grounding（Spec 009 不変条件）を破壊するため却下。
- **Consequences**: spec Req 1.1 文言と一致。compaction の利得（reflect プロンプト肥大抑制）を得つつ
  grounding を保全。受入条件で「compression は full digest」を固定する。

### ADR-B: `ResearchNote` は契約昇格 + `Finding.notes` 拡張（案 A）

- **Context**: note ハンドオフ carrier と契約所有の選択（gap-analysis 案 A/B/C）。
- **Decision**: `ResearchNote` を `patterns_contracts` の `BaseModel(frozen=True)` へ昇格し
  deep-research README が正本所有。`Finding` に `notes: list[ResearchNote]`（既定 `[]`）を追加し
  `distill_notes(collected)` で充填。`notes.py` は import 利用。
- **Alternatives**: (B) seam のみ／dataclass 据え置き → Req 2.1/2.3 未充足で却下。(C) 新規 carrier →
  summary/citation 二重定義・契約数増で過剰、却下。
- **Consequences**: 最小チャーンで Req 1〜5 を充足。ドリフト/カバレッジが Req 2.3 を自動検証。`Finding`
  既定 `[]` で後方互換（既存 fixtures/test/report writer を壊さない）。

### ADR-C: v1 は常時 digest 縮約、上限トリガ文脈再初期化は拡張点（spec ADR-3 を設計化）

- **Context**: Anthropic は軽量形からの compaction 導入を推奨。本レーンは決定論・byte 安定が方針。
- **Decision**: v1 は note ベースの常時縮約（cap/dedup/truncate）に限定。トークン上限近傍の文脈
  再初期化は実装せず、SECURITY-NOTES.md 記載の token-budget seam への接続を **拡張点として文書化**。
- **Alternatives**: 上限トリガの実測再初期化を v1 で実装 → 非決定的・byte 不安定で hermetic 方針に
  反するため却下。
- **Consequences**: Req 1.4 / 3.4 を満たす。docs と README に「v1 非対象」を明記（Req 5.1）。

## Risks & open questions

- ⚠️ **byte 同一性の検証粒度（Req 1.3）** — 既定 `digest_fn=_results_digest`（同一関数オブジェクト）で
  byte 一致は自明だが、回帰防止のロックテストが未存在。mitigation: FunctionModel で reflect プロンプト
  文字列を捕捉し、`_results_digest` から構築した期待文字列と完全一致をアサート（受入条件 1.3）。
- ⚠️ **`Finding.notes` 充填の常時化** — note 充填を全 research で常時行う。空 `collected` でも
  `distill_notes([])` は `[]` を返すため安全。mitigation: 空ケースの unit を追加。
- ⚠️ **契約 test の追従漏れ** — `test_deep_research_contracts.py` の `Finding.model_fields` 期待集合に
  `notes` を追加し、`ResearchNote` の reexport/field-set ケースを新設しないと drift が赤化。
  mitigation: tasks.md で契約 test 更新を明示タスク化。
- ⚠️ **凍結 6 パターン非干渉（NFR）** — 変更は deep-research README 正本ブロック・
  `patterns_contracts.deep_research`/`__init__`・deep-research レーン src/test/docs のみ。他レーン
  README・契約には触れない。mitigation: File Structure Plan で変更ファイルを限定。
- ❓ **`distill_notes` 設定の Finding.notes への露出** — v1 は既定 `max_notes`/`key_point_chars` 固定で
  充填。カスタム設定の露出は不要（digest 縮約は `compact_digest` 注入で制御）。拡張点として docstring に明記。
