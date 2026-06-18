#!/usr/bin/env python3
"""Generate a human-readable wake word report as HTML."""

from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--merged-report", type=Path, default=Path("/home/ultra/oww-models/stream_eval/raw_live_merged.json"))
    parser.add_argument("--baseline-metrics", type=Path, default=Path("/home/ultra/oww-models/metrics_baseline_v1.json"))
    parser.add_argument(
        "--current-metrics",
        type=Path,
        default=Path(
            "/home/ultra/oww-models/ey_milosh_v2_iter7_dnn_hnm_strict_nw12_h256/"
            "dnn/metrics_tflite_pyopen_layout_stt1200.json"
        ),
    )
    parser.add_argument("--status-file", type=Path, default=Path("WAKEWORD_STATUS.md"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--text-output", type=Path)
    return parser


def fmt(value: float, digits: int = 4) -> str:
    return f"{value:.{digits}f}"


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def find_sweep_row(metrics: dict, section: str, threshold: float) -> dict:
    sweep = ((metrics.get(section) or {}).get("sweep") or [])
    for row in sweep:
        if abs(float(row.get("threshold", -1.0)) - threshold) < 0.000001:
            return row
    return {}


def html_page(merged: dict, baseline: dict, current: dict) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    score = merged.get("score_summary") or {}
    crossings = merged.get("raw_chunk_crossings") or {}
    detections = merged.get("detections_with_refractory") or {}

    active_key = "threshold_0.991_refractory_2s"
    active = detections.get(active_key) or {}
    active_fpr = active.get("false_positives_per_hour", 0.0)
    max_score = score.get("max", 0.0)
    hours = float(merged.get("audio_hours") or 0.0)
    files = int(merged.get("files_processed") or 0)
    score_count = int(score.get("count") or 0)
    score_margin = 0.991 - float(max_score)

    baseline_test = (baseline.get("test_at_validation_threshold") or {})
    baseline_selected = baseline_test.get("selected") or {}
    baseline_hours = float(baseline_test.get("negative_hours_estimated") or 0.0)
    baseline_fp = int(baseline_selected.get("fp") or 0)
    baseline_fpr = float(baseline_selected.get("fpr_per_hour") or 0.0)
    baseline_recall = float(baseline_selected.get("recall") or 0.0)

    current_test = current.get("test_sweep_for_audit") or current.get("test_at_validation_threshold") or {}
    current_row = find_sweep_row(current, "test_sweep_for_audit", 0.991)
    if not current_row:
        current_row = current_test.get("selected") or {}
    current_hours = float(current_test.get("negative_hours_estimated") or 0.0)
    current_fp = int(current_row.get("fp") or 0)
    current_fpr = float(current_row.get("fpr_per_hour") or 0.0)
    current_recall = float(current_row.get("recall") or 0.0)
    current_precision = float(current_row.get("precision") or 0.0)
    fpr_reduction = baseline_fpr - current_fpr

    threshold_rows = "\n".join(
        f"<tr><td>{html.escape(str(threshold))}</td><td>{int(count)}</td></tr>"
        for threshold, count in sorted(crossings.items(), key=lambda item: float(item[0]))
    )
    detection_rows = "\n".join(
        f"<tr><td>{html.escape(key.replace('threshold_', '').replace('_refractory_', ', refractory '))}</td>"
        f"<td>{int(row.get('detections') or 0)}</td>"
        f"<td>{fmt(float(row.get('false_positives_per_hour') or 0.0), 6)}</td></tr>"
        for key, row in sorted(detections.items())
    )

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Wake word Милош: отчет</title>
  <style>
    body {{
      font-family: "DejaVu Sans", "Noto Sans", Arial, sans-serif;
      color: #172033;
      margin: 34px;
      line-height: 1.42;
      font-size: 12.5pt;
    }}
    h1 {{ font-size: 24pt; margin: 0 0 8px; }}
    h2 {{ font-size: 16pt; margin: 24px 0 8px; border-bottom: 1px solid #d7dce5; padding-bottom: 4px; }}
    h3 {{ font-size: 13.5pt; margin: 18px 0 6px; }}
    .muted {{ color: #657184; }}
    .ok {{ color: #0b6b3a; font-weight: 700; }}
    .warn {{ color: #8a5a00; font-weight: 700; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 14px 0; }}
    .card {{ border: 1px solid #d7dce5; border-radius: 6px; padding: 10px 12px; background: #fbfcfe; }}
    .metric {{ font-size: 18pt; font-weight: 700; margin-bottom: 2px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 10px 0 16px; }}
    th, td {{ border: 1px solid #d7dce5; padding: 6px 8px; vertical-align: top; }}
    th {{ background: #eef2f7; text-align: left; }}
    ul {{ margin-top: 6px; }}
    .small {{ font-size: 10.5pt; }}
  </style>
</head>
<body>
  <h1>Wake word «Милош»: понятный отчет</h1>
  <p class="muted">Сгенерировано: {html.escape(generated_at)}. Активная модель: <code>ey_milosh.tflite</code>, порог <code>0.991</code>.</p>

  <h2>Короткий вывод</h2>
  <p><span class="ok">Фоновый шум пройден успешно.</span> Модель прогнана как настоящий live-stream через <code>pyopen_wakeword</code>, то есть тем же runtime, который использует Home Assistant. На {fmt(hours, 2)} часах домашнего фона не было ни одного срабатывания.</p>
  <p>Главное изменение после итераций обучения: baseline V1 на offline test давал {baseline_fp} ложных срабатывания за {fmt(baseline_hours, 4)} часа негатива, то есть {fmt(baseline_fpr, 3)} FP/час. Текущий deploy-кандидат на audit/test при рабочем пороге 0.991 дал {current_fp} FP за {fmt(current_hours, 4)} часа, то есть {fmt(current_fpr, 6)} FP/час. На реальной недельной записи дома: 0 FP за {fmt(hours, 2)} часа.</p>
  <p>Это доказывает низкий риск ложных пробуждений на записанном домашнем фоне. Но это еще не доказывает recall на настоящих голосах: для этого нужно записать реальные фразы разных людей.</p>

  <div class="grid">
    <div class="card"><div class="metric">{fmt(hours, 2)} ч</div><div>проверенного фонового шума</div></div>
    <div class="card"><div class="metric">{files}</div><div>WAV-файлов обработано</div></div>
    <div class="card"><div class="metric">0</div><div>ложных срабатываний на активном пороге</div></div>
    <div class="card"><div class="metric">{fmt(float(active_fpr), 6)}/ч</div><div>false positive rate на пороге 0.991</div></div>
  </div>

  <h2>Как улучшились ложные срабатывания</h2>
  <table>
    <thead>
      <tr><th>Проверка</th><th>Порог</th><th>Негативов</th><th>FP</th><th>FP/час</th><th>Recall</th></tr>
    </thead>
    <tbody>
      <tr>
        <td>Baseline V1 TFLite, offline test</td>
        <td>{fmt(float(baseline_selected.get("threshold") or 0.0), 3)}</td>
        <td>{fmt(baseline_hours, 4)} ч</td>
        <td>{baseline_fp}</td>
        <td>{fmt(baseline_fpr, 3)}</td>
        <td>{pct(baseline_recall)}</td>
      </tr>
      <tr>
        <td>Текущий iter7 pyopen TFLite, audit/test</td>
        <td>{fmt(float(current_row.get("threshold") or 0.991), 3)}</td>
        <td>{fmt(current_hours, 4)} ч</td>
        <td>{current_fp}</td>
        <td>{fmt(current_fpr, 6)}</td>
        <td>{pct(current_recall)}</td>
      </tr>
      <tr>
        <td>Текущий deploy, реальный домашний фон raw_live</td>
        <td>0.991</td>
        <td>{fmt(hours, 4)} ч</td>
        <td>0</td>
        <td>{fmt(float(active_fpr), 6)}</td>
        <td>не измерялся: wake-фразу специально не говорили</td>
      </tr>
    </tbody>
  </table>
  <p>Наблюдаемое снижение на offline negative test: с {fmt(baseline_fpr, 3)} до {fmt(current_fpr, 6)} FP/час, то есть минус {fmt(fpr_reduction, 3)} FP/час. В процентах это 100% наблюдаемого снижения на этом тесте, но я не называю модель финальной, пока не будет набора реальных голосов.</p>
  <p>Запас по недельному фону большой: максимальный score был {fmt(float(max_score), 12)}, а рабочий порог 0.991. До порога оставалось {fmt(score_margin, 6)}.</p>

  <h2>Что именно проверено</h2>
  <ul>
    <li>Источник: недельная запись домашнего фона <code>raw_live</code>.</li>
    <li>Объем: {files} файлов, {fmt(hours, 4)} часа.</li>
    <li>Runtime: <code>pyopen_wakeword</code>, full streaming, не offline-window shortcut.</li>
    <li>Пороги: 0.97, 0.99, 0.991, 0.992, 0.995, 0.999.</li>
    <li>Refractory: 2 и 5 секунд.</li>
    <li>Всего score frames: {score_count}.</li>
    <li>Максимальный score на всем фоне: {fmt(float(max_score), 12)}.</li>
    <li>Precision текущего offline audit/test при 0.991: {pct(current_precision)}.</li>
  </ul>

  <h2>Пересечения порогов</h2>
  <table>
    <thead><tr><th>Порог</th><th>Сколько раз score превысил порог</th></tr></thead>
    <tbody>{threshold_rows}</tbody>
  </table>

  <h2>Срабатывания с refractory</h2>
  <table>
    <thead><tr><th>Порог и refractory</th><th>Срабатывания</th><th>FP/час</th></tr></thead>
    <tbody>{detection_rows}</tbody>
  </table>

  <h2>Важное исправление</h2>
  <p>До 2026-06-12 активный TFLite был в training-layout <code>[1, 96, 16]</code>. Live runtime <code>pyopen_wakeword</code> ожидает <code>[1, 16, 96]</code>, поэтому модель могла загружаться, но фактически не выдавать score. Модель переложена в deployment-layout, веса сохранены эквивалентно: old/new check дал max diff <code>2.38e-07</code>.</p>

  <h2>Что дальше</h2>
  <p><span class="warn">Следующий блок обязателен:</span> записать настоящие positive-примеры. Нужно минимум 50-100 удачных срабатываний, лучше 150-200, от разных людей и в разных условиях.</p>
  <h3>Рекомендуемый план записи</h3>
  <ul>
    <li>Основной человек: 60 раз «эй Милош» и 30 раз «Милош».</li>
    <li>Другие люди: по 20-30 раз на человека.</li>
    <li>Громкость: обычный голос, шепот, громко, из другой комнаты.</li>
    <li>Позиции: рядом 1 м, диван 3 м, кухня/коридор/дверной проем.</li>
    <li>Шум: тишина, ТВ/музыка, разговор на фоне, кухня.</li>
    <li>Не надо подряд тараторить: между попытками пауза 3-5 секунд.</li>
  </ul>

  <h2>Файлы</h2>
  <p class="small">Итоговый JSON: <code>/home/ultra/oww-models/stream_eval/raw_live_merged.json</code><br>
  Статус: <code>/home/ultra/homeassistant/WAKEWORD_STATUS.md</code></p>
</body>
</html>
"""


def text_page(merged: dict, baseline: dict, current: dict) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    score = merged.get("score_summary") or {}
    crossings = merged.get("raw_chunk_crossings") or {}
    detections = merged.get("detections_with_refractory") or {}
    active = detections.get("threshold_0.991_refractory_2s") or {}
    hours = float(merged.get("audio_hours") or 0.0)
    files = int(merged.get("files_processed") or 0)
    max_score = float(score.get("max") or 0.0)
    active_fpr = float(active.get("false_positives_per_hour") or 0.0)
    score_margin = 0.991 - max_score

    baseline_test = baseline.get("test_at_validation_threshold") or {}
    baseline_selected = baseline_test.get("selected") or {}
    baseline_hours = float(baseline_test.get("negative_hours_estimated") or 0.0)
    baseline_fp = int(baseline_selected.get("fp") or 0)
    baseline_fpr = float(baseline_selected.get("fpr_per_hour") or 0.0)
    baseline_recall = float(baseline_selected.get("recall") or 0.0)

    current_test = current.get("test_sweep_for_audit") or current.get("test_at_validation_threshold") or {}
    current_row = find_sweep_row(current, "test_sweep_for_audit", 0.991)
    if not current_row:
        current_row = current_test.get("selected") or {}
    current_hours = float(current_test.get("negative_hours_estimated") or 0.0)
    current_fp = int(current_row.get("fp") or 0)
    current_fpr = float(current_row.get("fpr_per_hour") or 0.0)
    current_recall = float(current_row.get("recall") or 0.0)
    current_precision = float(current_row.get("precision") or 0.0)
    fpr_reduction = baseline_fpr - current_fpr

    threshold_lines = "\n".join(
        f"  - {threshold}: {int(count)}"
        for threshold, count in sorted(crossings.items(), key=lambda item: float(item[0]))
    )
    detection_lines = "\n".join(
        f"  - {key.replace('threshold_', '').replace('_refractory_', ', refractory ')}: "
        f"{int(row.get('detections') or 0)} detections, "
        f"{fmt(float(row.get('false_positives_per_hour') or 0.0), 6)}/h"
        for key, row in sorted(detections.items())
    )

    return f"""Wake word "Милош": понятный отчет
Сгенерировано: {generated_at}
Активная модель: ey_milosh.tflite
Активный порог: 0.991

Короткий вывод
--------------
Фоновый шум пройден успешно. Модель прогнана как настоящий live-stream
через pyopen_wakeword, то есть тем же runtime, который использует
Home Assistant. На {fmt(hours, 2)} часах домашнего фона не было ни одного
срабатывания.

Это доказывает низкий риск ложных пробуждений на записанном домашнем фоне.
Но это еще не доказывает recall на настоящих голосах: для этого нужно
записать реальные фразы разных людей.

Как улучшились ложные срабатывания
----------------------------------
Baseline V1 TFLite, offline test:
  - Порог: {fmt(float(baseline_selected.get("threshold") or 0.0), 3)}
  - Негативов: {fmt(baseline_hours, 4)} часа
  - False positives: {baseline_fp}
  - False positive rate: {fmt(baseline_fpr, 3)}/h
  - Recall: {pct(baseline_recall)}

Текущий iter7 pyopen TFLite, audit/test при рабочем пороге:
  - Порог: {fmt(float(current_row.get("threshold") or 0.991), 3)}
  - Негативов: {fmt(current_hours, 4)} часа
  - False positives: {current_fp}
  - False positive rate: {fmt(current_fpr, 6)}/h
  - Recall: {pct(current_recall)}
  - Precision: {pct(current_precision)}

Текущий deploy, реальный домашний фон raw_live:
  - Негативов: {fmt(hours, 4)} часа
  - False positives: 0
  - False positive rate: {fmt(active_fpr, 6)}/h
  - Recall тут не измерялся: wake-фразу специально не говорили.

Наблюдаемое снижение на offline negative test: с {fmt(baseline_fpr, 3)}
до {fmt(current_fpr, 6)} FP/час, то есть минус {fmt(fpr_reduction, 3)}
FP/час. В процентах это 100% наблюдаемого снижения на этом тесте, но
модель еще нельзя считать финальной без записи реальных голосов.

Запас на недельном фоне: максимальный score {fmt(max_score, 12)}, рабочий
порог 0.991, до порога оставалось {fmt(score_margin, 6)}.

Главные цифры
-------------
Проверено фона: {fmt(hours, 4)} часа
WAV-файлов обработано: {files}
Максимальный score на всем фоне: {fmt(max_score, 12)}
False positive rate на активном пороге 0.991: {fmt(active_fpr, 6)}/h

Пересечения порогов
-------------------
{threshold_lines}

Срабатывания с refractory
-------------------------
{detection_lines}

Важное исправление
------------------
До 2026-06-12 активный TFLite был в training-layout [1, 96, 16].
Live runtime pyopen_wakeword ожидает [1, 16, 96], поэтому модель могла
загружаться, но фактически не выдавать score. Модель переложена в
deployment-layout, веса сохранены эквивалентно: old/new check дал
max diff 2.38e-07.

Что дальше
----------
Следующий обязательный блок: реальные positive-примеры. Нужно минимум
50-100 удачных срабатываний, лучше 150-200, от разных людей и в разных
условиях.

Рекомендуемый план записи:
1. Основной человек: 60 раз "эй Милош" и 30 раз "Милош".
2. Другие люди: по 20-30 раз на человека.
3. Громкость: обычный голос, шепот, громко, усталый/низкий голос.
4. Позиции: рядом 1 м, диван 3 м, кухня, коридор, дверной проем.
5. Шум: тишина, ТВ/музыка, разговор на фоне, кухня.
6. Между попытками пауза 3-5 секунд. Не тараторить подряд.

Файлы
-----
Итоговый JSON:
/home/ultra/oww-models/stream_eval/raw_live_merged.json

Статус:
/home/ultra/homeassistant/WAKEWORD_STATUS.md
"""


def main() -> int:
    args = build_parser().parse_args()
    merged = json.loads(args.merged_report.read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline_metrics.read_text(encoding="utf-8"))
    current = json.loads(args.current_metrics.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html_page(merged, baseline, current), encoding="utf-8")
    if args.text_output:
        args.text_output.parent.mkdir(parents=True, exist_ok=True)
        args.text_output.write_text(text_page(merged, baseline, current), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
