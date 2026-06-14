# Act Phase — 008-2c-cross-platform

PDCA Act: Check の結果を再利用可能なパターン・予防策へ形式化する。
`/sdd-reflect` が生成。

## Check Phase Summary

13 タスク（Spike 含む）全てが RED→GREEN→Refactor を経て green、37/37 要件被覆、SSE レーン
カバレッジ 99.01%（gate 98）、ルートワークフロー無変更を実測確認。Plan からの逸脱は全て
「実装ソース一次確認による前提補正」（prerelease 封じ込め・`is_disconnected` の位置づけ・
98 着地）で、spec の WHAT を損なわない。CRITICAL/HIGH なし。

## Outcome

**Success** — 計画完全充足。production 準備度は「応用レイヤデモとして堅牢」（本番公開は
認証・接続上限の実体化が前提、spec Out of Scope どおり）。

## Success Pattern OR Mistake Record

### Pattern（成功）

- **Problem**: SSE / 長寿命ストリーミングエンドポイントの「クライアント早期切断 →
  サーバ側ジェネレータ停止・リソース解放」経路を、実ソケットを開かず（hermetic に）
  決定論で検証したい。だが httpx `ASGITransport` は応答を**全文バッファ**し、
  クライアント切断を `http.disconnect` として ASGI app に伝播しない。
- **Solution**: ハッピーパスは `ASGITransport`（全文バッファ取得）で検証し、**切断経路だけは
  同一 ASGI アプリを `await app(scope, receive, send)` で直接駆動**する。カスタム `receive()` が
  初回 `http.request`（ボディパース用）の後、K 件の `data:` フレーム捕捉時点で
  `{"type": "http.disconnect"}` を注入する。さらに `ScriptedEventSource(block_after=K)` で
  生成器を最内 await に park させ、anyio task-group の cancel が `except CancelledError` へ
  決定論的に届くようにして race を排除する。
- **Implementation**: `.sdd/patterns/asgi-scope-drive-disconnect-hermetic.md` 参照。
  二役 `receive`（request → disconnect インジェクタ）+ send 側フレーム計数 + hang guard
  （`wait_for` timeout→AssertionError）+ park-the-source seam の4点セット。
- **Benefits**: ネットワーク I/O ゼロ・決定論・CI 安定。`ASGITransport` の上位互換として
  切断挙動を一次確認でき、`is_disconnected` poll に依存しない真の停止経路（CancelledError）を
  exercise できる。
- **Evidence**: Task 0 spike（ADR-4 確定）、Task 7（`asgi_driver.py` + `test_disconnect_cleanup.py`
  4 ケース green、RED で 10.42s hang→timeout を実証）、lane coverage 90.36%→93.98%。
- Saved to: `.sdd/patterns/asgi-scope-drive-disconnect-hermetic.md`

## Learnings → Rules Mapping

| Learning | Candidate rule / steering update |
|----------|----------------------------------|
| `ASGITransport` は全文バッファし `http.disconnect` を伝播しない | steering/tech.md に「ストリーミング切断検証は scope 直接駆動」を追記候補 |
| 共有契約への加法的追加は README owner 登録（別タスク）まで drift テストが赤になる | per-task 完了判定は「当該タスク自身の deliverable が green」で行い、下流結合由来の赤は根本原因 + 解消タスクを明示（既存 `doc-task-throwaway-red-green-teeth` を補強） |
| 無制約 `prerelease = "allow"` は共有 pydantic を alpha へ巻き込む | beta フレームワーク導入時は runtime dep に stable 上限ピン（`pydantic>=2,<2.14`）を併用（既存 `shared-contracts-package-promotion` に追記候補） |
| Protocol で async-generator を型付けるときは非 `async def` で宣言 | tdd/型規律のチェックリストへ（`def stream(...) -> AsyncIterator[...]`） |
| `is_disconnected` は事前キャンセル peek で実質ノーオペになり得る | 停止経路は CancelledError 一本に依存させ、poll は協調的二次手段と位置づける |

## Process Improvements

- **Spike を先頭ブロッキング gate に置いた判断が奏功**: ADR-4（切断挙動）と依存重量（R-3）の
  不確実性を Wave 1 着手前に実測確定したことで、後続 6 Wave が前提のブレなく直進できた。
  外部ライブラリの「ドキュメントに無い実挙動」が成否を左右するフィーチャでは、Spike-as-gate を
  既定とする。
- **境界厳守 + 中間 RED の明示保全**: Task 2 の drift 赤を README スタブで糊塗せず Task 11 まで
  保全した。wave 計画と per-task 検証ゲートの緊張は「deliverable 自身の green + 下流解消タスク
  明示」で解消できる — この運用を tasks 生成時の標準注記にする。
- **load-bearing RED の idiom 統一**: 純テスト/設定/docs タスクでも分岐 neuter（`and False`）や
  throwaway ハーネスで teeth を立証し、即 revert（`git diff --stat` 空）で境界 net-zero を保つ
  idiom が Task 5/6/8/9/10/12 で一貫適用された。

## Next Actions

- `/sdd-validate-impl 008-2c-cross-platform` で独立検証（要件トレース・テスト実行・
  カバレッジ・回帰の再確認）。
- 本番公開を見据える場合は後続イテレーションで認証・接続あたりリソース上限・レート制限を
  実体化（spec Out of Scope / SECURITY-NOTES の「認証前提」を解消）。
- フロントエンド（EventSource クライアント）と WebSocket / 双方向は idea2-008 §3 の後続。
- steering/tech.md への「ストリーミング切断検証 = ASGI scope 直接駆動」の追記を検討。
