<!-- doc-id: docs-scoring-constants | lang: zh | source-rev: 6006c067 -->

> 🌐 **中文翻译**，源文件 [`docs/scoring-constants.md`](../../../docs/scoring-constants.md)（rev `6006c067`）。以英文版为准：若两者不一致，请以英文版为准。本译文由机器翻译，尚未经母语者审校。

# 评分常量的依据

每个硬编码评分常量取现有值的原因。修改其中任何一个
都需要运行健全性测试套件：

```
python scripts/sanity_eval.py \
    --api-key=$API_KEY \
    --compare-baseline=tests/sanity_dataset/sanity_baseline.json
```

如果比较器报告偏差 > 5 分或任何档位翻转，请判断：

- **有意的重新校准？** → 更新 `sanity_baseline.json`，并在此
  记录该变更。
- **回归？** → 回滚。

---

## 1. GOP 校准：`_FLOOR = -25.0`，`_CEIL = -3.0`

- **位置：** `app/services/gop_service.py`（归一化步骤）
- **经验值：** 发音正确的音素的 CTC 对数概率大约在
  -25（很差）到 -3（极好）之间。由于 softmax 的概率质量分散在整个
  词表上，即使是完美的 TTS 也很少超过 -3。
- **修改的风险：** 线性重映射 → 所有 GOP 评分按比例偏移，
  进而影响 accuracy_score（权重 45%）和 overall_score。

## 2. 音素相似度部分得分：`0.3`

- **位置：** `app/services/pronunciation_service.py` —— 音素对齐
  代价矩阵。
- **经验值：** 用同一发音类别中的音素进行替换
  （例如 ɛ↔æ，都是前元音）得 0.3，而匹配为 1.0，不同
  类别为 0.0。更高的值会使准确度相对于 Azure 更严格的
  评分而虚高；更低的值会对轻微的口音差异惩罚过重。
- **修改的风险：** 逐音素准确度发生偏移 → 整体 IPA 准确度
  线性变化 → accuracy_score（权重 55%）发生偏移。

## 3. 发音错误阈值：`60.0`

- **位置：** `app/services/pronunciation_service.py` ——
  `_MISPRONUNCIATION_THRESHOLD`。
- **依据：** 与 Azure Speech SDK 的惯例一致 —— IPA 准确度低于 60%
  的单词被标记为发音错误。
- **修改的风险：** 单词级 `error_type` 分类发生变化；新被
  归为发音错误的单词不再计入
  `completeness_score`。

## 4. Wav2Vec2 跳步长度：`320`

- **位置：** `app/services/pronunciation_service.py` —— `_HOP_SIZE`。
- **依据：** Wav2Vec2 架构：16 kHz 下 20 ms 一帧 = 每帧 320 个采样点。
  用于单词时间戳的强制对齐，其结果会输入
  `fluency_score`。
- **修改的风险：** 任何改变跳步长度的模型替换也必须
  更新该常量；否则单词时间戳会出错 → 流利度
  指标返回无意义的值。
- **CI 保护：** 如果升级了模型而没有更新跳步长度，健全性测试套件会发现偏差。

## 5. 语速惩罚不一致：`30 pts/wps`（韵律）与 `20 pts/wps`（流利度）

- **位置：** `app/services/prosody_service.py`（约第 178 行）和
  `app/services/pronunciation_service.py` —— `_RATE_PENALTY_PER_WPS`。
- **状态：** **已知的不一致。** 代码库中没有记录
  这一不对称惩罚的历史原因。已标记，待有生产数据后在 v2
  校准时处理。
- **统一的风险：** 两个子评分都会偏移 → overall_score 的权重发生变化
  → 必须重新生成健全性基线。

---

## v2 常量（`app/services/v2/`）

第 1-5 节是 v1 的常量。v2 流水线有自己的常量，大多是从数据中学习得到的：

| 常量 | 值 | 位置 | 原因 |
| --- | --- | --- | --- |
| `SCORE_CURVE_EXPONENT` | `1.4` | `pronunciation_v2_service.py` | 将专家评分尺度上的预测值（大多为 6-10）映射到更严格的 v1 尺度：`100 x (s/10)^1.4`。1.3 会让 `poor_001` 停在 59.4，离 60 这条线太近。在 5 条合成音频上调校；请在真实学习者音频上重新校准。对话语相关系数的影响 <= 0.005 |
| `MIN_HEARD_RATIO` | `0.2` | `pronunciation_v2_service.py` | 识别到的预期音素低于 20% 时，该音频被视为没有语音（零分）。speechocean762 真实语音中的最低比例是 0.31 |
| `mdd_threshold` | `1.48`（满分 2） | `scorer.json` | 音素评分低于该值即 `is_correct_ipa = false`。其取值使 out-of-fold 训练集预测上的发音错误 F1 最大化 |
| `MIN_SAMPLES` | `400` | `phone_model.py` | HuBERT 卷积前端会拒绝更短的音频（25 ms） |
| `Z_CLIP` | `10` | `scorer.py` | 罕见音素的 one-hot 方差极小；未截断的 z 分数曾达到约 200，毁掉了拟合 |
| 单词发音错误阈值 | `60` | `scoring_rules.py` | 与 v1 共用（Azure 使用同样的值） |
| 停顿阈值 | `0.8 s` / `0.15 s` | `scoring_rules.py` | 与 v1 共用；v2 将其应用于对齐后的单词区间 |

更改音素模型、特征布局或音素集都需要重新训练 `scorer.json`（[training.md](training.md)）。质量通过 `scripts/speechocean762_eval.py --api v2` 检查（[evaluation.md](evaluation.md)）。

## 如何安全地更新常量

1. 在相关的服务文件中做出修改。
2. 重启本地服务器。
3. 运行：
   ```
   python scripts/sanity_eval.py \
       --api-key=$API_KEY \
       --compare-baseline=tests/sanity_dataset/sanity_baseline.json
   ```
4. 如果退出码为 0：变更在容差范围内。与下方更新日志中的一条记录
   一起提交。
5. 如果退出码为 1 且是有意的重新校准：重新生成基线，提交
   两个文件，并在此记录该次重新校准。
6. 如果退出码为 1 且是非预期的回归：回滚。

## 更新日志

- _2026-05-04_ —— 初始文档（Phase 06）。
