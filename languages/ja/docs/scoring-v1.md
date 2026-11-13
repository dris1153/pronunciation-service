<!-- doc-id: docs-scoring-v1 | lang: ja | source-rev: f3f95227 -->

> 🌐 [`docs/scoring-v1.md`](../../../docs/scoring-v1.md)（rev `f3f95227`）の**日本語訳**です。英語版が正です。内容が異なる場合は英語版に従ってください。機械翻訳であり、ネイティブによる校閲は受けていません。

# スコアリング v1（Wav2Vec2 ASR パイプライン）

`POST /api/v1/evaluate` がスコアを算出するしくみを説明します。単語 ASR、g2p による IPA 参照、CTC 事後確率による GOP、ピッチによる韻律、Azure 方式のサブスコアで構成されます。
このパイプラインは変更されていません。新しい音素レベルのパイプラインは [scoring-v2.md](scoring-v2.md) で説明しています。定数とそれが選ばれた理由は [scoring-constants.md](scoring-constants.md) にあります。

speechocean762（成人）で測定された v1 の弱点: 音素レベルの GOP は専門家スコアとの相関が 0.03、韻律は 0.11、認識された音と期待される音の比較による誤発音検出は F1 が 0.27（適合率 0.16）です。大きな誤りの多くは、アクセントのある音声に対する ASR の意味不明な出力に由来します。[evaluation.md](evaluation.md) を参照してください。

## パイプライン

### パイプラインの概要

```
Audio bytes → ASR (Wav2Vec2) → Transcription → IPA comparison + GOP scoring → Unified response
```

1. **音声処理** — 音声を読み込み、16 kHz モノラル float32 にリサンプリングする（librosa）
2. **ASR による書き起こし** — Wav2Vec2 が実際に発話された内容を書き起こす
3. **IPA 変換** — 参照と書き起こしの両方を IPA 音素に変換する（g2p_en + ARPAbet→IPA のマッピング）
4. **IPA 比較** — 単語（`_align_words`）と音素（`_align_phonemes`）を、ε 許容付きのバックトレースで、それぞれ別の DP でアライメントする
5. **GOP 採点** — 余りを考慮したフレーム配分（末尾のフレームを捨てない）による CTC 対数事後確率
6. **韻律分析** — librosa pyin によるピッチ抽出、ピッチの分散/範囲/輪郭のスコアリング、単調さの検出
7. **エラー分類** — 各単語に `ErrorType` が付与される: `None`、`Mispronunciation`、`Omission`、`Insertion`、`UnexpectedBreak`、`MissingBreak`
8. **サブスコア** — `accuracy_score` = 55% IPA + 45% GOP、`completeness_score` = 正しく発音された参照単語の、正確さで重み付けした比率、`fluency_score` = 発話速度 + ポーズの分析、`prosody_score` = イントネーション + 速度 + リズム
9. **統合スコア** — Azure 方式の加重式: 4 つのサブスコアを低い順に並べ、`0.4 × s0 + 0.2 × s1 + 0.2 × s2 + 0.2 × s3`

### 採点式

#### 正確さスコア（サブスコア）

音素レベルの IPA 比較と GOP 採点を組み合わせます。

```math
AccuracyScore = IPA_{accuracy} \times 0.55 + GOP_{score} \times 0.45
```

#### 完全性スコア（サブスコア）

話者が参照単語のうち、いくつを**正しく**発音したかを測ります。

```math
CompletenessScore = \frac{CorrectlyPronouncedWords}{ReferenceWords} \times 100
```

次の条件を満たす単語が「正しく発音された」とみなされます。

1. アライメントの操作が `match` または `substitute` である（単語が発話された）、**かつ**
2. 単語レベルの IPA 正確さが 60% 以上（`_MISPRONUNCIATION_THRESHOLD`）

脱落（`delete`）した単語と、誤発音の単語（正確さ < 60%）は数えられません。余分に発話された単語（`insert`）は完全性に影響しません。

#### 流暢さスコア（サブスコア）

GOP の強制アライメントから得た単語レベルの CTC フレームのタイミングを使って、発話のなめらかさを測ります。

```math
FluencyScore = 0.4 \times RateScore + 0.6 \times PauseScore
```

