<!-- doc-id: docs-scoring-v1 | lang: zh | source-rev: f3f95227 -->

> 🌐 **中文翻译**，源文件 [`docs/scoring-v1.md`](../../../docs/scoring-v1.md)（rev `f3f95227`）。以英文版为准：若两者不一致，请以英文版为准。本译文由机器翻译，尚未经母语者审校。

# 评分 v1（Wav2Vec2 ASR 流水线）

`POST /api/v1/evaluate` 如何产生评分：单词 ASR、g2p IPA 参考、基于 CTC 后验概率的 GOP、音高韵律以及 Azure 风格的子评分。
该流水线保持不变。较新的音素级流水线见 [scoring-v2.md](scoring-v2.md)；各常量及其取值依据见 [scoring-constants.md](scoring-constants.md)。

v1 在 speechocean762（成年人）上实测的弱点：音素级 GOP 与专家评分的相关系数仅为 0.03，韵律为 0.11，“识别出的与预期的对比”这种发音错误检测的 F1 为 0.27（精确率 0.16）。大多数较大的错误都可追溯到 ASR 在带口音语音上的胡乱输出。见 [evaluation.md](evaluation.md)。

## 流水线

### 流水线概览

```
Audio bytes → ASR (Wav2Vec2) → Transcription → IPA comparison + GOP scoring → Unified response
```

1. **音频处理** — 加载并重采样为 16 kHz 单声道 float32（librosa）
2. **ASR 转写** — Wav2Vec2 转写实际说出的内容
3. **IPA 转换** — 参考文本和转写文本都转换为 IPA 音素（g2p_en + ARPAbet→IPA 映射）
4. **IPA 比较** — 对单词（`_align_words`）和音素（`_align_phonemes`）分别做 DP 对齐，并使用 ε 容差回溯
5. **GOP 评分** — 基于 CTC 对数后验概率，按余数感知方式分配帧（不丢弃尾部帧）
6. **韵律分析** — 通过 librosa pyin 提取音高，对音高方差/范围/轮廓评分，并检测单调
7. **错误分类** — 每个单词获得一个 `ErrorType`：`None`、`Mispronunciation`、`Omission`、`Insertion`、`UnexpectedBreak` 或 `MissingBreak`
8. **子评分** — `accuracy_score` = 55% IPA + 45% GOP；`completeness_score` = 按准确度加权的、正确发音的参考单词比例；`fluency_score` = 语速 + 停顿分析；`prosody_score` = 语调 + 速度 + 节奏
9. **综合评分** — Azure 风格的加权公式：将 4 个子评分从低到高排序，`0.4 × s0 + 0.2 × s1 + 0.2 × s2 + 0.2 × s3`

### 评分公式

#### 准确度评分（子评分）

结合音素级 IPA 比较和 GOP 评分：

```math
AccuracyScore = IPA_{accuracy} \times 0.55 + GOP_{score} \times 0.45
```

#### 完整度评分（子评分）

衡量说话人**正确**发音了多少个参考单词：

```math
CompletenessScore = \frac{CorrectlyPronouncedWords}{ReferenceWords} \times 100
```

满足以下条件时，单词算“正确发音”：

1. 对齐操作是 `match` 或 `substitute`（尝试说了该单词），**并且**
2. 单词级 IPA 准确度 ≥ 60%（`_MISPRONUNCIATION_THRESHOLD`）

被遗漏（`delete`）的单词和发音错误的单词（准确度 < 60%）不计入。多说的单词（`insert`）不影响完整度。

#### 流利度评分（子评分）

利用 GOP 强制对齐得到的单词级 CTC 帧时间来衡量语音的流畅程度：

```math
FluencyScore = 0.4 \times RateScore + 0.6 \times PauseScore
```

**语速** — 与理想语速（约 3.0 词/秒）的偏差。语速在 ±0.5 wps 容差带内得满分；超出部分每 wps 扣 20 分。

**停顿惩罚** — 相邻单词之间的长间隙（>0.8 秒）会降低流利度，用于模拟犹豫和意外停顿。每多出 1 秒停顿扣 15 分。

Azure 将流利度定义为“语音在单词之间使用静音停顿的方式与母语者有多接近” —— 停顿模式是主要信号（60%），语速是次要的代理指标（40%）。

#### 韵律评分（子评分）

评估音高变化、语速和节奏的自然度。韵律评分有三个组成部分：

```math
ProsodyScore = 0.55 \times IntonationScore + 0.20 \times SpeedScore + 0.25 \times RhythmScore
```

**语调评分（55%）** — 结合三个音高指标：

```math
IntonationScore = 0.50 \times VarianceScore + 0.30 \times RangeScore + 0.20 \times ContourScore
```

