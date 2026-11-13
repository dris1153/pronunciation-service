<!-- doc-id: docs-scoring-v1 | lang: es | source-rev: f3f95227 -->

> 🌐 **Traducción al español** de [`docs/scoring-v1.md`](../../../docs/scoring-v1.md) (rev `f3f95227`). La versión en inglés es la oficial: si difieren, prevalece el inglés. Traducción automática, sin revisión de un hablante nativo.

# Puntuación v1 (pipeline ASR con Wav2Vec2)

Cómo produce sus puntuaciones `POST /api/v1/evaluate`: ASR de palabras, referencias IPA con g2p, GOP a partir de posteriors CTC, prosodia basada en el tono y subpuntuaciones al estilo Azure.
Este pipeline no ha cambiado. El pipeline más reciente a nivel de fonema se describe en [scoring-v2.md](scoring-v2.md); las constantes y por qué se eligieron están en [scoring-constants.md](scoring-constants.md).

Debilidades medidas de v1 en speechocean762 (adultos): el GOP a nivel de fonema correlaciona 0.03 con las puntuaciones de los expertos, la prosodia 0.11, y la detección de errores de pronunciación oído-frente-a-esperado tiene un F1 de 0.27 (precisión 0.16). La mayoría de los errores grandes se deben a transcripciones sin sentido del ASR con habla acentuada. Consulta [evaluation.md](evaluation.md).

## Pipeline

### Visión general del pipeline

```
Audio bytes → ASR (Wav2Vec2) → Transcription → IPA comparison + GOP scoring → Unified response
```

1. **Procesamiento del audio** — Carga y remuestreo del audio a 16 kHz mono float32 (librosa)
2. **Transcripción ASR** — Wav2Vec2 transcribe lo que se dijo realmente
3. **Conversión a IPA** — Tanto la referencia como la transcripción → fonemas IPA (g2p_en + mapeo ARPAbet→IPA)
4. **Comparación IPA** — Alineación DP separada para palabras (`_align_words`) y fonemas (`_align_phonemes`) con retroceso con tolerancia ε
5. **Puntuación GOP** — Log-posteriors CTC con distribución de fotogramas que tiene en cuenta el resto (sin descartar fotogramas finales)
6. **Análisis de prosodia** — Extracción del tono con librosa pyin, puntuación de varianza/rango/contorno del tono, detección de monotonía
7. **Clasificación de errores** — Cada palabra recibe un `ErrorType`: `None`, `Mispronunciation`, `Omission`, `Insertion`, `UnexpectedBreak` o `MissingBreak`
8. **Subpuntuaciones** — `accuracy_score` = 55% IPA + 45% GOP; `completeness_score` = razón ponderada por la precisión de las palabras de referencia pronunciadas correctamente; `fluency_score` = velocidad del habla + análisis de pausas; `prosody_score` = entonación + velocidad + ritmo
9. **Puntuación combinada** — Fórmula ponderada al estilo Azure: ordena las 4 subpuntuaciones de menor a mayor, `0.4 × s0 + 0.2 × s1 + 0.2 × s2 + 0.2 × s3`

### Fórmula de puntuación

#### Puntuación de precisión (subpuntuación)

Combina la comparación IPA a nivel de fonema y la puntuación GOP:

```math
AccuracyScore = IPA_{accuracy} \times 0.55 + GOP_{score} \times 0.45
```

#### Puntuación de completitud (subpuntuación)

Mide cuántas palabras de referencia pronunció **correctamente** el hablante:

```math
CompletenessScore = \frac{CorrectlyPronouncedWords}{ReferenceWords} \times 100
```

Una palabra está "pronunciada correctamente" si:

1. La operación de alineación es `match` o `substitute` (se intentó la palabra), **y**
2. La precisión IPA a nivel de palabra es ≥ 60% (`_MISPRONUNCIATION_THRESHOLD`)

Las palabras omitidas (`delete`) y las mal pronunciadas (precisión < 60%) no se cuentan. Las palabras extra pronunciadas (`insert`) no afectan a la completitud.

#### Puntuación de fluidez (subpuntuación)

Mide la fluidez del habla usando los tiempos de fotogramas CTC por palabra de la alineación forzada de GOP:

```math
FluencyScore = 0.4 \times RateScore + 0.6 \times PauseScore
```

**Velocidad del habla** — desviación respecto a la velocidad ideal (~3.0 palabras/s). Las velocidades dentro de una banda de tolerancia de ±0.5 wps reciben la puntuación completa; las desviaciones mayores se penalizan con 20 puntos por wps.

