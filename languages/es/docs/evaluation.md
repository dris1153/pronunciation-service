<!-- doc-id: docs-evaluation | lang: es | source-rev: e6f94b86 -->

> 🌐 **Traducción al español** de [`docs/evaluation.md`](../../../docs/evaluation.md) (rev `e6f94b86`). La versión en inglés es la oficial: si difieren, prevalece el inglés. Traducción automática, sin revisión de un hablante nativo.

# Evaluación, benchmarks y pruebas

## Calidad frente a las puntuaciones de expertos

[speechocean762](https://www.openslr.org/101/) (CC BY 4.0; Zhang et al., Interspeech 2021): 5000 enunciados de 250 hablantes no nativos (L1 mandarín, la mitad niños), puntuados por 5 expertos a nivel de fonema (0-2), palabra (0-10) y enunciado (0-10). Extráelo en `data/speechocean762/`. El harness ejecuta el pipeline en el mismo proceso (sin HTTP ni límite de peticiones) y se reanuda a partir de su salida JSONL.

```bash
python scripts/speechocean762_eval.py --api v1 --out data/so762-v1-test.jsonl --report data/so762-v1-test-report.json
python scripts/speechocean762_eval.py --api v2 --out data/so762-v2-test.jsonl --report data/so762-v2-test-report.json
python scripts/speechocean762_v2_signal.py data/so762-v2-test.jsonl     # phone correlation, MDD, confusions, latency
```

Informa de la correlación de Pearson para las puntuaciones de enunciado, palabra y fonema, y de la precisión / recall / F1 de la detección de errores de pronunciación (MDD), para todos los hablantes y solo para adultos (18+). "Mal pronunciado" significa una puntuación de fonema de los expertos inferior a 1.0 (alrededor del 4% de los fonemas).

| División de prueba | v1 adultos | v2 adultos | v2 todos |
| --- | --- | --- | --- |
| Enunciado: total / precisión | 0.619 / 0.669 | 0.852 / 0.829 | 0.779 / 0.749 |
| Enunciado: fluidez / prosodia | 0.630 / 0.108 | 0.876 / 0.853 | 0.817 / 0.796 |
| Precisión de la palabra | 0.020 | 0.643 | 0.591 |
| Precisión del fonema | 0.033 | 0.630 | 0.590 |
| MDD F1 | 0.269 | 0.537 | 0.480 |

Notas: las cifras de v2 usan el modelo FP32; INT8 queda a 0.004 o menos en todas las métricas (la completitud, una puntuación basada en reglas con casi ninguna varianza en las etiquetas, varió 0.010). La curva de puntuación cambia las correlaciones de enunciado en 0.005 o menos. Los mayores errores de v1 provienen de transcripciones sin sentido del ASR con habla acentuada. Cómo funciona v2: [scoring-v2.md](scoring-v2.md).

### Lo que estas cifras no te dicen

- **Todos los hablantes tienen L1 mandarín.** Los estudiantes vietnamitas cometen errores distintos (consonantes finales, th/dh, s/sh, grupos consonánticos). Todavía no existen cifras con L1 vietnamita.
- Los clips de sanidad que sustentan el exponente de la curva de puntuación son cinco grabaciones sintéticas (gTTS).
- El evaluador no se validó con audio de entre 20 y 30 s.

### Plan de datos para estudiantes vietnamitas

Una revisión no encontró **ningún corpus abierto y de uso comercial de inglés con L1 vietnamita y puntuaciones de pronunciación**. L2-ARCTIC tiene cuatro hablantes vietnamitas, pero con etiquetas binarias de fonema y una licencia no comercial; speechocean762 es solo de mandarín; los corpus de habla nativa vietnamita no contienen inglés. La vía realista es grabar y anotar a estudiantes con el protocolo de speechocean762 (3+ evaluadores, fonema 0-2 / palabra / enunciado), empezando con unos 50-100 hablantes adultos y 500-1000 enunciados para recalibrar el evaluador.

## Latencia y memoria

`debugs/benchmark.py` mide el tiempo del pipeline real en el mismo proceso. `--cpus N` fija el proceso a N núcleos para imitar un host de N vCPU.

```bash
python debugs/benchmark.py --api v1 --cpus 4
python debugs/benchmark.py --api v2 --int8 --cpus 4 --concurrency 2
```

Medido en una máquina de desarrollo con Windows (28 núcleos lógicos), clips de sanidad gTTS de 1.2-4.2 s, p50 en ms:

| Clip de 3.4 s | v1 | v2 FP32 | **v2 INT8** |
| --- | --- | --- | --- |
| 2 vCPU | 610 | 375 | **240** |
| 4 vCPU | 381 | 201 | **125** |

| Concurrencia (2 huecos, 30 peticiones) | v1 | v2 FP32 | **v2 INT8** |
| --- | --- | --- | --- |
| 4 vCPU, p50 / p90 ms | 461 / 891 | 155 / 416 | **93 / 271** |
| 4 vCPU, pet./s | 3.9 | 8.2 | **13.2** |
| 2 vCPU, pet./s | 2.7 | 4.5 | **7.4** |

| Memoria (RSS) | tras la carga | tras las peticiones |
| --- | --- | --- |
| v1 | 796 MB | 970-1090 MB |
| v2 FP32 | 928 MB | 1050-1170 MB |
| v2 INT8 | **430 MB** | 600-660 MB |
| v1 + v2 INT8 en un solo proceso | 1030 MB | no medido |

En v2 el modelo es prácticamente todo el coste (INT8, 4 vCPU, clip de 3.4 s: ONNX ~120 ms, alineación ~3 ms, evaluador ~1 ms). INT8 es el valor por defecto y la única opción razonable en hosts pequeños; FP32 es más pesado que v1 al cargar. Son cifras de una máquina de desarrollo: vuelve a ejecutar el benchmark en el host real antes de migrar clientes, porque la aceleración de INT8 depende del soporte de instrucciones de la CPU. Cada `/evaluate` también registra un `evaluate_timing` con los milisegundos de cada etapa.

## Pruebas

```bash
pytest tests/ -v
```

Unas 460 pruebas: API (v1 y v2), autenticación y límite de peticiones, manejo de audio, servicios de texto/IPA/GOP/prosodia, reglas de alineación y puntuación, la alineación CTC de v2 (paridad con `torchaudio.forced_align`), características, evaluador, y una comprobación de que `app/services/v2/` nunca importa torch. Las pruebas que necesitan los archivos reales del modelo v2 (bandas de sanidad, compuerta de ruido) se omiten solas cuando los archivos no están. `asyncio_mode = "auto"`.

`tests/sanity_dataset/` contiene cinco grabaciones sintéticas (3 buenas, 2 malas) con bandas de puntuación esperadas; regéneralas con `scripts/generate_sanity_audio.py`.

**Problema conocido:** dos casos de sanidad de v1 (`poor_001`, `poor_002`) fallan porque v1 puntúa esos clips justo por encima del techo de 60 de su banda. v2 pasa ambos.