- _方差评分_ — 音高变异系数（CV = 标准差/均值）。CV ≤ `monotone_threshold`（0.08）= 0 分；CV ≥ `cv_upper`（0.25）= 100 分。中间线性插值。
- _范围评分_ — 以半音为单位的音高范围。0 st = 0 分；≥ 15 st = 100 分。线性插值。
- _轮廓评分_ — 音高轮廓中方向变化的比例。目标比例 0.45 得满分；偏差按线性惩罚。

**速度评分（20%）** — 每秒单词数与理想值 3.0 wps 的偏差（容差 ±0.5）。超出容差的每 1 wps → 扣 30 分。

**节奏评分（25%）** — 归一化成对变异指数 (nPVI)。衡量重音计时的自然度；英语母语者的 nPVI 约为 50–70，音节计时语言约为 30–40。线性评分：nPVI ≤30 → 0，nPVI ≥70 → 100。

**单调检测** — 当音高 CV < 阈值（0.08）时，`is_monotone = True`，韵律评分上限为 30。

**浊音比例保护** — 如果浊音帧少于 10%，返回 0 分（浊音信号不足）。

**默认行为** — 当单词时长不可用（没有 CTC 时间信息）时，速度和节奏默认为 50（中性）。

#### 总体综合评分

子评分从低到高排序，并使用 Azure PronScore 公式组合：

```math
CombinedScore = 0.4 \times S_0 + 0.2 \times S_1 + 0.2 \times S_2 + 0.2 \times S_3
```

最低的子评分权重最大（40%），对最薄弱的维度给予重罚。

#### 单词级错误分类

结果中的每个单词根据对齐情况和准确度获得一个 `error_type`：

| 条件                                            | ErrorType          |
| ----------------------------------------------- | ------------------ |
| 单词已对齐（match/substitute），准确度 ≥ 60%    | `None`             |
| 单词已对齐（match/substitute），准确度 < 60%    | `Mispronunciation` |
| 单词在参考文本中但未被说出                      | `Omission`         |
| 单词被说出但不在参考文本中                      | `Insertion`        |
| 在单词之前检测到长停顿（>0.8 秒）               | `UnexpectedBreak`  |
| 标点边界处缺少停顿（<0.15 秒）                  | `MissingBreak`     |

阈值：`60.0`（与 Azure Speech SDK 一致）。

#### IPA 准确度（权重：55%）

使用基于 Levenshtein 的序列对齐（采用 `float64` 精度的动态规划，回溯容差 ε = 10⁻⁶），在**两个层级**上比较参考文本和转写文本：

**层级 1 — 单词对齐（`_align_words`）：**

参考单词列表和转写单词列表使用普通的 Levenshtein DP 对齐（没有音素相似度代价 —— 单词是否相等是二元的）。产生 match / substitute / insert / delete 操作。用户多说的单词（插入）会在总分中受到惩罚。

**层级 2 — 音素对齐（`_align_phonemes`，针对每个单词对）：**

对每个已对齐的单词对，用同样的 DP 算法对齐参考音素序列和实际音素序列。编辑距离使用**音系相似度** —— 把一个音素替换成同一音系类别中的音素（例如 `ɛ` ↔ `æ`，都是前元音）的代价，低于替换成不同类别的音素。

```
Reference IPA:   [h, ɛ, l, oʊ]
Actual IPA:      [h, ɛ, ə, l, oʊ]
Alignment:
  h  = h    ✓  match
  ɛ  = ɛ    ✓  match
  -  ← ə    ✗  insert (extra phoneme in actual)
  l  = l    ✓  match
  oʊ = oʊ   ✓  match
→ 4/4 correct ref phonemes = 100% (insertion penalised in overall score)
```

**音素置信度评分：**

| 对齐结果                                | 置信度     |
| --------------------------------------- | ---------- |
| 完全匹配                                | `1.0`      |
| 替换（同一音系类别）                    | `0.3`      |
| 替换（不同音系类别）                    | `0.0`      |
| 删除（实际中缺失）                      | `0.0`      |
| 插入（实际中多出）                      | `0.0`      |

**单词准确度：**

```math
WordAccuracy = \frac{CorrectPhonemes}{RefPhonemesInWord} \times 100
```

**总体 IPA 准确度（含插入惩罚）：**

```math
OverallIPA = \frac{\sum CorrectPhonemes}{\sum RefPhonemes + \sum InsertedPhonemes} \times 100
```

> 多说的单词会把它们的音素数加到分母上，从而降低总体准确度。

#### GOP 评分（权重：45%）

GOP (Goodness of Pronunciation，发音良好度) 使用 Wav2Vec2 的 CTC 对数后验概率：

**步骤 1 — CTC 对数后验概率：**

音频 → Wav2Vec2 → 输出 logits → `log_softmax` → 矩阵 `(T, V)`，其中 T = 帧数，V = 词表大小

**步骤 2 — 余数感知的帧分段：**

将 T 帧分配给 N 个音素。每个音素获得一个基础分配量，余数帧分配给**最后**的音素：

```math
base = \lfloor T / N \rfloor,\quad remainder = T \bmod N
```

