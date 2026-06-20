const WAKEWORD_PLAN = [
  {
    name: "Owner quiet warmup",
    phrase: "эй Милош",
    speaker: "speaker_1_owner",
    style: "normal",
    location: "near_satellite_1m_quiet",
    attempts: 30,
    cue: "Обычный голос рядом с микрофоном.",
  },
  {
    name: "Owner short phrase",
    phrase: "Милош",
    speaker: "speaker_1_owner",
    style: "normal",
    location: "near_satellite_1m_quiet",
    attempts: 20,
    cue: "Короткая фраза без спешки.",
  },
  {
    name: "Sofa distance",
    phrase: "эй Милош",
    speaker: "speaker_1_owner",
    style: "far",
    location: "sofa_3m_quiet",
    attempts: 20,
    cue: "С дивана или с расстояния около трех метров.",
  },
  {
    name: "Whisper",
    phrase: "эй Милош",
    speaker: "speaker_1_owner",
    style: "whisper",
    location: "near_satellite_1m_quiet",
    attempts: 10,
    cue: "Шепотом, но разборчиво.",
  },
  {
    name: "Loud voice",
    phrase: "эй Милош",
    speaker: "speaker_1_owner",
    style: "loud",
    location: "near_satellite_1m_quiet",
    attempts: 10,
    cue: "Громко, без крика в микрофон.",
  },
  {
    name: "Tired voice",
    phrase: "эй Милош",
    speaker: "speaker_1_owner",
    style: "tired",
    location: "sofa_3m_quiet",
    attempts: 10,
    cue: "Низко, сонно, как вечером.",
  },
  {
    name: "Hallway and doorway",
    phrase: "эй Милош",
    speaker: "speaker_1_owner",
    style: "other_room",
    location: "doorway",
    attempts: 20,
    cue: "Из дверного проема или коридора.",
  },
  {
    name: "TV or music noise",
    phrase: "эй Милош",
    speaker: "speaker_1_owner",
    style: "normal",
    location: "tv_or_music_noise",
    attempts: 20,
    cue: "На фоне ТВ или музыки.",
  },
  {
    name: "Kitchen noise",
    phrase: "эй Милош",
    speaker: "speaker_1_owner",
    style: "normal",
    location: "kitchen_noise",
    attempts: 20,
    cue: "С кухни или рядом с бытовым шумом.",
  },
  {
    name: "Second speaker",
    phrase: "эй Милош",
    speaker: "speaker_2",
    style: "normal",
    location: "near_satellite_1m_quiet",
    attempts: 30,
    cue: "Другой человек, обычный голос.",
  },
  {
    name: "Third or guest speaker",
    phrase: "эй Милош",
    speaker: "speaker_3",
    style: "normal",
    location: "sofa_3m_quiet",
    attempts: 30,
    cue: "Еще один голос, лучше с другого места.",
  },
  {
    name: "Guest noisy mix",
    phrase: "эй Милош",
    speaker: "guest",
    style: "moving",
    location: "conversation_noise",
    attempts: 20,
    cue: "Гость, движение или разговоры на фоне.",
  },
];

const LABELS = {
  phrase: {
    "эй Милош": "эй Милош",
    "Милош": "Милош",
  },
  speaker: {
    speaker_1_owner: "Владелец",
    speaker_2: "Человек 2",
    speaker_3: "Человек 3",
    guest: "Гость",
  },
  style: {
    normal: "Обычный",
    whisper: "Шепот",
    loud: "Громко",
    far: "Далеко",
    other_room: "Другая комната",
    moving: "В движении",
    tired: "Усталый голос",
  },
  location: {
    near_satellite_1m_quiet: "1 м, тихо",
    sofa_3m_quiet: "Диван 3 м",
    kitchen_noise: "Кухня/шум",
    hallway: "Коридор",
    doorway: "Дверной проем",
    tv_or_music_noise: "ТВ/музыка",
    conversation_noise: "Разговоры",
  },
};

const ROOM_POINTS = [
  { id: "near_satellite_1m_quiet", label: "1 м", x: 49, y: 52 },
  { id: "sofa_3m_quiet", label: "Диван", x: 18, y: 68 },
  { id: "kitchen_noise", label: "Кухня", x: 80, y: 26 },
  { id: "hallway", label: "Коридор", x: 83, y: 74 },
  { id: "doorway", label: "Проем", x: 52, y: 16 },
  { id: "tv_or_music_noise", label: "ТВ", x: 19, y: 25 },
  { id: "conversation_noise", label: "Разговор", x: 67, y: 68 },
];

class WakewordCollectionCard extends HTMLElement {
  setConfig(config) {
    this.config = config || {};
    this.reviewManifestUrl = this.config.review_manifest_url || "/local/wakeword/wakeword-sample-candidates.json";
    this.reviewStatusUrl = this.config.review_status_url || "/local/wakeword/review-status.json";
  }

