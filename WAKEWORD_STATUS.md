# Статус: кастомная wake word модель `ey_milosh`

Дата обновления: 2026-06-02

## 1. Текущий продакшен-статус

Активная модель заменена на V2 DNN:

- Активный файл: `/home/ultra/oww-models/ey_milosh.tflite`
- Размер: 862528 bytes
- Порог в `ha.docker-compose.yaml`: `0.97`
- Сервис: `wyoming-openwakeword`
- Wake word name в satellite: `ey_milosh`
- Backup V1: `/home/ultra/oww-models/backups/ey_milosh_v1_backup_20260601_130310.tflite`

После замены пересозданы только voice services:

```bash
docker compose -f ha.docker-compose.yaml up -d --force-recreate wyoming-openwakeword wyoming-satellite
docker compose -f ha.docker-compose.yaml up -d --force-recreate wyoming-openwakeword
```

Проверено по логам:

- `wyoming-openwakeword` видит только `ey_milosh`
- threshold загружен как `0.97`
- satellite подключился к wake service
- Home Assistant container не перезапускался

## 2. Что изменилось в методике

Старый статус был слишком оптимистичным: он опирался на random window split и не отделял модельную метрику от реального deployment-порога.

Новая методика:

1. Split делается по файлам, а не по окнам, чтобы окна одного WAV не попадали одновременно в train и validation.
2. Короткие synthetic positives паддятся до полного openWakeWord context window.
3. V2 использует `CONTEXT_FRAMES=16` (`~1.99s`) вместо V1 `CONTEXT_FRAMES=8` (`~1.35s`).
4. Валидация считает threshold sweep и выбирает более высокий порог среди вариантов с допустимым FPR, если recall почти не падает.
5. Отдельно считаются:
   - validation recall/FPR
   - test recall/FPR на holdout split
   - adversarial negatives
   - home false wake negatives
   - sampled STT debug negatives
6. Baseline и финальная модель проверяются именно как `.tflite`, а не только как PyTorch checkpoint.

Новый инструмент:

- `scripts/wakeword_iterate.py` - dataset discovery, feature extraction, training, threshold sweep, reports.
- `scripts/wakeword_torch_to_tflite.py` - прямой конвертер DNN checkpoint -> Keras/TFLite.

## 3. Важное открытие по данным

Каталог `/home/ultra/oww-dataset/raw/` нельзя считать 7k часами аудио.

Фактически найдено:

- `raw_empty_or_header_only`: 43602 WAV-файла
- почти все эти файлы имеют размер 44 bytes, то есть это только WAV header без аудио
- такие файлы исключены из обучения и метрик

Реально использованные данные:

| Source | Files | Hours / windows | Role |
|---|---:|---:|---|
| Synthetic positives | 4500 | 0.8469 h | train/val/test |
| Adversarial negatives | 2500 | 0.5856 h | train/val/test |
| Home false wake negatives | 216 | 0.1200 h | train/val/test |
| Debug STT recordings | 78 | 82.85 h available, 400 sampled windows | test only |

## 4. Итерации и метрики

Все цифры ниже получены через `scripts/wakeword_iterate.py` на seed `20260601`.

### Baseline: V1 TFLite

Файл: `/home/ultra/oww-models/ey_milosh_v1/ey_milosh.tflite`

| Metric | Value |
|---|---:|
| Context | 8 frames |
| Selected threshold | 0.99 |
| Validation recall | 0.000 |
| Validation FPR/hour | 0.000 |
| Test recall | 0.000 |
| Test FPR/hour | 15.835 |

Вывод: V1 практически непригодна. На безопасном пороге она не слышит positives, а на низких порогах дает сотни ложных срабатываний в час по validation estimate.

Report: `/home/ultra/oww-models/metrics_baseline_v1.json`

### Iteration 1: V2 DNN/GRU

Run dir: `/home/ultra/oww-models/ey_milosh_v2_iter1/`

| Model | Threshold | Validation recall | Validation FPR/h | Test recall | Test FPR/h | Notes |
|---|---:|---:|---:|---:|---:|---|
| DNN16 | 0.62 | 0.999 | 0.000 | 0.987 | 3.028 | 1 FP on adversarial `Милос` |
| GRU16 | 0.27 | 1.000 | 0.000 | 1.000 | 0.000 | Best metric, not deployed yet |

