<!-- doc-id: docs-workflow | lang: ja | source-rev: b030953c -->

> 🌐 [`docs/workflow.md`](../../../docs/workflow.md)（rev `b030953c`）の**日本語訳**です。英語版が正です。内容が異なる場合は英語版に従ってください。機械翻訳であり、ネイティブによる校閲は受けていません。

# ワークフローとリクエストフロー

> 発音検証サービス — リクエストがどう流れるか、認証がどう機能するか、デプロイがどう構成されているか。
> セクション 1〜2 は **v1** パイプラインを説明しています。v1 と v2 の比較図、v2 のリクエストシーケンス、起動の図は [architecture.md](architecture.md) にあります。

---

## 1. アーキテクチャ概要

```
┌──────────┐     ┌──────────────────────┐      ┌─────────────────────────┐
│  Client  │────▶│   FastAPI API         │────▶│  PronunciationService   │
│ (audio + │     │  /api/v1/evaluate     │      │  (orchestrator)         │
│  text)   │     │  /api/v1/text-analysis│      └──┬──────┬──────┬──────┬─┘
└──────────┘     │  /api/v1/transcribe   │         │      │      │      │
                 │  /api/v1/model-info   │         ▼      ▼      ▼      ▼
                 └──────────────────────┘    ┌──────┐ ┌────┐ ┌────┐ ┌───────┐
                                             │  ASR │ │IPA │ │GOP │ │Prosody│
                                             │  Svc │ │Svc │ │Svc │ │  Svc  │
                                             └──┬───┘ └──┬─┘ └──┬─┘ └───┬───┘
                                                │        │      │       │
                                           Wav2Vec2   g2p_en  CTC    librosa
                                           model     + NLTK  log-    pyin
                                                             posts
```

---

## 2. リクエストフロー（POST /api/v1/evaluate）

```
Client                  FastAPI                PronunciationService        ASR / IPA / GOP
  │                       │                           │                          │
  │── POST audio+text ──▶ │                          │                          │
  │   + X-API-Key header  │                           │                          │
  │                       │── verify_api_key() ──▶ ✓ │                          │
  │                       │── validate audio type     │                          │
  │                       │── read audio bytes        │                          │
  │                       │                           │                          │
  │                       │── svc.evaluate() ────────▶│                         │
  │                       │                           │── load_audio_from_bytes()
  │                       │                           │── validate_audio_duration()
  │                       │                           │── normalize_audio()      │
  │                       │                           │                          │
  │                       │                           │── asr.get_emission() ─▶ │ Wav2Vec2 (1 pass)
  │                       │                           │◀── emission ─────────── │
  │                       │                           │── asr.decode(emission)   │
  │                       │                           │   → transcription        │
  │                       │                           │                          │
  │                       │                           │── ipa.to_ipa() ───────▶ │ g2p_en
  │                       │                           │◀── ref_ipa + act_ipa ── │
  │                       │                           │── compare phonemes       │
  │                       │                           │                          │
  │                       │                           │── gop.score(emission) ▶ │ reuses emission
  │                       │                           │◀── gop_result ───────── │
  │                       │                           │                         │
  │                       │                           │── combined_score        │
  │                       │                           │   accuracy = 0.55×IPA   │
  │                       │                           │            + 0.45×GOP   │
  │                       │                           │   completeness =        │
  │                       │                           │     accuracy-weighted   │
  │                       │                           │     ratio of ref words  │
  │                       │                           │   fluency = 0.4×rate    │
  │                       │                           │          + 0.6×pause    │
  │                       │                           │   prosody = 0.55×int    │
  │                       │                           │     + 0.20×spd+0.25×rhy│
  │                       │                           │   overall = 0.4×s0      │
  │                       │                           │    + 0.2×s1+0.2×s2     │
  │                       │                           │          + 0.2×s3       │
  │                       │                           │── error_type per word   │
  │                       │                           │   (+ break detection)   │
  │                       │                           │── level + feedback      │
  │                       │                          │                          │
  │                       │◀── PronunciationResponse ─│                         │
  │◀── JSON response ────│                           │                          │
```

### ステップごとの説明

