# Comprehensive Plan: Custom openWakeWord Model for "jarvis"
## Environment-Optimized Wake Word Detection for Russian Household

**Date:** 2026-05-21  
**Hardware:** RTX 3060 (12GB VRAM), ReSpeaker 4-Mic Array (6-ch firmware), 14GB RAM, 468GB NVMe  
**Current Stack:** Wyoming Satellite (porcupine1) → Wyoming Faster-Whisper → Home Assistant  
**Target Wake Word:** `jarvis` / `hey_jarvis` (English)  
**Critical Issue:** False triggers in absolute silence and during TV playback

---

## Executive Summary

Your false triggers in **silence** are the smoking gun. The porcupine1/openWakeWord pre-trained models were trained on synthetic noise, music, and speech datasets — but **not** on the specific electrical/ADC noise signature of your ReSpeaker 4-Mic Array's channel-0 pipeline (beamformed + AEC + NS). When the room is silent, the array's noise suppression and AEC algorithms can inject artifacts, periodic ticks, or high-frequency residue that spectrally resembles parts of "jarvis" to the model.

The fix is not tuning sensitivity. It is **training a custom openWakeWord model with true negative data recorded from your actual microphone in your actual room**.

This plan describes a 14-day execution path: data collection (Days 1–7), training (Days 8–11), validation (Days 12–13), and deployment (Day 14).

---

## Part 1: Root Cause Analysis — Why Silence Triggers

### The ReSpeaker Pipeline Problem

Your satellite runs this capture script:

```sh
arecord -D plughw:2,0 -r 16000 -c 6 -f S16_LE -t raw | python3 -c "
import sys
while True:
    chunk = sys.stdin.buffer.read(12)
    if not chunk: break
    sys.stdout.buffer.write(chunk[:2])  # ONLY channel 0
"
```

Channel 0 is the **processed** output (beamformed + AEC + NS). When the room is silent:

1. **AEC artifacts:** The acoustic echo canceller can produce residual noise or musical noise when there is no reference signal and no near-end speech.
2. **Beamformer self-noise:** Adaptive beamformers can amplify spatially uncorrelated noise (electrical hum) when there is no dominant source.
3. **NS distortion:** Aggressive noise suppression (`--mic-noise-suppression 3`) can create "musical noise" — random spectral peaks that may overlap with "jarvis" phonemes (affricates /dʒ/ and /v/ have strong high-mid frequency energy).
4. **USB bus noise:** The ReSpeaker draws power over USB; bus voltage fluctuations can modulate the ADC noise floor.
5. **Model training gap:** openWakeWord's pre-trained models used ~30,000 hours of negative data (AudioSet, FMA, ACAV100M, etc.) but **none of it was recorded by a ReSpeaker in a Russian apartment at night.**

**Conclusion:** You need to record true silence, true TV noise, and true Russian speech from your actual microphone and use it as negative training data (either as raw audio or pre-computed openWakeWord features).

---

## Part 2: Data Collection Architecture

### 2.1 Audio Source Decision: Tap the Exact Same Stream

You have three options for continuous recording:

| Approach | Pros | Cons |
|---|---|---|
| **A. Tap wyoming-satellite container** | Same audio the wake word engine sees; zero additional mic contention; already Dockerized | Requires running a sidecar process in the container or reading from the same mic device |
| **B. Record directly from host via arecord** | Full control; can record all 6 channels for analysis | Competes with the container for the ALSA device; `plughw:2,0` may be busy |
| **C. Use `--debug-recording-dir` more aggressively** | Already enabled; no code needed | Only records around wake events; misses long silence/TV periods; files are 2s clips |

**Recommendation: Hybrid A + C.**
- Run a **continuous negative-data recorder** as a parallel service in the `wyoming-satellite` Docker Compose stack. It reads from the same ALSA device but captures channel 0 only, segments into 10-minute clips, and saves to a dedicated dataset directory.
- Keep `--debug-recording-dir` for positive candidate mining (when a false trigger fires, you automatically get the `-wake.wav` and `-stt.wav` files).

