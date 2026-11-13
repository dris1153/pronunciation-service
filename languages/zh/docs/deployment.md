<!-- doc-id: docs-deployment | lang: zh | source-rev: c9e42585 -->

> 🌐 **中文翻译**，源文件 [`docs/deployment.md`](../../../docs/deployment.md)（rev `c9e42585`）。以英文版为准：若两者不一致，请以英文版为准。本译文由机器翻译，尚未经母语者审校。

# 部署

一个容器同时提供两条流水线。v1 权重来自 Hugging Face 公共仓库；v2 文件（`model.int8.onnx`、`vocab.json`、`scorer.json`）来自一个**私有** Hugging Face 仓库。两者都在构建时内置到镜像中（无需持久卷）。

```mermaid
flowchart LR
    train["training/（GPU 机器）"] -->|"export_onnx --int8<br/>train_scorer"| files["model.int8.onnx<br/>vocab.json<br/>scorer.json"]
    files -->|"scripts/upload_v2_model.py<br/>(HF_TOKEN, 写权限)"| hf[("私有 HF 仓库<br/>dris1153/pronunciation-v2")]
    hf -->|"download_model.py<br/>V2_MODEL_REPO + HF_TOKEN"| build["docker build /<br/>nixpacks build"]
    pub[("facebook/wav2vec2-base-960h<br/>（公开）")] -->|"download_model.py"| build
    build --> img["镜像：/app/model_cache<br/>+ /app/data/models/hubert-phone-ctc"]
    img --> run["python main.py<br/>（1 个 uvicorn worker）"]
```

## 一次性操作：发布 v2 文件

需要 Hugging Face 账号和具有**写**权限的令牌。

```powershell
$env:HF_TOKEN = "hf_xxx"          # write token, never commit it
python scripts/upload_v2_model.py --repo dris1153/pronunciation-v2
```

脚本会将仓库创建为私有（不会把已有的公开仓库改为私有），并从 `data/models/hubert-phone-ctc/` 上传这三个文件。请为构建另外创建一个**读**令牌。

## Docker

```bash
# v1 only (v2 endpoint will answer 503)
docker build -t pronunciation-validator .

# v1 + v2: the token travels as a BuildKit secret, so it never lands in an image layer
docker build \
  --build-arg V2_MODEL_REPO=dris1153/pronunciation-v2 \
  --secret id=hf_token,env=HF_TOKEN \
  -t pronunciation-validator .

docker run -p 8000:8000 -e API_KEY=<32+ char key> -e DEBUG=false pronunciation-validator
```

镜像的构建内容：`python:3.11-slim` + ffmpeg/libsndfile、仅 CPU 的 PyTorch（v1）、`requirements.txt`（包含供 v2 使用的 `onnxruntime`），运行 `download_model.py`（先下载 v1 模型，设置了 `V2_MODEL_REPO` 时再下载 v2 文件），切换到非 root 用户，启动 `python main.py`。`.dockerignore` 排除了 `data/` 和 `.venv-train/`，因此本地数据集不会进入构建上下文。

> **状态：** Dockerfile 和 nixpacks 的下载步骤已经写好，但**尚未端到端运行过**。在依赖它们之前，请用 `V2_MODEL_REPO` 和令牌做一次干净构建，然后用 `docker history` 检查令牌是否泄露。

## Railway

`railway.toml` 使用 Dockerfile 构建器，健康检查为 `GET /health`（超时 120 秒），失败时重启（重试 3 次）。`PORT` 由 Railway 注入并由 pydantic-settings 读取。请在控制台中设置 `API_KEY`、`DEBUG=false` 及其余变量。

对于 v2，Railway 必须将 `HF_TOKEN` 暴露给构建。Railway 按**服务变量名**挂载构建 secret，因此 Dockerfile 中的 secret id（`hf_token`）在那里可能需要改为 `HF_TOKEN`；请在第一次真实构建时验证。没有令牌时，设置了 `V2_MODEL_REPO` 的 v2 构建步骤会失败；若只发布 v1，请不要设置 `V2_MODEL_REPO`。

## Coolify / nixpacks

`nixpacks.toml` 安装 CPU 版 PyTorch 和 `requirements.txt`，内置 v1 模型，然后运行 `python download_model.py --v2-only`。请将 `V2_MODEL_REPO` 和 `HF_TOKEN` 设为**构建变量**。Nixpacks 可能会把构建变量持久化到它生成的镜像中，因此请使用只读令牌，并在镜像被共享过时轮换该令牌。应用通过 `su` 以 `appuser` 身份启动。

## 资源规格与运行规则

| 主题 | 指导 |
| --- | --- |
| Worker | **一个** uvicorn worker。每个 worker 都会加载全部模型的一份副本 |
| 内存 | 加载后实测 RSS：仅 v1 为 796 MB，v1 + v2 INT8 一起为 1030 MB，仅 v2 约 430 MB，处理请求后增长到 600-660 MB（ONNX arena）。合并进程在处理请求后的 RSS 未测量；请为合并进程预留约 2 GB |
| CPU | 4 vCPU：`MAX_CONCURRENT_INFERENCES=2`。2 vCPU：保持自动。在 Docker `--cpus`/Railway 下设置 `OMP_NUM_THREADS` |
| 健康检查 | `GET /health` 是公开的。它只报告 v1 的加载状态；v2 模型缺失会表现为 `/api/v2/evaluate` 返回 `503`，并在启动日志中给出警告 |
| 故障隔离 | v2 模型缺失或损坏绝不会阻止启动；v1 继续提供服务 |
| 切换客户端之前 | 在真实主机上运行 `python debugs/benchmark.py --api v2 --int8 --cpus 4`。[evaluation.md](evaluation.md) 中的速度数据来自开发机 |

环境变量：[configuration.md](configuration.md)。