| #   | ステップ                 | コンポーネント         | 説明                                                                                                                                                                |
| --- | ------------------------ | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **認証**                 | `dependencies.py`      | `X-API-Key` ヘッダーを検証する（`API_KEY` が空ならスキップ）                                                                                                        |
| 2   | **入力の検証**           | `pronunciation.py`     | 音声のコンテンツタイプ、ファイルサイズ（≤10 MB）、参照テキストが空でないことを確認する                                                                              |
| 3   | **音声の読み込み**       | `utils/audio.py`       | 音声バイト列をデコードし、16 kHz モノラル float32 の numpy 配列にする（librosa）                                                                                    |
| 4   | **書き起こし**           | `ASRService`           | Wav2Vec2 モデルが音声からテキストを生成する                                                                                                                         |
| 5   | **フィラーの除去**       | `utils/text.py`        | `filter_fillers(text_to_words(...))` で言いよどみの語（uh、um、hmm…）を取り除く                                                                                     |
| 6   | **IPA 変換**             | `IPAService`           | 参照テキストと書き起こしの両方を IPA 音素列に変換する                                                                                                               |
| 7   | **IPA 比較**             | `PronunciationService` | 期待される音素と実際の音素をアライメントして比較し、正確さを計算する                                                                                                |
| 8   | **GOP 採点**             | `GOPService`           | 無音チェック → CTC 対数事後確率 → 強制アライメント → 音素ごとの GOP とタイミング                                                                                    |
| 9   | **韻律分析**             | `ProsodyService`       | ピッチ抽出（pyin）→ 分散・範囲・輪郭のスコアリング → 単調さの検出                                                                                                   |
| 10  | **エラー分類**           | `PronunciationService` | 単語ごとのエラー種別: None / Mispronunciation / Omission / Insertion / UnexpectedBreak / MissingBreak                                                               |
| 11  | **サブスコア**           | `PronunciationService` | `accuracy_score` = 55% IPA + 45% GOP、`completeness_score` = 正確さで重み付けした比率、`fluency_score` = 速度 + ポーズ、`prosody_score` = イントネーション + 速度 + リズム |
| 12  | **最終スコアの算出**     | `PronunciationService` | 総合 = 0.4×s0 + 0.2×s1 + 0.2×s2 + 0.2×s3（4 つのサブスコアを低い順に並べたもの）                                                                                     |
| 13  | **レスポンス**           | `pronunciation.py`     | レベルとフィードバック付きの `PronunciationResponse` JSON を返す                                                                                                    |

---

### v2 のリクエストフロー（POST /api/v2/evaluate）

検証、認証、レート制限、推論セマフォは v1 と同じです（`app/api/upload.py`）。その後は torch を使わずに、次の流れになります。
音声のデコード → ONNX 音素 CTC（20 ms フレーム）→ numpy による CTC 強制アライメント → 音素ごとの GOP 特徴量 + 認識された音素 → 学習済みスコアラー
（音素 MLP → 単語/発話のリッジ）→ 単語タイミング付きの v1 形式のレスポンス。ブレークのエラーは、アライメントされた単語区間に v1 のポーズのルールを再利用します。

## 3. 認証フロー

```
Request with X-API-Key header
            │
            ▼
   ┌─── API_KEY set? ───┐
   │                     │
   No                   Yes
   │                     │
   ▼                     ▼
 SKIP auth        ┌── Header present? ──┐
 (dev mode)       │                     │
                  No                   Yes
                  │                     │
                  ▼                     ▼
              401 Unauthorized    ┌── Key matches? ──┐
                                  │                   │
                                  No                 Yes
                                  │                   │
                                  ▼                   ▼
                              403 Forbidden       ✅ Proceed
```

| エンドポイント              | 認証の要否                           |
| --------------------------- | ------------------------------------ |
| `GET /health`               | ❌ 不要 — ヘルスチェック用に公開     |
| `GET /docs`                 | ❌ 不要 — Swagger UI                 |
| `GET /redoc`                | ❌ 不要 — ReDoc UI                   |
| `GET /api/v1/model-info`    | ❌ 不要 — 公開のサービスメタデータ   |
| `POST /api/v1/evaluate`     | ✅ 必要 — `X-API-Key` ヘッダーが必要 |
| `GET /api/v1/text-analysis` | ✅ 必要 — `X-API-Key` ヘッダーが必要 |
| `POST /api/v1/transcribe`   | ✅ 必要 — `X-API-Key` ヘッダーが必要 |