### 2.2 Continuous Recorder Design

Create a new service `audio-collector` in `ha.docker-compose.yaml`:

```yaml
  audio-collector:
    image: lunyaadev/rhasspy-wyoming-satellite:latest
    devices:
      - /dev/snd:/dev/snd
    group_add:
      - audio
    volumes:
      - /home/ultra/oww-dataset:/dataset
      - /home/ultra/audio-collector/scripts:/scripts
    command: ["/scripts/collect_negatives.sh"]
    restart: unless-stopped
    networks:
      - ha-net
```

Script `/home/ultra/audio-collector/scripts/collect_negatives.sh`:

```sh
#!/bin/sh
# Record channel 0 continuously in 10-minute chunks
# Directory structure: /dataset/raw/YYYY-MM-DD/HH/MMSS.wav

DEVICE="plughw:2,0"
RATE=16000
CH=6
CH_BYTES=2
CH0_BYTES=2
SEG_SEC=600
SEG_SAMPLES=$((RATE * SEG_SEC))
BYTES_PER_FRAME=$((CH * CH_BYTES))

mkdir -p /dataset/raw

while true; do
    DATE_DIR="/dataset/raw/$(date +%Y-%m-%d)"
    mkdir -p "$DATE_DIR"
    FILENAME="$DATE_DIR/$(date +%H%M%S).wav"

    arecord -D "$DEVICE" -r "$RATE" -c "$CH" -f S16_LE -t raw 2>/dev/null \
    | python3 -c "
import sys, struct
RATE=${RATE}
SEG_SAMPLES=${SEG_SAMPLES}
CH=${CH}
header = struct.pack('<4sI4s4sIHHIIHH4sI',
    b'RIFF', 36 + SEG_SAMPLES*2, b'WAVE', b'fmt ',
    16, 1, 1, RATE, RATE*2, 2, 16, b'data', SEG_SAMPLES*2)
sys.stdout.buffer.write(header)
written = 0
while written < SEG_SAMPLES:
    frame = sys.stdin.buffer.read(CH*2)
    if len(frame) < CH*2: break
    sys.stdout.buffer.write(frame[:2])
    written += 1
" > "$FILENAME"

    sleep 1
done
```

**Key details:**
- 10-minute WAV files = ~115MB each at 16kHz mono 16-bit.
- 24 hours = ~144 files = ~16.5GB/day.
- Target: 7 days = ~115GB raw.
- We will later compress/reformat the useful clips; most will be discarded after feature extraction.

### 2.3 Automated Labeling Pipeline

After collecting raw 10-minute segments, run an **offline labeling script** every hour to classify and slice them:

**Labels needed:**
1. `silence` — near-zero energy, no VAD, no TV
2. `tv_noise` — no VAD speech, but elevated energy and spectral characteristics of TV
3. `russian_speech` — Silero VAD detects speech, but STT (Whisper) transcribes Russian
4. `kitchen_noise` — transient non-speech (fridge, kettle, clinking)
5. `hvac_fan` — stationary noise, low-frequency dominant
6. `false_trigger_candidate` — segments where porcupine1 fired (cross-reference debug recordings)

**Labeling tool:** Python script using `silero-vad`, `webrtcvad`, and simple heuristics:

