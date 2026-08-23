# CRITICAL RESEARCH: Proprietary Wake Word Engines for Home Assistant
## User Profile: RTX 3060, Local Inference, Russian Background, English Wake Word "jarvis"

---

## 1. Microsoft Azure Custom Keyword (Speech Services)

### Training
- **Process:** Done entirely via the [Speech Studio](https://aka.ms/sdsdk-speechportal) web portal (no API/SDK training).
  1. Create a Custom Keyword project.
  2. Create a new model, enter your keyword (e.g., "jarvis" or "hey jarvis").
  3. The portal generates candidate pronunciations; you select the correct ones.
  4. Choose a model type: **Basic** or **Advanced**.
  5. Training begins. Basic = several hours; Advanced = up to a day.
  6. Download the resulting `.table` file (inside a `.zip`).
- **Pronunciation variants:** Yes. The portal auto-generates candidate pronunciations and you select the ones that match expected user speech. This could partially help with Russian-accented English, but it is not explicitly designed for accent adaptation.
- **Languages:** Explicitly limited to **English (United States)** and **Chinese (Mandarin, Simplified)** for custom keyword projects. Russian-accented English would have to fall under `en-US`.
- **Cost of training:** Ambiguous. The Azure Speech pricing page lists **"Custom Speech Training"** as billable per compute hour for newer models. However, the Custom Keyword documentation does not list a separate training fee. The **Free (F0)** tier includes 5 audio hours/month and 1 free hosted endpoint/month, but it is unclear if custom keyword model training incurs a compute charge on the free tier. For personal/hobbyist use, training one keyword is likely either free or extremely low cost, but this is not guaranteed.

### Edge Deployment
- **Local runtime:** Yes. Once you have the `.table` file, the **Azure Speech SDK** runs keyword recognition **100% locally** without internet. The docs explicitly state: *"local keyword recognition ... doesn't require a SpeechConfig object for authentication context, and doesn't contact the back-end."*
- **Runtime:** Azure Speech SDK for Linux (C++, C#, Python, Java, Go).
- **Supported Linux distros:** Ubuntu 20.04/22.04/24.04, Debian 11/12, Amazon Linux 2023, Azure Linux 3.0 on **x64, ARM32, ARM64**.
- **System requirements:** `libasound2`, `libssl`, `ca-certificates`, GNU C library, POSIX threads. Standard desktop/server Linux only.
- **GPU (CUDA):** **No.** There is **no mention of GPU acceleration** for the Speech SDK or keyword recognition. It is a CPU-only library. Your RTX 3060 would not be utilized.

### Accuracy
- **Published rates:** **No explicit FA/FR rates** published for custom keywords.
- **Recommendations:** Microsoft suggests 4-7 syllables, unique made-up words, and avoiding common English words to reduce false accepts. "Jarvis" (2 syllables) is shorter than the ideal recommendation, which may increase false accepts.
- **Two-stage verification:** Azure offers an optional **Keyword Verification** cloud service (post-detection cloud confirmation) to reduce false accepts, but this requires internet and adds latency. This is NOT fully local.
- **Comparison:** No direct benchmark against Porcupine/openWakeWord published by Microsoft. The model is trained by Microsoft on cloud data, not by you.

### Home Assistant Integration
- **Wyoming wrapper:** **None exists.**
- **Bridge options:**
  1. Write a small Python daemon using the Azure Speech SDK (`KeywordRecognizer` + `.table` file) that listens to the local microphone and, upon detection, emits a Wyoming protocol event to the HA Wyoming satellite.
  2. Alternatively, have the daemon trigger an MQTT message or HTTP call to HA when the keyword is detected.
  - The SDK supports continuous recognition patterns. It is a moderate coding task (a few hundred lines of Python).

### Pricing for Personal Use
- **Free (F0) tier:** 5 audio hours/month for STT, 0.5M chars/month for TTS. Custom model hosting is 1 model free/month.
- **Hidden costs:** If training is billed as "Custom Speech Training" compute hours, a single keyword training could cost a few dollars. If you later use the **disconnected container** option for fully offline STT/TTS, that requires a separate commitment tier ($$$).
- **Verdict:** Likely **free or near-free** for a single keyword if you stay on the F0 tier and training is included, but the pricing model is opaque.

---

## 2. Sensory TrulyHandsfree / Smart Wake Word

### Availability for Hobbyists
- **Can an individual get the Linux SDK?** **Effectively no.** Sensory is an **enterprise/OEM B2B licensor**. Their technology ships inside devices from Samsung, Amazon, Google, Microsoft, Jabra, Zoom, etc.
- **VoiceHub:** They offer a self-service portal ([VoiceHub](https://sensory.com/product/voicehub/)) to build custom wake words, but it requires **"Request Access"** via a sales form. It is aimed at "embedded engineers, UX teams, and system integrators" — not hobbyists.
- **Licensing model:** Not publicly disclosed. Historically, Sensory licenses are **per-device or annual**, negotiated with OEMs.
- **Trial/Evaluation:** You can "Request a Demo" or "Request Access to VoiceHub" via their sales team. There is no self-service download of a Linux desktop SDK.
- **How to contact:** `techsupport@sensory.com` or phone +1 (408) 625-3333, or fill out the web form.

### Technical Specs
- **Engine variants:**
  - **Sensory Wake Word:** Pre-built fixed wake words.
  - **Sensory Smart Wake Word:** Context-aware, adaptive thresholds, conversational flow support, multi-layer pipeline.
  - **Sensory Secure Wake Word:** Wake word + speaker verification.
  - **Sensory Personalized Wake Word:** User-trained custom wake words on-device.
- **GPU acceleration:** **No explicit GPU support** mentioned for wake word. Their edge AI targets **MCUs, DSPs, and NPUs** (e.g., LiteRT for Tiny STT). A Linux x86_64 desktop with an RTX 3060 is not their target market.
- **Model sizes:** VoiceHub offers "flexible model sizes" optimized for footprint, but no specific 80KB/250KB/1MB tiers are listed on the public site. They emphasize "ultra-low power" and "minimal memory footprint."
- **Published false accept rates:** Not publicly listed. They reference a [Vocalize.ai Wake Word Report](https://info.sensory.com/wake-word-evaluation) for evaluation data.
- **Custom wake words:** Yes, via VoiceHub or direct OEM engagement.

### Russian Background Robustness
- **Multilingual claims:** Sensory claims "dozens of languages" and "multilingual support" in VoiceHub. They have 30+ years of data.
- **Russian-accented English / non-English negative data:** **No explicit claim found** about cross-lingual robustness or training on non-English negative data specifically for English wake words. Their focus is on native-language wake words in each target locale.

### Home Assistant Integration
- **Known HA integrations:** **None found.** No community project wraps Sensory for HA.
- **Theoretical bridge:** If you obtained a Linux x86_64 library from Sensory, you could wrap it in a Wyoming server or MQTT bridge, similar to the Azure option. However, the library is not publicly available.

### Pricing
- **Public pricing:** **None.**
- **Ballpark:** Given their client list (Fortune 500 / global OEMs), licensing costs are almost certainly in the **$1,000s to $10,000s+** range for commercial products. There is **no evidence of a personal/non-commercial tier**.
- **Verdict:** Not viable for a Home Assistant hobbyist unless you have an enterprise budget.

---

## 3. Other Proprietary / Self-Hosted Options

### Picovoice Porcupine (Semi-Open, but proprietary model)
- **Note:** You likely already know this option, but it is the closest competitor.
- **Self-hosted:** Yes, runs locally on Linux x64/ARM.
- **GPU:** CPU-only.
- **Custom wake words:** Yes, via Picovoice Console. Free for personal use; commercial license required for products.
- **HA integration:** `wyoming-openwakeword` uses openWakeWord (inspired by Picovoice), not Picovoice itself. You would need a custom bridge.
- **Russian robustness:** English models only; no specific Russian-accent tuning advertised.

### Fluent.ai (Fluent Wake Word)
- **Profile:** Canadian company, edge-first wake word and speech recognition.
- **Self-hosted SDK:** Yes, they offer embedded wake word engines.
- **Availability:** B2B / device manufacturers. No clear hobbyist licensing.
- **HA integration:** None known.
- **Pricing:** Enterprise; no public hobbyist tier.

### Cyberon
- **Profile:** Taiwanese voice AI company. Offers wake word and command spotting for embedded devices.
- **Self-hosted:** Yes, but primarily for MCUs/DSPs.
- **Availability:** OEM licensing. No Linux desktop hobbyist SDK evident.

### Houndify / SoundHound
- **Profile:** Full voice AI platform.
- **Self-hosted:** Mostly cloud-centric. They have an edge solution but it is part of a broader platform deal.
- **Pricing:** Enterprise.

### Summary of "Other Options"
For a **self-hosted Linux SDK** (not cloud-only, not mobile-only), the realistic proprietary options are:
1. **Microsoft Azure Custom Keyword** (Speech SDK) — accessible, but limited language support and no GPU.
2. **Picovoice Porcupine** — accessible to hobbyists, free personal tier, but not HA-native.
3. **Sensory** — enterprise-only gatekeeping.
4. **Fluent.ai** — enterprise-only gatekeeping.

---

## Final Verdict & Recommendations

| Criteria | Azure Custom Keyword | Sensory TrulyHandsfree |
|---|---|---|
| **Accessible to hobbyist?** | ✅ Yes (free tier + SDK) | ❌ No (enterprise sales only) |
| **Fully local inference?** | ✅ Yes (`.table` + Speech SDK) | ✅ Yes (if you had the library) |
| **GPU (RTX 3060) support?** | ❌ No (CPU-only) | ❌ No (MCU/DSP target) |
| **Custom "jarvis" / "hey jarvis"?** | ✅ Yes | ✅ Yes (via VoiceHub/OEM) |
| **Russian accent robustness?** | ⚠️ Unclear (en-US only) | ⚠️ Unclear (dozens of languages, no specific claim) |
| **HA / Wyoming integration?** | ⚠️ Must build custom bridge | ❌ No known path |
| **Training cost (personal)** | ~Free (opaque, likely $0-$5) | N/A (inaccessible) |
| **Licensing cost (personal)** | Free tier available | $1,000s+ (estimated) |
| **Model size / efficiency** | Moderate (desktop/server) | Tiny (embedded) |

### Which is the better deal if willing to pay?
- **For a Home Assistant hobbyist:** **Azure Custom Keyword** is the only viable proprietary option. Sensory is not realistically obtainable.
- **Blockers for Azure:**
  1. Custom keyword training is limited to **en-US** (your Russian accent is not explicitly supported).
  2. No GPU acceleration (wastes your RTX 3060 for the wake word itself).
  3. **No existing Wyoming wrapper** — you must write and maintain a bridge daemon.
  4. The word "jarvis" is only **2 syllables**, whereas Microsoft recommends **4-7 syllables** for best accuracy. This may lead to higher false accept rates.

### Better path for your use case?
Given your constraints (RTX 3060, local inference, HA integration), the **highest quality practical option** may actually be **openWakeWord** (already used by HA's `wyoming-openwakeword`) or training a custom **openWakeWord** / **microWakeWord** model on Russian-accented English data, rather than paying for proprietary engines that are either inaccessible (Sensory) or poorly suited (Azure en-US only, no GPU, no HA wrapper).

If you specifically want to **pay for quality**, **Picovoice Porcupine** is the most mature commercial alternative with a free personal tier and a paid enterprise tier, but it also lacks a native HA Wyoming wrapper.

**Bottom line:** Between the two researched proprietary options, only **Azure Custom Keyword** is worth pursuing, and its value over the existing open-source HA stack (`openWakeWord`) is questionable for your specific scenario.