Вывод: GRU выглядит лучше, но DNN проще и уже конвертируется в TFLite. Для DNN методика выбора порога была улучшена, потому что порог 0.62 давал слабый запас против hard negatives.

### Iteration 2: V2 DNN with robust threshold

Run dir: `/home/ultra/oww-models/ey_milosh_v2_iter2_dnn_margin/`

Финальный TFLite:

- `/home/ultra/oww-models/ey_milosh_v2_iter2_dnn_margin/dnn/ey_milosh.tflite`
- Скопирован в `/home/ultra/oww-models/ey_milosh.tflite`

TFLite verification:

| Metric | Validation | Test |
|---|---:|---:|
| Threshold | 0.97 | 0.97 |
| Recall | 0.9928 | 0.9850 |
| Precision | 1.0000 | 1.0000 |
| FPR/hour | 0.0000 | 0.0000 |
| False positives | 0 / 425 negatives | 0 / 815 negatives |
| False negatives | 5 / 694 positives | 10 / 668 positives |

Report: `/home/ultra/oww-models/ey_milosh_v2_iter2_dnn_margin/dnn/metrics_tflite.json`

Вывод: V2 DNN TFLite достаточно хороша для live trial. Главная цена порога `0.97` - часть single-word positives `Милош` теряется. Фраза `эй Милош` на synthetic holdout прошла без FN.

### Iteration 3: DNN recall recovery, larger STT sample

Run dir: `/home/ultra/oww-models/ey_milosh_v2_iter3_dnn_recall/`

Параметры:

- `--max-stt-windows 1200`
- `--epochs 60`
- `--architectures dnn`
- `--context-frames 16`
- `--hidden 192`
- `--negative-weight 2.0`
- `--positive-augmentations 4`

PyTorch checkpoint metrics:

| Metric | Validation | Test |
|---|---:|---:|
| Selected threshold | 0.81 | 0.81 |
| Recall | 0.9914 | 0.9835 |
| FP / FPR/hour | 0 / 0.0000 | 0 / 0.0000 |
| Debug STT sampled windows | - | 1200 |
| Debug STT FP | - | 0 |
| Debug STT score max | - | 0.4866 |

Artifacts:

- `/home/ultra/oww-models/ey_milosh_v2_iter3_dnn_recall/dnn/ey_milosh_v2_iter3_dnn_recall_dnn.pt`
- `/home/ultra/oww-models/ey_milosh_v2_iter3_dnn_recall/dnn/ey_milosh_v2_iter3_dnn_recall_dnn.onnx`
- `/home/ultra/oww-models/ey_milosh_v2_iter3_dnn_recall/dnn/metrics.json`
- `/home/ultra/oww-models/ey_milosh_v2_iter3_dnn_recall/run_report.json`

Conversion blocker: `scripts/wakeword_torch_to_tflite.py` requires TensorFlow, but `oww-train:latest` and local `hga/` do not currently have TensorFlow installed. No TFLite was produced for this run.

Вывод: iter3 is safer on the enlarged STT sample than active iter2 TFLite, but recall regressed. Not a deploy candidate unless TFLite conversion is solved and the lower recall tradeoff is explicitly accepted.

### Iteration 4: DNN recall recovery, lower negative weight

Run dir: `/home/ultra/oww-models/ey_milosh_v2_iter4_dnn_recall_nw16/`

Параметры совпадают с iter3, except `--negative-weight 1.6`.

PyTorch checkpoint metrics:

| Metric | Validation | Test |
|---|---:|---:|
| Selected threshold | 0.97 | 0.97 |
| Recall | 0.9957 | 0.9835 |
| FP / FPR/hour | 0 / 0.0000 | 3 / 3.8839 |
| Debug STT sampled windows | - | 1200 |
| Debug STT FP | - | 3 |
| Debug STT score max | - | 0.9996 |

Artifacts:

- `/home/ultra/oww-models/ey_milosh_v2_iter4_dnn_recall_nw16/dnn/ey_milosh_v2_iter4_dnn_recall_nw16_dnn.pt`
- `/home/ultra/oww-models/ey_milosh_v2_iter4_dnn_recall_nw16/dnn/ey_milosh_v2_iter4_dnn_recall_nw16_dnn.onnx`
- `/home/ultra/oww-models/ey_milosh_v2_iter4_dnn_recall_nw16/dnn/metrics.json`
- `/home/ultra/oww-models/ey_milosh_v2_iter4_dnn_recall_nw16/run_report.json`

