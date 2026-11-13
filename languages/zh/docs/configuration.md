<!-- doc-id: docs-configuration | lang: zh | source-rev: e26350fb -->

> 🌐 **中文翻译**，源文件 [`docs/configuration.md`](../../../docs/configuration.md)（rev `e26350fb`）。以英文版为准：若两者不一致，请以英文版为准。本译文由机器翻译，尚未经母语者审校。

# 配置

所有设置都是环境变量（或 `.env` 中的条目，从项目根目录解析）。名称不区分大小写。模板为 [`.env.example`](../../../.env.example)；权威来源为 [`app/core/config.py`](../../../app/core/config.py)。

> `.env` 只接受下面列出的名称。未知的键（拼写错误，或 `V2_MODEL_REPO` 这类仅构建时使用的值）会导致启动失败并报 `extra_forbidden`。仅构建时使用的值请放在构建环境中，不要放进 `.env`。

## 应用

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_NAME` | `Pronunciation Validator` | 显示在 OpenAPI 和 `model-info` 中 |
| `APP_VERSION` | `1.0.0` | 显示在 OpenAPI、`/health`、`model-info` 中 |
| `APP_HOST` | `0.0.0.0` | 绑定地址 |
| `PORT` | `8000` | 服务器端口（Railway 在运行时注入） |
| `DEBUG` | `false` | `true` 会跳过 API key 强度校验并使用人类可读的日志。生产环境务必为 `false` |
| `LOG_LEVEL` | `INFO` | 日志级别。`DEBUG=false` 时每条记录输出一行 JSON 日志 |

## v1 模型（Wav2Vec2）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ASR_MODEL_NAME` | `facebook/wav2vec2-base-960h` | Hugging Face 模型 id。`...-large-960h-lv60-self` 对口音更准确，但约 1.2 GB，每段音频约 7 秒 |
| `ASR_MODEL_CACHE_DIR` | `./model_cache` | 模型缓存 |
| `DEVICE` | `cpu` | `cpu` 或 `cuda` |
| `INFERENCE_BACKEND` | `torch_fp32` | `torch_fp32` 或 `torch_int8`（v1 ASR 的动态 INT8） |

## v2 音素模型

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PHONE_MODEL_DIR` | `./data/models/hubert-phone-ctc` | 包含 `model.int8.onnx`（以及可选的 `model.onnx`）、`vocab.json`、`scorer.json` 的目录 |
| `PHONE_MODEL_INT8` | `true` | `true` 加载 `model.int8.onnx`（约 116 MB，快约 3 倍）；`false` 加载 `model.onnx`（FP32，约 360 MB） |

文件缺失或无法读取时，`/api/v2/evaluate` 返回 `503`；v1 不受影响。这些文件如何进入镜像：[deployment.md](deployment.md)。

## 音频

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AUDIO_SAMPLE_RATE` | `16000` | 模型采样率（Hz）。两条流水线都假定为 16 kHz |
| `AUDIO_MAX_DURATION_SEC` | `30` | 更长的音频会被拒绝并返回 `400` |

上传大小限制（10 MB）和可接受的 MIME 类型是 `app/core/constants.py` 中的常量。

## 安全

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `API_KEY` | _（空）_ | 受保护端点使用的 `X-API-Key`。`DEBUG=false` 时必填：至少 32 个字符且不在弱密钥列表中。生成方式：`python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `SERVICE_API_KEY` | _（空）_ | 为受信任的后端启用按终端用户限流（`X-Service-Auth`）。见 [internal-integration.md](internal-integration.md) |
| `TRUSTED_PROXY_CIDRS_STR` | `172.16.0.0/12,10.0.0.0/8,192.168.0.0/16` | 其 `X-Forwarded-For` 被信任的对端。请将其收窄到你的代理 |
| `CORS_ORIGINS_STR` | `*` | 以逗号分隔的来源（或 JSON 数组）。`*` 仅用于开发 |

## 限流、超时、并发

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RATE_LIMIT_ENABLED` | `true` | 总开关（测试和 CI 中关闭） |
| `RATE_LIMIT_EVALUATE_PER_MINUTE` | `20` | `/api/v1/evaluate` 和 `/api/v2/evaluate` 各自的限制（每条路由有自己的计数器） |
| `RATE_LIMIT_TRANSCRIBE_PER_MINUTE` | `15` | |
| `RATE_LIMIT_TEXT_ANALYSIS_PER_MINUTE` | `120` | |
| `REQUEST_TIMEOUT_SEC` | `90` | 超过该时长的请求返回 `504` |
| `MAX_CONCURRENT_INFERENCES` | `0` | 推理名额数。`0` = 自动（核心数 - 1，上限 4）。每个名额的线程数 = 核心数 / 名额数。实测：4 vCPU -> `2`；2 vCPU -> 自动（1 个名额） |
| `INFERENCE_QUEUE_TIMEOUT_SEC` | `60` | 请求等待名额的最长时间，超时后返回带 `Retry-After` 的 `503` |

在 Docker 的 `--cpus` 或 Railway 下，CPU 配额对亲和性探测不可见；请将 `OMP_NUM_THREADS` 设为 vCPU 数量，它的优先级高于计算得出的值。

## 韵律（仅 v1）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PROSODY_PITCH_MIN_HZ` / `PROSODY_PITCH_MAX_HZ` | `65` / `600` | pyin 搜索范围 |
| `PROSODY_MONOTONE_THRESHOLD` | `0.08` | 音高变异系数低于该值视为单调 |
| `PROSODY_PITCH_CV_UPPER` | `0.25` | 变异系数达到或超过该值得 100 分。必须大于单调阈值 |

## 仅构建时使用（不从 `.env` 读取）

| 名称 | 位置 | 说明 |
| --- | --- | --- |
| `V2_MODEL_REPO` | Docker 构建参数 / nixpacks 构建变量 | 存放 v2 文件的私有 Hugging Face 仓库，例如 `dris1153/pronunciation-v2` |
| `HF_TOKEN` | Docker 构建 secret（`--secret id=hf_token,env=HF_TOKEN`）/ nixpacks 构建变量 | 该仓库的读取令牌。切勿提交它，也不要将其写入镜像层 |
| `ASR_MODEL_NAME` | Docker 构建参数 | 覆盖镜像中内置的 v1 模型 |
