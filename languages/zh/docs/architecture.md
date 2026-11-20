<!-- doc-id: docs-architecture | lang: zh | source-rev: ec588fa9 -->

> 🌐 **中文翻译**，源文件 [`docs/architecture.md`](../../../docs/architecture.md)（rev `ec588fa9`）。以英文版为准：若两者不一致，请以英文版为准。本译文由机器翻译，尚未经母语者审校。

# 架构

## 系统概览

```mermaid
flowchart LR
    client["客户端 / 产品后端"] -->|"audio + reference_text<br/>X-API-Key"| mw
    subgraph svc["FastAPI 服务（一个进程，一个 worker）"]
        mw["中间件<br/>CORS、限流、超时、请求 ID"] --> val["鉴权 + 上传校验<br/>app/api/upload.py"]
        val --> sem["推理信号量<br/>队列，满时返回 503"]
        sem --> v1["v1 流水线<br/>Wav2Vec2 ASR, g2p, GOP, pyin"]
        sem --> v2["v2 流水线<br/>ONNX 音素 CTC，GOP 特征，学习式评分器"]
        mw --> misc["text-analysis、transcribe、<br/>model-info、health"]
    end
    v1 --> w1[("Wav2Vec2 权重<br/>内置于镜像")]
    v2 --> w2[("model.int8.onnx, vocab.json, scorer.json<br/>构建时从 HF 仓库获取")]
```

所有组件都在一个进程中运行，因为模型很大且只加载一次；额外的 uvicorn worker 会各自加载一份副本。CPU 推理由信号量（`MAX_CONCURRENT_INFERENCES`）限制，阻塞型工作在工作线程中运行，因此事件循环保持空闲。

## v1 与 v2 对比

```mermaid
flowchart TB
    subgraph V1["v1 (/api/v1/evaluate)"]
        direction TB
        a1["音频"] --> b1["Wav2Vec2 ASR<br/>字母 A-Z"]
        b1 --> c1["转写文本"]
        c1 --> d1["g2p 转 IPA，文本对齐<br/>IPA 准确度"]
        b1 --> e1["基于字母后验概率的 CTC 强制对齐<br/>GOP"]
        a1 --> f1["pyin 音高<br/>韵律"]
        d1 --> g1["手工调校的公式<br/>Azure 风格子评分"]
        e1 --> g1
        f1 --> g1
    end
    subgraph V2["v2 (/api/v2/evaluate)"]
        direction TB
        a2["音频"] --> b2["HuBERT 音素 CTC<br/>41 个 IPA 音素"]
        t2["参考文本"] --> c2["g2p 生成预期音素"]
        b2 --> d2["对预期音素<br/>做强制对齐"]
        c2 --> d2
        d2 --> e2["GOP 特征 + 识别出的音素"]
        e2 --> f2["学习式评分器<br/>基于专家评分训练"]
    end
```

| | v1 | v2 |
| --- | --- | --- |
| 评分对象 | ASR 识别出的单词 | 每个预期音素 |
| 音素证据 | 字母后验概率 | 音素后验概率 |
| 评分 | 公式（55% IPA + 45% GOP，按排序取最小值得到总分） | 从 speechocean762 专家评分中学习 |
| 韵律 / 流利度 | pyin 音高、语速、停顿 | 从对齐特征中学习（没有音高跟踪器） |
| 运行时 | PyTorch | ONNX Runtime (INT8)，v2 代码中不使用 PyTorch |
| 延迟 p50（3.4 秒音频，4 vCPU） | 381 ms | 125 ms |

## 一次 v2 请求

```mermaid
sequenceDiagram
    participant C as 客户端
    participant R as 路由 /api/v2/evaluate
    participant Q as 推理信号量
    participant S as V2 服务（工作线程）
    participant O as ONNX 音素模型
    participant Sc as 评分器
    C->>R: audio, reference_text, X-API-Key
    R->>R: 限流、API key、校验文本、大小、MIME、时长
    alt 输入无效
        R-->>C: 400 / 401 / 403 / 422 / 429
    end
    R->>R: 获取 V2 服务
    alt 模型文件缺失或损坏
        R-->>C: 503
    end
    R->>Q: 等待空闲名额（最长 60 秒）
    alt 队列超时
        Q-->>C: 503 Retry-After
    end
    Q->>S: 在线程中运行
    S->>S: 解码音频，静音检查
    S->>O: 波形
    O-->>S: 对数后验概率
    S->>S: 对齐预期音素，GOP 特征，识别出的音素
    alt 静音，或识别到的预期音素不足 20%
        S-->>C: 200 零分响应
    else 检测到语音
        S->>Sc: 逐音素特征
        Sc-->>S: 音素、单词、话语评分
        S-->>C: 200 响应，含单词 start_ms / end_ms
    end
```

服务产生的值错误（音频过短、参考文本中没有可发音的单词）会变成 `400`；任何意外错误会变成带通用消息的 `500`。

## 启动

```mermaid
flowchart TD
    s0["lifespan 开始"] --> s1["检查 TMPDIR 和缓存目录可写"]
    s1 --> s2["设置 torch 线程数（除非设置了 OMP_NUM_THREADS）"]
    s2 --> s3["API_KEY 为空时发出警告"]
    s3 --> s4["预加载 v1：ASR、IPA、GOP、韵律"]
    s4 --> s5{"预加载 v2"}
    s5 -->|ok| s6["ffmpeg 检查"]
    s5 -->|"任何错误"| s5w["记录警告；/api/v2 返回 503"] --> s6
    s6 --> s7["开始提供服务"]
```

v1 模型损坏会中止启动；v2 模型损坏或缺失则绝不会。

## 代码结构

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

各文件的详细说明：[structure.md](structure.md)。文字形式的 v1 请求流程：[workflow.md](workflow.md)。