**Penalización por pausas** — los huecos largos (>0.8s) entre palabras consecutivas reducen la fluidez, y modelan las vacilaciones y las pausas inesperadas. Cada segundo de pausa en exceso cuesta 15 puntos.

Azure define la fluidez como "cuánto se parece el habla al uso que hace un hablante nativo de las pausas silenciosas entre palabras" — los patrones de pausa son la señal principal (60%), y la velocidad del habla es un indicador secundario (40%).

#### Puntuación de prosodia (subpuntuación)

Evalúa la variación del tono, la velocidad del habla y la naturalidad del ritmo. La puntuación de prosodia tiene tres componentes:

```math
ProsodyScore = 0.55 \times IntonationScore + 0.20 \times SpeedScore + 0.25 \times RhythmScore
```

**Puntuación de entonación (55%)** — combina tres métricas del tono:

```math
IntonationScore = 0.50 \times VarianceScore + 0.30 \times RangeScore + 0.20 \times ContourScore
```

- _Puntuación de varianza_ — coeficiente de variación del tono (CV = std/media). CV ≤ `monotone_threshold` (0.08) = puntuación 0; CV ≥ `cv_upper` (0.25) = puntuación 100. Interpolación lineal entre ambos.
- _Puntuación de rango_ — rango del tono en semitonos. 0 st = puntuación 0; ≥ 15 st = puntuación 100. Interpolación lineal.
- _Puntuación de contorno_ — razón de cambios de dirección en el contorno del tono. La razón objetivo de 0.45 obtiene la puntuación completa; las desviaciones se penalizan linealmente.

**Puntuación de velocidad (20%)** — desviación de palabras por segundo respecto al ideal de 3.0 wps (tolerancia ±0.5). Cada 1 wps fuera de la tolerancia → −30 puntos.

**Puntuación de ritmo (25%)** — Índice de Variabilidad por Pares normalizado (nPVI). Mide la naturalidad del ritmo acentual; el nPVI del inglés nativo es ~50–70, y el de las lenguas de ritmo silábico ~30–40. Puntuación lineal: nPVI ≤30 → 0, nPVI ≥70 → 100.

**Detección de monotonía** — cuando el CV del tono < umbral (0.08), `is_monotone = True` y la puntuación de prosodia se limita a 30.

**Protección por proporción de sonoridad** — si menos del 10% de los fotogramas son sonoros, devuelve puntuación 0 (señal sonora insuficiente).

**Comportamiento por defecto** — cuando no hay duraciones de palabras (sin tiempos CTC), la velocidad y el ritmo valen 50 por defecto (neutro).

#### Puntuación global combinada

Las subpuntuaciones se ordenan de menor a mayor y se combinan con la fórmula PronScore de Azure:

```math
CombinedScore = 0.4 \times S_0 + 0.2 \times S_1 + 0.2 \times S_2 + 0.2 \times S_3
```

La subpuntuación más baja recibe el mayor peso (40%), con lo que se penaliza con fuerza la dimensión más débil.

#### Clasificación de errores a nivel de palabra

Cada palabra del resultado recibe un `error_type` según la alineación y la precisión:

| Condición                                       | ErrorType          |
| ----------------------------------------------- | ------------------ |
| Palabra alineada (match/substitute), precisión ≥ 60% | `None`             |
| Palabra alineada (match/substitute), precisión < 60% | `Mispronunciation` |
| Palabra en la referencia pero no pronunciada    | `Omission`         |
| Palabra pronunciada pero ausente de la referencia | `Insertion`        |
| Pausa larga (>0.8s) detectada antes de la palabra | `UnexpectedBreak`  |
| Falta de pausa en un límite de puntuación (<0.15s) | `MissingBreak`     |

Umbral: `60.0` (alineado con el Azure Speech SDK).

#### Precisión IPA (peso: 55%)

El texto de referencia y el transcrito se comparan en **dos niveles** mediante una alineación de secuencias basada en Levenshtein (programación dinámica con precisión `float64` y tolerancia de retroceso ε = 10⁻⁶):

**Nivel 1 — Alineación de palabras (`_align_words`):**

Las listas de palabras de referencia y transcritas se alinean con una DP de Levenshtein simple (sin costes de similitud fonética — la igualdad de palabras es binaria). Produce operaciones match / substitute / insert / delete. Las palabras extra pronunciadas por el usuario (inserciones) se penalizan en la puntuación global.