位置在 `[N - remainder, N)` 的音素获得 `base + 1` 帧；更靠前的音素获得 `base` 帧。这确保**所有 T 帧都被使用** —— 不丢弃尾部帧。

**步骤 3 — 每个音素的原始 GOP：**

对每个音素 `p`，通过 `_IPA_TO_WAV2VEC` 映射到 Wav2Vec2 词表 token，然后计算其所分配帧 `[start, end)` 上的平均对数概率：

```math
GOP_{raw}(p) = \frac{1}{d} \sum_{t=start}^{end-1} \log P(p \mid o_t)
```

其中 `d = end - start` 是分配给音素 `p` 的帧数。

> 如果音素不在词表中 → 回退：对这些帧使用整个词表上的最大对数概率。

**步骤 4 — 归一化到 [0, 100]：**

经验校准：发音正确的音素的 CTC 对数概率通常在 −25（很差）到 −3（极好）之间。即使是“完美”的 TTS 音频，原始评分也很少超过 −3，因为 CTC softmax 总是把概率质量分散到整个词表上。

```math
GOP_{norm} = \frac{\text{clamp}(GOP_{raw},\ -25,\ -3) - (-25)}{22} \times 100
```

截断到 `[0, 100]`。

**步骤 5 — 聚合：**

- **单词 GOP** = 该单词中各音素 GOP 评分的平均值
- **总体 GOP** = 所有音素 GOP 评分的平均值

> 单词边界使用基于索引的跟踪（而非字符串相等判断），因此 "the cat and the dog" 这类重复单词也能被正确处理。

#### 综合评分

```math
AccuracyScore = IPA_{accuracy} \times 0.55 + GOP_{score} \times 0.45
```

```math
CompletenessScore = \frac{CorrectlyPronouncedWords}{ReferenceWords} \times 100
```

```math
FluencyScore = 0.4 \times RateScore + 0.6 \times PauseScore
```

```math
ProsodyScore = 0.55 \times IntonationScore + 0.20 \times SpeedScore + 0.25 \times RhythmScore
```

```math
OverallScore = 0.4 \times S_0 + 0.2 \times S_1 + 0.2 \times S_2 + 0.2 \times S_3 \quad (S_0 \leq S_1 \leq S_2 \leq S_3)
```

#### 质量等级

| 评分范围     | 等级         | 反馈                                 |
| ------------ | ------------ | ------------------------------------ |
| **80 – 100** | 🟢 优秀      | 发音与参考高度吻合                   |
| **60 – 79**  | 🔵 良好      | 还可以做一些小的改进                 |
| **40 – 59**  | 🟡 一般      | 若干发音需要练习                     |
| **0 – 39**   | 🔴 较差      | 需要显著改进                         |

### 评分示例

```
Reference:     "the cat and the dog"
Transcription: "the cat an the dock"

Word alignment (DP):
  the  = the   ✓ match     → ErrorType: None
  cat  = cat   ✓ match     → ErrorType: None
  and  ≈ an    ~ substitute → ErrorType: depends on accuracy
  the  = the   ✓ match     → ErrorType: None
  dog  ≈ dock  ~ substitute → ErrorType: depends on accuracy

Phoneme alignment for "and" → "an":
  Reference: [æ, n, d]    Actual: [æ, n]
  æ = æ  ✓ match     confidence=1.0
  n = n  ✓ match     confidence=1.0
  d → ∅  ✗ delete    confidence=0.0
  → Word accuracy = 2/3 × 100 = 66.7%  → ErrorType: None (≥60%)

Phoneme alignment for "dog" → "dock":
  Reference: [d, ɑ, ɡ]    Actual: [d, ɑ, k]
  d = d  ✓ match     confidence=1.0
  ɑ = ɑ  ✓ match     confidence=1.0
  ɡ ≈ k  ✗ substitute (same group: voiced/voiceless plosive) confidence=0.3
  → Word accuracy = 2/3 × 100 = 66.7%  → ErrorType: None (≥60%)

Overall IPA = (3+3+2+3+2) / (3+3+3+3+3) = 13/15 × 100 = 86.7%

GOP Scoring: (per-phoneme CTC log-prob scores, normalised 0-100)
  → Overall GOP = 72.5 (example)

Sub-scores:
  Accuracy    = 86.7 × 0.55 + 72.5 × 0.45 = 47.7 + 32.6 = 80.3
  Completeness = 5/5 × 100 = 100.0  (all reference words attempted)
  Fluency      = 95.0  (normal speech rate, no long pauses)
  Prosody      = 78.0  (good pitch variation, not monotone)

Overall = sorted([80.3, 100.0, 95.0, 78.0]) = [78.0, 80.3, 95.0, 100.0]
        = 0.4 × 78.0 + 0.2 × 80.3 + 0.2 × 95.0 + 0.2 × 100.0
        = 31.2 + 16.06 + 19.0 + 20.0 = 86.3
Level = EXCELLENT ✔
```