**発話速度** — 理想の速度（約 3.0 語/秒）からのずれ。±0.5 wps の許容範囲内の速度は満点で、それを超えるずれは 1 wps あたり 20 点で減点されます。

**ポーズのペナルティ** — 連続する単語の間の長い間隔（>0.8 秒）は流暢さを下げます。ためらいや予期しない途切れをモデル化したものです。ポーズが 1 秒超過するごとに 15 点を失います。

Azure は流暢さを「発話が、単語間の無音の区切りの使い方においてネイティブスピーカーにどれだけ近いか」と定義しています。ポーズのパターンが主要な信号（60%）で、発話速度は補助的な代理指標（40%）です。

#### 韻律スコア（サブスコア）

ピッチの変化、発話速度、リズムの自然さを評価します。韻律スコアは 3 つの要素で構成されます。

```math
ProsodyScore = 0.55 \times IntonationScore + 0.20 \times SpeedScore + 0.25 \times RhythmScore
```

**イントネーションスコア（55%）** — 3 つのピッチ指標を組み合わせます。

```math
IntonationScore = 0.50 \times VarianceScore + 0.30 \times RangeScore + 0.20 \times ContourScore
```

- _分散スコア_ — ピッチの変動係数（CV = 標準偏差/平均）。CV ≤ `monotone_threshold`（0.08）= スコア 0、CV ≥ `cv_upper`（0.25）= スコア 100。その間は線形補間。
- _範囲スコア_ — ピッチの範囲（半音）。0 st = スコア 0、≥ 15 st = スコア 100。線形補間。
- _輪郭スコア_ — ピッチ輪郭における方向転換の比率。目標比率 0.45 で満点となり、ずれは線形に減点されます。

**速度スコア（20%）** — 理想の 3.0 wps（±0.5 の許容範囲）からの 1 秒あたりの単語数のずれ。許容範囲を超えるごとに、1 wps あたり −30 点。

**リズムスコア（25%）** — 正規化ペアワイズ変動指数（nPVI）。強勢拍リズムの自然さを測ります。ネイティブの英語の nPVI は約 50〜70、音節拍リズムは約 30〜40 です。線形にスコア化されます: nPVI ≤30 → 0、nPVI ≥70 → 100。

**単調さの検出** — ピッチの CV がしきい値（0.08）未満の場合、`is_monotone = True` となり、韻律スコアは 30 が上限になります。

**有声比率のガード** — 有声フレームが 10% 未満の場合は、スコア 0 を返します（有声の信号が不十分）。

**デフォルトの動作** — 単語の継続時間が得られない場合（CTC のタイミングがない場合）、速度とリズムはデフォルトで 50（中立）になります。

#### 総合の統合スコア

サブスコアを低い順に並べ、Azure の PronScore の式で統合します。

```math
CombinedScore = 0.4 \times S_0 + 0.2 \times S_1 + 0.2 \times S_2 + 0.2 \times S_3
```

最も低いサブスコアに最大の重み（40%）が与えられ、最も弱い側面を大きく減点します。

#### 単語レベルのエラー分類

結果に含まれる各単語には、アライメントと正確さに基づいて `error_type` が付与されます。

| 条件                                            | ErrorType          |
| ----------------------------------------------- | ------------------ |
| 単語がアライメントされ（match/substitute）、正確さ ≥ 60% | `None`             |
| 単語がアライメントされ（match/substitute）、正確さ < 60% | `Mispronunciation` |
| 参照にあるが発話されなかった単語                | `Omission`         |
| 発話されたが参照にない単語                      | `Insertion`        |
| 単語の前で長いポーズ（>0.8 秒）を検出           | `UnexpectedBreak`  |
| 句読点の境界でポーズがない（<0.15 秒）          | `MissingBreak`     |

しきい値: `60.0`（Azure Speech SDK に合わせたもの）。

#### IPA 正確さ（重み: 55%）

参照と書き起こしのテキストを、レーベンシュタイン距離に基づく系列アライメント（`float64` 精度の動的計画法、ε = 10⁻⁶ のバックトレース許容）を使って、**2 つのレベル**で比較します。

**レベル 1 — 単語のアライメント（`_align_words`）:**

参照と書き起こしの単語リストを、単純なレーベンシュタイン DP でアライメントします（音声的な類似度のコストはなく、単語の同一性は二値です）。match / substitute / insert / delete の操作が得られます。ユーザーが余分に発話した単語（挿入）は、総合スコアで減点されます。