Вывод: iter4 is not a deploy candidate. It improves validation recall vs iter3, but test recall remains below active iter2 and STT false positives return.

### Active iter2 TFLite re-check on 1200 STT windows

Report: `/home/ultra/oww-models/ey_milosh_v2_iter2_dnn_margin/dnn/metrics_tflite_stt1200.json`

| Metric | Value |
|---|---:|
| Threshold | 0.97 |
| Validation recall | 0.9928 |
| Validation FP / FPR/hour | 0 / 0.0000 |
| Test recall | 0.9850 |
| Test FP / FPR/hour | 3 / 3.8839 |
| Debug STT sampled windows | 1200 |
| Debug STT FP | 3 |
| Debug STT score max | 0.9977 |

This shows the previous `debug STT max score 0.8609` and FP=0 result was sample-size dependent (`max-stt-windows 400`). On the larger deterministic 1200-window sample, active iter2 still has the best available TFLite recall, but it no longer has offline FP=0.

## 5. Ограничения текущих метрик

Метрики стали честнее, но это еще не финальная оценка.

Ограничения:

1. Нет реальных positive-записей пользователя. Recall сейчас измерен на synthetic Piper voices.
2. STT negatives взяты sampled windows, а не полным 24h streaming-прогоном.
3. FPR/hour оценен по 1.99s windows; это приближение, не полная имитация `pyopen_wakeword` streaming + refractory.
4. `raw/` continuous recorder сломан и не дает usable audio.
5. GRU16 показал лучшие offline-метрики, но пока не конвертирован и не проверен как TFLite.

## 6. Следующий цикл

Приоритеты следующей итерации:

1. Live trial 24-48 часов на активной V2 DNN:
   - считать новые `*-wake.wav` в `/home/ultra/wyoming-debug/`
   - вручную пометить true wake / false wake
   - добавить false wakes в hard negatives
2. Записать 50-100 реальных positives:
   - `эй Милош`
   - `Милош`
   - разные расстояния, шум ТВ, обычная речь
3. Починить continuous recorder:
   - текущий `/home/ultra/oww-dataset/raw/` пишет пустые 44-byte WAV
   - нужен recorder, который реально сохраняет channel 0 PCM
4. Сделать full streaming evaluation:
   - прогонять `.tflite` через `pyopen_wakeword`
   - учитывать refractory seconds и trigger-level
   - считать detections/hour на длинных STT/debug записях
5. Проверить GRU16 TFLite feasibility:
   - если Keras GRU conversion пройдет и pyopen_wakeword примет модель, сравнить live с DNN.

## 7. Команды воспроизведения

Baseline V1:

```bash
docker run --rm --user 1000:1000 \
  -v /home/ultra/homeassistant:/workspace/homeassistant:ro \
  -v /home/ultra/oww-dataset:/workspace/dataset:ro \
  -v /home/ultra/oww-models:/workspace/models \
  -v /home/ultra/wyoming-debug:/workspace/wyoming-debug:ro \
  -v /home/ultra/openWakeWord:/workspace/openWakeWord:ro \
  oww-train:latest \
  python3 /workspace/homeassistant/scripts/wakeword_iterate.py \
    --max-stt-windows 400 \
    evaluate-tflite \
    --model /workspace/models/ey_milosh_v1/ey_milosh.tflite \
    --output /workspace/models/metrics_baseline_v1.json
```

Final DNN iteration:

```bash
docker run --rm --user 1000:1000 \
  -v /home/ultra/homeassistant:/workspace/homeassistant \
  -v /home/ultra/oww-dataset:/workspace/dataset:ro \
  -v /home/ultra/oww-models:/workspace/models \
  -v /home/ultra/wyoming-debug:/workspace/wyoming-debug:ro \
  -v /home/ultra/openWakeWord:/workspace/openWakeWord:ro \
  oww-train:latest \
  python3 /workspace/homeassistant/scripts/wakeword_iterate.py \
    --max-stt-windows 400 \
    --selection-recall-tolerance 0.005 \
    iterate \
    --run-name ey_milosh_v2_iter2_dnn_margin \
    --epochs 45 \
    --architectures dnn \
    --context-frames 16 \
    --negative-weight 2.5 \
    --positive-augmentations 2
```