```python
# /home/ultra/oww-dataset/scripts/label_segments.py (conceptual)
import torch, torchaudio, numpy as np, os, json
from pathlib import Path
from silero_vad import get_speech_timestamps, read_audio

SILERO_MODEL, utils = torch.hub.load(
    repo_or_dir='snakers4/silero-vad',
    model='silero_vad',
    force_reload=False,
    onnx=False)

def label_file(wav_path: Path):
    wav = read_audio(str(wav_path), sampling_rate=16000)
    timestamps = get_speech_timestamps(wav, SILERO_MODEL, sampling_rate=16000,
                                       threshold=0.5, min_silence_duration_ms=500)

    # RMS energy per 1s frame
    frames = wav.unfold(0, 16000, 16000)  # 1-second windows
    rms = frames.pow(2).mean(dim=1).sqrt().numpy()

    labels = []
    for i, energy in enumerate(rms):
        t0, t1 = i, i+1
        has_speech = any(s['start'] < t1*16000 and s['end'] > t0*16000 for s in timestamps)

        if has_speech:
            labels.append(('speech', t0, t1))
        elif energy < 0.005:
            labels.append(('silence', t0, t1))
        elif energy < 0.02:
            labels.append(('low_noise', t0, t1))
        else:
            labels.append(('high_noise', t0, t1))

    # Merge contiguous labels
    merged = []
    for lab, t0, t1 in labels:
        if merged and merged[-1][0] == lab:
            merged[-1] = (lab, merged[-1][1], t1)
        else:
            merged.append((lab, t0, t1))
    return merged
```

**Post-processing:**
- Slice 10-minute files into labeled 30–60 second clips.
- Save to `/dataset/negatives/<class>/`.
- Convert to 16-bit 16kHz mono (already is).
- Compute openWakeWord features on-the-fly and append to `.npy` files to save disk space.

### 2.4 Feature Pre-computation (Critical for Scale)

openWakeWord training does **not** use raw WAVs for negatives. It uses pre-computed embeddings from the shared feature extractor (Google speech_embedding model). This is why the official notebook downloads `openwakeword_features_ACAV100M_2000_hrs_16bit.npy` (~30GB).

You should create your own `.npy` feature file from your environment recordings:

```python
# Conceptual: convert negative WAVs to openWakeWord features
import numpy as np
from openwakeword.utils import compute_features_from_clip

features = []
for wav in Path('/dataset/negatives/silence').glob('*.wav'):
    feats = compute_features_from_clip(str(wav))  # returns (T, F) array
    features.append(feats)

# Concatenate and save
np.save('custom_negatives_silence_500h.npy', np.concatenate(features, axis=0))
```

**Storage math:**
- Raw audio: 500h silence + 500h Russian + 2000h noise/TV = 3000h = ~345GB raw WAV.
- Pre-computed features: ~1.5MB per hour of audio → 3000h = ~4.5GB. **This is the key insight.** You only need to keep the raw audio temporarily; after feature extraction, the `.npy` file is tiny.

---

## Part 3: Positive Data — Synthetic Generation

openWakeWord uses **100% synthetic speech** for positive samples. You do not need to record yourself saying "jarvis" 50,000 times.

### 3.1 Local Piper Sample Generator (RTX 3060)

Clone and set up on the host (not in a container, so the GPU is accessible):

```bash
cd /home/ultra
git clone https://github.com/rhasspy/piper-sample-generator
wget -O piper-sample-generator/models/en_US-libritts_r-medium.pt \
  https://github.com/rhasspy/piper-sample-generator/releases/download/v2.0.0/en_US-libritts_r-medium.pt

# Install in a dedicated venv for training
python3 -m venv oww-train
source oww-train/bin/activate
pip install piper-phonemize webrtcvad
pip install mutagen torchinfo torchmetrics speechbrain audiomentations torch-audiomentations acoustics
pip install tensorflow-cpu==2.8.1 tensorflow_probability==0.16.0 onnx_tf==1.10.0 pronouncing datasets deep-phonemizer

# Install openWakeWord (full, editable)
git clone https://github.com/dscripka/openWakeWord
cd openWakeWord
pip install -e .

# Download backbone models
mkdir -p openwakeword/resources/models
wget https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/embedding_model.onnx \
  -O openwakeword/resources/models/embedding_model.onnx
wget https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/melspectrogram.onnx \
  -O openwakeword/resources/models/melspectrogram.onnx
```

### 3.2 Positive Sample Count