  set hass(hass) {
    this._hass = hass;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.render();
    }
    this.update();
  }

  getCardSize() {
    return 12;
  }

  connectedCallback() {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.render();
    }
    clearInterval(this.liveTimer);
    this.liveTimer = setInterval(() => this.update(), 1000);
    this.loadReviewManifest();
  }

  disconnectedCallback() {
    clearInterval(this.liveTimer);
    clearTimeout(this.metricPulseTimer);
    this.pauseReviewPlaylist();
  }

  directionEntityId() {
    return this.config?.direction_entity || "sensor.wakeword_mic_direction";
  }

  levelEntityId() {
    return this.config?.level_entity || "sensor.wakeword_mic_level";
  }

  state(entityId) {
    return this._hass?.states?.[entityId];
  }

  value(entityId, fallback = "") {
    const state = this.state(entityId)?.state;
    return state === undefined || state === "unknown" || state === "unavailable" ? fallback : state;
  }

  attr(entityId, name, fallback = undefined) {
    const value = this.state(entityId)?.attributes?.[name];
    return value === undefined || value === null ? fallback : value;
  }

  async call(domain, service, data = {}) {
    await this._hass.callService(domain, service, data);
  }

  async setSelect(entityId, option) {
    await this.call("input_select", "select_option", { entity_id: entityId, option });
  }

  async setNumber(entityId, value) {
    await this.call("input_number", "set_value", { entity_id: entityId, value: Number(value) });
  }

  async setText(entityId, value) {
    await this.call("input_text", "set_value", { entity_id: entityId, value: String(value || "") });
  }

  async applyStep(step) {
    if (!step) return;
    await this.setSelect("input_select.wakeword_collection_phrase", step.phrase);
    await this.setSelect("input_select.wakeword_collection_speaker", step.speaker);
    await this.setSelect("input_select.wakeword_collection_style", step.style);
    await this.setSelect("input_select.wakeword_collection_location", step.location);
    await this.setNumber("input_number.wakeword_collection_expected_attempts", step.attempts);
    this.playSound("click");
  }

  async selectPlanStep(index) {
    const clamped = Math.max(0, Math.min(WAKEWORD_PLAN.length - 1, index));
    await this.setNumber("input_number.wakeword_collection_plan_step", clamped + 1);
    await this.applyStep(WAKEWORD_PLAN[clamped]);
  }

  async startSession() {
    this.playSound("start");
    await this.call("script", "turn_on", { entity_id: "script.wakeword_collection_start" });
  }

  async finishSession() {
    this.playSound("success");
    await this.call("script", "turn_on", { entity_id: "script.wakeword_collection_finish" });
    this.captureCounterState = null;
    setTimeout(() => this.refreshSession(), 1200);
  }

  async refreshSession() {
    await this.call("homeassistant", "update_entity", { entity_id: "sensor.wakeword_positive_session" });
    await this.loadReviewManifest(true);
  }

  async loadReviewManifest(force = false) {
    if (this.reviewLoading || (!force && this.reviewLoaded)) return;
    this.reviewLoading = true;
    this.reviewError = "";
    this.renderReview();
    try {
      const manifestUrl = this.getReviewManifestUrl();
      const separator = manifestUrl.includes("?") ? "&" : "?";
      const response = await fetch(`${manifestUrl}${separator}t=${Date.now()}`, { cache: "no-store" });
      if (response.status === 404) {
        this.reviewSamples = [];
        this.reviewLoaded = true;
        return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const rawSamples = Array.isArray(data) ? data : (data.samples || data.fragments || data.candidates || data.items || []);
      const statuses = await this.loadReviewStatuses(true);
      this.reviewSamples = rawSamples
        .map((sample, index) => this.normalizeReviewSample(sample, index, statuses))
        .filter((sample) => sample.url)
        .sort((left, right) => (right.sampleTimeEpoch || 0) - (left.sampleTimeEpoch || 0));
      this.reviewLoaded = true;
    } catch (error) {
      this.reviewSamples = [];
      this.reviewLoaded = true;
      this.reviewError = error?.message || String(error);
    } finally {
      this.reviewLoading = false;
      this.renderReview();
    }
  }

  async loadReviewStatuses(force = false) {
    if (this.reviewStatuses && !force) return this.reviewStatuses;
    try {
      const url = this.getReviewStatusUrl();
      const separator = url.includes("?") ? "&" : "?";
      const response = await fetch(`${url}${separator}t=${Date.now()}`, { cache: "no-store" });
      if (response.status === 404) {
        this.reviewStatuses = {};
        return this.reviewStatuses;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      this.reviewStatuses = data.items || data || {};
    } catch (_error) {
      this.reviewStatuses = {};
    }
    return this.reviewStatuses;
  }

  normalizeReviewSample(sample, index, statuses = {}) {
    const rawUrl = sample.url || sample.path || "";
    const label = sample.label || sample.phrase || sample.text || "candidate";
    const detected = sample.detected_by_model;
    const missed = sample.missed_by_model === true || (detected === false && this.isShortPhrase(label));
    const id = this.reviewSampleId(sample, index);
    const status = statuses[id] || statuses[String(sample.path || "")] || statuses[String(sample.url || "")] || {};
    const reviewStatus = status.status || sample.review_status || (sample.confirmed_for_training ? "confirmed" : sample.negative_added ? "negative" : "pending");
    const sampleTimeEpoch = Number(sample.sample_time_epoch ?? sample.captured_at_epoch ?? sample.created_at_epoch ?? sample.source_mtime_epoch ?? 0);
    const sampleTime = sample.sample_time || sample.captured_at || sample.created_at || sample.source_modified_at || "";
    return {
      id,
      url: this.normalizeReviewUrl(rawUrl),
      label: String(label),
      duration: Number(sample.duration ?? sample.duration_s ?? 0),
      score: Number(sample.score ?? sample.model_score ?? NaN),
      detectedByModel: detected === undefined ? undefined : Boolean(detected),
      missedByModel: Boolean(missed),
      trainingMode: Boolean(sample.training_mode || sample.training_session_id),
      trainingSessionId: sample.training_session_id || "",
      reviewStatus,
      confirmedForTraining: Boolean(status.confirmed_for_training || sample.confirmed_for_training || reviewStatus === "confirmed"),
      negativeAdded: Boolean(status.negative_added || sample.negative_added || reviewStatus === "negative"),
      destinationPath: String(status.destination_path || sample.destination_path || ""),
      sampleTimeEpoch: Number.isFinite(sampleTimeEpoch) ? sampleTimeEpoch : 0,
      sampleTime: String(sampleTime || ""),
      whenLabel: this.formatSampleTime(sampleTimeEpoch, sampleTime),
      path: String(sample.path || sample.url || ""),
    };
  }

  getReviewManifestUrl() {
    return this.reviewManifestUrl || this.config?.review_manifest_url || "/local/wakeword/wakeword-sample-candidates.json";
  }

  getReviewStatusUrl() {
    return this.reviewStatusUrl || this.config?.review_status_url || "/local/wakeword/review-status.json";
  }

  reviewSampleId(sample, index) {
    if (sample.id !== undefined && sample.id !== null && sample.id !== "") return String(sample.id);
    const fields = ["path", "url", "source_path", "start_seconds", "end_seconds", "duration"]
      .map((key) => sample[key])
      .filter((value) => value !== undefined && value !== null && value !== "");
    return fields.length ? fields.map((value) => String(value)).join("|") : `sample-${index}`;
  }

  formatSampleTime(epoch, value) {
    let date = null;
    if (Number.isFinite(epoch) && epoch > 0) {
      date = new Date(epoch * 1000);
    } else if (value) {
      const parsed = new Date(value);
      if (!Number.isNaN(parsed.getTime())) date = parsed;
    }
    if (!date) return "время неизвестно";
    return date.toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      year: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }

  normalizeReviewUrl(rawUrl) {
    const url = String(rawUrl || "");
    if (!url) return "";
    if (/^(https?:)?\/\//.test(url) || url.startsWith("/local/")) return url;
    if (url.startsWith("/config/www/")) return `/local/${url.slice("/config/www/".length)}`;
    if (url.startsWith("/home/ultra/homeassistant/www/")) return `/local/${url.slice("/home/ultra/homeassistant/www/".length)}`;
    if (url.startsWith("www/")) return `/local/${url.slice(4)}`;
    return url.startsWith("/") ? url : `/local/${url}`;
  }

  isShortPhrase(label) {
    const normalized = String(label || "").trim().toLowerCase();
    return normalized === "милош" || normalized === "milos" || normalized === "milosh";
  }

  deletedReviewSamples() {
    try {
      return new Set(JSON.parse(localStorage.getItem("wakewordReviewDeleted") || "[]"));
    } catch (_err) {
      return new Set();
    }
  }

  storeDeletedReviewSamples(deleted) {
    localStorage.setItem("wakewordReviewDeleted", JSON.stringify([...deleted]));
  }

  reviewVisibleSamples() {
    return this.reviewSamples || [];
  }

  async toggleReviewPlaylist() {
    if (this.reviewPlaying) {
      this.pauseReviewPlaylist();
      return;
    }
    const samples = this.reviewVisibleSamples();
    if (!samples.length) return;
    const nextIndex = this.reviewIndex >= 0 && this.reviewIndex < samples.length ? this.reviewIndex : 0;
    await this.playReviewSample(nextIndex, true);
  }

  async playReviewSample(index, continuePlaylist = false) {
    const samples = this.reviewVisibleSamples();
    if (!samples[index]) return;
    clearTimeout(this.reviewTimer);
    this.reviewAudio = this.reviewAudio || new Audio();
    this.reviewAudio.onended = () => {
      this.reviewPlaying = false;
      this.renderReview();
      if (continuePlaylist) {
        this.reviewTimer = setTimeout(() => this.playReviewSample(index + 1, true), 500);
      }
    };
    this.reviewAudio.onerror = () => {
      this.reviewPlaying = false;
      this.renderReview();
      if (continuePlaylist) {
        this.reviewTimer = setTimeout(() => this.playReviewSample(index + 1, true), 500);
      }
    };
    this.reviewIndex = index;
    this.reviewPlaying = true;
    this.reviewAudio.src = samples[index].url;
    this.reviewAudio.currentTime = 0;
    this.renderReview();
    try {
      await this.reviewAudio.play();
    } catch (error) {
      this.reviewPlaying = false;
      this.reviewError = error?.message || String(error);
      this.renderReview();
    }
  }

  pauseReviewPlaylist() {
    clearTimeout(this.reviewTimer);
    this.reviewPlaying = false;
    this.reviewAudio?.pause();
    this.renderReview();
  }

  async reviewCandidateAction(action, sampleId) {
    const sample = (this.reviewSamples || []).find((item) => item.id === sampleId);
    if (!sample || sample.busy) return;
    sample.busy = true;
    this.renderReview();
    try {
      const service = action === "confirm" ? "wakeword_review_candidate_confirm" : "wakeword_review_candidate_negative";
      await this.call("shell_command", service, { sample_id: sample.id });
      sample.reviewStatus = action === "confirm" ? "confirmed" : "negative";
      sample.confirmedForTraining = action === "confirm";
      sample.negativeAdded = action === "negative";
      await this.loadReviewStatuses(true);
      this.playSound(action === "confirm" ? "success" : "click");
    } catch (error) {
      this.reviewError = error?.message || String(error);
      this.playSound("warn");
    } finally {
      sample.busy = false;
      this.renderReview();
    }
  }

  confirmReviewSample(sampleId) {
    this.reviewCandidateAction("confirm", sampleId);
  }

  addReviewSampleToNegative(sampleId) {
    this.reviewCandidateAction("negative", sampleId);
  }

  deleteReviewSample(sampleId) {
    this.addReviewSampleToNegative(sampleId);
  }

  updateReviewSampleStatuses(statuses = {}) {
    for (const sample of this.reviewSamples || []) {
      const status = statuses[sample.id];
      if (!status) continue;
      sample.reviewStatus = status.status || sample.reviewStatus;
      sample.confirmedForTraining = Boolean(status.confirmed_for_training || sample.reviewStatus === "confirmed");
      sample.negativeAdded = Boolean(status.negative_added || sample.reviewStatus === "negative");
      sample.destinationPath = String(status.destination_path || sample.destinationPath || "");
    }
    this.renderReview();
  }

  soundEnabled() {
    return localStorage.getItem("wakewordCollectionSound") !== "off";
  }

  setSoundEnabled(enabled) {
    localStorage.setItem("wakewordCollectionSound", enabled ? "on" : "off");
    if (enabled) this.playSound("success");
    this.update();
  }

  async playSound(kind) {
    if (!this.soundEnabled()) return;
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) return;
      this.audioContext = this.audioContext || new AudioContext();
      const ctx = this.audioContext;
      if (ctx.state === "suspended") await ctx.resume();
      const oscillator = ctx.createOscillator();
      const gain = ctx.createGain();
      const now = ctx.currentTime;
      const sequence = {
        click: [520, 680],
        start: [440, 660, 880],
        success: [660, 880, 1040],
        warn: [220, 180],
      }[kind] || [440];
      oscillator.type = "sine";
      oscillator.frequency.setValueAtTime(sequence[0], now);
      sequence.forEach((freq, index) => {
        oscillator.frequency.setValueAtTime(freq, now + index * 0.075);
      });
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(0.09, now + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + Math.max(0.14, sequence.length * 0.08));
      oscillator.connect(gain);
      gain.connect(ctx.destination);
      oscillator.start(now);
      oscillator.stop(now + Math.max(0.16, sequence.length * 0.09));
    } catch (_err) {
      // Browser audio is best-effort only.
    }
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          color: var(--primary-text-color);
          --ww-ink: #20242c;
          --ww-muted: #687385;
          --ww-line: rgba(68, 78, 97, 0.18);
          --ww-panel: var(--card-background-color, #ffffff);
          --ww-soft: rgba(28, 132, 126, 0.10);
          --ww-good: #0f8f64;
          --ww-teal: #147c8c;
          --ww-warn: #b36b00;
          --ww-coral: #c84d42;
        }
        ha-card {
          overflow: hidden;
          border-radius: 8px;
          border: 1px solid var(--ww-line);
          background:
            linear-gradient(120deg, rgba(20, 124, 140, 0.10), rgba(15, 143, 100, 0.08) 42%, rgba(200, 77, 66, 0.06)),
            var(--ww-panel);
        }
        .wrap { padding: 18px; }
        .top {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          gap: 14px;
          align-items: start;
          margin-bottom: 16px;
        }
        .title {
          display: flex;
          align-items: center;
          gap: 10px;
          min-width: 0;
        }
        .title ha-icon { color: var(--ww-teal); }
        h1 {
          margin: 0;
          font-size: 24px;
          line-height: 1.1;
          letter-spacing: 0;
          color: var(--ww-ink);
        }
        .subtitle {
          margin-top: 7px;
          color: var(--ww-muted);
          font-size: 13px;
          line-height: 1.35;
        }
        .status {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          padding: 7px 10px;
          border-radius: 999px;
          background: rgba(255, 255, 255, 0.72);
          border: 1px solid var(--ww-line);
          font-weight: 700;
          font-size: 13px;
          white-space: nowrap;
        }
        .dot {
          width: 9px;
          height: 9px;
          border-radius: 50%;
          background: var(--ww-muted);
        }
        .status.active .dot {
          background: var(--ww-coral);
          box-shadow: 0 0 0 5px rgba(200, 77, 66, 0.16);
        }
        .main {
          display: grid;
          grid-template-columns: minmax(320px, 1.2fr) minmax(300px, 0.8fr);
          gap: 16px;
        }
        .panel {
          background: rgba(255, 255, 255, 0.78);
          border: 1px solid var(--ww-line);
          border-radius: 8px;
          padding: 14px;
          min-width: 0;
        }
        .hero {
          display: grid;
          grid-template-columns: minmax(0, 1fr) 132px;
          gap: 16px;
          align-items: center;
          margin-bottom: 14px;
        }
        .eyebrow {
          color: var(--ww-muted);
          text-transform: uppercase;
          font-size: 11px;
          font-weight: 800;
          letter-spacing: 0.08em;
        }
        .phrase {
          margin-top: 6px;
          font-size: 48px;
          line-height: 1;
          font-weight: 850;
          color: var(--ww-ink);
          overflow-wrap: anywhere;
        }
        .cue {
          margin-top: 9px;
          font-size: 14px;
          color: var(--ww-muted);
          line-height: 1.35;
        }
        .ring {
          position: relative;
          width: 126px;
          height: 126px;
        }
        .ring svg {
          width: 126px;
          height: 126px;
          transform: rotate(-90deg);
        }
        .ring .bg { stroke: rgba(104, 115, 133, 0.18); }
        .ring .fg {
          stroke: var(--ww-good);
          stroke-linecap: round;
          transition: stroke-dashoffset 0.35s ease;
        }
        .ring-label {
          position: absolute;
          inset: 0;
          display: grid;
          place-items: center;
          text-align: center;
          font-weight: 850;
          color: var(--ww-ink);
        }
        .ring-label span {
          display: block;
          color: var(--ww-muted);
          font-size: 11px;
          font-weight: 700;
          margin-top: 2px;
        }
        .progressbar {
          height: 9px;
          border-radius: 999px;
          background: rgba(104, 115, 133, 0.16);
          overflow: hidden;
          margin: 10px 0 8px;
        }
        .progressbar > div {
          height: 100%;
          width: 0%;
          background: linear-gradient(90deg, var(--ww-teal), var(--ww-good));
          transition: width 0.35s ease;
        }
        .metrics {
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 8px;
          margin: 12px 0 14px;
        }
        .metric {
          border: 1px solid var(--ww-line);
          background: rgba(255, 255, 255, 0.68);
          border-radius: 8px;
          padding: 9px;
          min-width: 0;
        }
        .metric strong {
          display: block;
          font-size: 20px;
          color: var(--ww-ink);
          line-height: 1.05;
          overflow-wrap: anywhere;
        }
        .metric span {
          display: block;
          margin-top: 4px;
          color: var(--ww-muted);
          font-size: 11px;
          line-height: 1.2;
        }
        .metric.pulse {
          animation: metricPulse 0.55s ease;
        }
        @keyframes metricPulse {
          0% { box-shadow: 0 0 0 0 rgba(15, 143, 100, 0.0); }
          35% { box-shadow: 0 0 0 7px rgba(15, 143, 100, 0.18); }
          100% { box-shadow: 0 0 0 0 rgba(15, 143, 100, 0.0); }
        }
        .controls {
          display: grid;
          grid-template-columns: repeat(4, minmax(120px, 1fr));
          gap: 10px;
          margin-top: 12px;
        }
        label {
          display: grid;
          gap: 5px;
          color: var(--ww-muted);
          font-size: 12px;
          font-weight: 700;
        }
        select, input {
          appearance: none;
          width: 100%;
          box-sizing: border-box;
          border: 1px solid var(--ww-line);
          background: rgba(255, 255, 255, 0.92);
          border-radius: 7px;
          padding: 9px 10px;
          color: var(--ww-ink);
          font: inherit;
          min-height: 38px;
        }
        .actions {
          display: flex;
          flex-wrap: wrap;
          gap: 9px;
          margin-top: 13px;
        }
        button {
          border: 1px solid var(--ww-line);
          border-radius: 7px;
          min-height: 40px;
          padding: 0 12px;
          background: rgba(255, 255, 255, 0.82);
          color: var(--ww-ink);
          font: inherit;
          font-weight: 800;
          display: inline-flex;
          align-items: center;
          gap: 7px;
          cursor: pointer;
        }
        button.primary {
          background: var(--ww-good);
          color: white;
          border-color: rgba(15, 143, 100, 0.4);
        }
        button.stop {
          background: var(--ww-coral);
          color: white;
          border-color: rgba(200, 77, 66, 0.4);
        }
        button:disabled {
          opacity: 0.45;
          cursor: not-allowed;
        }
        .review-head {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          gap: 12px;
          align-items: center;
        }
        .review-actions {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          justify-content: flex-end;
        }
        .review-list {
          display: grid;
          gap: 8px;
          margin-top: 12px;
          max-height: 440px;
          overflow: auto;
          padding-right: 2px;
        }
        .sample {
          display: grid;
          grid-template-columns: 44px minmax(0, 1fr) auto;
          gap: 10px;
          align-items: center;
          border: 1px solid var(--ww-line);
          background: rgba(255, 255, 255, 0.72);
          border-radius: 8px;
          padding: 9px;
        }
        .sample.missed {
          border-color: rgba(200, 77, 66, 0.55);
          background: rgba(200, 77, 66, 0.10);
        }
        .sample.playing {
          border-color: rgba(20, 124, 140, 0.62);
          box-shadow: inset 3px 0 0 var(--ww-teal);
        }
        .sample.confirmed {
          border-color: rgba(15, 143, 100, 0.60);
          background: rgba(15, 143, 100, 0.10);
        }
        .sample.negative {
          border-color: rgba(104, 115, 133, 0.34);
          background: rgba(104, 115, 133, 0.10);
        }
        .sample-main {
          min-width: 0;
        }
        .sample-title {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          align-items: center;
          color: var(--ww-ink);
          font-weight: 850;
          line-height: 1.25;
        }
        .sample-path {
          color: var(--ww-muted);
          font-size: 11px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          margin-top: 3px;
        }
        .badge {
          display: inline-flex;
          align-items: center;
          min-height: 20px;
          border-radius: 999px;
          border: 1px solid var(--ww-line);
          padding: 0 7px;
          font-size: 11px;
          font-weight: 850;
          background: rgba(255, 255, 255, 0.78);
          color: var(--ww-muted);
        }
        .badge.missed {
          color: var(--ww-coral);
          border-color: rgba(200, 77, 66, 0.38);
          background: rgba(200, 77, 66, 0.11);
        }
        .badge.detected {
          color: var(--ww-good);
          border-color: rgba(15, 143, 100, 0.34);
          background: rgba(15, 143, 100, 0.10);
        }
        .badge.training {
          color: var(--ww-teal);
          border-color: rgba(20, 124, 140, 0.34);
          background: rgba(20, 124, 140, 0.10);
        }
        .badge.confirmed {
          color: var(--ww-good);
          border-color: rgba(15, 143, 100, 0.34);
          background: rgba(15, 143, 100, 0.12);
        }
        .badge.negative {
          color: var(--ww-muted);
          border-color: rgba(104, 115, 133, 0.34);
          background: rgba(104, 115, 133, 0.12);
        }
        .icon-btn {
          width: 40px;
          min-width: 40px;
          padding: 0;
          justify-content: center;
        }
        .icon-btn.confirm { color: var(--ww-good); }
        .icon-btn.negative { color: var(--ww-muted); }
        .sample-buttons {
          display: flex;
          gap: 7px;
        }
        .empty {
          margin-top: 12px;
          border: 1px dashed var(--ww-line);
          border-radius: 8px;
          padding: 16px;
          color: var(--ww-muted);
          background: rgba(255, 255, 255, 0.50);
          line-height: 1.4;
        }
        .plan-list {
          display: grid;
          gap: 7px;
          max-height: 410px;
          overflow: auto;
          padding-right: 2px;
        }
        .step {
          display: grid;
          grid-template-columns: 30px minmax(0, 1fr) auto;
          gap: 9px;
          align-items: center;
          border: 1px solid var(--ww-line);
          background: rgba(255, 255, 255, 0.70);
          border-radius: 8px;
          padding: 9px;
          cursor: pointer;
        }
        .step.active {
          border-color: rgba(20, 124, 140, 0.55);
          background: rgba(20, 124, 140, 0.11);
        }
        .step.done {
          opacity: 0.66;
        }
        .num {
          width: 26px;
          height: 26px;
          border-radius: 50%;
          display: grid;
          place-items: center;
          background: rgba(104, 115, 133, 0.16);
          font-weight: 850;
          font-size: 12px;
        }
        .step.active .num { background: var(--ww-teal); color: white; }
        .step-title {
          color: var(--ww-ink);
          font-weight: 850;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .step-sub {
          color: var(--ww-muted);
          font-size: 12px;
          margin-top: 2px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .attempts {
          color: var(--ww-muted);
          font-size: 12px;
          font-weight: 850;
        }
        .room {
          position: relative;
          height: 236px;
          border-radius: 8px;
          border: 1px solid var(--ww-line);
          background:
            linear-gradient(90deg, transparent 49.5%, rgba(104, 115, 133, 0.18) 50%, transparent 50.5%),
            linear-gradient(0deg, transparent 49.5%, rgba(104, 115, 133, 0.18) 50%, transparent 50.5%),
            rgba(255, 255, 255, 0.62);
          margin-top: 10px;
          overflow: hidden;
        }
        .room::before {
          content: "микрофон";
          position: absolute;
          left: 50%;
          top: 50%;
          transform: translate(-50%, -50%);
          padding: 6px 9px;
          border-radius: 999px;
          background: var(--ww-ink);
          color: white;
          font-size: 11px;
          font-weight: 850;
        }
        .point {
          position: absolute;
          transform: translate(-50%, -50%);
          border: 1px solid var(--ww-line);
          border-radius: 999px;
          background: rgba(255, 255, 255, 0.92);
          padding: 5px 8px;
          font-size: 11px;
          font-weight: 800;
          cursor: pointer;
        }
        .point.active {
          background: var(--ww-good);
          color: white;
          border-color: rgba(15, 143, 100, 0.5);
        }
        .direction {
          margin-top: 10px;
          display: grid;
          grid-template-columns: 58px minmax(0, 1fr);
          gap: 10px;
          align-items: center;
        }
        .compass {
          position: relative;
          width: 52px;
          height: 52px;
          border-radius: 50%;
          border: 1px solid var(--ww-line);
          background: rgba(255, 255, 255, 0.75);
        }
        .needle {
          position: absolute;
          left: 50%;
          top: 50%;
          width: 3px;
          height: 21px;
          background: var(--ww-coral);
          transform-origin: 50% 100%;
          transform: translate(-50%, -100%) rotate(0deg);
          border-radius: 999px;
        }
        .direction-text {
          color: var(--ww-muted);
          font-size: 13px;
          line-height: 1.35;
        }
        .mic {
          margin-top: 12px;
          border-top: 1px solid var(--ww-line);
          padding-top: 12px;
        }
        .meter {
          height: 14px;
          border-radius: 999px;
          background: rgba(104, 115, 133, 0.16);
          overflow: hidden;
          margin: 8px 0 6px;
        }
        .meter > div {
          height: 100%;
          width: 0%;
          background: linear-gradient(90deg, #78a843, var(--ww-good), var(--ww-warn), var(--ww-coral));
          transition: width 0.08s linear;
        }
        .fineprint {
          color: var(--ww-muted);
          font-size: 11px;
          line-height: 1.35;
        }
        @media (max-width: 900px) {
          .top, .main, .hero { grid-template-columns: 1fr; }
          .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .controls { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .ring { margin: 0 auto; }
          .review-head { grid-template-columns: 1fr; }
          .review-actions { justify-content: flex-start; }
        }
        @media (max-width: 520px) {
          .wrap { padding: 12px; }
          .metrics, .controls { grid-template-columns: 1fr; }
          h1 { font-size: 21px; }
          .phrase { font-size: 38px; }
          .sample { grid-template-columns: 40px minmax(0, 1fr); }
          .sample-buttons { grid-column: 1 / -1; justify-content: flex-end; }
        }
      </style>
      <ha-card>
        <div class="wrap">
          <div class="top">
            <div>
              <div class="title">
                <ha-icon icon="mdi:account-voice"></ha-icon>
                <h1>Милош: запись обучающих фраз</h1>
              </div>
              <div class="subtitle" id="subtitle"></div>
            </div>
            <div class="status" id="status"><span class="dot"></span><span id="statusText">idle</span></div>
          </div>

          <div class="main">
            <div class="panel">
              <div class="hero">
                <div>
                  <div class="eyebrow" id="stepLabel"></div>
                  <div class="phrase" id="phrase"></div>
                  <div class="cue" id="cue"></div>
                </div>
                <div class="ring">
                  <svg viewBox="0 0 120 120">
                    <circle class="bg" cx="60" cy="60" r="52" fill="none" stroke-width="11"></circle>
                    <circle class="fg" id="ringFg" cx="60" cy="60" r="52" fill="none" stroke-width="11" stroke-dasharray="326.7256" stroke-dashoffset="326.7256"></circle>
                  </svg>
                  <div class="ring-label"><div><b id="ringText">0%</b><span id="ringSub">0/0</span></div></div>
                </div>
              </div>

              <div class="progressbar"><div id="progressFill"></div></div>
              <div class="metrics">
                <div class="metric"><strong id="metricObserved">0</strong><span>записано в блоке</span></div>
                <div class="metric"><strong id="metricRemaining">0</strong><span>осталось попыток</span></div>
                <div class="metric"><strong id="metricSaved">0</strong><span>сохранено WAV</span></div>
                <div class="metric"><strong>0 / 222ч</strong><span>ложных на фоне</span></div>
              </div>

              <div class="controls">
                <label>Фраза<select id="phraseSelect"></select></label>
                <label>Говорящий<select id="speakerSelect"></select></label>
                <label>Стиль<select id="styleSelect"></select></label>
                <label>Место/шум<select id="locationSelect"></select></label>
                <label>Попыток<input id="attemptsInput" type="number" min="5" max="100" step="5"></label>
                <label>Заметка<input id="notesInput" type="text" maxlength="255" placeholder="например: гость у двери"></label>
              </div>

              <div class="actions">
                <button class="primary" id="startBtn"><ha-icon icon="mdi:record-rec"></ha-icon>Начать</button>
                <button class="stop" id="finishBtn"><ha-icon icon="mdi:stop-circle-outline"></ha-icon>Завершить</button>
                <button id="refreshBtn"><ha-icon icon="mdi:refresh"></ha-icon>Обновить</button>
                <button id="soundBtn"><ha-icon icon="mdi:volume-high"></ha-icon>Звук</button>
              </div>
            </div>

            <div class="panel">
              <div class="eyebrow">План записи</div>
              <div class="subtitle" id="planSubtitle"></div>
              <div class="actions">
                <button id="prevStep"><ha-icon icon="mdi:chevron-left"></ha-icon>Назад</button>
                <button id="applyStep"><ha-icon icon="mdi:tune"></ha-icon>Применить</button>
                <button id="nextStep"><ha-icon icon="mdi:chevron-right"></ha-icon>Дальше</button>
              </div>
              <div class="plan-list" id="planList"></div>
            </div>
          </div>

          <div class="main" style="margin-top:16px">
            <div class="panel">
              <div class="eyebrow">Комната и направление</div>
              <div class="room" id="room"></div>
              <div class="direction">
                <div class="compass"><div class="needle" id="needle"></div></div>
                <div class="direction-text" id="directionText"></div>
              </div>
            </div>
            <div class="panel">
              <div class="eyebrow">Микрофон и качество</div>
              <div class="mic">
                <div class="meter"><div id="micFill"></div></div>
                <div class="direction-text" id="micText"></div>
                <div class="fineprint">Уровень и направление берутся из 6-канального потока ReSpeaker, который одновременно кормит Wyoming satellite.</div>
              </div>
              <div class="metrics" style="grid-template-columns: repeat(3, minmax(0, 1fr)); margin-bottom: 0">
                <div class="metric"><strong id="metricSessions">0</strong><span>завершено сессий</span></div>
                <div class="metric"><strong id="metricRecall">0%</strong><span>записи блока</span></div>
                <div class="metric"><strong id="metricNext">1/12</strong><span>следующий шаг</span></div>
              </div>
            </div>
          </div>

          <div class="panel" style="margin-top:16px">
            <div class="review-head">
              <div>
                <div class="eyebrow">Review wake samples</div>
                <div class="subtitle" id="reviewSubtitle"></div>
              </div>
              <div class="review-actions">
                <button id="reviewPlaylistBtn"><ha-icon icon="mdi:play"></ha-icon>Play</button>
                <button id="reviewRefreshBtn"><ha-icon icon="mdi:refresh"></ha-icon>Refresh</button>
              </div>
            </div>
            <div id="reviewBody"></div>
          </div>
        </div>
      </ha-card>
    `;
    this.fillSelects();
    this.bindEvents();
    this.renderRoom();
    this.renderPlan();
  }

  fillSelects() {
    this.fillSelect("phraseSelect", LABELS.phrase);
    this.fillSelect("speakerSelect", LABELS.speaker);
    this.fillSelect("styleSelect", LABELS.style);
    this.fillSelect("locationSelect", LABELS.location);
  }

  fillSelect(id, labels) {
    const select = this.shadowRoot.getElementById(id);
    select.innerHTML = Object.entries(labels)
      .map(([value, label]) => `<option value="${this.escape(value)}">${this.escape(label)}</option>`)
      .join("");
  }

  bindEvents() {
    const $ = (id) => this.shadowRoot.getElementById(id);
    $("phraseSelect").addEventListener("change", (event) => this.setSelect("input_select.wakeword_collection_phrase", event.target.value));
    $("speakerSelect").addEventListener("change", (event) => this.setSelect("input_select.wakeword_collection_speaker", event.target.value));
    $("styleSelect").addEventListener("change", (event) => this.setSelect("input_select.wakeword_collection_style", event.target.value));
    $("locationSelect").addEventListener("change", (event) => this.setSelect("input_select.wakeword_collection_location", event.target.value));
    $("attemptsInput").addEventListener("change", (event) => this.setNumber("input_number.wakeword_collection_expected_attempts", event.target.value));
    $("notesInput").addEventListener("change", (event) => this.setText("input_text.wakeword_collection_notes", event.target.value));
    $("startBtn").addEventListener("click", () => this.startSession());
    $("finishBtn").addEventListener("click", () => this.finishSession());
    $("refreshBtn").addEventListener("click", () => this.refreshSession());
    $("soundBtn").addEventListener("click", () => this.setSoundEnabled(!this.soundEnabled()));
    $("prevStep").addEventListener("click", () => this.selectPlanStep(this.currentPlanIndex() - 1));
    $("nextStep").addEventListener("click", () => this.selectPlanStep(this.currentPlanIndex() + 1));
    $("applyStep").addEventListener("click", () => this.applyStep(WAKEWORD_PLAN[this.currentPlanIndex()]));
    $("reviewPlaylistBtn").addEventListener("click", () => this.toggleReviewPlaylist());
    $("reviewRefreshBtn").addEventListener("click", () => this.loadReviewManifest(true));
  }

  currentPlanIndex() {
    return Math.max(0, Math.min(WAKEWORD_PLAN.length - 1, Number(this.value("input_number.wakeword_collection_plan_step", 1)) - 1));
  }

  renderPlan() {
    const list = this.shadowRoot.getElementById("planList");
    list.innerHTML = WAKEWORD_PLAN.map((step, index) => `
      <div class="step" data-step="${index}">
        <div class="num">${index + 1}</div>
        <div>
          <div class="step-title">${this.escape(step.name)}</div>
          <div class="step-sub">${this.escape(LABELS.phrase[step.phrase])} · ${this.escape(LABELS.speaker[step.speaker])} · ${this.escape(LABELS.location[step.location])}</div>
        </div>
        <div class="attempts">${step.attempts}x</div>
      </div>
    `).join("");
    list.querySelectorAll(".step").forEach((node) => {
      node.addEventListener("click", () => this.selectPlanStep(Number(node.dataset.step)));
    });
  }

  renderRoom() {
    const room = this.shadowRoot.getElementById("room");
    room.innerHTML = ROOM_POINTS.map((point) => `
      <button class="point" data-location="${this.escape(point.id)}" style="left:${point.x}%;top:${point.y}%">${this.escape(point.label)}</button>
    `).join("");
    room.querySelectorAll(".point").forEach((node) => {
      node.addEventListener("click", () => this.setSelect("input_select.wakeword_collection_location", node.dataset.location));
    });
  }

  renderReview() {
    if (!this.shadowRoot) return;
    const body = this.shadowRoot.getElementById("reviewBody");
    const subtitle = this.shadowRoot.getElementById("reviewSubtitle");
    const playlistBtn = this.shadowRoot.getElementById("reviewPlaylistBtn");
    if (!body || !subtitle || !playlistBtn) return;

    const samples = this.reviewVisibleSamples();
    const missedCount = samples.filter((sample) => sample.missedByModel).length;
    const confirmedCount = samples.filter((sample) => sample.confirmedForTraining).length;
    const negativeCount = samples.filter((sample) => sample.negativeAdded).length;
    subtitle.textContent = this.reviewLoading
      ? "Загружаю manifest кандидатов..."
      : `${samples.length} фрагментов, новые сверху. ${missedCount} не распознаны моделью, ${confirmedCount} подтверждены, ${negativeCount} добавлены в шумовые negatives.`;
    playlistBtn.disabled = !samples.length;
    playlistBtn.innerHTML =
      `<ha-icon icon="${this.reviewPlaying ? "mdi:pause" : "mdi:play"}"></ha-icon>${this.reviewPlaying ? "Pause" : "Play"}`;

    if (this.reviewLoading) {
      body.innerHTML = `<div class="empty">Manifest загружается из ${this.escape(this.getReviewManifestUrl())}.</div>`;
      return;
    }
    if (!samples.length) {
      const details = this.reviewError
        ? `Manifest недоступен (${this.reviewError}).`
        : "Manifest пока отсутствует или в нем нет кандидатов.";
      body.innerHTML = `<div class="empty">${this.escape(details)} Когда другой агент создаст JSON со списком samples, они появятся здесь автоматически после Refresh.</div>`;
      return;
    }

    body.innerHTML = `
      <div class="review-list">
        ${samples.map((sample, index) => this.renderReviewSample(sample, index)).join("")}
      </div>
    `;
    body.querySelectorAll("[data-review-play]").forEach((button) => {
      button.addEventListener("click", () => this.playReviewSample(Number(button.dataset.reviewPlay), false));
    });
    body.querySelectorAll("[data-review-confirm]").forEach((button) => {
      button.addEventListener("click", () => this.confirmReviewSample(button.dataset.reviewConfirm));
    });
    body.querySelectorAll("[data-review-negative]").forEach((button) => {
      button.addEventListener("click", () => this.addReviewSampleToNegative(button.dataset.reviewNegative));
    });
  }

  renderReviewSample(sample, index) {
    const playing = this.reviewPlaying && this.reviewIndex === index;
    const score = Number.isFinite(sample.score) ? sample.score.toFixed(3) : "n/a";
    const duration = sample.duration > 0 ? `${sample.duration.toFixed(2)}s` : "duration n/a";
    const statusBadge = sample.confirmedForTraining
      ? `<span class="badge confirmed">подтверждено</span>`
      : sample.negativeAdded
        ? `<span class="badge negative">noise negative</span>`
        : "";
    const trainingBadge = sample.trainingMode ? `<span class="badge training">режим тренировки</span>` : "";
    const detectedBadge = sample.missedByModel
      ? `<span class="badge missed">missed by model</span>`
      : sample.detectedByModel === true
        ? `<span class="badge detected">detected</span>`
        : `<span class="badge">not detected</span>`;
    return `
      <div class="sample ${sample.missedByModel ? "missed" : ""} ${playing ? "playing" : ""} ${sample.confirmedForTraining ? "confirmed" : ""} ${sample.negativeAdded ? "negative" : ""}">
        <button class="icon-btn" title="Play sample" data-review-play="${index}">
          <ha-icon icon="${playing ? "mdi:volume-high" : "mdi:play"}"></ha-icon>
        </button>
        <div class="sample-main">
          <div class="sample-title">
            <span>${this.escape(sample.label)}</span>
            ${detectedBadge}
            ${statusBadge}
            ${trainingBadge}
            <span class="badge">${this.escape(duration)}</span>
            <span class="badge">score ${this.escape(score)}</span>
            <span class="badge">${this.escape(sample.whenLabel)}</span>
          </div>
          <div class="sample-path">${this.escape(sample.path || sample.url)}</div>
        </div>
        <div class="sample-buttons">
          <button class="icon-btn confirm" title="Подтвердить для обучения" data-review-confirm="${this.escape(sample.id)}" ${sample.busy ? "disabled" : ""}>
            <ha-icon icon="mdi:check-circle"></ha-icon>
          </button>
          <button class="icon-btn negative" title="Добавить в шумовые negative samples" data-review-negative="${this.escape(sample.id)}" ${sample.busy ? "disabled" : ""}>
            <ha-icon icon="mdi:minus-circle-outline"></ha-icon>
          </button>
        </div>
      </div>
    `;
  }

  handleCaptureCounter(active, sessionId, observed) {
    const current = {
      active,
      sessionId: String(sessionId || ""),
      observed: Number.isFinite(observed) ? observed : 0,
    };
    if (!active) {
      this.captureCounterState = current;
      return;
    }
    const previous = this.captureCounterState;
    const sameSession = previous?.active && previous.sessionId === current.sessionId;
    if (!sameSession) {
      this.captureCounterState = current;
      return;
    }
    if (current.observed > previous.observed) {
      this.playSound("click");
      this.pulseObservedMetric();
    }
    this.captureCounterState = current;
  }

  pulseObservedMetric() {
    const metric = this.shadowRoot?.getElementById("metricObserved")?.closest(".metric");
    if (!metric) return;
    metric.classList.remove("pulse");
    window.requestAnimationFrame(() => metric.classList.add("pulse"));
    clearTimeout(this.metricPulseTimer);
    this.metricPulseTimer = setTimeout(() => metric.classList.remove("pulse"), 700);
  }

  update() {
    if (!this.shadowRoot || !this._hass) return;
    const active = this.value("sensor.wakeword_positive_session") === "active";
    const observed = Number(this.attr("sensor.wakeword_positive_session", "captured_files_since_start", this.attr("sensor.wakeword_positive_session", "wake_files_since_start", 0)));
    const sessionId = String(this.attr("sensor.wakeword_positive_session", "id", ""));
    this.handleCaptureCounter(active, sessionId, observed);
    const expected = Number(this.attr("sensor.wakeword_positive_session", "expected_attempts", this.value("input_number.wakeword_collection_expected_attempts", 30))) || 30;
    const progress = expected > 0 ? Math.min(1, observed / expected) : 0;
    const planIndex = this.currentPlanIndex();
    const step = WAKEWORD_PLAN[planIndex];
    const phrase = this.value("input_select.wakeword_collection_phrase", step.phrase);
    const speaker = this.value("input_select.wakeword_collection_speaker", step.speaker);
    const style = this.value("input_select.wakeword_collection_style", step.style);
    const location = this.value("input_select.wakeword_collection_location", step.location);
    const totalSaved = Number(this.attr("sensor.wakeword_positive_session", "real_positive_files_total", 0));
    const sessions = Number(this.attr("sensor.wakeword_positive_session", "session_summaries_total", 0));
    const recall = expected > 0 ? Math.round((observed / expected) * 100) : 0;
    const totalPlan = WAKEWORD_PLAN.reduce((sum, item) => sum + item.attempts, 0);

    this.shadowRoot.getElementById("subtitle").textContent =
      `План: ${WAKEWORD_PLAN.length} блоков, ${totalPlan} попыток. Текущий блок: ${LABELS.speaker[speaker] || speaker}, ${LABELS.style[style] || style}, ${LABELS.location[location] || location}.`;
    this.shadowRoot.getElementById("status").classList.toggle("active", active);
    this.shadowRoot.getElementById("statusText").textContent = active ? "идет запись" : "готово";
    this.shadowRoot.getElementById("stepLabel").textContent = `Шаг ${planIndex + 1} из ${WAKEWORD_PLAN.length} · ${step.name}`;
    this.shadowRoot.getElementById("phrase").textContent = LABELS.phrase[phrase] || phrase;
    this.shadowRoot.getElementById("cue").textContent = step.cue;
    this.shadowRoot.getElementById("ringText").textContent = `${Math.min(100, Math.round(progress * 100))}%`;
    this.shadowRoot.getElementById("ringSub").textContent = `${observed}/${expected}`;
    this.shadowRoot.getElementById("ringFg").style.strokeDashoffset = String(326.7256 * (1 - progress));
    this.shadowRoot.getElementById("progressFill").style.width = `${Math.min(100, Math.round(progress * 100))}%`;
    this.shadowRoot.getElementById("metricObserved").textContent = String(observed);
    this.shadowRoot.getElementById("metricRemaining").textContent = String(Math.max(0, expected - observed));
    this.shadowRoot.getElementById("metricSaved").textContent = String(totalSaved);
    this.shadowRoot.getElementById("metricSessions").textContent = String(sessions);
    this.shadowRoot.getElementById("metricRecall").textContent = `${recall}%`;
    this.shadowRoot.getElementById("metricNext").textContent = `${planIndex + 1}/${WAKEWORD_PLAN.length}`;
    this.shadowRoot.getElementById("planSubtitle").textContent =
      `Сделано блоков: ${this.value("counter.wakeword_collection_blocks_done", 0)}. Завершить только останавливает запись; следующий шаг выбирайте вручную.`;

    this.setControlValue("phraseSelect", phrase);
    this.setControlValue("speakerSelect", speaker);
    this.setControlValue("styleSelect", style);
    this.setControlValue("locationSelect", location);
    this.setControlValue("attemptsInput", expected);
    if (this.shadowRoot.activeElement?.id !== "notesInput") {
      this.setControlValue("notesInput", this.value("input_text.wakeword_collection_notes", ""));
    }

    this.shadowRoot.getElementById("startBtn").disabled = active;
    this.shadowRoot.getElementById("finishBtn").disabled = !active;
    this.shadowRoot.getElementById("soundBtn").innerHTML =
      `<ha-icon icon="${this.soundEnabled() ? "mdi:volume-high" : "mdi:volume-off"}"></ha-icon>${this.soundEnabled() ? "Звук вкл" : "Звук выкл"}`;

    this.shadowRoot.querySelectorAll(".step").forEach((node) => {
      const index = Number(node.dataset.step);
      node.classList.toggle("active", index === planIndex);
      node.classList.toggle("done", index < planIndex);
    });
    this.shadowRoot.querySelectorAll(".point").forEach((node) => {
      node.classList.toggle("active", node.dataset.location === location);
    });
    this.updateDirection(location);
    this.updateMicOnly();
  }

  updateDirection(location) {
    const entityId = this.directionEntityId();
    const levelEntity = this.levelEntityId();
    const raw = this.value(entityId, "");
    const fallbackDirection = this.attr(levelEntity, "direction_degrees", "");
    const numeric = raw === "" ? Number(fallbackDirection) : Number(raw);
    const confidence = Number(this.attr(entityId, "confidence", this.attr(levelEntity, "confidence", NaN)));
    const age = Number(this.attr(entityId, "age_seconds", this.attr(levelEntity, "age_seconds", NaN)));
    const point = ROOM_POINTS.find((item) => item.id === location);
    const needle = this.shadowRoot.getElementById("needle");
    const text = this.shadowRoot.getElementById("directionText");
    if (Number.isFinite(numeric)) {
      needle.style.transform = `translate(-50%, -100%) rotate(${numeric}deg)`;
      const confidenceText = Number.isFinite(confidence) ? `, уверенность ${Math.round(confidence * 100)}%` : "";
      const ageText = Number.isFinite(age) ? `, обновлено ${Math.round(age)} c назад` : "";
      text.textContent = `Направление от ReSpeaker массива: ${Math.round(numeric)} градусов${confidenceText}${ageText}. Выбранная позиция: ${LABELS.location[location] || location}.`;
    } else {
      const angle = point ? Math.atan2(point.y - 50, point.x - 50) * 180 / Math.PI + 90 : 0;
      needle.style.transform = `translate(-50%, -100%) rotate(${angle}deg)`;
      text.textContent = `ReSpeaker direction sensor ждет данные. Стрелка показывает выбранную позицию записи: ${LABELS.location[location] || location}.`;
    }
  }

  updateMicOnly() {
    if (!this.shadowRoot) return;
    const levelEntity = this.levelEntityId();
    const directionEntity = this.directionEntityId();
    const rawDb = this.value(levelEntity, "");
    const db = rawDb === "" ? NaN : Number(rawDb);
    const confidence = Number(this.attr(directionEntity, "confidence", this.attr(levelEntity, "confidence", NaN)));
    const age = Number(this.attr(directionEntity, "age_seconds", this.attr(levelEntity, "age_seconds", NaN)));
    const level = Number.isFinite(db) ? Math.max(0, Math.min(1, (db + 70) / 55)) : 0;
    const micFill = this.shadowRoot.getElementById("micFill");
    const micText = this.shadowRoot.getElementById("micText");
    if (!micFill || !micText) return;
    micFill.style.width = `${Math.round(level * 100)}%`;
    if (Number.isFinite(db)) {
      const hint = db > -18 ? "громко" : db > -34 ? "хороший уровень" : db > -52 ? "тихо" : "почти тишина";
      const confidenceText = Number.isFinite(confidence) ? ` Direction confidence ${Math.round(confidence * 100)}%.` : "";
      const ageText = Number.isFinite(age) ? ` Обновлено ${Math.round(age)} c назад.` : "";
      micText.textContent = `ReSpeaker массив: ${Math.round(db)} dBFS, ${hint}.${confidenceText}${ageText}`;
    } else {
      micText.textContent = "ReSpeaker monitor ждет live данные от Wyoming capture pipeline.";
    }
  }

  setControlValue(id, value) {
    const element = this.shadowRoot.getElementById(id);
    if (element && String(element.value) !== String(value)) element.value = value;
  }

  escape(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
}

if (!customElements.get("wakeword-collection-card")) {
  customElements.define("wakeword-collection-card", WakewordCollectionCard);
}
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "wakeword-collection-card")) {
  window.customCards.push({
    type: "wakeword-collection-card",
    name: "Wakeword Collection Card",
    preview: false,
    description: "Guided wake word positive dataset collection for Home Assistant.",
  });
}