**Nivel 2 — Alineación de fonemas (`_align_phonemes`, por pareja de palabras):**

Para cada pareja de palabras alineada, las secuencias de fonemas de referencia y reales se alinean con el mismo algoritmo de DP. La distancia de edición usa la **similitud fonética** — sustituir un fonema por otro del mismo grupo fonético (p. ej. `ɛ` ↔ `æ`, ambas vocales anteriores) cuesta menos que sustituirlo por un fonema de un grupo distinto.

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

**Puntuación de confianza de los fonemas:**

| Resultado de la alineación              | Confianza  |
| --------------------------------------- | ---------- |
| Coincidencia exacta                     | `1.0`      |
| Sustitución (mismo grupo fonético)      | `0.3`      |
| Sustitución (grupo fonético distinto)   | `0.0`      |
| Eliminación (ausente en lo real)        | `0.0`      |
| Inserción (extra en lo real)            | `0.0`      |

**Precisión por palabra:**

```math
WordAccuracy = \frac{CorrectPhonemes}{RefPhonemesInWord} \times 100
```

**Precisión IPA global (con penalización por inserciones):**

```math
OverallIPA = \frac{\sum CorrectPhonemes}{\sum RefPhonemes + \sum InsertedPhonemes} \times 100
```

> Las palabras extra pronunciadas suman su número de fonemas al denominador, lo que reduce la precisión global.

#### Puntuación GOP (peso: 45%)

GOP (Goodness of Pronunciation) usa los log-posteriors CTC de Wav2Vec2:

**Paso 1 — Log-posteriors CTC:**

Audio → Wav2Vec2 → logits de salida → `log_softmax` → matriz `(T, V)` donde T = fotogramas, V = tamaño del vocabulario

**Paso 2 — Segmentación de fotogramas que tiene en cuenta el resto:**

Se reparten los T fotogramas entre N fonemas. Cada fonema recibe una asignación base, y los fotogramas sobrantes se reparten entre los **últimos** fonemas:

```math
base = \lfloor T / N \rfloor,\quad remainder = T \bmod N
```

Los fonemas en las posiciones `[N - remainder, N)` reciben `base + 1` fotogramas; los anteriores reciben `base`. Esto garantiza que **se usan los T fotogramas** — no se descarta ninguno del final.

**Paso 3 — GOP sin procesar por fonema:**

Para cada fonema `p`, se asigna al token del vocabulario de Wav2Vec2 mediante `_IPA_TO_WAV2VEC` y se calcula la log-probabilidad media sobre sus fotogramas asignados `[start, end)`:

```math
GOP_{raw}(p) = \frac{1}{d} \sum_{t=start}^{end-1} \log P(p \mid o_t)
```

donde `d = end - start` es el número de fotogramas asignados al fonema `p`.

> Si el fonema no está en el vocabulario → alternativa: se usa la log-prob máxima de todo el vocabulario para esos fotogramas.

**Paso 4 — Normalización a [0, 100]:**

Calibrado empíricamente: los log-probs de CTC para fonemas bien pronunciados suelen ir de −25 (muy malo) a −3 (excelente). Incluso el audio TTS "perfecto" rara vez produce puntuaciones sin procesar superiores a −3, porque el softmax de CTC siempre reparte la masa de probabilidad por todo el vocabulario.

```math
GOP_{norm} = \frac{\text{clamp}(GOP_{raw},\ -25,\ -3) - (-25)}{22} \times 100
```

Recortado a `[0, 100]`.

**Paso 5 — Agregación:**

- **GOP por palabra** = media de las puntuaciones GOP de los fonemas de esa palabra
- **GOP global** = media de todas las puntuaciones GOP de los fonemas

> Los límites de palabra usan un seguimiento basado en índices (no en igualdad de cadenas), de modo que las palabras repetidas como en "the cat and the dog" se manejan correctamente.

#### Puntuación combinada

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

#### Niveles de calidad

| Rango de puntuación | Nivel        | Retroalimentación                    |
| ------------ | ------------ | ------------------------------------ |
| **80 – 100** | 🟢 Excellent | El habla se ajusta mucho a la referencia |
| **60 – 79**  | 🔵 Good      | Se podrían hacer pequeñas mejoras    |
| **40 – 59**  | 🟡 Fair      | Varios sonidos necesitan práctica    |
| **0 – 39**   | 🔴 Poor      | Se necesita una mejora significativa |

### Ejemplo de puntuación

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