| Metric | Recommended | Minimum |
|---|---|---|
| Positive synthetic clips | 50,000–100,000 | 20,000 |
| Adversarial negative clips (phonetically similar) | 5,000–10,000 | 2,000 |
| Validation positive clips | 2,000–5,000 | 1,000 |
| Validation adversarial clips | 1,000–2,000 | 500 |

Generate with Piper using variations:
- "jarvis"
- "hey jarvis"
- "okay jarvis" (as negative/adversarial)
- "service" (adversarial: contains /v/ and /s/ but not /dʒ/)

### 3.3 Adversarial Negative Strategy

openWakeWord's `train.py` automatically generates adversarial negatives based on **phoneme overlap** with the target phrase. For "jarvis" (/dʒ/ /ɑːr/ /v/ /ɪ/ /s/), phonetically similar words include:
- "service" (/s/ /ɜːr/ /v/ /ɪ/ /s/)
- "harvest" (/h/ /ɑːr/ /v/ /ɪ/ /s/ /t/)
- "chassis" (/ʃ/ /æ/ /s/ /iː/)
- "garbage" (/ɡ/ /ɑːr/ /b/ /ɪ/ /dʒ/)

The training script will automatically sample these from the Piper generator if configured.

---

## Part 4: Training Pipeline on RTX 3060

### 4.1 Why Local Training Beats Colab

- RTX 3060 12GB is faster than a Colab T4 for this workload because the bottleneck is I/O (reading `.npy` features), not raw FLOPS.
- You can keep the large 2000-hour `.npy` file on local NVMe (~30GB), whereas Colab disk is ephemeral and small.
- Piper generation on RTX 3060 is ~10–20 clips/sec, so 50k positives = ~1 hour.

### 4.2 Feasible Batch Size on RTX 3060

The automated training in `train.py` uses **gradient accumulation**. The `batch_n_per_class` defines the logical batch size (sum = ~1174 in the default config), but the GPU batch size is much smaller and accumulated.

With 12GB VRAM:
- **GPU batch size:** 64–128 (features are small: ~ (batch, 32, 96) tensors)
- **Gradient accumulation steps:** ~10–20 to reach the logical batch size of 1024–4096
- **Training time:** ~2–4 hours for 50k steps on RTX 3060 (the model is tiny: 32-unit DNN)

### 4.3 Training Configuration (`custom_jarvis.yml`)

```yaml
model_name: "jarvis_home_v1"
target_phrase:
  - "jarvis"
  - "hey jarvis"
custom_negative_phrases:
  - "service"
  - "harvest"
  - "garbage"

n_samples: 50000
n_samples_val: 5000
tts_batch_size: 50
augmentation_batch_size: 16
piper_sample_generator_path: "./piper-sample-generator"
output_dir: "./jarvis_home_v1"

rir_paths:
  - "./mit_rirs"
background_paths:
  - "./audioset_16k"
  - "./fma"
  - "./dataset/negatives/tv_noise"      # your collected TV noise
  - "./dataset/negatives/kitchen_noise" # your collected kitchen noise
background_paths_duplication_rate:
  - 1
  - 1
  - 5   # oversample your TV noise 5x
  - 2   # oversample kitchen 2x

false_positive_validation_data_path: "./validation_set_features.npy"

augmentation_rounds: 2

# YOUR custom negatives as pre-computed features
feature_data_files:
  "ACAV100M": "./openwakeword_features_ACAV100M_2000_hrs_16bit.npy"
  "home_silence": "./custom_negatives_silence_500h.npy"
  "home_russian": "./custom_negatives_russian_500h.npy"
  "home_tv": "./custom_negatives_tv_1000h.npy"

batch_n_per_class:
  "ACAV100M": 512
  "home_silence": 256
  "home_russian": 256
  "home_tv": 256
  "adversarial_negative": 50
  "positive": 50

model_type: "dnn"
layer_size: 32

steps: 50000
max_negative_weight: 1500
target_false_positives_per_hour: 0.1   # stricter than default 0.2
```

### 4.4 Training Steps