---

## 4. アプリケーションの起動（Lifespan）

```
uvicorn starts
    │
    ▼
create_app()
    │── configure FastAPI (title, version, docs)
    │── register_middleware (CORS, exception handlers)
    │── include_router (health, pronunciation, ipa, transcribe, model_info)
    │
    ▼
lifespan() — async context manager
    │── setup_logging()
    │── get_settings()           ← load .env via absolute path
    │── check ffmpeg available   ← needed for MP3/OGG/WebM decoding
    │── get_asr_service()        ← download/load Wav2Vec2 model
    │── get_ipa_service()        ← init g2p_en + NLTK data
    │── get_gop_service()        ← init GOP scorer
    │── get_prosody_service()    ← init prosody analyser
    │── log "All models loaded ✓"
    │
    ▼
Application is ready to serve requests
    │
    ▼ (on shutdown)
    └── log "Shutting down …"
```

---

## 5. デプロイフロー

### 5a. Railway（本番）

```
git push to Railway
    │
    ▼
Railway reads railway.toml
    │── builder = "dockerfile"
    │── healthcheckPath = "/health"
    │── healthcheckTimeout = 120
    │── restartPolicyType = "on_failure"
    │
    ▼
Docker build
    │── python:3.11-slim base
    │── install ffmpeg, libsndfile1
    │── pip install CPU-only PyTorch (torch+cpu from PyTorch CPU index)
    │── pip install requirements.txt
    │── ENV ASR_MODEL_NAME (set before RUN — build-arg override works)
    │── BAKE Wav2Vec2 model into image  ← no persistent volumes on Railway
    │── ENV PORT=8000 (default; Railway overrides at runtime)
    │
    ▼
CMD ["python", "main.py"]
    │── pydantic-settings reads PORT env var → Settings.port
    │── uvicorn binds to 0.0.0.0:$PORT
    │
    ▼
Railway health check → GET /health
    │── Returns { status: "ok", version, model_loaded }
```

**要点:**

- Railway は実行時に `PORT` を注入し、pydantic-settings がそれをネイティブに読み取ります（シェルの `$PORT` 展開は不要）
- モデルはビルド時に Docker イメージに**組み込まれます**（Railway には永続ボリュームがないため）
- `--build-arg` による上書きが機能するよう、`ENV ASR_MODEL_NAME` はモデルをダウンロードする `RUN` ステップの**前**に設定します
- 環境変数（`API_KEY`、`ASR_MODEL_NAME` など）は Railway のダッシュボードで設定します
- `railway.toml` には `healthcheckPath = "/health"` と `healthcheckTimeout = 120` があります
- `startCommand` はありません — Dockerfile の CMD がそのまま使われます

---

## 6. スコアリングシステム

v1 の計算式（正確さ、完全性、流暢さ、韻律、総合、エラー種別）は [scoring-v1.md](scoring-v1.md) に、音素ネイティブの v2 のスコアリングは [scoring-v2.md](scoring-v2.md) にあります。

---

## 7. 対応する音声形式

| 形式   | MIME タイプ                              |
| ------ | ---------------------------------------- |
| WAV    | `audio/wav`, `audio/x-wav`, `audio/wave` |
| MP3    | `audio/mpeg`, `audio/mp3`                |
| OGG    | `audio/ogg`                              |
| FLAC   | `audio/flac`                             |
| WebM   | `audio/webm`                             |

すべての音声は、librosa によって **16 kHz モノラル float32** の numpy 配列に変換されます。

---

## 8. API レスポンススキーマ

v1 と v2 を含むすべてのエンドポイントのレスポンススキーマと例: [api.md](api.md)。

---

## 9. リソースのベンチマーク

v1、v2 FP32、v2 INT8 のレイテンシとメモリの実測値: [evaluation.md](evaluation.md)。サイジングとランタイムのルール: [deployment.md](deployment.md)。
