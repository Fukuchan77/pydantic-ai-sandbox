# 011-eval-graders — Discovery & Research Log

`/sdd-plan` で作成。承認済み要件（EARS, `requirements-generated`）を設計（HOW）へ落とす過程の
調査・決定・リスクを記録する。出力言語 `ja`（spec.json）。

## Discovery type

**Extension（既存システムへの純加算）** — `patterns_contracts` に新規契約モジュールを足し（既存契約は無改変）、初の
横断 README `patterns/EVAL-GRADERS.md` を単一点ドリフトテストへ登録する。ランタイム本線
（`OptimizationResult` / `ResearchReport` / `AgentRunResult`）は無改変。新規外部依存ゼロ（pydantic のみ）。

## Investigations

### I-1: ドリフト parser は int 値 Literal を非対称に扱う（最重要）

- **Question**: `離散 1–5 rating`（R1.2）を素朴に `Literal[1,2,3,4,5]` で型付けすると単一点ドリフトテスト
  （R4.3）はどう振る舞うか。
- **Findings**: parser は両側で **非対称**。
  - README 側 [`_annotation_literal`](../../patterns/contracts/tests/unit/test_contract_drift.py#L121-L140) は
    `isinstance(element.value, str)` の要素のみ収集 → 整数 Literal は **空集合**になる。
  - パッケージ側 [`_value_literal`](../../patterns/contracts/tests/unit/test_contract_drift.py#L203-L207) は
    `frozenset(str(arg) for arg in get_args(value))` → 整数 Literal は `{"1".."5"}` に **文字列化**される。
  - 結果 `Literal[1,2,3,4,5]` は README=`{}` ≠ package=`{"1".."5"}` で **ドリフトテストが赤化**する。
- **Evidence**: [test_contract_drift.py:121-140, 203-207](../../patterns/contracts/tests/unit/test_contract_drift.py#L121)
- **決定**: → **AD-1**（文字列 Literal 名前付きエイリアス `Rating` を採用、parser 無改修）。

### I-2: 既存契約の不変条件は pipeline 側、契約は plain shape

- **Question**: R1.5「rationale 空なら `GradeReport` 構築拒否・loud-fail」は契約内 validator か pipeline か。
- **Findings**: RAG / deep-research の grounding 不変条件（`≥1 citation`・dangling）は **pipeline** で loud-fail
  し、契約は plain shape を保つ（[rag.py:14-17](../../patterns/contracts/src/patterns_contracts/rag.py#L14)、
  [deep_research.py:24-27](../../patterns/contracts/src/patterns_contracts/deep_research.py#L24)）。ただしそれらは
  **クロスオブジェクト不変条件**（citation が実在 chunk を指す＝chunk 集合が要る）であり、validator では表せない。
  R1.5 は **単一オブジェクト内・単一フィールド非空**であり pydantic `field_validator` で完結し、文言は明確に
  「構築を拒否」。
- **Evidence**: 既存 pipeline loud-fail 例 / pydantic のみ依存で validator は依存追加なし。
- **決定**: → **AD-3**（`AxisScore.rationale` に in-contract `field_validator`）。

### I-3: 契約パッケージに seam Protocol を置く前例（`Tool`）

- **Question**: judge シーム（R3.1/3.2）を契約に置くか、レーン局所にするか。ADR-3「契約は純データ + judge 最小メタ」
  と両立するか。
- **Findings**: [`Tool` Protocol](../../patterns/contracts/src/patterns_contracts/autonomous_agent.py#L34-L49) が
  既に契約パッケージに存在し、ドリフト parser は [`_is_protocol`](../../patterns/contracts/tests/unit/test_contract_drift.py#L111-L118)
  で **スキップ**（`model_fields` を持たない）。クロスレーン一致は pyright strict が担保。ADR-3 が禁じるのは
  *`GradeReport` データ形状*への discipline フラグ混入であって、注入シーム Protocol の存在ではない（R3.1 は
  「judge シーム（注入）」を明示的に要求）。
- **Evidence**: [autonomous_agent.py:34-57](../../patterns/contracts/src/patterns_contracts/autonomous_agent.py#L34)、
  parser スキップ [test_contract_drift.py:111-118, 218-224](../../patterns/contracts/tests/unit/test_contract_drift.py#L111)
- **決定**: → **AD-4**（最小ジェネリック `Judge[SubjectT]` Protocol を `eval_graders.py` に配置）。

### I-4: レーンは別 venv で相互 import 不可 → 「3 パターン参照」検証はレーン側

- **Question**: R4.2「3 パターン eval からの参照」をどこで検証するか。
- **Findings**: 各レーンは独立 uv プロジェクトで別 venv 解決（structure.md §8）。`patterns_contracts` はレーンを
  import できず、レーン間 import も禁止。ワークフロー 2 パターン（evaluator-optimizer / autonomous-agent）は
  pydantic-ai レーンに実体 [`evaluator_optimizer.py` / `autonomous_agent.py`](../../patterns/frameworks/pydantic-ai/src/patterns_pydantic_ai/) があり、
  deep-research は単一応用レーン。フェイクは各レーン `tests/support/` がフレームワーク固有に持つ（§8.4）。
- **Evidence**: pydantic-ai レーン `tests/{unit,support}/` 既存、deep-research レーン `tests/support/`（model_fakes/fake_search/hermetic）既存。
- **決定**: → **AD-5**（pydantic-ai レーンに 2 パターン分、deep-research レーンに 1 パターン分の hermetic eval テスト + 決定論フェイク judge）。

### I-5: 横断 README は `## パターン契約` + python fence 形式を厳守

- **Question**: 初の非単一パターン README をどう正本化するか。
- **Findings**: parser は `## パターン契約` 見出し直後の最初の `python` fence を `ast` 解析する
  （[_normative_block](../../patterns/contracts/tests/unit/test_contract_drift.py#L82-L88)）。`Rating = Literal[...]`
  のような **col-0 代入**は [`_collect_named_literals`](../../patterns/contracts/tests/unit/test_contract_drift.py#L143-L158)
  が named-literal として拾う（`Route` 前例）。one-README 不変条件
  （[test_each_package_model_is_documented_in_exactly_one_readme](../../patterns/contracts/tests/unit/test_contract_drift.py#L269)）
  により `GradeReport`/`AxisScore` は EVAL-GRADERS.md のみで宣言し、他 README は **参照のみ**（`Citation` が rag 所有・
  deep-research 参照という前例と同型）。
- **Evidence**: 上記 parser 箇所 / `Citation` 再利用注記 [deep_research.py:18-22](../../patterns/contracts/src/patterns_contracts/deep_research.py#L18)
- **決定**: → **AD-1 / AD-6**。

## Existing patterns to reuse

| Pattern | Location | Why reuse |
|---|---|---|
| 文字列 `Literal` 語彙 + named alias | `verdict`/`stop_reason`/`Route`（[routing.py] 等） | parser が文字列 Literal を両側対称に扱う唯一の安全形。`Rating` を同型に。 |
| seam `Protocol`（parser スキップ） | [`Tool`](../../patterns/contracts/src/patterns_contracts/autonomous_agent.py#L34) | `Judge[SubjectT]` を同じ扱いで配置（pyright strict 担保）。 |
| 不変条件は契約外／plain shape | rag/deep-research の pipeline loud-fail | R1.5 のみ単一フィールド validator として例外的に契約内（AD-3 で理由明記）。 |
| フラット再エクスポート `__all__` | [`__init__.py`](../../patterns/contracts/src/patterns_contracts/__init__.py) | `Rating`/`AxisScore`/`GradeReport`/`Judge` を同様に公開。 |
| 契約再利用を README で参照（再宣言しない） | `Citation`（rag 所有→deep-research 参照） | EVAL-GRADERS.md 所有→3 パターン README 参照。one-README 不変条件を満たす。 |
| レーン毎フェイク（`tests/support/`） | model_fakes / fake_search / hermetic（§8.4） | 決定論フェイク `Judge` を各レーンに追加。フレームワーク固有手段。 |

## External dependencies

| Dependency | Version | Purpose | Verified |
|---|---|---|---|
| pydantic | `>=2` | 契約モデル + `field_validator` | ✅ 既存唯一依存。新規追加なし（NFR 依存ゼロ維持）。 |

## Architecture decisions

### AD-1: rating は文字列 Literal 名前付きエイリアス `Rating = Literal["1","2","3","4","5","unknown"]`

- **Context**: I-1 のとおり int Literal は parser 非対称で R4.3 と衝突。`離散 1–5 rating + Unknown`（R1.2）を
  ドリフト無改修で満たす型が必要。
- **Decision**: 文字列 Literal の **named alias** `Rating` を採用。`AxisScore.rating: Rating`。`Unknown` は
  語彙内の `"unknown"` として明示。
- **Alternatives**:
  - (b) `rating: int = Field(ge=1, le=5)` + `Unknown` を別表現（`int | None` 等）→ parser はスキップするが
    Unknown の型表現が sentinel/union に分裂し、rating 語彙がドリフト検査の **対象外**になる（カバレッジ低下）。
  - (c) `Literal[1..5]` + drift parser を int 対応に拡張 → **凍結済み共有テスト infra への変更**で他 8 契約への
    波及リスク。R4.3 を最優先制約とする方針に反する。
- **Consequences**: rating は意味的に「序数カテゴリ・ラベル」になる（算術は集約 float 側が担う）。**利点**:
  named alias `Rating` は drift `named_literals` で、`AxisScore.rating` は `field_literals` で **二重に**語彙一致
  検証される（両側とも文字列で一致）。既存 `Route`/`verdict` 等の idiom と整合。

### AD-2: スコア形状 = `outcome_scores[]` / `behavior_scores[]` の **物理分離**、集約は plain float

- **Context**: R1.2「outcome 軸と behavior 軸を **分離して保持**」、R1.3「集約は partial credit float」。
- **Decision**: `GradeReport` に `outcome_scores: list[AxisScore]` と `behavior_scores: list[AxisScore]` を
  **別フィールド**で保持（軸は所属リストで決まる＝`AxisScore` に冗長な `axis` 判別子を置かない）。
  `aggregate: float`（範囲はハーネス定義、契約は plain）。`criterion` は **自由 `str`**（spec の軸名は「例」で
  3 パターンが異なる criteria を採点、閉語彙にすると硬直化。自由 str なら criterion は drift Literal 問題に
  波及しない）。
- **Alternatives**: 単一 `list[AxisScore]` + `axis: Literal["outcome","behavior"]` 判別子 → 「分離して保持」の
  文言には filter 派生で間接的。物理分離の方が R1.2 に忠実（gap-analysis も「outcome[]/behavior[] が素直」）。
- **Consequences**: 軸の所属が型で自明。`criterion` 自由化でドリフトは `Rating` 語彙のみに限定（最小面積）。

### AD-3: R1.5 loud-fail は `AxisScore.rationale` の in-contract `field_validator`

- **Context**: I-2。文言「`GradeReport` の構築を拒否」は validator 寄り。既存は「不変条件 = pipeline」だが、
  それはクロスオブジェクト不変条件に限る。
- **Decision**: `AxisScore.rationale` に空/空白のみを拒否する `field_validator` を置く。ネストされた `AxisScore`
  構築失敗が `GradeReport` 構築失敗へ伝播し、文言「構築を拒否」を忠実に満たす。
- **Alternatives**: pipeline loud-fail（Citation 前例と一貫）→ 単一フィールド非空をわざわざ外出しする必然性が薄く、
  「構築を拒否」の文言からも遠い。
- **Consequences**: 契約が「plain shape」原則からこの 1 点だけ逸脱するが、(a) 単一フィールド・単一オブジェクトに
  閉じる、(b) pydantic のみ依存で依存追加ゼロ、(c) validator はメソッドで `model_fields` に出ないため drift parser
  非干渉、で正当化。プロジェクトの「silent empty 禁止」規律とも一致。

### AD-4: judge シームは最小ジェネリック `Judge[SubjectT]` Protocol を契約パッケージに配置

- **Context**: I-3。R3.1「被評価系と分離した judge シーム（注入）」、ADR-3「契約は純データ + judge 最小メタ」。
- **Decision**: `eval_graders.py` に `class Judge[SubjectT](Protocol): async def grade(self, subject: SubjectT, /) -> GradeReport: ...`
  を置く（`Tool` Protocol 前例）。入力 `SubjectT` は採点対象（`OptimizationResult`/`ResearchReport`/`AgentRunResult`）、
  出力は共有 `GradeReport`。独立性（別モデル注入・物理分離）は **実装規律**で担保し、型に `self_eval_forbidden`
  等のフラグは入れない（R3.3）。
- **Alternatives**: レーン局所の seam → 「注入シームの形」が 3 レーンで分裂し単一ソース化の利得が薄れる。
  契約に Protocol を一切置かない → `Tool` 前例と非対称。
- **Consequences**: drift parser は Protocol をスキップ（`Tool` と同扱い、安全）。seam 形状の単一ソース化を達成
  しつつ `GradeReport` は純データを維持。フェイク実装はレーン `tests/support/`（§8.4、AD-5）。

### AD-5: 「3 パターン参照」検証はレーン側 hermetic eval テスト（pydantic-ai ×2 + deep-research ×1）

- **Context**: I-4。別 venv 制約で contracts からレーンを import 不可。
- **Decision**: pydantic-ai レーンに evaluator-optimizer / autonomous-agent の eval テストを各 1 本、deep-research
  レーンに deep-research の eval テストを 1 本置く。各レーンに決定論フェイク `Judge` を `tests/support/` 追加し、
  ネットワーク I/O ゼロで `GradeReport` 構築形状を検証（R4.1）。deep-research の eval は `Finding.notes`
  （distill 済 `ResearchNote`）を採点対象に含め（R2.3）、空/低信号 `key_point` を faithfulness 軸の `Unknown`
  へマップする（R2.4）。
- **Alternatives**: contracts パッケージに import-site テストを集約 → レーンを import できず不成立。3 フレームワーク
  レーン全部に展開 → スコープ（3 パターン・eval 限定）超過。
- **Consequences**: 触れるレーンは 2 つ（pydantic-ai / deep-research）でパターン 3 つを網羅。contracts 側にも
  Protocol 準拠の inline フェイクで seam 形状の hermetic 検証を 1 本置く（R3.2）。

### AD-6: rubric 文言は EVAL-GRADERS.md 正本の散文に置き、契約スコア出力には載せない

- **Context**: R1.4「各 rating 段階（1–5）の意味を rubric 文言で定義（Vertex 方式）」。Vertex の rating_rubric は
  **メトリクス定義側**であってスコア出力側ではない。
- **Decision**: 1–5 各段階の rubric 定義は **EVAL-GRADERS.md 正本**（`契約基盤` subsystem の一部）に散文で置く。
  `AxisScore` は選択された `rating` + `rationale` のみ保持し、毎レポートに rubric 全文を載せない。
- **Alternatives**: 型内 `RubricLevel(level, descriptor)` → 毎インスタンスに定義文を載せ ADR-3「純データ」を濁す、
  かつ多行 rubric 文字列が drift parser を複雑化。
- **Consequences**: 契約は lean。R1.4 は `契約基盤`（= 契約 + 正本 README + ドリフトテスト）が満たす。

## Risks & open questions

- ⚠️ **drift parser 赤化（R4.3）** — AD-1 で de-risk 済。検証トレース: `Rating` 名前付きエイリアスは README
  `_collect_named_literals` とパッケージ `_value_literal` の両方で文字列語彙 `{"1".."5","unknown"}` を返し一致。
  `AxisScore.rating: Rating` の field literal も両側でエイリアス解決され一致。**mitigation**: 最初の緑化対象を
  ドリフトテストにし、`EVAL-GRADERS.md` 正本ブロックに `Rating = Literal[...]` を col-0 で必ず含める。
- ⚠️ **one-README 不変条件の初・横断ケース** — `GradeReport`/`AxisScore` を 3 パターン README に再宣言すると
  `test_each_package_model_is_documented_in_exactly_one_readme` が赤化。**mitigation**: 3 パターン README は
  EVAL-GRADERS.md を **参照のみ**（`Citation` 前例を踏襲）。
- ⚠️ **契約パッケージ coverage ratchet** — 新規 `eval_graders.py` は validator・models のフル unit 被覆が必要。
  `Judge` Protocol スタブ本体（`...`）は `Tool` 前例どおりゲート緑（Protocol は instantiate されない）。
  **mitigation**: contracts `tests/unit/test_eval_graders.py` で AxisScore/GradeReport/validator/Rating 全分岐を被覆。
- ❓ **`Judge.grade` の同期/非同期** — 実 LLM judge は I/O を伴うため `async def` を採用（`Tool.run` は同期だが
  judge は agent.run 相当の I/O を表す）。フェイクは `async` 自明実装。— design で確定済（AD-4）。