```bash
cd /home/ultra/openWakeWord
source ../oww-train/bin/activate

# Step 1: Generate synthetic clips (~1 hr on RTX 3060)
python openwakeword/train.py --training_config custom_jarvis.yml --generate_clips

# Step 2: Augment clips with RIRs and background noise (~30 min)
python openwakeword/train.py --training_config custom_jarvis.yml --augment_clips

# Step 3: Train model (~2–4 hrs on RTX 3060)
python openwakeword/train.py --training_config custom_jarvis.yml --train_model

# Output: jarvis_home_v1/jarvis_home_v1.tflite
```

### 4.5 Advanced Training Techniques

#### Focal Loss for Imbalanced Data
The default openWakeWord `train.py` uses binary cross-entropy. For your severe imbalance (50k positives vs. 3000h negatives), you can patch `train.py` to use focal loss:

```python
# In train.py, replace BCE with:
import torch.nn.functional as F

def focal_loss(inputs, targets, alpha=0.25, gamma=2.0):
    bce = F.binary_cross_entropy_with_logits(inputs, targets, reduction='none')
    pt = torch.exp(-bce)
    loss = alpha * (1-pt)**gamma * bce
    return loss.mean()
```

This down-weights easy negatives (silence, constant TV hum) and focuses training on hard negatives (Russian words containing /dʒ/ or /v/ sounds).

#### Hard Negative Mining
After the first training run, identify clips from your environment that still cause false triggers:
1. Run the trained model on your 10-minute raw recordings.
2. Any frame where model score > 0.3 but no true wake word occurred = hard negative.
3. Extract ±1.5s around that frame.
4. Add these clips to `feature_data_files` as a new class `hard_negatives` with high batch weight.
5. Retrain for another 10k steps.

#### Temporal Context Tuning
openWakeWord uses a **1.5-second sliding window** (80ms frames, 18 frames of context = 1.44s). This is hardcoded in the melspectrogram/embedding model and **cannot** be easily changed without retraining the backbone (which is frozen and pre-trained by Google). However, you can influence temporal sensitivity via:
- **Post-processing:** Require 2+ consecutive frames above threshold before declaring detection. This adds ~80ms latency but dramatically reduces random false peaks.
- **Threshold scheduling:** Use adaptive thresholding based on recent ambient noise level.

#### Quantization
Do **not** quantize to INT8 for the RTX 3060 deployment. The model is already tiny (~50KB), and FP32/FP16 inference is negligible on a desktop GPU. Quantization can slightly degrade discrimination of subtle noise artifacts. Keep the `.tflite` in FP32 (default).

---

## Part 5: Validation Protocol

### 5.1 Metrics

| Metric | Target | Measurement |
|---|---|---|
| False Accept Rate (FAR) | < 0.1 / hour | Run model on 24h of continuous home audio |
| False Reject Rate (FRR) | < 5% | 100 intentional wake word utterances at 3m distance |
| Recall @ threshold 0.5 | > 95% | Same 100 utterances, mixed with TV at 60dB |
| Precision @ threshold 0.5 | > 99% | Ratio of true detects to total detects over 24h |

### 5.2 Validation Datasets

1. **Synthetic positive test set:** 1000 augmented "jarvis" clips (not seen in training).
2. **Home positive test set:** Record yourself saying "jarvis" 100 times from various positions in the room.
3. **Home negative test set:** 24 hours of pre-collected home audio (silence + TV + Russian speech).
4. **Dinner Party Corpus:** 5.5 hours of challenging multi-speaker party noise (standard benchmark).

### 5.3 Evaluation Script

```python
import numpy as np
from openwakeword.model import Model
from pathlib import Path

model = Model(wakeword_models=["jarvis_home_v1.tflite"])

# Evaluate FAR on 24h home negatives
scores = []
for wav in Path('/dataset/val/24h_home').glob('*.wav'):
    scores.extend(model.predict_clip(str(wav))["jarvis_home_v1"])

# Count peaks above threshold
threshold = 0.5
peaks = np.array(scores) > threshold
# Apply 2-frame hold (reduce single-frame noise)
activations = np.convolve(peaks, [1,1], mode='same') == 2
far_per_hour = activations.sum() / 24.0
print(f"FAR: {far_per_hour:.2f} per hour")
```

