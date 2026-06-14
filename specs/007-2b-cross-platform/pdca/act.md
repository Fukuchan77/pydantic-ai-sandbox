# Act Phase — 007-2b-cross-platform

PDCA Act: Check の学びを再利用パターン・予防策へ形式化する。`/sdd-reflect` が生成。

## Check Phase Summary

初の応用レイヤ（RAG）を独立 uv レーン `patterns/rag/` として 13 タスクで完遂し、
`/sdd-validate-impl` は CRITICAL ゼロで **GO**。要件 41/41 トレース・RAG カバレッジ
100%（gate 98）・ルート無変更グリーン（277 passed）。spike が委ねた2論点（配置・tokenizer）は
いずれも実装フェーズの実測で確定し、hermetic 主張は cold-cache + ネット遮断で立証した。

## Outcome

**Success**

## Success Pattern OR Mistake Record

### Pattern（成功）

- **Problem**: 依存閉包に存在する「オフライン依存」（tiktoken 等）が cold cache では
  ネット DL し、hermetic CI で初めて落ちる。spike の「追加依存ゼロ」推論は採否の十分条件でない。
- **Solution**: (A) hermetic 主張は cache 無効化 + ネット遮断で**実測**確定、(B) 実物コア
  （HybridChunker）は保ちつつ tokenizer/embed/llm を **DI seam** に切り決定論オフライン実装を注入、
  (C) hermetic ガード本体に load-bearing テストで teeth を持たせる。
- **Implementation**: `chunk_document(..., tokenizer: BaseTokenizer, max_tokens)` で seam 化、
  unit は資産ゼロの `WordTokenizer` を注入。`block_network` フィクスチャは AF_INET/AF_INET6 の
  connect/getaddrinfo のみ遮断（AF_UNIX 素通し）+ ガード下 connect の `NetworkReachError` を実証。
- **Benefits**: flakiness ゼロの golden 安定・実物挙動の保持・将来の hermetic 崩壊を loud-fail。
- **Evidence**: do.md Task 3（cl100k_base `ProxyError` 実測）/ Task 9（ガード teeth）、
  chunking.py 100%・全 run ネットワークゼロ。
- Saved to: `.sdd/patterns/hermetic-tokenizer-di-seam.md`

## Learnings → Rules Mapping

| Learning | Candidate rule / steering update |
|----------|----------------------------------|
| 「閉包に居る」≠「hermetic」。spike の暫定は実測で覆り得る | tech.md §6「カバレッジ ratchet」近傍に「hermetic 主張は cache 無効化 + ネット遮断で実測してから確定」を1行追記候補（既存 §8 の hermetic 規律を補強） |
| 非決定論・ネット依存の重い境界は tokenizer も含め DI seam に切る | 新パターン `hermetic-tokenizer-di-seam` で形式化済（steering 追記は不要、Golden Rule） |
| 契約 package 追加（Task 2）→ 正本記載（Task 11）の DAG 分離は計画済み RED 窓を生む | 既存 [[shared-contracts-package-promotion]] / [[doc-task-throwaway-red-green-teeth]] の射程内。fix-forward 禁止・所有タスクで閉鎖を再確認（新規 steering 不要） |
| DAG の未配線ギャップは「未配線 + 後続所有者明記」で前進（Task 7.3 tracing 再エクスポート→Task 8 待ち） | 境界規律の既存運用どおり。act の Process Improvements に運用注記 |

## Process Improvements

- **spike の結論に「確定 / 暫定（実装で実測）」のラベルを付ける**。Task 0 の tiktoken 採否は
  暫定だったが主策表現が強く、Task 3 で覆る際に方針転換コストが生じた。spike ノートに
  「hermetic 可否は実装 Task で実測確定」と明示すれば手戻りの心理的コストを下げられる。
- **計画済み RED 窓は tasks.md に「RED 窓: Task X が開き Task Y が閉じる」を明記**して運用継続。
  007 では Implementation Notes に都度記録され機能した（Task 9 の contracts 停止も既知ギャップと
  判別できた）。この明示運用を次サイクルでも標準とする。
- 重い/非決定論な upstream を使う前に **1巡通す事前 spike**（Task 7/8 の astructured_predict・
  span 名実測）が方針確定を前倒しした。TDD 前の de-risk spike を引き続き標準動作とする。

## Next Actions

- `/sdd-reflect` 完了 → ブランチ `007-cross-pratform` の PR 化（CI gated env で結合 live-green を確認）。
- 後続イテレーション（idea2-007 §3 / idea2-006 §2c–2e）: マルチモーダルチャンク化・再ランキング・
  PydanticAI/BeeAI への RAG 移植・FastAPI SSE（spec 008 既に draft 起票済み）・A2A/ACP・Evals CI。
- `hermetic-tokenizer-di-seam` パターンは llamaindex レーン等、HF/tiktoken backed ライブラリを
  使う他レーンの hermetic 化にも横展開可能 — 該当時に参照する。
