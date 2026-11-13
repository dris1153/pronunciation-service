<!-- doc-id: training-readme | lang: es | source-rev: e36372fb -->

> 🌐 **Traducción al español** de [`training/README.md`](../../../training/README.md) (rev `e36372fb`). La versión en inglés es la oficial: si difieren, prevalece el inglés. Traducción automática, sin revisión de un hablante nativo.

# training/ — entrenamiento de modelos sin conexión (Fase B)

No lo importa `app/`. Usa su propio venv de CUDA para que el venv del servicio siga siendo solo de CPU.

```bash
py -V:3.11 -m venv .venv-train
.venv-train/Scripts/python -m pip install torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124
.venv-train/Scripts/python -m pip install -r training/requirements-train.txt
```

## Modelo CTC de fonemas (HuBERT-base)

Datos: LibriSpeech `train-clean-100`, `dev-clean`, `test-clean` (openslr.org/12, CC BY 4.0) extraídos en `data/librispeech/`.
Etiquetas: transcripción → `g2p_en` → IPA, vocabulario = los 41 símbolos IPA del servicio + blank (`training/phone_labels.py`).

```bash
.venv-train/Scripts/python -m training.train_phone_ctc --steps 25000      # best dev PER checkpoint → data/models/hubert-phone-ctc/
.venv-train/Scripts/python -m training.eval_per --split test-clean
```

Contrato de entrada (debe coincidir con el runtime): 16 kHz mono float32, **normalizado por pico**, sin normalización de media/varianza.
Solo habla nativa — nunca entrenes con audio L2 y etiquetas canónicas (el modelo aprendería a perdonar los errores).

Exportación para el servicio (FP32, longitud dinámica, comprueba la paridad frente a torch):

```bash
.venv-train/Scripts/python -m training.export_onnx   # -> data/models/hubert-phone-ctc/model.onnx
```

## Evaluador (MLP por fonema + cabezales ridge)

Necesita las características de train/test de speechocean762 (CC BY 4.0, L1 mandarín — consulta también la nota sobre la brecha de dominio en el informe de la Fase 03):

```bash
python scripts/speechocean762_eval.py --api v2 --split train --out data/so762-v2-train.jsonl --report data/so762-v2-train-report.json
python scripts/speechocean762_eval.py --api v2 --split test  --out data/so762-v2-test.jsonl  --report data/so762-v2-test-report.json
.venv/Scripts/python -m training.train_scorer      # -> data/models/hubert-phone-ctc/scorer.json
```

Sin `scorer.json`, el harness igualmente escribe las características por fonema (las puntuaciones son ceros), que es todo lo que necesita el entrenamiento.
La partición de prueba solo se usa para el informe final; los lambdas y el umbral de MDD provienen de las predicciones out-of-fold de train.