---

## Part 6: Deployment into Wyoming Stack

### 6.1 Replace porcupine1 with wyoming-openwakeword

```yaml
  wyoming-openwakeword:
    image: rhasspy/wyoming-openwakeword
    volumes:
      - /home/ultra/oww-models:/custom-models
    command:
      - --uri
      - tcp://0.0.0.0:10400
      - --custom-model-dir
      - /custom-models
      - --preload-model
      - jarvis_home_v1
      - --threshold
      - "0.5"
      - --debug
    ports:
      - "10400:10400"
    restart: unless-stopped
    networks:
      - ha-net
```

Update `wyoming-satellite` service:
```yaml
      - --wake-uri
      - tcp://wyoming-openwakeword:10400
      - --wake-word-name
      - jarvis_home_v1
```

Remove `wyoming-porcupine1` service entirely.

### 6.2 Running Multiple Models (Ensemble)

You can run the **pre-trained** `hey_jarvis` model AND your custom `jarvis_home_v1` simultaneously:

```yaml
    command:
      - --custom-model-dir
      - /custom-models
      - --preload-model
      - hey_jarvis
      - --preload-model
      - jarvis_home_v1
```

Then ensemble in the satellite or in HA:
- **AND logic:** Only trigger if both models score > 0.5. This is extremely conservative; FRR will increase but FAR will drop to near zero.
- **OR with custom priority:** If custom model scores > 0.6, trigger immediately. If only pre-trained scores > 0.5, require a second confirm.
- **Weighted average:** `score = 0.7*custom + 0.3*pretrained`. Threshold at 0.5.

However, `wyoming-openwakeword` returns detections per-model to the satellite. The satellite only listens for one `--wake-word-name`. To ensemble properly, you need a thin proxy or modify the satellite's wake-word-name matching.

**Simpler approach:** Train your custom model, validate that it outperforms the pre-trained one in your environment, and use it standalone.

### 6.3 Custom Verifier Model (Second-Stage Filter)

If the custom base model still has occasional false triggers, train a **speaker-specific verifier** (logistic regression on embeddings) using your own voice:

```python
import openwakeword
openwakeword.train_custom_verifier(
    positive_reference_clips=["my_jarvis_1.wav", "my_jarvis_2.wav", "my_jarvis_3.wav"],
    negative_reference_clips=["my_other_speech_1.wav", "silence_false_trigger.wav"],
    output_path="/home/ultra/oww-models/jarvis_verifier.pkl",
    model_name="jarvis_home_v1.tflite"
)
```

Then load it:
```python
model = Model(
    wakeword_models=["jarvis_home_v1.tflite"],
    custom_verifier_models={"jarvis_home_v1": "jarvis_verifier.pkl"},
    custom_verifier_threshold=0.3
)
```

**Caveat:** The verifier will make the system less responsive to other family members' voices. Only use if the primary user is the main speaker.

---

## Part 7: Day-by-Day Execution Plan

### Day 1 — Infrastructure & Baseline
- [ ] Fix nvidia-smi driver mismatch (reboot or reinstall NVIDIA drivers).
- [ ] Create `/home/ultra/oww-dataset/` tree: `raw/`, `negatives/{silence,tv_noise,russian_speech,kitchen_noise,hvac}/`, `positives/`, `models/`.
- [ ] Add `audio-collector` service to `ha.docker-compose.yaml`.
- [ ] Start continuous recording. Validate 10-minute WAV files are created.
- [ ] Baseline measurement: Count false triggers in the next 24 hours using existing porcupine1.

