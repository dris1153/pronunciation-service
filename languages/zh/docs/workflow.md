<!-- doc-id: docs-workflow | lang: zh | source-rev: b030953c -->

> 🌐 **中文翻译**，源文件 [`docs/workflow.md`](../../../docs/workflow.md)（rev `b030953c`）。以英文版为准：若两者不一致，请以英文版为准。本译文由机器翻译，尚未经母语者审校。

# 工作流程与请求流程

> 发音校验服务 —— 请求如何流转、鉴权如何工作、部署如何搭建。
> 第 1-2 节描述 **v1** 流水线；v1 与 v2 的对比图、v2 请求时序和启动流程见 [architecture.md](architecture.md)。

---

## 1. 架构概览

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

## 2. 请求流程（POST /api/v1/evaluate）

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

### 分步说明

| #   | 步骤                     | 组件                   | 说明                                                                                                                                                                |
| --- | ------------------------ | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **鉴权**                 | `dependencies.py`      | 校验 `X-API-Key` 请求头（`API_KEY` 为空时跳过）                                                                                                                     |
| 2   | **输入校验**             | `pronunciation.py`     | 检查音频内容类型、文件大小（≤10 MB）以及参考文本非空                                                                                                                |
| 3   | **音频加载**             | `utils/audio.py`       | 将音频字节解码为 16 kHz 单声道 float32 numpy 数组（librosa）                                                                                                        |
| 4   | **转写**                 | `ASRService`           | Wav2Vec2 模型从语音生成文本                                                                                                                                         |
| 5   | **填充词过滤**           | `utils/text.py`        | 通过 `filter_fillers(text_to_words(...))` 去除不流利的词（uh、um、hmm…）                                                                                            |
| 6   | **IPA 转换**             | `IPAService`           | 参考文本和转写文本都转换为 IPA 音素序列                                                                                                                             |
| 7   | **IPA 比较**             | `PronunciationService` | 对齐并比较预期音素与实际音素，计算准确度                                                                                                                            |
| 8   | **GOP 评分**             | `GOPService`           | 静音检查 → CTC 对数后验概率 → 强制对齐 → 逐音素 GOP + 时间信息                                                                                                      |
| 9   | **韵律分析**             | `ProsodyService`       | 音高提取（pyin）→ 方差、范围、轮廓评分 → 单调检测                                                                                                                   |
| 10  | **错误分类**             | `PronunciationService` | 每个单词的错误类型：None / Mispronunciation / Omission / Insertion / UnexpectedBreak / MissingBreak                                                                 |
| 11  | **子评分**               | `PronunciationService` | `accuracy_score` = 55% IPA + 45% GOP；`completeness_score` = 按准确度加权的比例；`fluency_score` = 语速 + 停顿；`prosody_score` = 语调 + 速度 + 节奏                  |
| 12  | **最终评分**             | `PronunciationService` | 总分 = 0.4×s0 + 0.2×s1 + 0.2×s2 + 0.2×s3（4 个子评分从低到高排序）                                                                                                  |
| 13  | **响应**                 | `pronunciation.py`     | 返回带等级和反馈的 `PronunciationResponse` JSON                                                                                                                     |

---

### v2 请求流程（POST /api/v2/evaluate）

鉴权、限流、推理信号量和校验与 v1 相同（`app/api/upload.py`），之后不涉及 torch：
音频解码 → ONNX 音素 CTC（20 ms 帧）→ numpy CTC 强制对齐 → 逐音素 GOP 特征 + 识别出的音素 → 学习式评分器
（音素 MLP → 单词/话语岭回归）→ 带单词时间戳的 v1 结构响应。停顿错误对对齐后的单词区间复用 v1 的停顿规则。

## 3. 鉴权流程

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

| 端点                        | 是否需要鉴权                         |
| --------------------------- | ------------------------------------ |
| `GET /health`               | ❌ 否 —— 公开，用于健康检查          |
| `GET /docs`                 | ❌ 否 —— Swagger UI                  |
| `GET /redoc`                | ❌ 否 —— ReDoc UI                    |
| `GET /api/v1/model-info`    | ❌ 否 —— 公开的服务元数据            |
| `POST /api/v1/evaluate`     | ✅ 是 —— 需要 `X-API-Key` 请求头     |
| `GET /api/v1/text-analysis` | ✅ 是 —— 需要 `X-API-Key` 请求头     |
| `POST /api/v1/transcribe`   | ✅ 是 —— 需要 `X-API-Key` 请求头     |

---

## 4. 应用启动（Lifespan）

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

## 5. 部署流程

### 5a. Railway（生产）

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

**要点：**

- Railway 在运行时注入 `PORT` —— pydantic-settings 原生读取它（不需要 shell 的 `$PORT` 展开）
- 模型在构建时被**内置**到 Docker 镜像中（Railway 没有持久卷）
- `ENV ASR_MODEL_NAME` 设置在 `RUN` 模型下载步骤**之前**，因此 `--build-arg` 的覆盖有效
- 环境变量（`API_KEY`、`ASR_MODEL_NAME` 等）在 Railway 控制台中设置
- `railway.toml` 中有 `healthcheckPath = "/health"` 和 `healthcheckTimeout = 120`
- 没有 `startCommand` —— 直接使用 Dockerfile 中的 CMD

---

## 6. 评分系统

v1 的公式（准确度、完整度、流利度、韵律、总分、错误类型）见 [scoring-v1.md](scoring-v1.md)；音素原生的 v2 评分见 [scoring-v2.md](scoring-v2.md)。

---

## 7. 支持的音频格式

| 格式   | MIME 类型                                |
| ------ | ---------------------------------------- |
| WAV    | `audio/wav`, `audio/x-wav`, `audio/wave` |
| MP3    | `audio/mpeg`, `audio/mp3`                |
| OGG    | `audio/ogg`                              |
| FLAC   | `audio/flac`                             |
| WebM   | `audio/webm`                             |

所有音频都通过 librosa 转换为 **16 kHz 单声道 float32** numpy 数组。

---

## 8. API 响应结构

每个端点（v1 和 v2）的响应结构和示例：[api.md](api.md)。

---

## 9. 资源基准测试

v1、v2 FP32 和 v2 INT8 的实测延迟和内存：[evaluation.md](evaluation.md)。资源规格和运行规则：[deployment.md](deployment.md)。
