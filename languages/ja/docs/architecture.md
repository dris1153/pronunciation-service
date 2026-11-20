<!-- doc-id: docs-architecture | lang: ja | source-rev: ec588fa9 -->

> 🌐 [`docs/architecture.md`](../../../docs/architecture.md)（rev `ec588fa9`）の**日本語訳**です。英語版が正です。内容が異なる場合は英語版に従ってください。機械翻訳であり、ネイティブによる校閲は受けていません。

# アーキテクチャ

## システム概要

```mermaid
flowchart LR
    client["クライアント / プロダクトのバックエンド"] -->|"audio + reference_text<br/>X-API-Key"| mw
    subgraph svc["FastAPI サービス（1 プロセス、1 ワーカー）"]
        mw["ミドルウェア<br/>CORS、レート制限、タイムアウト、リクエスト ID"] --> val["認証 + アップロード検証<br/>app/api/upload.py"]
        val --> sem["推論セマフォ<br/>キュー、満杯時は 503"]
        sem --> v1["v1 パイプライン<br/>Wav2Vec2 ASR、g2p、GOP、pyin"]
        sem --> v2["v2 パイプライン<br/>ONNX 音素 CTC、GOP 特徴量、学習済みスコアラー"]
        mw --> misc["text-analysis、transcribe、<br/>model-info、health"]
    end
    v1 --> w1[("Wav2Vec2 の重み<br/>イメージに組み込み済み")]
    v2 --> w2[("model.int8.onnx、vocab.json、scorer.json<br/>ビルド時に HF リポジトリから取得")]
```

モデルは大きく、一度だけロードされるため、すべてが 1 つのプロセスで動作します。uvicorn のワーカーを増やすと、ワーカーごとにモデルのコピーをロードしてしまいます。CPU 推論はセマフォ（`MAX_CONCURRENT_INFERENCES`）で上限が決まり、ブロッキングする処理はワーカースレッドで実行されるため、イベントループは空いたままになります。

## v1 と v2 の比較

```mermaid
flowchart TB
    subgraph V1["v1 (/api/v1/evaluate)"]
        direction TB
        a1["音声"] --> b1["Wav2Vec2 ASR<br/>文字 A-Z"]
        b1 --> c1["書き起こし"]
        c1 --> d1["g2p で IPA へ、テキストのアライメント<br/>IPA 正確さ"]
        b1 --> e1["文字事後確率に対する CTC 強制アライメント<br/>GOP"]
        a1 --> f1["pyin ピッチ<br/>韻律"]
        d1 --> g1["手動で調整した計算式<br/>Azure 方式のサブスコア"]
        e1 --> g1
        f1 --> g1
    end
    subgraph V2["v2 (/api/v2/evaluate)"]
        direction TB
        a2["音声"] --> b2["HuBERT 音素 CTC<br/>41 個の IPA 音素"]
        t2["参照テキスト"] --> c2["g2p で期待される音素へ"]
        b2 --> d2["期待される音素の<br/>強制アライメント"]
        c2 --> d2
        d2 --> e2["GOP 特徴量 + 認識された音素"]
        e2 --> f2["学習済みスコアラー<br/>専門家スコアで学習"]
    end
```

| | v1 | v2 |
| --- | --- | --- |
| 採点の単位 | ASR で認識された単語 | 期待される各音素 |
| 音素の根拠 | 文字の事後確率 | 音素の事後確率 |
| スコア | 計算式（55% IPA + 45% GOP、ソートした最小値による総合スコア） | speechocean762 の専門家スコアから学習 |
| 韻律 / 流暢さ | pyin ピッチ、発話速度、ポーズ | アライメント特徴量から学習（ピッチトラッカーなし） |
| ランタイム | PyTorch | ONNX Runtime（INT8）、v2 のコードに PyTorch はなし |
| レイテンシ p50（3.4 秒のクリップ、4 vCPU） | 381 ms | 125 ms |

## v2 リクエスト 1 件の流れ

