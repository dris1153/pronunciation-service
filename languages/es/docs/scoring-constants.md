<!-- doc-id: docs-scoring-constants | lang: es | source-rev: 6006c067 -->

> 🌐 **Traducción al español** de [`docs/scoring-constants.md`](../../../docs/scoring-constants.md) (rev `6006c067`). La versión en inglés es la oficial: si difieren, prevalece el inglés. Traducción automática, sin revisión de un hablante nativo.

# Justificación de las constantes de puntuación

Por qué cada constante de puntuación fijada en el código tiene el valor que
tiene. Cambiar cualquiera de ellas exige ejecutar la suite de sanidad:

```
python scripts/sanity_eval.py \
    --api-key=$API_KEY \
    --compare-baseline=tests/sanity_dataset/sanity_baseline.json
```

Si el comparador informa de una desviación > 5pt o de cualquier cambio de nivel, decide:

- **¿Recalibración intencionada?** → actualiza `sanity_baseline.json` y documenta
  el cambio aquí.
- **¿Regresión?** → revierte.

---

## 1. Calibración de GOP: `_FLOOR = -25.0`, `_CEIL = -3.0`

- **Dónde:** `app/services/gop_service.py` (paso de normalización)
- **Empírico:** los log-probs de CTC para fonemas bien pronunciados van de
  aproximadamente -25 (muy malo) a -3 (excelente). Incluso un TTS perfecto rara vez supera
  -3 porque la masa del softmax se reparte por todo el vocabulario.
- **Riesgo si se cambia:** reasignación lineal → todas las puntuaciones GOP se desplazan proporcionalmente,
  lo que alimenta accuracy_score (45% de peso) y overall_score.

## 2. Crédito parcial por similitud de fonemas: `0.3`

- **Dónde:** `app/services/pronunciation_service.py` — matriz de costes de la
  alineación de fonemas.
- **Empírico:** sustituir un fonema por otro del mismo grupo fonético
  (p. ej. ɛ↔æ, ambas vocales anteriores) obtiene 0.3 frente a 1.0 (coincidencia) o 0.0 (grupo
  distinto). Un valor mayor inflaría la precisión frente a la puntuación más estricta de Azure;
  un valor menor penaliza demasiado duramente las variaciones leves de acento.
- **Riesgo si se cambia:** la precisión por fonema cambia → la precisión IPA agregada
  se mueve linealmente → cambia accuracy_score (55% de peso).

## 3. Umbral de error de pronunciación: `60.0`

- **Dónde:** `app/services/pronunciation_service.py` —
  `_MISPRONUNCIATION_THRESHOLD`.
- **Justificación:** alineado con la convención del Azure Speech SDK — las palabras por debajo del 60%
  de precisión IPA se marcan como errores de pronunciación.
- **Riesgo si se cambia:** cambia la clasificación `error_type` a nivel de palabra; las palabras
  recién clasificadas como mal pronunciadas dejan de contar para
  `completeness_score`.

## 4. Tamaño de salto (hop) de Wav2Vec2: `320`

- **Dónde:** `app/services/pronunciation_service.py` — `_HOP_SIZE`.
- **Justificación:** arquitectura de Wav2Vec2: fotogramas de 20 ms a 16 kHz = 320 muestras
  por fotograma. Se usa en la alineación forzada de tiempos por palabra que alimenta
  `fluency_score`.
- **Riesgo si se cambia:** cualquier cambio de modelo que modifique el hop EXIGE también
  actualizar esta constante; de lo contrario los tiempos por palabra serán erróneos → la
  métrica de fluidez devuelve basura.
- **Protección en CI:** la suite de sanidad detecta la desviación si se actualiza el modelo sin
  actualizar el hop.

## 5. Inconsistencia de la penalización por velocidad: `30 pts/wps` (prosodia) frente a `20 pts/wps` (fluidez)

- **Dónde:** `app/services/prosody_service.py` (~línea 178) y
  `app/services/pronunciation_service.py` — `_RATE_PENALTY_PER_WPS`.
- **Estado:** **inconsistencia conocida.** El motivo histórico de la
  penalización asimétrica no está documentado en el código. Marcada para la calibración
  de v2 cuando haya datos de producción.
- **Riesgo si se unifica:** ambas subpuntuaciones cambian → cambian los pesos de overall_score
  → hay que regenerar la línea base de sanidad.

---

## Constantes de v2 (`app/services/v2/`)

Las secciones 1-5 son constantes de v1. El pipeline v2 tiene las suyas, en su mayoría aprendidas de los datos:

| Constante | Valor | Dónde | Por qué |
| --- | --- | --- | --- |
| `SCORE_CURVE_EXPONENT` | `1.4` | `pronunciation_v2_service.py` | Traslada las predicciones en la escala de los expertos (sobre todo 6-10) a la escala más estricta de v1: `100 x (s/10)^1.4`. Con 1.3, `poor_001` quedaba en 59.4, demasiado cerca de la línea de 60. Ajustado con 5 clips sintéticos; recalíbralo con audio real de estudiantes. Modifica las correlaciones de enunciado en <= 0.005 |
| `MIN_HEARD_RATIO` | `0.2` | `pronunciation_v2_service.py` | Si se oye menos del 20% de los fonemas esperados, el audio se trata como ausencia de habla (puntuación cero). La menor proporción en habla real de speechocean762 es 0.31 |
| `mdd_threshold` | `1.48` (de 2) | `scorer.json` | Una puntuación de fonema inferior a este valor implica `is_correct_ipa = false`. Elegido para maximizar el F1 de errores de pronunciación sobre las predicciones out-of-fold de train |
| `MIN_SAMPLES` | `400` | `phone_model.py` | El front-end convolucional de HuBERT rechaza audio más corto (25 ms) |
| `Z_CLIP` | `10` | `scorer.py` | Los one-hot de fonemas raros tienen una varianza minúscula; los z-scores sin recortar llegaban a ~200 y rompían el ajuste |
| Umbral de palabra mal pronunciada | `60` | `scoring_rules.py` | Compartido con v1 (Azure usa el mismo) |
| Umbrales de pausa | `0.8 s` / `0.15 s` | `scoring_rules.py` | Compartidos con v1; v2 los aplica a los intervalos de palabras alineadas |

Cambiar el modelo de fonemas, la disposición de las características o el inventario de fonemas exige reentrenar `scorer.json` ([training.md](training.md)). La calidad se comprueba con `scripts/speechocean762_eval.py --api v2` ([evaluation.md](evaluation.md)).

## Cómo actualizar una constante de forma segura

1. Haz el cambio en el archivo de servicio correspondiente.
2. Reinicia el servidor local.
3. Ejecuta:
   ```
   python scripts/sanity_eval.py \
       --api-key=$API_KEY \
       --compare-baseline=tests/sanity_dataset/sanity_baseline.json
   ```
4. Si el código de salida es 0: el cambio está dentro de la tolerancia. Haz commit junto con una entrada en
   el registro de cambios de abajo.
5. Si el código de salida es 1 con una recalibración intencionada: regenera la línea base, haz commit de
   ambos archivos y documenta la recalibración aquí.
6. Si el código de salida es 1 con una regresión no intencionada: revierte.

## Registro de cambios

- _2026-05-04_ — Documentación inicial (Fase 06).