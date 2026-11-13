<!-- doc-id: docs-evaluation | lang: zh | source-rev: e6f94b86 -->

> 🌐 **中文翻译**，源文件 [`docs/evaluation.md`](../../../docs/evaluation.md)（rev `e6f94b86`）。以英文版为准：若两者不一致，请以英文版为准。本译文由机器翻译，尚未经母语者审校。

# 评估、基准测试与测试

## 与专家评分对比的质量

[speechocean762](https://www.openslr.org/101/)（CC BY 4.0；Zhang 等，Interspeech 2021）：来自 250 名非母语说话人（母语为普通话，其中一半是儿童）的 5000 条话语，由 5 位专家在音素（0-2）、单词（0-10）和话语（0-10）三个层级打分。将其解压到 `data/speechocean762/`。评测脚本在进程内运行流水线（不经过 HTTP，没有限流），并可从其 JSONL 输出中断点续跑。

```bash
python scripts/speechocean762_eval.py --api v1 --out data/so762-v1-test.jsonl --report data/so762-v1-test-report.json
python scripts/speechocean762_eval.py --api v2 --out data/so762-v2-test.jsonl --report data/so762-v2-test-report.json
python scripts/speechocean762_v2_signal.py data/so762-v2-test.jsonl     # phone correlation, MDD, confusions, latency
```

它报告话语、单词和音素评分的 Pearson 相关系数，以及发音错误检测 (MDD) 的精确率 / 召回率 / F1，分别针对所有说话人和仅成年人（18 岁以上）。“发音错误”指专家音素评分低于 1.0（约占音素的 4%）。

| 测试集 | v1 成年人 | v2 成年人 | v2 全部 |
| --- | --- | --- | --- |
| 话语总分 / 准确度 | 0.619 / 0.669 | 0.852 / 0.829 | 0.779 / 0.749 |
| 话语流利度 / 韵律 | 0.630 / 0.108 | 0.876 / 0.853 | 0.817 / 0.796 |
| 单词准确度 | 0.020 | 0.643 | 0.591 |
| 音素准确度 | 0.033 | 0.630 | 0.590 |
| MDD F1 | 0.269 | 0.537 | 0.480 |

说明：v2 的数值使用 FP32 模型；INT8 在每项指标上的差异在 0.004 以内（完整度是基于规则的评分，标签中几乎没有方差，变化了 0.010）。评分曲线对话语相关系数的影响不超过 0.005。v1 最大的错误来自 ASR 在带口音语音上的胡乱输出。v2 的工作原理：[scoring-v2.md](scoring-v2.md)。

### 这些数据没有告诉你的事

- **所有说话人的母语都是普通话。** 越南语学习者会犯不同的错误（词尾辅音、th/dh、s/sh、辅音丛）。目前还没有越南语母语者的数据。
- 用于确定评分曲线指数的健全性测试音频是五条合成（gTTS）录音。
- 评分器没有在 20 到 30 秒的音频上验证过。

### 越南语学习者数据计划

调研发现**没有开放的、可商用的、带发音评分的越南语母语者英语语料库**。L2-ARCTIC 有四位越南语说话人，但只有二元音素标签且许可证为非商用；speechocean762 只有普通话；越南语母语语音语料库不包含英语。现实的路径是按 speechocean762 的协议（3 名以上评分员，音素 0-2 / 单词 / 话语）自行录制并标注学习者语音，先从大约 50-100 名成年说话人和 500-1000 条话语开始，用来重新校准评分器。

## 延迟与内存

`debugs/benchmark.py` 在进程内对真实流水线计时。`--cpus N` 将进程绑定到 N 个核心，以模拟 N 个 vCPU 的主机。

```bash
python debugs/benchmark.py --api v1 --cpus 4
python debugs/benchmark.py --api v2 --int8 --cpus 4 --concurrency 2
```

在 Windows 开发机（28 个逻辑核心）上测得，gTTS 健全性测试音频 1.2-4.2 秒，p50，单位 ms：

| 3.4 秒音频 | v1 | v2 FP32 | **v2 INT8** |
| --- | --- | --- | --- |
| 2 vCPU | 610 | 375 | **240** |
| 4 vCPU | 381 | 201 | **125** |

| 并发（2 个名额，30 个请求） | v1 | v2 FP32 | **v2 INT8** |
| --- | --- | --- | --- |
| 4 vCPU，p50 / p90 ms | 461 / 891 | 155 / 416 | **93 / 271** |
| 4 vCPU，req/s | 3.9 | 8.2 | **13.2** |
| 2 vCPU，req/s | 2.7 | 4.5 | **7.4** |

| 内存 (RSS) | 加载后 | 处理请求后 |
| --- | --- | --- |
| v1 | 796 MB | 970-1090 MB |
| v2 FP32 | 928 MB | 1050-1170 MB |
| v2 INT8 | **430 MB** | 600-660 MB |
| v1 + v2 INT8 在同一进程中 | 1030 MB | 未测量 |

在 v2 中，模型基本上就是全部开销（INT8、4 vCPU、3.4 秒音频：ONNX 约 120 ms，对齐约 3 ms，评分器约 1 ms）。INT8 是默认选项，也是小型主机上唯一合理的选择；FP32 在加载时比 v1 更重。这些是开发机的数据：切换客户端之前请在真实主机上重新运行基准测试，因为 INT8 的加速效果取决于 CPU 的指令集支持。每次 `/evaluate` 还会记录一条 `evaluate_timing` 日志，包含各阶段的毫秒数。

## 测试

```bash
pytest tests/ -v
```

约 460 个测试：API（v1 和 v2）、鉴权和限流、音频处理、文本/IPA/GOP/韵律服务、对齐和评分规则、v2 CTC 对齐（与 `torchaudio.forced_align` 一致）、特征、评分器，以及一个确保 `app/services/v2/` 绝不导入 torch 的守卫测试。需要真实 v2 模型文件的测试（健全性分数区间、噪声关卡）在文件缺失时会自动跳过。`asyncio_mode = "auto"`。

`tests/sanity_dataset/` 存放五条合成录音（3 条好、2 条差）及其预期评分区间；可用 `scripts/generate_sanity_audio.py` 重新生成。

**已知问题：** 两个 v1 健全性用例（`poor_001`、`poor_002`）失败，因为 v1 给这两段音频打的分刚好高于其区间 60 的上限。v2 两个都通过。
