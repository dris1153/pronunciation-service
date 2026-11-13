<!-- doc-id: docs-configuration | lang: ja | source-rev: e26350fb -->

> 🌐 [`docs/configuration.md`](../../../docs/configuration.md)（rev `e26350fb`）の**日本語訳**です。英語版が正です。内容が異なる場合は英語版に従ってください。機械翻訳であり、ネイティブによる校閲は受けていません。

# 設定

すべての設定は環境変数（またはプロジェクトルートから解決される `.env` のエントリ）です。名前は大文字小文字を区別しません。テンプレートは [`.env.example`](../../../.env.example)、正となる情報源は [`app/core/config.py`](../../../app/core/config.py) です。

> `.env` が受け付けるのは以下の名前だけです。未知のキー（タイプミスや、`V2_MODEL_REPO` のようなビルド専用の値）があると、起動が `extra_forbidden` で失敗します。ビルド専用の値は `.env` ではなく、ビルド環境に設定してください。

## アプリケーション

| 変数 | デフォルト | 説明 |
| --- | --- | --- |
| `APP_NAME` | `Pronunciation Validator` | OpenAPI と `model-info` に表示される |
| `APP_VERSION` | `1.0.0` | OpenAPI、`/health`、`model-info` に表示される |
| `APP_HOST` | `0.0.0.0` | バインドするアドレス |
| `PORT` | `8000` | サーバーのポート（Railway は実行時に注入する） |
| `DEBUG` | `false` | `true` にすると API キーの強度検証をスキップし、人間が読みやすい形式でログを出力する。本番では常に `false` |
| `LOG_LEVEL` | `INFO` | ログレベル。`DEBUG=false` のときは 1 レコードにつき JSON 1 行を出力する |

## v1 モデル（Wav2Vec2）

| 変数 | デフォルト | 説明 |
| --- | --- | --- |
| `ASR_MODEL_NAME` | `facebook/wav2vec2-base-960h` | Hugging Face のモデル ID。`...-large-960h-lv60-self` はアクセントに対する精度が高いが、約 1.2 GB で 1 クリップあたり約 7 秒かかる |
| `ASR_MODEL_CACHE_DIR` | `./model_cache` | モデルのキャッシュ |
| `DEVICE` | `cpu` | `cpu` または `cuda` |
| `INFERENCE_BACKEND` | `torch_fp32` | `torch_fp32` または `torch_int8`（v1 ASR 用の動的 INT8） |

## v2 音素モデル

| 変数 | デフォルト | 説明 |
| --- | --- | --- |
| `PHONE_MODEL_DIR` | `./data/models/hubert-phone-ctc` | `model.int8.onnx`（任意で `model.onnx`）、`vocab.json`、`scorer.json` を置くディレクトリ |
| `PHONE_MODEL_INT8` | `true` | `true` なら `model.int8.onnx`（約 116 MB、約 3 倍高速）をロードし、`false` なら `model.onnx`（FP32、約 360 MB）をロードする |

ファイルがない、または読み取れない場合、`/api/v2/evaluate` は `503` を返しますが、v1 には影響しません。ファイルをイメージに入れる方法: [deployment.md](deployment.md)。

## 音声

| 変数 | デフォルト | 説明 |
| --- | --- | --- |
| `AUDIO_SAMPLE_RATE` | `16000` | モデルのサンプルレート（Hz）。両パイプラインとも 16 kHz を前提とする |
| `AUDIO_MAX_DURATION_SEC` | `30` | これより長い音声は `400` で拒否される |

アップロードサイズの上限（10 MB）と受け付ける MIME タイプは、`app/core/constants.py` の定数です。

## セキュリティ

| 変数 | デフォルト | 説明 |
| --- | --- | --- |
| `API_KEY` | _（空）_ | 保護されたエンドポイント用の `X-API-Key`。`DEBUG=false` のときは必須で、32 文字以上かつ弱いキーの一覧に含まれないこと。生成方法: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `SERVICE_API_KEY` | _（空）_ | 信頼できるバックエンド向けに、エンドユーザーごとのレート制限を有効にする（`X-Service-Auth`）。[internal-integration.md](internal-integration.md) を参照 |
| `TRUSTED_PROXY_CIDRS_STR` | `172.16.0.0/12,10.0.0.0/8,192.168.0.0/16` | `X-Forwarded-For` を信頼するピア。自分のプロキシに絞り込むこと |
| `CORS_ORIGINS_STR` | `*` | カンマ区切りのオリジン（または JSON 配列）。`*` は開発専用 |

## レート制限、タイムアウト、並行実行

| 変数 | デフォルト | 説明 |
| --- | --- | --- |
| `RATE_LIMIT_ENABLED` | `true` | マスタースイッチ（テストと CI ではオフにする） |
| `RATE_LIMIT_EVALUATE_PER_MINUTE` | `20` | `/api/v1/evaluate` と `/api/v2/evaluate` のそれぞれに対する制限（各ルートが独自のカウンターを持つ） |
| `RATE_LIMIT_TRANSCRIBE_PER_MINUTE` | `15` | |
| `RATE_LIMIT_TEXT_ANALYSIS_PER_MINUTE` | `120` | |
| `REQUEST_TIMEOUT_SEC` | `90` | これより長いリクエストは `504` を返す |
| `MAX_CONCURRENT_INFERENCES` | `0` | 推論スロットの数。`0` = 自動（コア数 - 1、最大 4）。スロットあたりのスレッド数 = コア数 / スロット数。実測: 4 vCPU -> `2`、2 vCPU -> 自動（1 スロット） |
| `INFERENCE_QUEUE_TIMEOUT_SEC` | `60` | リクエストがスロットを待てる時間。超えると `Retry-After` 付きで `503` を返す |

Docker の `--cpus` や Railway では、CPU クォータがアフィニティの調査から見えません。`OMP_NUM_THREADS` に vCPU 数を設定すると、計算された値より優先されます。

## 韻律（v1 のみ）

| 変数 | デフォルト | 説明 |
| --- | --- | --- |
| `PROSODY_PITCH_MIN_HZ` / `PROSODY_PITCH_MAX_HZ` | `65` / `600` | pyin の探索範囲 |
| `PROSODY_MONOTONE_THRESHOLD` | `0.08` | ピッチの変動係数がこれを下回ると単調と判定する |
| `PROSODY_PITCH_CV_UPPER` | `0.25` | 変動係数がこの値以上なら 100 点になる。単調判定のしきい値より大きくなければならない |

## ビルド時専用（`.env` からは読み込まれない）

| 名前 | 設定場所 | 説明 |
| --- | --- | --- |
| `V2_MODEL_REPO` | Docker のビルド引数 / nixpacks のビルド変数 | v2 のファイルを置いたプライベートな Hugging Face リポジトリ。例: `dris1153/pronunciation-v2` |
| `HF_TOKEN` | Docker のビルドシークレット（`--secret id=hf_token,env=HF_TOKEN`）/ nixpacks のビルド変数 | そのリポジトリの読み取りトークン。コミットしたり、イメージのレイヤーに焼き込んだりしないこと |
| `ASR_MODEL_NAME` | Docker のビルド引数 | イメージに組み込まれる v1 モデルを上書きする |