**レベル 2 — 音素のアライメント（`_align_phonemes`、単語ペアごと）:**

アライメントされた単語ペアごとに、参照と実際の音素列を同じ DP アルゴリズムでアライメントします。編集距離は**音声的な類似度**を使います。音素を同じ音声学的グループの音素に置換する場合（例: `ɛ` ↔ `æ`、どちらも前舌母音）は、異なるグループの音素に置換するよりコストが低くなります。

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

**音素の信頼度スコア:**

| アライメントの結果                      | 信頼度     |
| --------------------------------------- | ---------- |
| 完全一致                                | `1.0`      |
| 置換（同じ音声学的グループ）            | `0.3`      |
| 置換（異なる音声学的グループ）          | `0.0`      |
| 脱落（実際の発話にない）                | `0.0`      |
| 挿入（実際の発話に余分にある）          | `0.0`      |

**単語ごとの正確さ:**

```math
WordAccuracy = \frac{CorrectPhonemes}{RefPhonemesInWord} \times 100
```

**IPA 正確さ全体（挿入ペナルティ付き）:**

```math
OverallIPA = \frac{\sum CorrectPhonemes}{\sum RefPhonemes + \sum InsertedPhonemes} \times 100
```

> 余分に発話された単語の音素数は分母に加算され、全体の正確さを下げます。

#### GOP スコア（重み: 45%）

GOP（Goodness of Pronunciation）は、Wav2Vec2 の CTC 対数事後確率を使います。

**ステップ 1 — CTC 対数事後確率:**

Audio → Wav2Vec2 → 出力 logits → `log_softmax` → 行列 `(T, V)`。T = フレーム数、V = 語彙サイズ

**ステップ 2 — 余りを考慮したフレーム分割:**

T 個のフレームを N 個の音素に分配します。各音素には基本の割り当てがあり、余りのフレームは**後ろの**音素に分配されます。

```math
base = \lfloor T / N \rfloor,\quad remainder = T \bmod N
```

位置 `[N - remainder, N)` の音素には `base + 1` フレーム、それより前の音素には `base` フレームが割り当てられます。これにより、**T 個のフレームがすべて使われ**、末尾のフレームが捨てられることはありません。

**ステップ 3 — 音素ごとの生の GOP:**

各音素 `p` を `_IPA_TO_WAV2VEC` で Wav2Vec2 の語彙トークンに対応付け、割り当てられたフレーム `[start, end)` にわたる対数確率の平均を計算します。

```math
GOP_{raw}(p) = \frac{1}{d} \sum_{t=start}^{end-1} \log P(p \mid o_t)
```

ここで `d = end - start` は、音素 `p` に割り当てられたフレーム数です。

> 音素が語彙にない場合 → フォールバック: そのフレームについて、語彙全体での最大対数確率を使います。

**ステップ 4 — [0, 100] に正規化:**

経験的にキャリブレーションされています。正しく発音された音素の CTC 対数確率は、通常 −25（非常に悪い）から −3（非常に良い）の範囲に収まります。「完璧な」TTS 音声であっても、CTC の softmax が常に確率質量を語彙全体に分散させるため、生のスコアが −3 を超えることはまれです。

```math
GOP_{norm} = \frac{\text{clamp}(GOP_{raw},\ -25,\ -3) - (-25)}{22} \times 100
```

`[0, 100]` にクランプされます。

**ステップ 5 — 集計:**

- **単語ごとの GOP** = その単語に含まれる音素の GOP スコアの平均
- **全体の GOP** = すべての音素の GOP スコアの平均

> 単語の境界は（文字列の等価性ではなく）インデックスで追跡するため、「the cat and the dog」のように重複する単語も正しく処理されます。

#### 統合スコア

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

#### 品質レベル

| スコア範囲   | レベル       | フィードバック                       |
| ------------ | ------------ | ------------------------------------ |
| **80 – 100** | 🟢 Excellent | 発話が参照にほぼ一致している         |
| **60 – 79**  | 🔵 Good      | 軽微な改善の余地がある               |
| **40 – 59**  | 🟡 Fair      | いくつかの音に練習が必要             |
| **0 – 39**   | 🔴 Poor      | 大幅な改善が必要                     |

### 採点の例

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

