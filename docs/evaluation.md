<!-- doc-id: docs-evaluation | rev: e6f94b86 -->
# Evaluation, benchmarks and tests

## Quality against expert scores

[speechocean762](https://www.openslr.org/101/) (CC BY 4.0; Zhang et al., Interspeech 2021): 5000 utterances from 250 non-native speakers (Mandarin L1, half children), scored by 5 experts at phone (0-2), word (0-10) and utterance (0-10) level. Extract it to `data/speechocean762/`. The harness runs the pipeline in-process (no HTTP, no rate limit) and resumes from its JSONL output.

```bash
python scripts/speechocean762_eval.py --api v1 --out data/so762-v1-test.jsonl --report data/so762-v1-test-report.json
python scripts/speechocean762_eval.py --api v2 --out data/so762-v2-test.jsonl --report data/so762-v2-test-report.json
python scripts/speechocean762_v2_signal.py data/so762-v2-test.jsonl     # phone correlation, MDD, confusions, latency
```

It reports Pearson correlation for utterance, word and phone scores, and mispronunciation detection (MDD) precision / recall / F1, for all speakers and for adults (18+) only. "Mispronounced" means an expert phone score below 1.0 (about 4% of phones).

| Test split | v1 adults | v2 adults | v2 all |
| --- | --- | --- | --- |
| Utterance total / accuracy | 0.619 / 0.669 | 0.852 / 0.829 | 0.779 / 0.749 |
| Utterance fluency / prosodic | 0.630 / 0.108 | 0.876 / 0.853 | 0.817 / 0.796 |
| Word accuracy | 0.020 | 0.643 | 0.591 |
| Phone accuracy | 0.033 | 0.630 | 0.590 |
| MDD F1 | 0.269 | 0.537 | 0.480 |

Notes: v2 numbers use the FP32 model; INT8 is within 0.004 on every metric (completeness, a rule-based score with almost no variance in the labels, moved by 0.010). The score curve changes utterance correlations by 0.005 or less. v1's largest errors come from ASR gibberish on accented speech. How v2 works: [scoring-v2.md](scoring-v2.md).

### What this does not tell you

- **Every speaker is Mandarin-L1.** Vietnamese learners make different errors (final consonants, th/dh, s/sh, clusters). No Vietnamese-L1 numbers exist yet.
- The sanity clips behind the score-curve exponent are five synthetic (gTTS) recordings.
- The scorer was not validated on audio between 20 and 30 s.

### Data plan for Vietnamese learners

A survey found **no open, commercially usable Vietnamese-L1 English corpus with pronunciation scores**. L2-ARCTIC has four Vietnamese speakers but binary phone labels and a non-commercial licence; speechocean762 is Mandarin only; Vietnamese native-speech corpora do not contain English. The realistic route is to record and annotate learners with the speechocean762 protocol (3+ raters, phone 0-2 / word / utterance), starting with roughly 50-100 adult speakers and 500-1000 utterances to recalibrate the scorer.

## Latency and memory

`debugs/benchmark.py` times the real pipeline in-process. `--cpus N` pins the process to N cores to mimic an N-vCPU host.

```bash
python debugs/benchmark.py --api v1 --cpus 4
python debugs/benchmark.py --api v2 --int8 --cpus 4 --concurrency 2
```

Measured on a Windows dev box (28 logical cores), gTTS sanity clips 1.2-4.2 s, p50 in ms:

| 3.4 s clip | v1 | v2 FP32 | **v2 INT8** |
| --- | --- | --- | --- |
| 2 vCPU | 610 | 375 | **240** |
| 4 vCPU | 381 | 201 | **125** |

| Concurrent (2 slots, 30 requests) | v1 | v2 FP32 | **v2 INT8** |
| --- | --- | --- | --- |
| 4 vCPU, p50 / p90 ms | 461 / 891 | 155 / 416 | **93 / 271** |
| 4 vCPU, req/s | 3.9 | 8.2 | **13.2** |
| 2 vCPU, req/s | 2.7 | 4.5 | **7.4** |

| Memory (RSS) | after load | after requests |
| --- | --- | --- |
| v1 | 796 MB | 970-1090 MB |
| v2 FP32 | 928 MB | 1050-1170 MB |
| v2 INT8 | **430 MB** | 600-660 MB |
| v1 + v2 INT8 in one process | 1030 MB | not measured |

In v2 the model is essentially the whole cost (INT8, 4 vCPU, 3.4 s clip: ONNX ~120 ms, alignment ~3 ms, scorer ~1 ms). INT8 is the default and the only reasonable choice on small hosts; FP32 is heavier than v1 at load. These are dev-box numbers: re-run the benchmark on the real host before switching clients, because INT8 speed-up depends on CPU instruction support. Every `/evaluate` also logs one `evaluate_timing` record with per-stage milliseconds.

## Tests

```bash
pytest tests/ -v
```

About 460 tests: API (v1 and v2), auth and rate limiting, audio handling, text/IPA/GOP/prosody services, alignment and scoring rules, the v2 CTC alignment (parity with `torchaudio.forced_align`), features, scorer, and a guard that `app/services/v2/` never imports torch. Tests needing the real v2 model files (sanity bands, noise gate) skip themselves when the files are absent. `asyncio_mode = "auto"`.

`tests/sanity_dataset/` holds five synthetic recordings (3 good, 2 poor) with expected score bands; regenerate them with `scripts/generate_sanity_audio.py`.

**Known issue:** two v1 sanity cases (`poor_001`, `poor_002`) fail because v1 scores those clips just above the 60 ceiling of their band. v2 passes both.