```mermaid
sequenceDiagram
    participant C as クライアント
    participant R as ルート /api/v2/evaluate
    participant Q as 推論セマフォ
    participant S as V2 サービス（ワーカースレッド）
    participant O as ONNX 音素モデル
    participant Sc as スコアラー
    C->>R: audio, reference_text, X-API-Key
    R->>R: レート制限、API キー、テキスト・サイズ・MIME・長さの検証
    alt 入力が不正
        R-->>C: 400 / 401 / 403 / 422 / 429
    end
    R->>R: V2 サービスを取得
    alt モデルファイルがない、または破損
        R-->>C: 503
    end
    R->>Q: スロットを待つ（最大 60 秒）
    alt キューのタイムアウト
        Q-->>C: 503 Retry-After
    end
    Q->>S: スレッドで実行
    S->>S: 音声をデコード、無音チェック
    S->>O: 波形
    O-->>S: 対数事後確率
    S->>S: 期待される音素のアライメント、GOP 特徴量、認識された音素
    alt 無音、または期待される音素の 20% 未満しか認識されない
        S-->>C: 200 ゼロスコア応答
    else 発話あり
        S->>Sc: 音素ごとの特徴量
        Sc-->>S: 音素、単語、発話のスコア
        S-->>C: 200 単語の start_ms / end_ms 付きレスポンス
    end
```

サービスが返す値エラー（音声が短すぎる、発音可能な単語がない参照テキスト）は `400` になります。予期しないエラーは汎用的なメッセージ付きの `500` になります。

## 起動

```mermaid
flowchart TD
    s0["lifespan 開始"] --> s1["TMPDIR とキャッシュディレクトリが書き込み可能か確認"]
    s1 --> s2["torch のスレッド数を設定（OMP_NUM_THREADS がある場合を除く）"]
    s2 --> s3["API_KEY が空なら警告"]
    s3 --> s4["v1 をプリロード: ASR、IPA、GOP、韻律"]
    s4 --> s5{"v2 をプリロード"}
    s5 -->|ok| s6["ffmpeg を確認"]
    s5 -->|"any error"| s5w["警告をログ出力、/api/v2 は 503 を返す"] --> s6
    s6 --> s7["サービス開始"]
```

v1 モデルに問題があると起動が止まりますが、v2 モデルが壊れている、またはない場合に起動が止まることはありません。

## コード構成

```
app/
  application.py            FastAPI factory + lifespan (model preload)
  api/
    routes/                 health, ipa, model_info, pronunciation (v1), pronunciation_v2, transcribe
    dependencies.py         API key, service lookup (v1, v2 with 503)
    middleware.py           CORS, rate limit, timeout, exception handlers
    upload.py               upload + reference text validation shared by v1 and v2
  core/                     config (pydantic-settings), concurrency, constants, logging
  models/schemas.py         Pydantic schemas (v1 and additive V2 subclasses)
  services/
    pronunciation_service.py  v1 orchestrator
    asr_service.py, gop_service.py, ipa_service.py, prosody_service.py   v1 components
    phoneme_align.py        phone similarity groups + DP alignment (no torch, shared)
    scoring_rules.py        level/feedback, error types, break detection (no torch, shared)
    v2/
      phone_model.py        ONNX session -> log-posteriors
      ctc_align.py          numpy CTC forced alignment
      gop_features.py       GOP features, heard phones
      scorer.py             numpy phone MLP + word/utterance ridge
      analyser.py           audio + text -> V2Analysis
      pronunciation_v2_service.py   response assembly, gates, score curve
  utils/                    audio I/O, text normalisation
training/                   offline training and export (own CUDA venv, not imported by app/)
scripts/                    evaluation harness, sanity set, HF upload
debugs/                     benchmark and diagnostics
tests/                      pytest suite (+ synthetic sanity recordings)
```

ファイルごとの詳細: [structure.md](structure.md)。v1 のリクエストフローをテキスト形式で説明したもの: [workflow.md](workflow.md)。