### Day 2 — Labeling Pipeline
- [ ] Install `silero-vad` in the `oww-train` venv.
- [ ] Write `label_segments.py` to classify Day 1 recordings.
- [ ] Manually verify 10 random clips per class to ensure auto-labeling accuracy.
- [ ] Begin slicing and sorting into class directories.

### Days 3–7 — Data Collection Marathon
- [ ] Let continuous recorder run 24/7.
- [ ] Nightly cron: run `label_segments.py` on the previous day's raw files.
- [ ] Move verified clips to class folders.
- [ ] **Critical:** Ensure at least:
  - 100 hours of silence (empty apartment / night time)
  - 100 hours of TV-on-no-speech
  - 100 hours of Russian conversations
  - 50 hours of kitchen noises
  - 50 hours of HVAC/fan
- [ ] Compute openWakeWord features nightly and append to `.npy` files.
- [ ] Prune raw WAVs after feature extraction to save disk (keep only 1 day of raw backup).

### Day 8 — Positive Data Generation
- [ ] Clone `piper-sample-generator` and `openWakeWord`.
- [ ] Download Piper model checkpoint.
- [ ] Generate 50,000 positive clips for "jarvis" and "hey jarvis".
- [ ] Generate 10,000 adversarial clips.
- [ ] Generate 5,000 validation clips.

### Day 9 — Augmentation
- [ ] Download MIT RIRs and background datasets (AudioSet, FMA) if not cached.
- [ ] Run augmentation: mix positives with RIRs and background noise.
- [ ] Run augmentation on adversarial negatives.

### Day 10 — Training Run 1
- [ ] Assemble final `custom_jarvis.yml` with your custom negatives.
- [ ] Launch `train.py --train_model`.
- [ ] Monitor validation metrics. Target: FAR < 0.2/hr on validation set.
- [ ] If training diverges, reduce `max_negative_weight` or increase `home_*` batch sizes.

### Day 11 — Hard Negative Mining & Retrain
- [ ] Run trained model on 24h of collected home audio.
- [ ] Extract top 500 false trigger frames as hard negatives.
- [ ] Add to config as `hard_negatives` class.
- [ ] Retrain for 10k–20k more steps.
- [ ] Export final `.tflite`.

### Day 12 — Validation
- [ ] Run FAR test on 24h home negatives.
- [ ] Run FRR test with 100 live utterances.
- [ ] Run TV-noise stress test (TV at volume 40, speak "jarvis" from 3m).
- [ ] If metrics fail targets, iterate: collect more of the failing class, retrain.

### Day 13 — A/B Deployment Test
- [ ] Deploy `wyoming-openwakeword` alongside `porcupine1` on separate ports.
- [ ] Configure a second satellite instance (or use HA automation) to route 50% of traffic to the new model.
- [ ] Compare false trigger counts over 24 hours.

### Day 14 — Full Cutover
- [ ] Replace `wyoming-porcupine1` with `wyoming-openwakeword` in `ha.docker-compose.yaml`.
- [ ] Update satellite `--wake-uri` and `--wake-word-name`.
- [ ] Document final model file location and backup `.tflite` to `backups/`.
- [ ] Write HA automation: if false triggers exceed 5/day, alert to retrain.

---

## Part 8: Hardware & Storage Requirements

| Resource | Required | Available | Status |
|---|---|---|---|
| Disk (raw audio, 7 days) | ~120GB | 284GB | OK |
| Disk (features + models) | ~40GB | 284GB | OK |
| Disk (Piper + openWakeWord repos) | ~5GB | 284GB | OK |
| RAM (training) | 8GB | 14GB | OK |
| GPU VRAM | 4GB+ | 12GB | OK (after driver fix) |
| GPU Compute | CUDA 11.8+ | RTX 3060 | Needs driver check |
| Microphone access | `plughw:2,0` exclusive | arecord works | OK |

**Note on nvidia-smi:** The current environment shows `Failed to initialize NVML: Driver/library version mismatch`. This must be resolved before training. Run:

```bash
sudo apt update && sudo apt install --reinstall nvidia-driver-535
# or reboot if a kernel update happened recently
```

---

## Part 9: Exact Commands Reference

### Start Continuous Recording
```bash
docker compose -f /home/ultra/homeassistant/ha.docker-compose.yaml up -d audio-collector
```

### Label Yesterday's Data
```bash
source /home/ultra/oww-train/bin/activate
python3 /home/ultra/oww-dataset/scripts/label_segments.py \
  /home/ultra/oww-dataset/raw/$(date -d yesterday +%Y-%m-%d) \
  /home/ultra/oww-dataset/negatives
```

### Compute Features for a Class
```bash
python3 -c "
import numpy as np, sys
from openwakeword.utils import compute_features_from_clip
from pathlib import Path

out = 'custom_negatives_silence.npy'
feats = [compute_features_from_clip(str(p)) for p in Path(sys.argv[1]).glob('*.wav')]
np.save(out, np.concatenate(feats, axis=0)) if feats else print('no files')
" /home/ultra/oww-dataset/negatives/silence
```

### Generate Positive Clips
```bash
cd /home/ultra/openWakeWord
source ../oww-train/bin/activate
python openwakeword/train.py --training_config custom_jarvis.yml --generate_clips
```

### Full Training (One Shot)
```bash
python openwakeword/train.py --training_config custom_jarvis.yml \
  --generate_clips --augment_clips --train_model
```

### Deploy Model
```bash
cp /home/ultra/openWakeWord/jarvis_home_v1/jarvis_home_v1.tflite \
   /home/ultra/oww-models/
# Then update ha.docker-compose.yaml and recreate wyoming-openwakeword
```

---

## Part 10: Risk Mitigation & Fallbacks

| Risk | Mitigation |
|---|---|
| RTX 3060 driver remains broken | Fall back to CPU training (slower: ~12 hrs instead of 3 hrs, but functional). |
| Not enough silence recorded (apartment never empty) | Record overnight while sleeping; use noise gate in post-processing to synthesize "quieter" silence from low-noise periods. |
| Custom model still triggers on TV | Increase `background_paths_duplication_rate` for TV noise to 10x; add specific TV show audio as a new class. |
| Russian speech contains "jarvis-like" sounds | Hard-negative mining will catch these; also add Russian words with /dʒ/ or /v/ as adversarial negatives. |
| Family members can't trigger verifier model | Don't deploy the verifier; use only the base custom model. |
| Training crashes OOM | Reduce `batch_n_per_class` values to 256 total; reduce `augmentation_batch_size` to 8. |
| Disk fills up | Set up a nightly cron to delete raw WAVs older than 2 days after feature extraction. |

---

## Appendix: Quick Reference — Why Each Negative Class Matters

| Class | Why It Reduces False Triggers |
|---|---|
| **Silence** | Teaches the model what your microphone's *actual* zero-signal noise floor looks like (AEC residue, ADC hum, USB noise). |
| **TV noise** | TV audio contains speech-like spectral patterns (formants, fricatives) that generic music datasets miss. |
| **Russian speech** | Russian phonology has sounds like /ʐ/, /tɕ/, /ɕː/ that can be confusable with English /dʒ/ and /v/. Your model must learn they are not "jarvis". |
| **Kitchen noise** | Transient sounds (clinking, water, microwave beeps) can create short spectral bursts that look like plosives or affricates. |
| **HVAC/fan** | Stationary noise shapes the baseline energy; the model learns to ignore low-frequency rumble and focus on speech-band features. |

---

## Summary

The false triggers in silence are a **data problem, not a model architecture problem.** Your ReSpeaker array produces a unique noise signature that the pre-trained model has never seen. The solution is to collect 500+ hours of **your own environment's audio**, convert it to openWakeWord features, and retrain a custom model with these true negatives heavily oversampled. With an RTX 3060, the entire pipeline — from data collection to a deployed `.tflite` — is achievable in **14 days**.
